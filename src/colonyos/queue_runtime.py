from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from colonyos.models import QueueItem, QueueItemStatus, QueueState, compute_runtime_priority

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = {
    QueueItemStatus.COMPLETED,
    QueueItemStatus.FAILED,
    QueueItemStatus.REJECTED,
}
_ACTIVE_STATUSES = {
    QueueItemStatus.PENDING,
    QueueItemStatus.RUNNING,
}
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "be",
        "for",
        "from",
        "have",
        "i",
        "in",
        "into",
        "it",
        "of",
        "on",
        "or",
        "should",
        "that",
        "the",
        "this",
        "to",
        "we",
        "with",
    }
)
_ARCHIVE_DIR = ".colonyos/archive"
_ARCHIVE_FILE = "queue_history.jsonl"
_MAX_ACTIVE_TERMINAL_ITEMS = 200


@dataclass(frozen=True)
class SimilarQueueMatch:
    item: QueueItem
    similarity: float


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def queue_item_text(item: QueueItem) -> str:
    return (
        item.raw_prompt
        or item.summary
        or item.issue_title
        or item.source_value
    )


def normalize_request_text(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"<[^>]+>", " ", lowered)
    lowered = re.sub(r"[^a-z0-9\s]+", " ", lowered)
    tokens = [tok for tok in lowered.split() if tok and tok not in _STOPWORDS]
    return " ".join(tokens)


def _token_set(text: str) -> set[str]:
    return set(normalize_request_text(text).split())


def request_similarity(left: str, right: str) -> float:
    left_norm = normalize_request_text(left)
    right_norm = normalize_request_text(right)
    if not left_norm or not right_norm:
        return 0.0
    seq = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = _token_set(left_norm)
    right_tokens = _token_set(right_norm)
    if not left_tokens or not right_tokens:
        return seq
    jaccard = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    return max(seq, jaccard, (seq + jaccard) / 2.0)


def is_mergeable_source(source_type: str) -> bool:
    return source_type in {"slack", "prompt", "issue", "ceo"}


def find_similar_queue_item(
    queue_state: QueueState,
    *,
    source_type: str,
    prompt_text: str,
    similarity_threshold: float = 0.60,
) -> SimilarQueueMatch | None:
    if not is_mergeable_source(source_type):
        return None
    best: SimilarQueueMatch | None = None
    for item in queue_state.items:
        if item.status not in _ACTIVE_STATUSES:
            continue
        if not is_mergeable_source(item.source_type):
            continue
        similarity = request_similarity(prompt_text, queue_item_text(item))
        if similarity < similarity_threshold:
            continue
        if best is None or similarity > best.similarity:
            best = SimilarQueueMatch(item=item, similarity=similarity)
    return best


def find_related_history_items(
    queue_state: QueueState,
    *,
    prompt_text: str,
    limit: int = 3,
    similarity_threshold: float = 0.55,
) -> list[QueueItem]:
    matches: list[tuple[float, QueueItem]] = []
    for item in queue_state.items:
        if item.status not in _TERMINAL_STATUSES:
            continue
        similarity = request_similarity(prompt_text, queue_item_text(item))
        if similarity >= similarity_threshold:
            matches.append((similarity, item))
    matches.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _score, item in matches[:limit]]


def attach_demand_signal(
    item: QueueItem,
    *,
    source_type: str,
    source_value: str,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
    related_item_id: str | None = None,
) -> None:
    item.demand_count = max(1, item.demand_count) + 1
    if related_item_id and related_item_id not in item.related_item_ids:
        item.related_item_ids.append(related_item_id)
    entry = {
        "source_type": source_type,
        "source_value": source_value[:500],
        "summary": summary or "",
    }
    if metadata:
        entry.update(metadata)
    item.merged_sources.append(entry)


def notification_targets(item: QueueItem) -> list[tuple[str, str]]:
    """Return unique Slack thread targets for the canonical and merged requests."""
    targets: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(channel: str | None, thread_ts: str | None) -> None:
        if not channel or not thread_ts:
            return
        target = (channel, thread_ts)
        if target in seen:
            return
        seen.add(target)
        targets.append(target)

    _add(item.notification_channel or item.slack_channel, item.notification_thread_ts or item.slack_ts)
    for source in item.merged_sources:
        if not isinstance(source, dict):
            continue
        _add(
            source.get("notification_channel") or source.get("channel") or source.get("slack_channel"),
            source.get("notification_thread_ts") or source.get("thread_ts") or source.get("ts") or source.get("slack_ts"),
        )
    return targets


def build_similarity_context(item: QueueItem, queue_state: QueueState) -> str:
    lines: list[str] = []
    if item.demand_count > 1:
        lines.append(
            f"This queue item aggregates {item.demand_count} similar requests."
        )
    related_ids = set(item.related_item_ids)
    if related_ids:
        related = [
            other for other in queue_state.items
            if other.id in related_ids and other.id != item.id
        ]
        if related:
            lines.append("Related prior work:")
            for other in related[:5]:
                status = other.status.value
                detail = other.summary or other.issue_title or queue_item_text(other)[:120]
                parts = [f"- {other.source_type} [{status}] {detail}"]
                if other.branch_name:
                    parts.append(f"branch={other.branch_name}")
                if other.pr_url:
                    parts.append(f"pr={other.pr_url}")
                lines.append(" ".join(parts))
    return "\n".join(lines).strip()


def reprioritize_queue_item(
    item: QueueItem,
    *,
    now: datetime | None = None,
) -> None:
    current_time = now or datetime.now(timezone.utc)
    base_priority = compute_runtime_priority(item.source_type)
    adjusted = base_priority
    reasons = [f"base:{item.source_type}"]

    if item.demand_count >= 3:
        adjusted = min(adjusted, 0)
        reasons.append(f"demand:{item.demand_count}")
    elif item.demand_count == 2:
        adjusted = min(adjusted, 1)
        reasons.append("demand:2")

    try:
        age_hours = (current_time - _parse_iso(item.added_at)).total_seconds() / 3600
    except Exception:
        age_hours = 0.0
    if age_hours >= 24:
        adjusted = max(0, adjusted - 1)
        reasons.append("age:24h")
    if age_hours >= 72:
        adjusted = max(0, adjusted - 1)
        reasons.append("age:72h")

    if item.urgency_score >= 0.85:
        adjusted = 0
        reasons.append(f"urgency:{item.urgency_score:.2f}")
    elif item.urgency_score >= 0.6:
        adjusted = max(0, adjusted - 1)
        reasons.append(f"urgency:{item.urgency_score:.2f}")

    item.priority = adjusted
    item.priority_reason = ", ".join(reasons)
    item.last_reprioritized_at = current_time.isoformat()


def reprioritize_queue(queue_state: QueueState) -> None:
    now = datetime.now(timezone.utc)
    for item in queue_state.items:
        if item.status == QueueItemStatus.PENDING:
            reprioritize_queue_item(item, now=now)


def select_next_pending_item(queue_state: QueueState) -> QueueItem | None:
    reprioritize_queue(queue_state)
    pending = [
        item for item in queue_state.items
        if item.status == QueueItemStatus.PENDING
    ]
    if not pending:
        return None
    pending.sort(key=lambda item: (item.priority, item.added_at))
    return pending[0]


def archive_terminal_queue_items(repo_root: Path, queue_state: QueueState) -> int:
    terminal_items = [
        item for item in queue_state.items
        if item.status in _TERMINAL_STATUSES
    ]
    if len(terminal_items) <= _MAX_ACTIVE_TERMINAL_ITEMS:
        return 0

    terminal_items.sort(key=lambda item: item.added_at)
    to_archive = terminal_items[:-_MAX_ACTIVE_TERMINAL_ITEMS]
    keep_ids = {item.id for item in to_archive}

    archive_dir = repo_root / _ARCHIVE_DIR
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / _ARCHIVE_FILE
    with archive_path.open("a", encoding="utf-8") as handle:
        for item in to_archive:
            handle.write(json.dumps(item.to_dict()))
            handle.write("\n")

    queue_state.items = [
        item for item in queue_state.items
        if item.id not in keep_ids
    ]
    logger.info("Archived %d terminal queue items to %s", len(to_archive), archive_path)
    return len(to_archive)


def pending_queue_snapshot(queue_state: QueueState, *, limit: int = 3) -> list[QueueItem]:
    reprioritize_queue(queue_state)
    pending = [
        item for item in queue_state.items
        if item.status == QueueItemStatus.PENDING
    ]
    pending.sort(key=lambda item: (item.priority, item.added_at))
    return pending[:limit]


def sorted_pending_items(queue_state: QueueState) -> list[QueueItem]:
    reprioritize_queue(queue_state)
    pending = [
        item for item in queue_state.items
        if item.status == QueueItemStatus.PENDING
    ]
    pending.sort(key=lambda item: (item.priority, item.added_at))
    return pending
