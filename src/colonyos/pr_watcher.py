"""PR Lifecycle Watcher for ColonyOS.

This module provides merge polling logic that monitors completed PRs and posts
notifications back to Slack when they are merged. It is designed to run as a
background thread within the `colonyos watch` command.

Key components:
- extract_pr_number_from_url: Parse PR number from GitHub URL
- check_pr_merged: Check if a PR has been merged via `gh pr view`
- poll_merged_prs: Main orchestration function that polls all eligible items
- update_run_log_merged_at: Update RunLog with merge timestamp

Security considerations:
- PR URLs are validated against a strict regex before being passed to `gh`
- Only PRs from the last 7 days are polled to prevent unbounded state growth
- All merge events are logged with structured AUDIT logging
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import TYPE_CHECKING, Any

from colonyos.config import SlackConfig, runs_dir_path
from colonyos.slack import post_merge_notification

if TYPE_CHECKING:
    from colonyos.models import QueueItem, QueueState
    from colonyos.slack import SlackClient, SlackWatchState

logger = logging.getLogger(__name__)

# Strict regex for GitHub PR URLs - validates format before passing to `gh`
# Security: Prevents injection attacks via malicious URLs
PR_URL_PATTERN = re.compile(
    r"^https://github\.com/[\w.-]+/[\w.-]+/pull/\d+$"
)

# Maximum age for PRs to poll (7 days)
_POLLING_WINDOW_DAYS = 7


def extract_pr_number_from_url(pr_url: str) -> int | None:
    """Extract PR number from a GitHub PR URL.

    Args:
        pr_url: GitHub PR URL (e.g., "https://github.com/org/repo/pull/42")

    Returns:
        The PR number, or None if the URL is invalid.

    Security:
        Uses strict regex validation to prevent injection attacks.
    """
    if not pr_url or not PR_URL_PATTERN.match(pr_url):
        return None

    # Extract the number from the end of the URL
    # URL is already validated, so this is safe
    parts = pr_url.rstrip("/").split("/")
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return None


def check_pr_merged(pr_number: int, repo_root: Path) -> tuple[bool, str | None]:
    """Check if a PR has been merged via `gh pr view`.

    Args:
        pr_number: The PR number to check.
        repo_root: Repository root directory (used as cwd for `gh`).

    Returns:
        A tuple of (is_merged, merged_at_iso). If the PR is merged,
        merged_at_iso contains the ISO timestamp from GitHub's mergedAt field.
        Otherwise, merged_at_iso is None.
    """
    try:
        result = subprocess.run(
            [
                "gh", "pr", "view", str(pr_number),
                "--json", "state,mergedAt",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
    except FileNotFoundError:
        logger.warning("GitHub CLI (gh) not found")
        return False, None
    except subprocess.TimeoutExpired:
        logger.warning("Timed out checking PR #%d", pr_number)
        return False, None

    if result.returncode != 0:
        logger.warning(
            "Failed to check PR #%d: %s",
            pr_number,
            result.stderr.strip()[:200],
        )
        return False, None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("Failed to parse gh pr view output for PR #%d", pr_number)
        return False, None

    state = data.get("state", "").upper()
    merged_at = data.get("mergedAt")

    if state == "MERGED" and merged_at:
        return True, merged_at

    return False, None


def is_within_polling_window(added_at_iso: str) -> bool:
    """Check if an item is within the 7-day polling window.

    Args:
        added_at_iso: ISO timestamp when the item was added.

    Returns:
        True if the item is within 7 days old, False otherwise.
    """
    if not added_at_iso:
        return False

    try:
        # Parse ISO timestamp, handling both with and without timezone
        if added_at_iso.endswith("Z"):
            added_at_iso = added_at_iso[:-1] + "+00:00"
        added_at = datetime.fromisoformat(added_at_iso)
        if added_at.tzinfo is None:
            added_at = added_at.replace(tzinfo=timezone.utc)
    except ValueError:
        logger.warning("Invalid timestamp format: %s", added_at_iso[:50])
        return False

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=_POLLING_WINDOW_DAYS)

    return added_at >= window_start


def update_run_log_merged_at(
    repo_root: Path,
    run_id: str,
    merged_at: str,
) -> bool:
    """Update a RunLog with the merged_at timestamp.

    Uses atomic write pattern (temp file + rename) to prevent corruption.

    Args:
        repo_root: Repository root directory.
        run_id: The run ID to update.
        merged_at: ISO timestamp when the PR was merged.

    Returns:
        True if the update was successful, False otherwise.
    """
    runs_dir = runs_dir_path(repo_root)
    run_log_path = runs_dir / f"run-{run_id}.json"

    if not run_log_path.exists():
        logger.warning(
            "RunLog not found for run_id=%s, cannot update merged_at",
            run_id,
        )
        return False

    try:
        data = json.loads(run_log_path.read_text(encoding="utf-8"))
        data["merged_at"] = merged_at

        # Atomic write: temp file + rename
        fd, tmp_path_str = tempfile.mkstemp(
            dir=str(runs_dir), suffix=".tmp", prefix="run_log_",
        )
        fd_closed = False
        try:
            os.write(fd, json.dumps(data, indent=2).encode("utf-8"))
            os.close(fd)
            fd_closed = True
            os.replace(tmp_path_str, str(run_log_path))
        except BaseException:
            if not fd_closed:
                try:
                    os.close(fd)
                except OSError:
                    pass
            Path(tmp_path_str).unlink(missing_ok=True)
            raise

        logger.info(
            "AUDIT: run_log_updated run_id=%s merged_at=%s",
            run_id,
            merged_at,
        )
        return True

    except Exception as exc:
        logger.warning(
            "Failed to update RunLog for run_id=%s: %s",
            run_id,
            str(exc)[:200],
        )
        return False


def poll_merged_prs(
    repo_root: Path,
    queue_state: "QueueState",
    watch_state: "SlackWatchState",
    slack_client: "SlackClient",
    config: SlackConfig,
    state_lock: Lock,
) -> int:
    """Poll for merged PRs and send notifications.

    This function:
    1. Filters queue items to find eligible PRs (completed, with pr_url, not notified)
    2. Checks each PR's merge status via `gh pr view`
    3. Posts notifications for merged PRs
    4. Updates RunLog with merged_at timestamp
    5. Marks items as notified

    Thread safety:
    - Acquires state_lock when reading/writing queue state
    - Releases lock during GitHub API calls to prevent blocking Slack handlers

    Args:
        repo_root: Repository root directory.
        queue_state: Current queue state.
        watch_state: Current watch state.
        slack_client: Slack client instance.
        config: Slack configuration.
        state_lock: Threading lock for state access.

    Returns:
        Number of notifications sent.
    """
    from colonyos.models import QueueItemStatus

    # Check if notifications are enabled
    if not config.notify_on_merge:
        return 0

    # Snapshot items to check under lock
    with state_lock:
        items_to_check: list[tuple[QueueItem, int]] = []
        for idx, item in enumerate(queue_state.items):
            if (
                item.status == QueueItemStatus.COMPLETED
                and item.pr_url
                and not item.merge_notified
                and is_within_polling_window(item.added_at)
            ):
                items_to_check.append((item, idx))

    if not items_to_check:
        return 0

    notifications_sent = 0

    # Check each item (lock released during API calls)
    for item, idx in items_to_check:
        # Validate PR URL before calling gh
        pr_number = extract_pr_number_from_url(item.pr_url or "")
        if pr_number is None:
            logger.warning(
                "Invalid PR URL for item %s: %s",
                item.id,
                (item.pr_url or "")[:100],
            )
            continue

        # Check if PR is merged (network call, no lock held)
        is_merged, merged_at = check_pr_merged(pr_number, repo_root)

        if not is_merged:
            continue

        logger.info(
            "AUDIT: pr_merge_detected pr_url=%s item_id=%s merged_at=%s",
            item.pr_url,
            item.id,
            merged_at,
        )

        # Get feature title from raw_prompt or fall back to source_value
        feature_title = item.raw_prompt or item.source_value or "Feature"

        # Post notification
        try:
            if item.slack_channel and item.slack_ts:
                post_merge_notification(
                    client=slack_client,
                    channel=item.slack_channel,
                    thread_ts=item.slack_ts,
                    pr_number=pr_number,
                    feature_title=feature_title,
                    cost_usd=item.cost_usd,
                    duration_ms=item.duration_ms,
                )
                logger.info(
                    "AUDIT: merge_notification_sent channel=%s thread_ts=%s pr_url=%s",
                    item.slack_channel,
                    item.slack_ts,
                    item.pr_url,
                )
                notifications_sent += 1

                # Update RunLog (best effort)
                if item.run_id and merged_at:
                    update_run_log_merged_at(repo_root, item.run_id, merged_at)

                # Mark as notified under lock
                with state_lock:
                    queue_state.items[idx].merge_notified = True

        except Exception as exc:
            # Don't mark as notified on failure - will retry next cycle
            logger.warning(
                "Failed to send merge notification for item %s: %s",
                item.id,
                str(exc)[:200],
            )

    return notifications_sent


class MergeWatcher(Thread):
    """Background thread that polls for merged PRs and sends notifications.

    This thread runs alongside the main Slack event loop in the `watch` command,
    periodically checking for merged PRs and posting notifications to the original
    Slack threads.

    Lifecycle:
    - Created after Slack client is available
    - Polls immediately on start, then every `merge_poll_interval_sec` seconds
    - Exits cleanly when `shutdown_event` is set

    Thread safety:
    - Uses `state_lock` when accessing queue/watch state
    - All state mutations are protected

    Usage:
        watcher = MergeWatcher(...)
        watcher.start()
        # ... later ...
        shutdown_event.set()
        watcher.join()
    """

    def __init__(
        self,
        repo_root: Path,
        queue_state: "QueueState",
        watch_state: "SlackWatchState",
        slack_client: "SlackClient",
        config: SlackConfig,
        state_lock: Lock,
        shutdown_event: Event,
    ) -> None:
        super().__init__(daemon=True, name="merge-watcher")
        self._repo_root = repo_root
        self._queue_state = queue_state
        self._watch_state = watch_state
        self._slack_client = slack_client
        self._config = config
        self._state_lock = state_lock
        self._shutdown = shutdown_event

    def run(self) -> None:
        """Main thread loop."""
        logger.info(
            "MergeWatcher started (poll_interval=%d sec)",
            self._config.merge_poll_interval_sec,
        )

        while not self._shutdown.is_set():
            try:
                count = poll_merged_prs(
                    repo_root=self._repo_root,
                    queue_state=self._queue_state,
                    watch_state=self._watch_state,
                    slack_client=self._slack_client,
                    config=self._config,
                    state_lock=self._state_lock,
                )
                if count > 0:
                    logger.info(
                        "AUDIT: merge_poll_cycle notifications_sent=%d",
                        count,
                    )
            except Exception as exc:
                # Log and continue - don't let exceptions kill the thread
                logger.warning(
                    "MergeWatcher poll error: %s",
                    str(exc)[:200],
                )

            # Wait for next poll cycle or shutdown
            self._shutdown.wait(timeout=self._config.merge_poll_interval_sec)

        logger.info("MergeWatcher shutting down")
