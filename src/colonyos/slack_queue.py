from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from colonyos.config import ColonyConfig
from colonyos.models import QueueItem, QueueItemStatus, QueueState, compute_priority
from colonyos.queue_runtime import (
    attach_demand_signal,
    find_similar_queue_item,
    find_related_history_items,
    reprioritize_queue_item,
    sorted_pending_items,
)
from colonyos.slack import (
    SlackClient,
    SlackWatchState,
    check_rate_limit,
    extract_base_branch,
    extract_prompt_from_mention,
    find_parent_queue_item,
    format_fix_acknowledgment,
    format_fix_error,
    format_fix_round_limit,
    format_slack_as_prompt,
    increment_hourly_count,
    post_message,
    post_triage_acknowledgment,
    post_triage_skip,
    react_to_message,
    should_process_message,
    should_process_thread_fix,
    triage_message,
)

logger = logging.getLogger(__name__)


def _generate_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}-{stamp}"


@dataclass
class SlackQueueEngine:
    repo_root: Path
    config: ColonyConfig
    queue_state: QueueState
    watch_state: SlackWatchState
    state_lock: threading.Lock
    shutdown_event: threading.Event
    bot_user_id: str
    slack_client_ready: threading.Event
    publish_client: Callable[[SlackClient], None]
    persist_queue: Callable[[], None]
    persist_watch_state: Callable[[], None]
    is_time_exceeded: Callable[[], bool]
    is_budget_exceeded: Callable[[], bool]
    is_daily_budget_exceeded: Callable[[], bool]
    dry_run: bool = False

    def register(self, bolt_app: Any) -> None:
        bolt_app.event("app_mention")(self._handle_event)
        if self.config.slack.trigger_mode not in ("reaction", "all"):
            bolt_app.event("reaction_added")(lambda event, client: None)
            return
        bolt_app.event("reaction_added")(self._handle_reaction)

    def _handle_reaction(self, event: dict[str, Any], client: SlackClient) -> None:
        item = event.get("item", {})
        if item.get("type") != "message":
            return
        channel = item.get("channel", "")
        ts = item.get("ts", "")
        try:
            result = client.conversations_history(
                channel=channel,
                latest=ts,
                inclusive=True,
                limit=1,
            )
            messages = result.get("messages", [])
            if not messages:
                return
            msg = messages[0]
            synthetic_event = {
                "channel": channel,
                "ts": ts,
                "user": msg.get("user", "unknown"),
                "text": msg.get("text", ""),
            }
            self._handle_event(synthetic_event, client)
        except Exception:
            logger.debug("Failed to fetch message for reaction event", exc_info=True)

    def _handle_event(self, event: dict[str, Any], client: SlackClient) -> None:
        if not self.slack_client_ready.is_set():
            self.publish_client(client)
            self.slack_client_ready.set()

        if not should_process_message(event, self.config.slack, self.bot_user_id):
            with self.state_lock:
                items_snapshot = list(self.queue_state.items)
            if should_process_thread_fix(event, self.config.slack, self.bot_user_id, items_snapshot):
                if self.is_time_exceeded() or self.is_budget_exceeded() or self.is_daily_budget_exceeded():
                    logger.warning("Thread fix rejected due to daemon/watch limits")
                    return
                self._handle_thread_fix(event, client)
            return

        if self.is_time_exceeded() or self.is_budget_exceeded() or self.is_daily_budget_exceeded():
            logger.warning("Slack event rejected due to daemon/watch limits")
            return

        channel = event.get("channel", "")
        ts = event.get("ts", "")
        user = event.get("user", "unknown")
        raw_text = event.get("text", "")
        prompt_text = extract_prompt_from_mention(raw_text, self.bot_user_id)
        if not prompt_text.strip():
            return

        with self.state_lock:
            if self.watch_state.is_processed(channel, ts):
                logger.info("Message %s:%s already processed, skipping", channel, ts)
                return
            if not check_rate_limit(self.watch_state, self.config.slack):
                logger.warning("Rate limit reached, skipping message %s:%s", channel, ts)
                try:
                    post_message(
                        client,
                        channel,
                        ":warning: Rate limit reached. Try again later.",
                        thread_ts=ts,
                    )
                except Exception:
                    logger.debug("Failed to post rate-limit message", exc_info=True)
                return

        if self.dry_run:
            logger.info("[DRY RUN] Would trigger pipeline for Slack prompt: %s", prompt_text[:120])
            return

        try:
            react_to_message(client, channel, ts, "eyes")
        except Exception:
            logger.debug("Failed to add :eyes: reaction", exc_info=True)

        threading.Thread(
            target=self._triage_and_enqueue,
            kwargs={
                "client": client,
                "channel": channel,
                "ts": ts,
                "user": user,
                "prompt_text": prompt_text,
            },
            daemon=True,
            name=f"triage-{ts}",
        ).start()

    def _triage_and_enqueue(
        self,
        *,
        client: SlackClient,
        channel: str,
        ts: str,
        user: str,
        prompt_text: str,
    ) -> None:
        if self.shutdown_event.is_set():
            return

        triage_kwargs: dict[str, str] = {}
        if self.config.project:
            triage_kwargs["project_name"] = self.config.project.name
            triage_kwargs["project_description"] = self.config.project.description
            triage_kwargs["project_stack"] = self.config.project.stack
        if self.config.vision:
            triage_kwargs["vision"] = self.config.vision
        if self.config.slack.triage_scope:
            triage_kwargs["triage_scope"] = self.config.slack.triage_scope

        try:
            triage_result = triage_message(
                prompt_text,
                repo_root=self.repo_root,
                **triage_kwargs,
            )
        except Exception:
            logger.exception("Triage failed for message %s:%s", channel, ts)
            try:
                post_message(
                    client,
                    channel,
                    ":warning: Triage failed. Check server logs for details.",
                    thread_ts=ts,
                )
            except Exception:
                logger.debug("Failed to post triage failure message", exc_info=True)
            return

        if self.shutdown_event.is_set():
            logger.info(
                "Shutdown in progress; dropping triaged message %s:%s before enqueue",
                channel,
                ts,
            )
            return

        if not triage_result.actionable:
            try:
                if triage_result.answer:
                    post_message(client, channel, triage_result.answer, thread_ts=ts)
                elif self.config.slack.triage_verbose:
                    post_triage_skip(client, channel, ts, triage_result.reasoning)
            except Exception:
                logger.debug("Failed to post non-actionable triage result", exc_info=True)
            with self.state_lock:
                self.watch_state.mark_processed(channel, ts, "triage-skip")
                self.persist_watch_state()
            return

        base_branch = triage_result.base_branch or extract_base_branch(prompt_text)
        formatted_prompt = format_slack_as_prompt(prompt_text, channel, user)
        merged_item: QueueItem | None = None
        merged_similarity = 0.0
        queue_item: QueueItem | None = None

        with self.state_lock:
            if self.shutdown_event.is_set():
                return
            related_history = find_related_history_items(
                self.queue_state,
                prompt_text=prompt_text,
            )
            similar = find_similar_queue_item(
                self.queue_state,
                source_type="slack",
                prompt_text=prompt_text,
            )
            if similar is not None:
                merged_item = similar.item
                merged_similarity = similar.similarity
                attach_demand_signal(
                    merged_item,
                    source_type="slack",
                    source_value=prompt_text,
                    summary=triage_result.summary,
                    metadata={
                        "channel": channel,
                        "user": user,
                        "ts": ts,
                        "similarity": round(similar.similarity, 3),
                    },
                )
                reprioritize_queue_item(merged_item)
            else:
                queue_item = QueueItem(
                    id=_generate_id("slack"),
                    source_type="slack",
                    source_value=formatted_prompt,
                    raw_prompt=prompt_text,
                    summary=triage_result.summary,
                    status=QueueItemStatus.PENDING,
                    slack_ts=ts,
                    slack_channel=channel,
                    notification_channel=channel,
                    notification_thread_ts=ts,
                    base_branch=base_branch,
                    priority=compute_priority("slack"),
                    priority_reason="base:slack",
                    related_item_ids=[related.id for related in related_history],
                )
                reprioritize_queue_item(queue_item)
                self.queue_state.items.append(queue_item)
            self.watch_state.mark_processed(
                channel,
                ts,
                (merged_item.id if merged_item else queue_item.id),  # type: ignore[union-attr]
            )
            increment_hourly_count(self.watch_state)
            self.watch_state.runs_triggered += 1
            self.persist_queue()
            self.persist_watch_state()
            pending = sorted_pending_items(self.queue_state)
            target = merged_item or queue_item
            assert target is not None
            position = pending.index(target) + 1 if target in pending else None
            total = len(pending)

        if merged_item is not None:
            try:
                post_message(
                    client,
                    channel,
                    (
                        ":link: This request matched an existing queued item.\n"
                        f"Summary: {merged_item.summary or triage_result.summary}\n"
                        f"Demand signals: {merged_item.demand_count}\n"
                        f"Queue position: {position} of {total}\n"
                        f"Similarity: {merged_similarity:.0%}"
                    ),
                    thread_ts=ts,
                )
            except Exception:
                logger.debug("Failed to post merge acknowledgment", exc_info=True)
            return

        try:
            post_triage_acknowledgment(
                client,
                channel,
                ts,
                triage_result.summary,
                needs_approval=not self.config.slack.auto_approve,
                queue_position=position,
                queue_total=total,
            )
        except Exception:
            logger.debug("Failed to post triage acknowledgment", exc_info=True)

    def _handle_thread_fix(self, event: dict[str, Any], client: SlackClient) -> None:
        channel = event.get("channel", "")
        ts = event.get("ts", "")
        thread_ts = event.get("thread_ts", "")
        user = event.get("user", "unknown")
        raw_text = event.get("text", "")
        fix_prompt_text = extract_prompt_from_mention(raw_text, self.bot_user_id)
        if not fix_prompt_text.strip():
            return

        with self.state_lock:
            parent_item = find_parent_queue_item(thread_ts, self.queue_state.items)
            if parent_item is None:
                logger.warning("Thread fix: no completed parent for thread_ts=%s", thread_ts)
                return
            if parent_item.fix_rounds >= self.config.slack.max_fix_rounds_per_thread:
                cumulative_cost = parent_item.cost_usd + sum(
                    qi.cost_usd
                    for qi in self.queue_state.items
                    if qi.parent_item_id == parent_item.id
                )
                try:
                    post_message(
                        client,
                        channel,
                        format_fix_round_limit(cumulative_cost),
                        thread_ts=thread_ts,
                    )
                except Exception:
                    logger.debug("Failed to post fix round limit message", exc_info=True)
                return
            if not parent_item.branch_name:
                try:
                    post_message(
                        client,
                        channel,
                        format_fix_error("No branch", "No branch name recorded for the original run."),
                        thread_ts=thread_ts,
                    )
                except Exception:
                    logger.debug("Failed to post no-branch message", exc_info=True)
                return

            parent_item.fix_rounds += 1
            fix_item = QueueItem(
                id=_generate_id("slack-fix"),
                source_type="slack_fix",
                source_value=format_slack_as_prompt(fix_prompt_text, channel, user),
                raw_prompt=fix_prompt_text,
                summary=f"Follow-up fix for {parent_item.summary or parent_item.branch_name}",
                status=QueueItemStatus.PENDING,
                slack_ts=thread_ts,
                slack_channel=channel,
                branch_name=parent_item.branch_name,
                parent_item_id=parent_item.id,
                pr_url=parent_item.pr_url,
                base_branch=parent_item.base_branch,
                head_sha=parent_item.head_sha,
                notification_channel=channel,
                notification_thread_ts=thread_ts,
                priority=compute_priority("slack_fix"),
                priority_reason="base:slack_fix",
            )
            reprioritize_queue_item(fix_item)
            self.queue_state.items.append(fix_item)
            self.persist_queue()
            self.persist_watch_state()

        try:
            react_to_message(client, channel, ts, "eyes")
        except Exception:
            logger.debug("Failed to add :eyes: reaction to fix request", exc_info=True)
        try:
            post_message(
                client,
                channel,
                format_fix_acknowledgment(parent_item.branch_name),
                thread_ts=thread_ts,
            )
        except Exception:
            logger.debug("Failed to post fix acknowledgment", exc_info=True)
