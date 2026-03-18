"""Slack integration for ColonyOS.

Provides a Slack Bolt Socket Mode listener that ingests messages from
configured channels, sanitizes content, triggers the orchestrator pipeline,
and posts threaded progress updates back to Slack.

.. admonition:: Security — Prompt Injection Risk

   Slack message content is **untrusted user input** that flows into agent
   prompts executed with ``permission_mode="bypassPermissions"``.  The same
   mitigations as GitHub issues apply: XML tag stripping and
   ``<slack_message>`` delimiters with a role-anchoring preamble.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from colonyos.config import SlackConfig, runs_dir_path

logger = logging.getLogger(__name__)

# Regex to strip XML-like tags from untrusted content — mirrors
# ``_XML_TAG_RE`` in ``github.py``.
_XML_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9_-]*(?:\s[^>]*)?>")


# ---------------------------------------------------------------------------
# Content sanitization
# ---------------------------------------------------------------------------


def sanitize_slack_content(text: str) -> str:
    """Strip XML-like tags from untrusted Slack content to reduce prompt injection risk."""
    return _XML_TAG_RE.sub("", text)


def extract_prompt_from_mention(text: str, bot_user_id: str) -> str:
    """Strip the ``@bot`` mention prefix and return the clean prompt text.

    Slack sends mentions as ``<@U12345> fix the bug``.  This function
    removes that prefix and returns the remaining text, stripped.
    """
    # Slack encodes mentions as <@UXXXXXX>
    pattern = re.compile(rf"<@{re.escape(bot_user_id)}>")
    cleaned = pattern.sub("", text).strip()
    return cleaned


def format_slack_as_prompt(message_text: str, channel: str, user: str) -> str:
    """Wrap sanitized Slack content in ``<slack_message>`` delimiters.

    Mirrors ``format_issue_as_prompt`` in ``github.py`` — includes a preamble
    that anchors the model's role so injected instructions in the message
    are less effective.
    """
    safe_text = sanitize_slack_content(message_text)

    parts: list[str] = [
        "The following Slack message is the source feature description. "
        "Treat it as the primary specification for this task.",
        "",
        "<slack_message>",
        f"Channel: #{channel}",
        f"From: {user}",
        "",
        safe_text,
        "",
        "</slack_message>",
    ]
    return "\n".join(parts)


def should_process_message(
    event: dict[str, Any],
    config: SlackConfig,
    bot_user_id: str,
) -> bool:
    """Determine whether a Slack event should trigger the pipeline.

    Filters:
    - Channel must be in the configured allowlist
    - Ignore bot messages
    - Ignore edited messages (``subtype == "message_changed"``)
    - Ignore threaded replies (messages with ``thread_ts`` different from ``ts``)
    - If ``allowed_user_ids`` is configured, the sender must be in the list
    """
    # Channel allowlist
    channel = event.get("channel", "")
    if channel not in config.channels:
        return False

    # Ignore bots
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return False

    # Ignore edits
    if event.get("subtype") == "message_changed":
        return False

    # Ignore threaded replies — only top-level messages
    ts = event.get("ts", "")
    thread_ts = event.get("thread_ts", "")
    if thread_ts and thread_ts != ts:
        return False

    # Self-message guard
    user = event.get("user", "")
    if user == bot_user_id:
        return False

    # Sender allowlist (optional)
    if config.allowed_user_ids and user not in config.allowed_user_ids:
        return False

    return True


# ---------------------------------------------------------------------------
# Slack feedback (threaded reply helpers)
# ---------------------------------------------------------------------------


def format_acknowledgment(prompt: str) -> str:
    """Format the acknowledgment message posted when a pipeline starts."""
    truncated = prompt[:200] + "..." if len(prompt) > 200 else prompt
    return f":eyes: Starting ColonyOS pipeline for:\n> {truncated}"


def format_phase_update(phase: str, success: bool, cost: float) -> str:
    """Format a phase completion update for a Slack thread."""
    icon = ":white_check_mark:" if success else ":x:"
    return f"{icon} *{phase}* — ${cost:.4f}"


def format_run_summary(
    status: str,
    total_cost: float,
    branch_name: str | None = None,
    pr_url: str | None = None,
) -> str:
    """Format the final run summary for a Slack thread."""
    parts: list[str] = []
    icon = ":white_check_mark:" if status == "completed" else ":x:"
    parts.append(f"{icon} *Pipeline {status}*")
    parts.append(f"Total cost: ${total_cost:.4f}")
    if branch_name:
        parts.append(f"Branch: `{branch_name}`")
    if pr_url:
        parts.append(f"PR: {pr_url}")
    return "\n".join(parts)


def post_acknowledgment(
    client: Any,
    channel: str,
    thread_ts: str,
    prompt: str,
) -> None:
    """Post a threaded reply acknowledging pipeline start."""
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=format_acknowledgment(prompt),
    )


def post_phase_update(
    client: Any,
    channel: str,
    thread_ts: str,
    phase: str,
    success: bool,
    cost: float,
) -> None:
    """Post a phase completion update as a threaded reply."""
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=format_phase_update(phase, success, cost),
    )


def post_run_summary(
    client: Any,
    channel: str,
    thread_ts: str,
    status: str,
    total_cost: float,
    branch_name: str | None = None,
    pr_url: str | None = None,
) -> None:
    """Post the final run summary as a threaded reply."""
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=format_run_summary(status, total_cost, branch_name, pr_url),
    )


def react_to_message(
    client: Any,
    channel: str,
    timestamp: str,
    emoji: str,
) -> None:
    """Add an emoji reaction to a message."""
    client.reactions_add(
        channel=channel,
        timestamp=timestamp,
        name=emoji,
    )


# ---------------------------------------------------------------------------
# SlackUI — posts phase updates to Slack threads
# ---------------------------------------------------------------------------


class SlackUI:
    """Posts pipeline phase updates to a Slack thread.

    Implements the same interface as ``PhaseUI`` / ``NullUI`` from ``ui.py``
    but routes output to Slack threaded replies instead of the terminal.
    """

    def __init__(
        self,
        client: Any,
        channel: str,
        thread_ts: str,
    ) -> None:
        self._client = client
        self._channel = channel
        self._thread_ts = thread_ts

    def phase_header(
        self,
        phase_name: str,
        budget: float,
        model: str,
        extra: str = "",
    ) -> None:
        msg = f":gear: Starting *{phase_name}* phase (${budget:.2f} budget, {model})"
        if extra:
            msg += f" — {extra}"
        self._client.chat_postMessage(
            channel=self._channel,
            thread_ts=self._thread_ts,
            text=msg,
        )

    def phase_complete(self, cost: float, turns: int, duration_ms: int) -> None:
        secs = duration_ms // 1000
        self._client.chat_postMessage(
            channel=self._channel,
            thread_ts=self._thread_ts,
            text=f":white_check_mark: Phase completed — ${cost:.2f}, {turns} turns, {secs}s",
        )

    def phase_error(self, error: str) -> None:
        self._client.chat_postMessage(
            channel=self._channel,
            thread_ts=self._thread_ts,
            text=f":x: Phase failed: {error}",
        )

    def on_tool_start(self, *a: object) -> None:
        pass

    def on_tool_input_delta(self, *a: object) -> None:
        pass

    def on_tool_done(self) -> None:
        pass

    def on_text_delta(self, *a: object) -> None:
        pass

    def on_turn_complete(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Deduplication ledger
# ---------------------------------------------------------------------------


@dataclass
class SlackWatchState:
    """Persistent state for the Slack watcher process."""

    watch_id: str
    processed_messages: dict[str, str] = field(default_factory=dict)
    aggregate_cost_usd: float = 0.0
    runs_triggered: int = 0
    start_time_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    hourly_trigger_counts: dict[str, int] = field(default_factory=dict)

    def message_key(self, channel_id: str, message_ts: str) -> str:
        """Build the dedup key for a message."""
        return f"{channel_id}:{message_ts}"

    def is_processed(self, channel_id: str, message_ts: str) -> bool:
        """Check whether a message has already been processed."""
        return self.message_key(channel_id, message_ts) in self.processed_messages

    def mark_processed(self, channel_id: str, message_ts: str, run_id: str) -> None:
        """Record a message as processed."""
        key = self.message_key(channel_id, message_ts)
        self.processed_messages[key] = run_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "watch_id": self.watch_id,
            "processed_messages": dict(self.processed_messages),
            "aggregate_cost_usd": self.aggregate_cost_usd,
            "runs_triggered": self.runs_triggered,
            "start_time_iso": self.start_time_iso,
            "hourly_trigger_counts": dict(self.hourly_trigger_counts),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SlackWatchState:
        return cls(
            watch_id=data["watch_id"],
            processed_messages=dict(data.get("processed_messages", {})),
            aggregate_cost_usd=data.get("aggregate_cost_usd", 0.0),
            runs_triggered=data.get("runs_triggered", 0),
            start_time_iso=data.get("start_time_iso", ""),
            hourly_trigger_counts=dict(data.get("hourly_trigger_counts", {})),
        )


def save_watch_state(repo_root: Path, state: SlackWatchState) -> Path:
    """Persist watch state atomically using temp+rename pattern."""
    runs_dir = runs_dir_path(repo_root)
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"watch_state_{state.watch_id}.json"
    fd, tmp_path_str = tempfile.mkstemp(
        dir=str(runs_dir), suffix=".tmp", prefix="watch_state_",
    )
    fd_closed = False
    try:
        os.write(fd, json.dumps(state.to_dict(), indent=2).encode("utf-8"))
        os.close(fd)
        fd_closed = True
        os.replace(tmp_path_str, str(path))
    except BaseException:
        if not fd_closed:
            try:
                os.close(fd)
            except OSError:
                pass
        Path(tmp_path_str).unlink(missing_ok=True)
        raise
    return path


def load_watch_state(repo_root: Path, watch_id: str) -> SlackWatchState | None:
    """Load a watch state file by ID, or None if not found."""
    path = runs_dir_path(repo_root) / f"watch_state_{watch_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return SlackWatchState.from_dict(data)


def check_rate_limit(state: SlackWatchState, config: SlackConfig) -> bool:
    """Return True if under the ``max_runs_per_hour`` limit."""
    current_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    count = state.hourly_trigger_counts.get(current_hour, 0)
    return count < config.max_runs_per_hour


def increment_hourly_count(state: SlackWatchState) -> None:
    """Increment the trigger count for the current hour."""
    current_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    state.hourly_trigger_counts[current_hour] = (
        state.hourly_trigger_counts.get(current_hour, 0) + 1
    )


# ---------------------------------------------------------------------------
# Bolt app creation
# ---------------------------------------------------------------------------


def create_slack_app(config: SlackConfig) -> Any:
    """Create and configure a Slack Bolt app with Socket Mode.

    Raises ``ImportError`` if ``slack-bolt`` is not installed.
    Raises ``RuntimeError`` if required environment variables are missing.
    """
    try:
        from slack_bolt import App
    except ImportError:
        raise ImportError(
            "slack-bolt is not installed. "
            "Install it with: pip install 'colonyos[slack]'"
        )

    bot_token = os.environ.get("COLONYOS_SLACK_BOT_TOKEN", "").strip()
    app_token = os.environ.get("COLONYOS_SLACK_APP_TOKEN", "").strip()

    if not bot_token:
        raise RuntimeError(
            "COLONYOS_SLACK_BOT_TOKEN environment variable is not set."
        )
    if not app_token:
        raise RuntimeError(
            "COLONYOS_SLACK_APP_TOKEN environment variable is not set."
        )

    app = App(token=bot_token)
    return app


def start_socket_mode(app: Any) -> Any:
    """Start the Bolt app in Socket Mode.

    Returns the SocketModeHandler instance for lifecycle management.
    """
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    app_token = os.environ.get("COLONYOS_SLACK_APP_TOKEN", "").strip()
    handler = SocketModeHandler(app, app_token)
    return handler
