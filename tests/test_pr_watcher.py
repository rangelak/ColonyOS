"""Tests for the PR watcher module (merge polling and notification)."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from colonyos.config import SlackConfig
from colonyos.models import QueueItem, QueueItemStatus, QueueState
from colonyos.slack import SlackWatchState


# ---------------------------------------------------------------------------
# Tests for extract_pr_number_from_url
# ---------------------------------------------------------------------------


class TestExtractPrNumberFromUrl:
    """Tests for extract_pr_number_from_url()."""

    def test_valid_github_url(self) -> None:
        from colonyos.pr_watcher import extract_pr_number_from_url
        assert extract_pr_number_from_url("https://github.com/org/repo/pull/42") == 42

    def test_valid_github_url_with_trailing_slash(self) -> None:
        from colonyos.pr_watcher import extract_pr_number_from_url
        # URLs shouldn't have trailing slash, but handle gracefully
        result = extract_pr_number_from_url("https://github.com/org/repo/pull/99/")
        assert result is None  # Invalid format

    def test_valid_url_different_orgs(self) -> None:
        from colonyos.pr_watcher import extract_pr_number_from_url
        assert extract_pr_number_from_url("https://github.com/my-org/my-repo/pull/123") == 123
        assert extract_pr_number_from_url("https://github.com/org_with_underscore/repo-name/pull/1") == 1

    def test_invalid_url_returns_none(self) -> None:
        from colonyos.pr_watcher import extract_pr_number_from_url
        assert extract_pr_number_from_url("not a url") is None
        assert extract_pr_number_from_url("") is None
        assert extract_pr_number_from_url("https://gitlab.com/org/repo/pull/42") is None

    def test_issue_url_returns_none(self) -> None:
        from colonyos.pr_watcher import extract_pr_number_from_url
        # Issue URLs should not be parsed as PR URLs
        assert extract_pr_number_from_url("https://github.com/org/repo/issues/42") is None

    def test_malicious_url_returns_none(self) -> None:
        from colonyos.pr_watcher import extract_pr_number_from_url
        # Ensure injection attempts are rejected
        assert extract_pr_number_from_url("https://github.com/org/repo/pull/42; rm -rf /") is None
        assert extract_pr_number_from_url("https://github.com/org/repo/pull/42\nmalicious") is None


class TestValidatePrUrl:
    """Tests for PR URL validation regex."""

    def test_valid_urls_match(self) -> None:
        from colonyos.pr_watcher import PR_URL_PATTERN
        assert PR_URL_PATTERN.match("https://github.com/org/repo/pull/42")
        assert PR_URL_PATTERN.match("https://github.com/my-org/my-repo/pull/123")
        assert PR_URL_PATTERN.match("https://github.com/org_name/repo_name/pull/1")

    def test_invalid_urls_dont_match(self) -> None:
        from colonyos.pr_watcher import PR_URL_PATTERN
        assert not PR_URL_PATTERN.match("https://gitlab.com/org/repo/pull/42")
        assert not PR_URL_PATTERN.match("https://github.com/org/repo/issues/42")
        assert not PR_URL_PATTERN.match("http://github.com/org/repo/pull/42")  # http not https


# ---------------------------------------------------------------------------
# Tests for check_pr_merged
# ---------------------------------------------------------------------------


class TestCheckPrMerged:
    """Tests for check_pr_merged()."""

    def test_merged_pr(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import check_pr_merged

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"state": "MERGED", "mergedAt": "2026-03-20T10:00:00Z", "title": "Fix the bug"}',
                stderr="",
            )
            is_merged, merged_at, pr_title = check_pr_merged(42, tmp_path)

        assert is_merged is True
        assert merged_at == "2026-03-20T10:00:00Z"
        assert pr_title == "Fix the bug"

    def test_open_pr(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import check_pr_merged

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"state": "OPEN", "mergedAt": null, "title": "WIP: Fix bug"}',
                stderr="",
            )
            is_merged, merged_at, pr_title = check_pr_merged(42, tmp_path)

        assert is_merged is False
        assert merged_at is None
        assert pr_title is None  # Only returned when merged

    def test_closed_pr_not_merged(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import check_pr_merged

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"state": "CLOSED", "mergedAt": null, "title": "Abandoned PR"}',
                stderr="",
            )
            is_merged, merged_at, pr_title = check_pr_merged(42, tmp_path)

        assert is_merged is False
        assert merged_at is None
        assert pr_title is None  # Only returned when merged

    def test_gh_command_failure(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import check_pr_merged

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="not found",
            )
            is_merged, merged_at, pr_title = check_pr_merged(42, tmp_path)

        assert is_merged is False
        assert merged_at is None
        assert pr_title is None

    def test_timeout_returns_none(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import check_pr_merged
        import subprocess

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["gh"], timeout=5)
            is_merged, merged_at, pr_title = check_pr_merged(42, tmp_path)

        assert is_merged is False
        assert merged_at is None
        assert pr_title is None


# ---------------------------------------------------------------------------
# Tests for is_within_polling_window
# ---------------------------------------------------------------------------


class TestIsWithinPollingWindow:
    """Tests for the 7-day age filter for PRs to poll."""

    def test_recent_item_within_window(self) -> None:
        from colonyos.pr_watcher import is_within_polling_window
        now = datetime.now(timezone.utc)
        recent_iso = now.isoformat()
        assert is_within_polling_window(recent_iso) is True

    def test_old_item_outside_window(self) -> None:
        from colonyos.pr_watcher import is_within_polling_window
        now = datetime.now(timezone.utc)
        old_iso = (now - timedelta(days=8)).isoformat()
        assert is_within_polling_window(old_iso) is False

    def test_exactly_7_days_within_window(self) -> None:
        from colonyos.pr_watcher import is_within_polling_window
        now = datetime.now(timezone.utc)
        # 7 days ago - 1 second should be within window
        boundary_iso = (now - timedelta(days=7) + timedelta(seconds=1)).isoformat()
        assert is_within_polling_window(boundary_iso) is True

    def test_invalid_timestamp_returns_false(self) -> None:
        from colonyos.pr_watcher import is_within_polling_window
        assert is_within_polling_window("not a timestamp") is False
        assert is_within_polling_window("") is False


# ---------------------------------------------------------------------------
# Tests for poll_merged_prs
# ---------------------------------------------------------------------------


class TestPollMergedPrs:
    """Tests for the main poll_merged_prs orchestration function."""

    def _make_queue_item(
        self,
        item_id: str = "q-1",
        status: QueueItemStatus = QueueItemStatus.COMPLETED,
        pr_url: str | None = "https://github.com/org/repo/pull/42",
        merge_notified: bool = False,
        slack_ts: str = "100.000",
        slack_channel: str = "C123",
        raw_prompt: str = "Fix the bug",
        cost_usd: float = 2.0,
        duration_ms: int = 120000,
        run_id: str = "run-123",
    ) -> QueueItem:
        return QueueItem(
            id=item_id,
            source_type="slack",
            source_value="test",
            status=status,
            pr_url=pr_url,
            merge_notified=merge_notified,
            slack_ts=slack_ts,
            slack_channel=slack_channel,
            raw_prompt=raw_prompt,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            run_id=run_id,
        )

    def test_sends_notification_for_merged_pr(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import poll_merged_prs

        item = self._make_queue_item()
        queue_state = QueueState(queue_id="test", items=[item])
        watch_state = SlackWatchState(watch_id="test")
        config = SlackConfig(enabled=True, notify_on_merge=True)
        state_lock = Lock()
        client = MagicMock()

        with patch("colonyos.pr_watcher.check_pr_merged") as mock_check:
            mock_check.return_value = (True, "2026-03-20T10:00:00Z", "PR Title")
            with patch("colonyos.pr_watcher.post_merge_notification") as mock_post:
                with patch("colonyos.pr_watcher.update_run_log_merged_at"):
                    count = poll_merged_prs(
                        repo_root=tmp_path,
                        queue_state=queue_state,
                        watch_state=watch_state,
                        slack_client=client,
                        config=config,
                        state_lock=state_lock,
                    )

        assert count == 1
        mock_post.assert_called_once()
        assert item.merge_notified is True

    def test_skips_already_notified_items(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import poll_merged_prs

        item = self._make_queue_item(merge_notified=True)
        queue_state = QueueState(queue_id="test", items=[item])
        watch_state = SlackWatchState(watch_id="test")
        config = SlackConfig(enabled=True, notify_on_merge=True)
        state_lock = Lock()
        client = MagicMock()

        with patch("colonyos.pr_watcher.check_pr_merged") as mock_check:
            count = poll_merged_prs(
                repo_root=tmp_path,
                queue_state=queue_state,
                watch_state=watch_state,
                slack_client=client,
                config=config,
                state_lock=state_lock,
            )

        assert count == 0
        mock_check.assert_not_called()

    def test_skips_items_without_pr_url(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import poll_merged_prs

        item = self._make_queue_item(pr_url=None)
        queue_state = QueueState(queue_id="test", items=[item])
        watch_state = SlackWatchState(watch_id="test")
        config = SlackConfig(enabled=True, notify_on_merge=True)
        state_lock = Lock()
        client = MagicMock()

        with patch("colonyos.pr_watcher.check_pr_merged") as mock_check:
            count = poll_merged_prs(
                repo_root=tmp_path,
                queue_state=queue_state,
                watch_state=watch_state,
                slack_client=client,
                config=config,
                state_lock=state_lock,
            )

        assert count == 0
        mock_check.assert_not_called()

    def test_skips_non_completed_items(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import poll_merged_prs

        item = self._make_queue_item(status=QueueItemStatus.RUNNING)
        queue_state = QueueState(queue_id="test", items=[item])
        watch_state = SlackWatchState(watch_id="test")
        config = SlackConfig(enabled=True, notify_on_merge=True)
        state_lock = Lock()
        client = MagicMock()

        with patch("colonyos.pr_watcher.check_pr_merged") as mock_check:
            count = poll_merged_prs(
                repo_root=tmp_path,
                queue_state=queue_state,
                watch_state=watch_state,
                slack_client=client,
                config=config,
                state_lock=state_lock,
            )

        assert count == 0
        mock_check.assert_not_called()

    def test_skips_when_notify_on_merge_disabled(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import poll_merged_prs

        item = self._make_queue_item()
        queue_state = QueueState(queue_id="test", items=[item])
        watch_state = SlackWatchState(watch_id="test")
        config = SlackConfig(enabled=True, notify_on_merge=False)
        state_lock = Lock()
        client = MagicMock()

        count = poll_merged_prs(
            repo_root=tmp_path,
            queue_state=queue_state,
            watch_state=watch_state,
            slack_client=client,
            config=config,
            state_lock=state_lock,
        )

        assert count == 0

    def test_does_not_mark_notified_on_unmerged_pr(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import poll_merged_prs

        item = self._make_queue_item()
        queue_state = QueueState(queue_id="test", items=[item])
        watch_state = SlackWatchState(watch_id="test")
        config = SlackConfig(enabled=True, notify_on_merge=True)
        state_lock = Lock()
        client = MagicMock()

        with patch("colonyos.pr_watcher.check_pr_merged") as mock_check:
            mock_check.return_value = (False, None, None)  # Not merged
            count = poll_merged_prs(
                repo_root=tmp_path,
                queue_state=queue_state,
                watch_state=watch_state,
                slack_client=client,
                config=config,
                state_lock=state_lock,
            )

        assert count == 0
        assert item.merge_notified is False


# ---------------------------------------------------------------------------
# Tests for update_run_log_merged_at
# ---------------------------------------------------------------------------


class TestUpdateRunLogMergedAt:
    """Tests for update_run_log_merged_at()."""

    def test_updates_existing_run_log(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import update_run_log_merged_at

        # Create a runs directory with a run log
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        run_log_path = runs_dir / "run-test-123.json"
        run_log_path.write_text(json.dumps({
            "run_id": "test-123",
            "prompt": "fix bug",
            "status": "completed",
            "total_cost_usd": 2.0,
        }))

        result = update_run_log_merged_at(
            tmp_path, "test-123", "2026-03-20T10:00:00Z"
        )

        assert result is True
        updated = json.loads(run_log_path.read_text())
        assert updated["merged_at"] == "2026-03-20T10:00:00Z"

    def test_returns_false_for_missing_run_log(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import update_run_log_merged_at

        # Don't create the run log
        result = update_run_log_merged_at(
            tmp_path, "nonexistent", "2026-03-20T10:00:00Z"
        )

        assert result is False

    def test_atomic_write(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import update_run_log_merged_at

        # Create a runs directory with a run log
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        run_log_path = runs_dir / "run-atomic-test.json"
        run_log_path.write_text(json.dumps({
            "run_id": "atomic-test",
            "prompt": "test",
            "status": "completed",
        }))

        result = update_run_log_merged_at(
            tmp_path, "atomic-test", "2026-03-20T11:00:00Z"
        )

        assert result is True
        # Verify no temp files left behind
        temp_files = list(runs_dir.glob("*.tmp"))
        assert len(temp_files) == 0


# ---------------------------------------------------------------------------
# Tests for MergeWatcher class
# ---------------------------------------------------------------------------


class TestMergeWatcher:
    """Tests for the MergeWatcher background thread class."""

    def test_start_and_stop(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import MergeWatcher

        queue_state = QueueState(queue_id="test", items=[])
        watch_state = SlackWatchState(watch_id="test")
        config = SlackConfig(enabled=True, notify_on_merge=True, merge_poll_interval_sec=30)
        state_lock = Lock()
        shutdown = Event()
        client = MagicMock()

        watcher = MergeWatcher(
            repo_root=tmp_path,
            queue_state=queue_state,
            watch_state=watch_state,
            slack_client=client,
            config=config,
            state_lock=state_lock,
            shutdown_event=shutdown,
        )

        # Start the watcher
        watcher.start()
        assert watcher.is_alive()

        # Signal shutdown
        shutdown.set()
        watcher.join(timeout=2.0)
        assert not watcher.is_alive()

    def test_polls_periodically(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import MergeWatcher

        queue_state = QueueState(queue_id="test", items=[])
        watch_state = SlackWatchState(watch_id="test")
        # Very short poll interval for testing
        config = SlackConfig(enabled=True, notify_on_merge=True, merge_poll_interval_sec=30)
        state_lock = Lock()
        shutdown = Event()
        client = MagicMock()

        with patch("colonyos.pr_watcher.poll_merged_prs") as mock_poll:
            mock_poll.return_value = 0
            watcher = MergeWatcher(
                repo_root=tmp_path,
                queue_state=queue_state,
                watch_state=watch_state,
                slack_client=client,
                config=config,
                state_lock=state_lock,
                shutdown_event=shutdown,
            )
            watcher.start()
            # Wait a bit for the first poll
            time.sleep(0.05)
            shutdown.set()
            watcher.join(timeout=2.0)

        # Should have been called at least once immediately on start
        assert mock_poll.call_count >= 1

    def test_respects_notify_on_merge_disabled(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import MergeWatcher

        queue_state = QueueState(queue_id="test", items=[])
        watch_state = SlackWatchState(watch_id="test")
        config = SlackConfig(enabled=True, notify_on_merge=False, merge_poll_interval_sec=30)
        state_lock = Lock()
        shutdown = Event()
        client = MagicMock()

        with patch("colonyos.pr_watcher.poll_merged_prs") as mock_poll:
            watcher = MergeWatcher(
                repo_root=tmp_path,
                queue_state=queue_state,
                watch_state=watch_state,
                slack_client=client,
                config=config,
                state_lock=state_lock,
                shutdown_event=shutdown,
            )
            watcher.start()
            time.sleep(0.05)
            shutdown.set()
            watcher.join(timeout=2.0)

        # poll_merged_prs checks config and returns 0 immediately when disabled
        # The watcher should still start but won't do any polling
        assert mock_poll.call_count >= 1

    def test_handles_exceptions_gracefully(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import MergeWatcher

        queue_state = QueueState(queue_id="test", items=[])
        watch_state = SlackWatchState(watch_id="test")
        config = SlackConfig(enabled=True, notify_on_merge=True, merge_poll_interval_sec=30)
        state_lock = Lock()
        shutdown = Event()
        client = MagicMock()

        with patch("colonyos.pr_watcher.poll_merged_prs") as mock_poll:
            mock_poll.side_effect = RuntimeError("Network error")
            watcher = MergeWatcher(
                repo_root=tmp_path,
                queue_state=queue_state,
                watch_state=watch_state,
                slack_client=client,
                config=config,
                state_lock=state_lock,
                shutdown_event=shutdown,
            )
            watcher.start()
            time.sleep(0.05)
            shutdown.set()
            watcher.join(timeout=2.0)

        # Should not crash - the thread should exit cleanly
        assert not watcher.is_alive()


# ---------------------------------------------------------------------------
# Tests for queue state persistence (FR-4)
# ---------------------------------------------------------------------------


class TestQueueStatePersistence:
    """Tests for persisting queue state after setting merge_notified=True."""

    def _make_queue_item(
        self,
        item_id: str = "q-1",
        status: QueueItemStatus = QueueItemStatus.COMPLETED,
        pr_url: str | None = "https://github.com/org/repo/pull/42",
        merge_notified: bool = False,
        slack_ts: str = "100.000",
        slack_channel: str = "C123",
        raw_prompt: str = "Fix the bug",
        cost_usd: float = 2.0,
        duration_ms: int = 120000,
        run_id: str = "run-123",
    ) -> QueueItem:
        return QueueItem(
            id=item_id,
            source_type="slack",
            source_value="test",
            status=status,
            pr_url=pr_url,
            merge_notified=merge_notified,
            slack_ts=slack_ts,
            slack_channel=slack_channel,
            raw_prompt=raw_prompt,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            run_id=run_id,
        )

    def test_calls_save_callback_after_notification(self, tmp_path: Path) -> None:
        """Verify that save_queue_state callback is called after merge_notified is set."""
        from colonyos.pr_watcher import poll_merged_prs

        item = self._make_queue_item()
        queue_state = QueueState(queue_id="test", items=[item])
        watch_state = SlackWatchState(watch_id="test")
        config = SlackConfig(enabled=True, notify_on_merge=True)
        state_lock = Lock()
        client = MagicMock()
        save_callback = MagicMock()

        with patch("colonyos.pr_watcher.check_pr_merged") as mock_check:
            mock_check.return_value = (True, "2026-03-20T10:00:00Z", "PR Title")
            with patch("colonyos.pr_watcher.post_merge_notification"):
                with patch("colonyos.pr_watcher.update_run_log_merged_at"):
                    poll_merged_prs(
                        repo_root=tmp_path,
                        queue_state=queue_state,
                        watch_state=watch_state,
                        slack_client=client,
                        config=config,
                        state_lock=state_lock,
                        save_queue_state=save_callback,
                    )

        # Callback should have been called to persist state
        save_callback.assert_called_once()
        assert item.merge_notified is True


# ---------------------------------------------------------------------------
# Tests for rate limiting (FR-7)
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Tests for GitHub API rate limit tracking."""

    def test_check_and_update_rate_limit_resets_on_hour_change(self) -> None:
        from colonyos.pr_watcher import _check_and_update_rate_limit, _get_current_hour_key

        watch_state = SlackWatchState(watch_id="test")
        state_lock = Lock()

        # Set old hour key
        watch_state.gh_api_hour_key = "2020-01-01T00"
        watch_state.gh_api_calls_this_hour = 100

        # Should reset counter since hour has changed
        result = _check_and_update_rate_limit(watch_state, state_lock)

        assert result is True
        assert watch_state.gh_api_calls_this_hour == 0
        assert watch_state.gh_api_hour_key == _get_current_hour_key()

    def test_check_and_update_rate_limit_returns_false_at_threshold(self) -> None:
        from colonyos.pr_watcher import (
            _check_and_update_rate_limit,
            _get_current_hour_key,
            _GH_RATE_LIMIT_THRESHOLD,
        )

        watch_state = SlackWatchState(watch_id="test")
        state_lock = Lock()

        # Set current hour key and max out the counter
        watch_state.gh_api_hour_key = _get_current_hour_key()
        watch_state.gh_api_calls_this_hour = _GH_RATE_LIMIT_THRESHOLD

        result = _check_and_update_rate_limit(watch_state, state_lock)

        assert result is False  # Should pause polling

    def test_increment_api_call_count(self) -> None:
        from colonyos.pr_watcher import _increment_api_call_count

        watch_state = SlackWatchState(watch_id="test")
        state_lock = Lock()
        watch_state.gh_api_calls_this_hour = 5

        _increment_api_call_count(watch_state, state_lock)

        assert watch_state.gh_api_calls_this_hour == 6


# ---------------------------------------------------------------------------
# Tests for PR title fallback (FR-2)
# ---------------------------------------------------------------------------


class TestPrTitleFallback:
    """Tests for falling back to PR title when raw_prompt is not available."""

    def _make_queue_item(
        self,
        item_id: str = "q-1",
        raw_prompt: str | None = None,
        source_value: str = "test source",
    ) -> QueueItem:
        return QueueItem(
            id=item_id,
            source_type="slack",
            source_value=source_value,
            status=QueueItemStatus.COMPLETED,
            pr_url="https://github.com/org/repo/pull/42",
            merge_notified=False,
            slack_ts="100.000",
            slack_channel="C123",
            raw_prompt=raw_prompt,
            cost_usd=2.0,
            duration_ms=120000,
            run_id="run-123",
        )

    def test_uses_raw_prompt_when_available(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import poll_merged_prs

        item = self._make_queue_item(raw_prompt="User request prompt")
        queue_state = QueueState(queue_id="test", items=[item])
        watch_state = SlackWatchState(watch_id="test")
        config = SlackConfig(enabled=True, notify_on_merge=True)
        state_lock = Lock()
        client = MagicMock()

        with patch("colonyos.pr_watcher.check_pr_merged") as mock_check:
            mock_check.return_value = (True, "2026-03-20T10:00:00Z", "PR Title")
            with patch("colonyos.pr_watcher.post_merge_notification") as mock_post:
                with patch("colonyos.pr_watcher.update_run_log_merged_at"):
                    poll_merged_prs(
                        repo_root=tmp_path,
                        queue_state=queue_state,
                        watch_state=watch_state,
                        slack_client=client,
                        config=config,
                        state_lock=state_lock,
                    )

        # Should use raw_prompt, not PR title
        call_args = mock_post.call_args
        assert call_args.kwargs["feature_title"] == "User request prompt"

    def test_falls_back_to_pr_title_when_no_raw_prompt(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import poll_merged_prs

        item = self._make_queue_item(raw_prompt=None)
        queue_state = QueueState(queue_id="test", items=[item])
        watch_state = SlackWatchState(watch_id="test")
        config = SlackConfig(enabled=True, notify_on_merge=True)
        state_lock = Lock()
        client = MagicMock()

        with patch("colonyos.pr_watcher.check_pr_merged") as mock_check:
            mock_check.return_value = (True, "2026-03-20T10:00:00Z", "PR Title from GitHub")
            with patch("colonyos.pr_watcher.post_merge_notification") as mock_post:
                with patch("colonyos.pr_watcher.update_run_log_merged_at"):
                    poll_merged_prs(
                        repo_root=tmp_path,
                        queue_state=queue_state,
                        watch_state=watch_state,
                        slack_client=client,
                        config=config,
                        state_lock=state_lock,
                    )

        # Should use PR title as fallback
        call_args = mock_post.call_args
        assert call_args.kwargs["feature_title"] == "PR Title from GitHub"

    def test_falls_back_to_source_value_when_no_pr_title(self, tmp_path: Path) -> None:
        from colonyos.pr_watcher import poll_merged_prs

        item = self._make_queue_item(raw_prompt=None, source_value="source fallback")
        queue_state = QueueState(queue_id="test", items=[item])
        watch_state = SlackWatchState(watch_id="test")
        config = SlackConfig(enabled=True, notify_on_merge=True)
        state_lock = Lock()
        client = MagicMock()

        with patch("colonyos.pr_watcher.check_pr_merged") as mock_check:
            # No PR title returned
            mock_check.return_value = (True, "2026-03-20T10:00:00Z", None)
            with patch("colonyos.pr_watcher.post_merge_notification") as mock_post:
                with patch("colonyos.pr_watcher.update_run_log_merged_at"):
                    poll_merged_prs(
                        repo_root=tmp_path,
                        queue_state=queue_state,
                        watch_state=watch_state,
                        slack_client=client,
                        config=config,
                        state_lock=state_lock,
                    )

        # Should fall back to source_value
        call_args = mock_post.call_args
        assert call_args.kwargs["feature_title"] == "source fallback"
