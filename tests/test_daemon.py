"""Tests for daemon orchestration."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from colonyos.cleanup import ComplexityCategory, FileComplexity
from colonyos.config import ColonyConfig, DaemonConfig
from colonyos.daemon import Daemon, DaemonError, _CombinedUI
from colonyos.daemon_state import DaemonState, save_daemon_state
from colonyos.models import (
    Phase,
    PhaseResult,
    PreflightError,
    QueueItem,
    QueueItemStatus,
    QueueState,
    RunLog,
    RunStatus,
)
from colonyos.recovery import PreservationResult
from colonyos.runtime_lock import RuntimeBusyError
from colonyos.slack import SlackWatchState, save_watch_state
from colonyos.tui.adapter import ToolLineMsg
from colonyos.tui.monitor_protocol import decode_monitor_event_line


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / ".colonyos").mkdir()
    return tmp_path


@pytest.fixture
def config() -> ColonyConfig:
    return ColonyConfig(daemon=DaemonConfig(daily_budget_usd=50.0))


@pytest.fixture
def daemon_instance(tmp_repo: Path, config: ColonyConfig) -> Daemon:
    return Daemon(tmp_repo, config, dry_run=True)


class TestDaemonInit:
    def test_creates_with_defaults(self, tmp_repo: Path, config: ColonyConfig):
        d = Daemon(tmp_repo, config)
        assert d.repo_root == tmp_repo
        assert d.daily_budget == 50.0
        assert d.dry_run is False

    def test_cli_budget_override(self, tmp_repo: Path, config: ColonyConfig):
        d = Daemon(tmp_repo, config, max_budget=25.0)
        assert d.daily_budget == 25.0

    def test_unlimited_budget_override(self, tmp_repo: Path, config: ColonyConfig):
        d = Daemon(tmp_repo, config, unlimited_budget=True)
        assert d.daily_budget is None

    def test_cli_max_hours(self, tmp_repo: Path, config: ColonyConfig):
        d = Daemon(tmp_repo, config, max_hours=8.0)
        assert d.max_hours == 8.0


class TestCrashRecovery:
    def test_marks_running_items_as_failed(self, tmp_repo: Path, config: ColonyConfig):
        # Create queue with a RUNNING item
        queue = QueueState(
            queue_id="test-q",
            items=[
                QueueItem(
                    id="item-1",
                    source_type="prompt",
                    source_value="test",
                    status=QueueItemStatus.RUNNING,
                ),
                QueueItem(
                    id="item-2",
                    source_type="prompt",
                    source_value="test2",
                    status=QueueItemStatus.PENDING,
                ),
            ],
        )
        queue_path = tmp_repo / ".colonyos" / "queue.json"
        queue_path.write_text(json.dumps(queue.to_dict()), encoding="utf-8")

        d = Daemon(tmp_repo, config, dry_run=True)

        with patch("colonyos.recovery.git_status_porcelain", return_value=""), \
             patch("colonyos.recovery.preserve_and_reset_worktree"):
            d._recover_from_crash()

        # Item 1 should be FAILED, item 2 still PENDING
        assert d._queue_state.items[0].status == QueueItemStatus.FAILED
        assert d._queue_state.items[0].error == "daemon crash recovery"
        assert d._queue_state.items[1].status == QueueItemStatus.PENDING

    def test_dirty_startup_recovery_writes_incident(self, tmp_repo: Path, config: ColonyConfig):
        d = Daemon(tmp_repo, config, dry_run=True)
        preserve_result = PreservationResult(
            snapshot_dir=tmp_repo / ".colonyos" / "recovery" / "daemon_crash_recovery",
            preservation_mode="stash",
            stash_message="stash-msg",
        )

        with patch("colonyos.recovery.git_status_porcelain", return_value=" M foo.py"), \
             patch("colonyos.recovery.preserve_and_reset_worktree", return_value=preserve_result):
            d._recover_from_crash()

        recovery_files = sorted((tmp_repo / ".colonyos" / "recovery").glob("*.md"))
        assert recovery_files
        summary = recovery_files[0].read_text(encoding="utf-8")
        assert "dirty worktree" in summary.lower()
        assert "stash-msg" in summary


class TestPriorityQueue:
    def test_selects_highest_priority(self, daemon_instance: Daemon):
        daemon_instance._queue_state.items = [
            QueueItem(id="low", source_type="cleanup", source_value="x", status=QueueItemStatus.PENDING, priority=3),
            QueueItem(id="high", source_type="slack", source_value="y", status=QueueItemStatus.PENDING, priority=0),
            QueueItem(id="med", source_type="issue", source_value="z", status=QueueItemStatus.PENDING, priority=1),
        ]
        item = daemon_instance._next_pending_item()
        assert item is not None
        assert item.id == "high"

    def test_fifo_within_same_priority(self, daemon_instance: Daemon):
        daemon_instance._queue_state.items = [
            QueueItem(id="second", source_type="slack", source_value="b", status=QueueItemStatus.PENDING, priority=1, added_at="2026-01-01T00:01:00+00:00"),
            QueueItem(id="first", source_type="slack", source_value="a", status=QueueItemStatus.PENDING, priority=1, added_at="2026-01-01T00:00:00+00:00"),
        ]
        item = daemon_instance._next_pending_item()
        assert item is not None
        assert item.id == "first"

    def test_skips_non_pending(self, daemon_instance: Daemon):
        daemon_instance._queue_state.items = [
            QueueItem(id="done", source_type="prompt", source_value="x", status=QueueItemStatus.COMPLETED, priority=0),
            QueueItem(id="pending", source_type="prompt", source_value="y", status=QueueItemStatus.PENDING, priority=1),
        ]
        item = daemon_instance._next_pending_item()
        assert item is not None
        assert item.id == "pending"

    def test_returns_none_when_empty(self, daemon_instance: Daemon):
        daemon_instance._queue_state.items = []
        assert daemon_instance._next_pending_item() is None

    def test_starvation_promotion(self, daemon_instance: Daemon):
        old_time = (datetime.now(timezone.utc) - __import__("datetime").timedelta(hours=25)).isoformat()
        daemon_instance._queue_state.items = [
            QueueItem(id="old", source_type="cleanup", source_value="x", status=QueueItemStatus.PENDING, priority=3, added_at=old_time),
        ]
        item = daemon_instance._next_pending_item()
        assert item is not None
        assert item.priority == 1  # Cleanup defaults to P2, age promotes it to P1

    def test_tick_does_not_schedule_ceo_after_executing_item(self, daemon_instance: Daemon):
        daemon_instance._pipeline_running = False
        daemon_instance._last_github_poll_time = -1e9
        daemon_instance._last_cleanup_time = -1e9
        daemon_instance._last_reprioritize_time = -1e9
        daemon_instance._last_heartbeat_time = -1e9
        daemon_instance._last_outcome_poll_time = -1e9
        with patch.object(daemon_instance, "_try_execute_next", return_value=True) as mock_execute, \
             patch.object(daemon_instance, "_schedule_ceo") as mock_ceo, \
             patch.object(daemon_instance, "_poll_github_issues") as mock_poll, \
             patch.object(daemon_instance, "_schedule_cleanup") as mock_cleanup, \
             patch.object(daemon_instance, "_reprioritize_queue") as mock_reprioritize, \
             patch.object(daemon_instance, "_post_heartbeat") as mock_heartbeat, \
             patch.object(daemon_instance, "_poll_pr_outcomes") as mock_outcomes, \
             patch.object(daemon_instance, "_post_daily_digest_if_due") as mock_digest, \
             patch.object(daemon_instance, "_sync_stale_prs") as mock_sync:
            daemon_instance._tick()

        mock_execute.assert_called_once()
        mock_ceo.assert_not_called()
        mock_poll.assert_called_once()
        mock_cleanup.assert_called_once()
        mock_reprioritize.assert_called_once()
        mock_heartbeat.assert_called_once()
        mock_outcomes.assert_called_once()
        mock_digest.assert_called_once()
        # PR sync is disabled by default, so not called
        mock_sync.assert_not_called()


class TestBudgetEnforcement:
    def test_skips_execution_when_budget_exhausted(self, daemon_instance: Daemon):
        daemon_instance._state.daily_spend_usd = 50.0
        daemon_instance._queue_state.items = [
            QueueItem(id="item", source_type="prompt", source_value="x", status=QueueItemStatus.PENDING, priority=1),
        ]
        daemon_instance._try_execute_next()
        # Item should still be PENDING (not executed)
        assert daemon_instance._queue_state.items[0].status == QueueItemStatus.PENDING

    def test_skips_when_paused(self, daemon_instance: Daemon):
        daemon_instance._state.paused = True
        daemon_instance._queue_state.items = [
            QueueItem(id="item", source_type="prompt", source_value="x", status=QueueItemStatus.PENDING, priority=1),
        ]
        daemon_instance._try_execute_next()
        assert daemon_instance._queue_state.items[0].status == QueueItemStatus.PENDING

    def test_budget_exhaustion_writes_incident_summary(self, daemon_instance: Daemon):
        daemon_instance._state.daily_spend_usd = 50.0
        daemon_instance._queue_state.items = [
            QueueItem(id="item", source_type="prompt", source_value="x", status=QueueItemStatus.PENDING, priority=1),
        ]

        daemon_instance._try_execute_next()

        recovery_files = sorted((daemon_instance.repo_root / ".colonyos" / "recovery").glob("*.md"))
        assert recovery_files
        summary = recovery_files[0].read_text(encoding="utf-8")
        assert "daily budget was exhausted" in summary.lower()
        assert "--unlimited-budget" in summary


class TestCircuitBreaker:
    def test_skips_when_circuit_breaker_active(self, daemon_instance: Daemon):
        daemon_instance._state.activate_circuit_breaker(30)
        daemon_instance._queue_state.items = [
            QueueItem(id="item", source_type="prompt", source_value="x", status=QueueItemStatus.PENDING, priority=1),
        ]
        daemon_instance._try_execute_next()
        assert daemon_instance._queue_state.items[0].status == QueueItemStatus.PENDING


class TestDirtyWorktreeRecovery:
    def test_try_execute_next_preserves_dirty_worktree_and_retries_once(self, daemon_instance: Daemon):
        daemon_instance.dry_run = False
        daemon_instance.daemon_config.auto_recover_dirty_worktree = True
        item = QueueItem(
            id="item-1",
            source_type="prompt",
            source_value="ship it",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]
        dirty_error = PreflightError(
            "Uncommitted changes detected",
            code="dirty_worktree",
            details={"dirty_output": " M src/dirty.py"},
        )
        preserve_result = PreservationResult(
            snapshot_dir=daemon_instance.repo_root / ".colonyos" / "recovery" / "dirty-retry",
            preservation_mode="stash",
            stash_message="stash-msg",
        )
        fake_log = RunLog(
            run_id="run-1",
            prompt=item.source_value,
            status=RunStatus.COMPLETED,
            total_cost_usd=0.1,
        )

        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("clean", "")), \
             patch("colonyos.cli.run_pipeline_for_queue_item", side_effect=[dirty_error, fake_log]) as mock_run, \
             patch("colonyos.recovery.preserve_and_reset_worktree", return_value=preserve_result) as mock_preserve:
            assert daemon_instance._try_execute_next() is True

        assert mock_run.call_count == 2
        mock_preserve.assert_called_once()
        assert item.status == QueueItemStatus.COMPLETED
        assert daemon_instance._state.consecutive_failures == 0
        assert daemon_instance._pipeline_running is False

    def test_try_execute_next_fails_after_single_dirty_worktree_retry(self, daemon_instance: Daemon):
        daemon_instance.dry_run = False
        daemon_instance.daemon_config.auto_recover_dirty_worktree = True
        item = QueueItem(
            id="item-2",
            source_type="prompt",
            source_value="ship it",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]
        dirty_error = PreflightError(
            "Uncommitted changes detected",
            code="dirty_worktree",
            details={"dirty_output": " M src/dirty.py"},
        )
        preserve_result = PreservationResult(
            snapshot_dir=daemon_instance.repo_root / ".colonyos" / "recovery" / "dirty-retry",
            preservation_mode="stash",
            stash_message="stash-msg",
        )

        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("clean", "")), \
             patch("colonyos.cli.run_pipeline_for_queue_item", side_effect=[dirty_error, dirty_error]) as mock_run, \
             patch("colonyos.recovery.preserve_and_reset_worktree", return_value=preserve_result) as mock_preserve, \
             patch.object(daemon_instance, "_post_execution_failure"):
            assert daemon_instance._try_execute_next() is True

        assert mock_run.call_count == 2
        mock_preserve.assert_called_once()
        assert item.status == QueueItemStatus.FAILED
        assert "Uncommitted changes detected" in (item.error or "")
        assert daemon_instance._state.consecutive_failures == 1
        assert daemon_instance._pipeline_running is False

    def test_try_execute_next_does_not_auto_recover_when_disabled(self, daemon_instance: Daemon):
        daemon_instance.dry_run = False
        daemon_instance.daemon_config.auto_recover_dirty_worktree = False
        item = QueueItem(
            id="item-3",
            source_type="prompt",
            source_value="ship it",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]
        dirty_error = PreflightError(
            "Uncommitted changes detected",
            code="dirty_worktree",
            details={"dirty_output": " M src/dirty.py"},
        )

        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("clean", "")), \
             patch("colonyos.cli.run_pipeline_for_queue_item", side_effect=dirty_error), \
             patch("colonyos.recovery.preserve_and_reset_worktree") as mock_preserve, \
             patch.object(daemon_instance, "_post_execution_failure"):
            assert daemon_instance._try_execute_next() is True

        mock_preserve.assert_not_called()
        assert item.status == QueueItemStatus.FAILED
        assert daemon_instance._state.consecutive_failures == 1

    def test_run_pipeline_for_item_recovers_real_dirty_git_worktree(self, tmp_repo: Path, config: ColonyConfig):
        daemon_instance = Daemon(tmp_repo, config, dry_run=False)
        daemon_instance.daemon_config.auto_recover_dirty_worktree = True
        tracked = tmp_repo / "src" / "dirty.py"
        tracked.parent.mkdir(parents=True)
        tracked.write_text("print('clean')\n", encoding="utf-8")

        git_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test User",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test User",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "src/dirty.py"], cwd=tmp_repo, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_repo,
            check=True,
            capture_output=True,
            text=True,
            env=git_env,
        )

        tracked.write_text("print('dirty')\n", encoding="utf-8")
        item = QueueItem(
            id="item-4",
            source_type="prompt",
            source_value="ship it",
            status=QueueItemStatus.PENDING,
            priority=1,
        )

        call_count = 0

        def fake_run_pipeline_for_queue_item(**kwargs: object) -> RunLog:
            nonlocal call_count
            call_count += 1
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=tmp_repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if call_count == 1:
                raise PreflightError(
                    "Uncommitted changes detected",
                    code="dirty_worktree",
                    details={"dirty_output": status},
                )
            visible_dirty = [
                line for line in status.splitlines()
                if not line[3:].startswith(".colonyos/")
            ]
            assert visible_dirty == []
            return RunLog(
                run_id="run-1",
                prompt=item.source_value,
                status=RunStatus.COMPLETED,
                total_cost_usd=0.1,
            )

        with patch("colonyos.cli.run_pipeline_for_queue_item", side_effect=fake_run_pipeline_for_queue_item):
            log = daemon_instance._run_pipeline_for_item(item)

        assert log.status == RunStatus.COMPLETED
        assert call_count == 2
        stash_list = subprocess.run(
            ["git", "stash", "list"],
            cwd=tmp_repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert "colonyos-nuke-" in stash_list
        recovery_notes = sorted((tmp_repo / ".colonyos" / "recovery").glob("*.md"))
        assert recovery_notes


class TestDeduplication:
    def test_detects_duplicate_pending(self, daemon_instance: Daemon):
        daemon_instance._queue_state.items = [
            QueueItem(id="existing", source_type="issue", source_value="42", status=QueueItemStatus.PENDING),
        ]
        assert daemon_instance._is_duplicate("issue", "42") is True

    def test_allows_after_completion(self, daemon_instance: Daemon):
        daemon_instance._queue_state.items = [
            QueueItem(id="done", source_type="issue", source_value="42", status=QueueItemStatus.COMPLETED),
        ]
        assert daemon_instance._is_duplicate("issue", "42") is False

    def test_different_source_not_duplicate(self, daemon_instance: Daemon):
        daemon_instance._queue_state.items = [
            QueueItem(id="existing", source_type="prompt", source_value="42", status=QueueItemStatus.PENDING),
        ]
        assert daemon_instance._is_duplicate("issue", "42") is False


class TestPidLock:
    def test_acquires_and_releases_lock(self, tmp_repo: Path, config: ColonyConfig):
        d = Daemon(tmp_repo, config, dry_run=True)
        d._acquire_pid_lock()
        pid_path = tmp_repo / ".colonyos" / "daemon.pid"
        runtime_lock = tmp_repo / ".colonyos" / "runtime.lock"
        assert pid_path.exists()
        assert runtime_lock.exists()
        d._release_pid_lock()

    def test_second_instance_fails(self, tmp_repo: Path, config: ColonyConfig):
        d2 = Daemon(tmp_repo, config, dry_run=True)
        with patch("colonyos.daemon.RepoRuntimeGuard.acquire", side_effect=RuntimeBusyError(tmp_repo)):
            with pytest.raises(DaemonError, match="Another daemon instance"):
                d2._acquire_pid_lock()


class TestHealthReport:
    def test_healthy_status(self, daemon_instance: Daemon):
        health = daemon_instance.get_health()
        assert health["status"] == "healthy"
        assert health["paused"] is False
        assert health["circuit_breaker_active"] is False

    def test_degraded_when_paused(self, daemon_instance: Daemon):
        daemon_instance._state.paused = True
        health = daemon_instance.get_health()
        assert health["status"] == "degraded"

    def test_stopped_when_budget_exhausted(self, daemon_instance: Daemon):
        daemon_instance._state.daily_spend_usd = 100.0
        health = daemon_instance.get_health()
        assert health["status"] == "stopped"


class TestSlackKillSwitch:
    """Tests for FR-11 Slack kill switch (pause/resume/status)."""

    def test_pause_by_authorized_user(self, tmp_repo: Path):
        config = ColonyConfig(
            daemon=DaemonConfig(
                daily_budget_usd=50.0,
                allowed_control_user_ids=["U12345"],
            ),
        )
        d = Daemon(tmp_repo, config, dry_run=True)
        result = d._handle_control_command("U12345", "pause")
        assert result is not None
        assert "paused" in result.lower() or "Paused" in result
        assert d._state.paused is True

    def test_resume_by_authorized_user(self, tmp_repo: Path):
        config = ColonyConfig(
            daemon=DaemonConfig(
                daily_budget_usd=50.0,
                allowed_control_user_ids=["U12345"],
            ),
        )
        d = Daemon(tmp_repo, config, dry_run=True)
        d._state.paused = True
        d._state.consecutive_failures = 3
        d._state.circuit_breaker_until = datetime.now(timezone.utc).isoformat()
        d._state.circuit_breaker_activations = 2
        d._recent_failure_codes = ["dirty_worktree", "dirty_worktree", "dirty_worktree"]
        result = d._handle_control_command("U12345", "resume")
        assert result is not None
        assert d._state.paused is False
        assert d._state.consecutive_failures == 0
        assert d._state.circuit_breaker_until is None
        assert d._state.circuit_breaker_activations == 0
        assert d._recent_failure_codes == []

    def test_status_returns_health(self, tmp_repo: Path):
        config = ColonyConfig(
            daemon=DaemonConfig(
                daily_budget_usd=50.0,
                allowed_control_user_ids=["U12345"],
            ),
        )
        d = Daemon(tmp_repo, config, dry_run=True)
        result = d._handle_control_command("U12345", "status")
        assert result is not None
        assert "Status" in result or "status" in result

    def test_unauthorized_user_rejected(self, tmp_repo: Path):
        config = ColonyConfig(
            daemon=DaemonConfig(
                daily_budget_usd=50.0,
                allowed_control_user_ids=["U12345"],
            ),
        )
        d = Daemon(tmp_repo, config, dry_run=True)
        result = d._handle_control_command("U99999", "pause")
        assert result is None
        assert d._state.paused is False

    def test_empty_allowed_ids_rejects_all(self, daemon_instance: Daemon):
        result = daemon_instance._handle_control_command("U12345", "pause")
        assert result is None
        assert daemon_instance._state.paused is False

    def test_allow_all_control_users_accepts_without_allowlist(self, tmp_repo: Path):
        config = ColonyConfig(
            daemon=DaemonConfig(
                daily_budget_usd=50.0,
                allow_all_control_users=True,
            ),
        )
        d = Daemon(tmp_repo, config, dry_run=True)
        result = d._handle_control_command("U-anyone", "pause")
        assert result is not None
        assert d._state.paused is True

    def test_halt_aliases_pause(self, tmp_repo: Path):
        config = ColonyConfig(
            daemon=DaemonConfig(
                daily_budget_usd=50.0,
                allowed_control_user_ids=["U12345"],
            ),
        )
        d = Daemon(tmp_repo, config, dry_run=True)
        result = d._handle_control_command("U12345", "halt")
        assert d._state.paused is True

    def test_start_aliases_resume(self, tmp_repo: Path):
        config = ColonyConfig(
            daemon=DaemonConfig(
                daily_budget_usd=50.0,
                allowed_control_user_ids=["U12345"],
            ),
        )
        d = Daemon(tmp_repo, config, dry_run=True)
        d._state.paused = True
        d._handle_control_command("U12345", "start")
        assert d._state.paused is False


class TestBudgetAlerts:
    """Tests for FR-6 budget threshold Slack alerts."""

    def test_80_percent_alert_fires_once(self, daemon_instance: Daemon):
        daemon_instance._state.daily_spend_usd = 42.0  # 84% of $50
        daemon_instance._queue_state.items = [
            QueueItem(
                id="item",
                source_type="prompt",
                source_value="x",
                status=QueueItemStatus.PENDING,
                priority=1,
            ),
        ]
        def _is_budget_80_warning(call: Any) -> bool:
            if not call[0]:
                return False
            text = call[0][0]
            return "Budget warning" in text and "Approaching daily limit" in text

        with patch.object(daemon_instance, "_post_slack_message") as mock_slack:
            daemon_instance._try_execute_next()
            assert mock_slack.called
            assert sum(1 for c in mock_slack.call_args_list if _is_budget_80_warning(c)) == 1

        assert daemon_instance._budget_80_alerted is True

        with patch.object(daemon_instance, "_post_slack_message") as mock_slack2:
            daemon_instance._try_execute_next()
            assert sum(1 for c in mock_slack2.call_args_list if _is_budget_80_warning(c)) == 0

    def test_100_percent_alert_fires(self, daemon_instance: Daemon):
        daemon_instance._state.daily_spend_usd = 50.0  # 100% of $50
        daemon_instance._queue_state.items = [
            QueueItem(
                id="item",
                source_type="prompt",
                source_value="x",
                status=QueueItemStatus.PENDING,
                priority=1,
            ),
        ]
        with patch.object(daemon_instance, "_post_slack_message") as mock_slack:
            daemon_instance._try_execute_next()
            assert mock_slack.called
            args = mock_slack.call_args_list[0][0][0]
            assert "100%" in args or "exhausted" in args.lower()

        assert daemon_instance._budget_100_alerted is True


class TestCleanupDedup:
    """Tests for cleanup dedup fix."""

    def test_cleanup_dedup_uses_path(self, daemon_instance: Daemon):
        # Add a cleanup item with path as source_value
        daemon_instance._queue_state.items = [
            QueueItem(
                id="cleanup-1",
                source_type="cleanup",
                source_value="src/foo.py",
                status=QueueItemStatus.PENDING,
                priority=3,
            ),
        ]
        # Should detect duplicate when checking same path
        assert daemon_instance._is_duplicate("cleanup", "src/foo.py") is True
        # Formatted string should NOT match
        assert daemon_instance._is_duplicate(
            "cleanup", "Refactor src/foo.py (500 lines)"
        ) is False

    def test_schedule_cleanup_uses_string_path_basename(self, daemon_instance: Daemon):
        candidate = FileComplexity(
            path="nested/foo.py",
            line_count=900,
            function_count=30,
            category=ComplexityCategory.LARGE,
        )

        with patch("colonyos.cleanup.list_merged_branches", return_value=[]), \
             patch("colonyos.cleanup.scan_directory", return_value=[candidate]), \
             patch.object(daemon_instance, "_persist_queue"), \
             patch.object(daemon_instance, "_post_queue_enqueued"):
            daemon_instance._schedule_cleanup()

        cleanup_items = [
            item for item in daemon_instance._queue_state.items
            if item.source_type == "cleanup"
        ]
        assert len(cleanup_items) == 1
        assert cleanup_items[0].source_value == "nested/foo.py"
        assert cleanup_items[0].summary == "Cleanup/refactor foo.py"


class TestStarvationPersistence:
    """Test that starvation promotion persists immediately."""

    def test_promotion_persists_queue(self, daemon_instance: Daemon):
        old_time = (
            datetime.now(timezone.utc) - __import__("datetime").timedelta(hours=25)
        ).isoformat()
        daemon_instance._queue_state.items = [
            QueueItem(
                id="old",
                source_type="cleanup",
                source_value="x",
                status=QueueItemStatus.PENDING,
                priority=3,
                added_at=old_time,
            ),
        ]
        with patch.object(daemon_instance, "_persist_queue") as mock_persist:
            daemon_instance._next_pending_item()
            # Promotion should trigger a persist call
            assert mock_persist.called


class TestTickIntegration:
    """Integration test for _tick() scheduling logic."""

    def test_tick_calls_heartbeat_on_interval(self, daemon_instance: Daemon):
        daemon_instance._last_heartbeat_time = 0.0
        daemon_instance.daemon_config = DaemonConfig(
            heartbeat_interval_minutes=0,  # Trigger immediately
        )
        with patch.object(daemon_instance, "_post_heartbeat") as mock_hb, \
             patch.object(daemon_instance, "_poll_github_issues"), \
             patch.object(daemon_instance, "_schedule_cleanup"):
            daemon_instance._tick()
            assert mock_hb.called

    def test_tick_skips_execution_when_pipeline_running(self, daemon_instance: Daemon):
        daemon_instance._pipeline_running = True
        with patch.object(daemon_instance, "_try_execute_next") as mock_exec, \
             patch.object(daemon_instance, "_poll_github_issues"), \
             patch.object(daemon_instance, "_post_heartbeat"), \
             patch.object(daemon_instance, "_schedule_cleanup"):
            daemon_instance._tick()
            assert not mock_exec.called

    def test_tick_polls_github_on_interval(self, daemon_instance: Daemon):
        daemon_instance._last_github_poll_time = 0.0
        daemon_instance.daemon_config = DaemonConfig(
            github_poll_interval_seconds=0,  # Trigger immediately
        )
        with patch.object(daemon_instance, "_poll_github_issues") as mock_poll, \
             patch.object(daemon_instance, "_post_heartbeat"), \
             patch.object(daemon_instance, "_schedule_cleanup"):
            daemon_instance._tick()
            assert mock_poll.called


class TestCeoScheduling:
    def test_schedule_ceo_enqueues_prompt_from_run_ceo_tuple(self, daemon_instance: Daemon):
        daemon_instance.dry_run = False
        with patch("colonyos.orchestrator.run_ceo", return_value=("Ship feature X", MagicMock(success=True, error=None))):
            daemon_instance._schedule_ceo()

        queued = [item for item in daemon_instance._queue_state.items if item.source_type == "ceo"]
        assert len(queued) == 1
        assert queued[0].source_value == "Ship feature X"

    def test_schedule_ceo_skips_failed_result(self, daemon_instance: Daemon):
        daemon_instance.dry_run = False
        failed = MagicMock(success=False, error="boom")
        with patch("colonyos.orchestrator.run_ceo", return_value=("", failed)):
            daemon_instance._schedule_ceo()

        assert not any(item.source_type == "ceo" for item in daemon_instance._queue_state.items)


class TestSlackNotifications:
    def test_execute_item_posts_threaded_summary_for_auto_work(self, daemon_instance: Daemon):
        daemon_instance.dry_run = False
        daemon_instance._slack_client = MagicMock()
        item = QueueItem(
            id="cleanup-1",
            source_type="cleanup",
            source_value="src/foo.py",
            summary="Cleanup/refactor foo.py",
            notification_channel="C1",
            status=QueueItemStatus.PENDING,
        )
        fake_log = RunLog(
            run_id="run-1",
            prompt="cleanup",
            status=RunStatus.COMPLETED,
            phases=[
                PhaseResult(
                    phase=Phase.PLAN,
                    success=True,
                    cost_usd=0.1,
                    duration_ms=100,
                )
            ],
            branch_name="colonyos/cleanup-foo",
            pr_url="https://example.com/pr/1",
        )
        fake_log.total_cost_usd = 0.1

        with patch("colonyos.cli.run_pipeline_for_queue_item", return_value=fake_log), \
             patch("colonyos.slack.post_message", return_value={"ts": "1234.5"}) as mock_post, \
             patch("colonyos.slack.post_run_summary") as mock_summary:
            log = daemon_instance._execute_item(item)

        assert log is fake_log
        assert item.notification_thread_ts == "1234.5"
        assert mock_post.called
        mock_summary.assert_called_once()

    def test_execute_item_fanouts_summary_to_merged_slack_threads(self, daemon_instance: Daemon):
        daemon_instance.dry_run = False
        daemon_instance._slack_client = MagicMock()
        item = QueueItem(
            id="slack-1",
            source_type="slack",
            source_value="Add brew install support",
            summary="Add brew install support",
            slack_channel="C1",
            slack_ts="111.1",
            notification_channel="C1",
            notification_thread_ts="111.1",
            merged_sources=[
                {"source_type": "slack", "channel": "C2", "ts": "222.2"},
            ],
            status=QueueItemStatus.PENDING,
        )
        fake_log = RunLog(
            run_id="run-merged-1",
            prompt="brew",
            status=RunStatus.COMPLETED,
            phases=[
                PhaseResult(
                    phase=Phase.PLAN,
                    success=True,
                    cost_usd=0.1,
                    duration_ms=100,
                )
            ],
            branch_name="colonyos/brew",
            pr_url="https://example.com/pr/2",
            total_cost_usd=0.1,
        )

        with patch("colonyos.cli.run_pipeline_for_queue_item", return_value=fake_log), \
             patch("colonyos.slack.post_message") as mock_post, \
             patch("colonyos.slack.post_run_summary") as mock_summary:
            daemon_instance._execute_item(item)

        summary_targets = [
            (call.args[1], call.args[2])
            for call in mock_summary.call_args_list
        ]
        assert summary_targets == [("C1", "111.1"), ("C2", "222.2")]
        start_targets = [
            (call.args[1], call.kwargs.get("thread_ts"))
            for call in mock_post.call_args_list
        ]
        assert ("C1", "111.1") in start_targets
        assert ("C2", "222.2") in start_targets

    def test_execute_item_does_not_duplicate_start_message_on_dirty_worktree_retry(self, daemon_instance: Daemon):
        daemon_instance.dry_run = False
        daemon_instance.daemon_config.auto_recover_dirty_worktree = True
        daemon_instance._slack_client = MagicMock()
        item = QueueItem(
            id="slack-1",
            source_type="slack",
            source_value="Add brew install support",
            summary="Add brew install support",
            slack_channel="C1",
            slack_ts="111.1",
            notification_channel="C1",
            status=QueueItemStatus.PENDING,
        )
        dirty_error = PreflightError(
            "Uncommitted changes detected",
            code="dirty_worktree",
            details={"dirty_output": " M src/dirty.py"},
        )
        fake_log = RunLog(
            run_id="run-1",
            prompt="brew",
            status=RunStatus.COMPLETED,
            total_cost_usd=0.1,
        )
        preserve_result = PreservationResult(
            snapshot_dir=daemon_instance.repo_root / ".colonyos" / "recovery" / "dirty-retry",
            preservation_mode="stash",
            stash_message="stash-msg",
        )

        with patch("colonyos.cli.run_pipeline_for_queue_item", side_effect=[dirty_error, fake_log]) as mock_run, \
             patch("colonyos.recovery.preserve_and_reset_worktree", return_value=preserve_result), \
             patch("colonyos.slack.post_message", return_value={"ts": "1234.5"}) as mock_post, \
             patch("colonyos.slack.post_run_summary"):
            log = daemon_instance._execute_item(item)

        assert log is fake_log
        assert mock_run.call_count == 2
        assert mock_post.call_count == 2

    def test_try_execute_next_posts_failure_to_slack_thread(self, daemon_instance: Daemon):
        daemon_instance.dry_run = False
        daemon_instance._slack_client = MagicMock()
        daemon_instance._queue_state.items = [
            QueueItem(
                id="issue-1",
                source_type="issue",
                source_value="1",
                summary="Fix prod bug",
                notification_channel="C1",
                status=QueueItemStatus.PENDING,
                priority=1,
            )
        ]
        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("clean", "")), \
             patch.object(daemon_instance, "_execute_item", side_effect=RuntimeError("boom")), \
             patch("colonyos.slack.post_message", return_value={"ts": "1234.5"}) as mock_post:
            daemon_instance._try_execute_next()

        item = daemon_instance._queue_state.items[0]
        assert item.status == QueueItemStatus.FAILED
        assert mock_post.called
        assert any(
            "execution failed" in str(call)
            for call in mock_post.call_args_list
        )

    def test_ensure_notification_thread_single_intro_under_concurrency(self, daemon_instance: Daemon):
        """Concurrent callers for the same item must not each post an intro message."""
        daemon_instance._slack_client = MagicMock()
        item = QueueItem(
            id="concurrent-intro-1",
            source_type="prompt",
            source_value="x",
            notification_channel="C1",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        post_calls = {"n": 0}
        guard = threading.Lock()

        def counted_post(*args: Any, **kwargs: Any) -> dict[str, str]:
            with guard:
                post_calls["n"] += 1
            return {"ts": "99.0"}

        def worker() -> None:
            daemon_instance._ensure_notification_thread(item, "intro")

        with patch("colonyos.slack.post_message", side_effect=counted_post):
            threads = [threading.Thread(target=worker) for _ in range(16)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30.0)
                assert not t.is_alive()

        assert post_calls["n"] == 1
        assert item.notification_thread_ts == "99.0"


class TestMonitorUi:
    def test_make_monitor_ui_uses_task_badge_for_parallel_tasks(
        self, tmp_repo: Path, config: ColonyConfig, capsys: pytest.CaptureFixture[str]
    ) -> None:
        daemon = Daemon(tmp_repo, config, dry_run=True)
        daemon._monitor_mode = True

        ui = daemon._make_monitor_ui(task_id="2.0")

        assert ui is not None
        ui.on_tool_start("Read")
        ui.on_tool_input_delta('{"path":"src/main.py"}')
        ui.on_tool_done()

        output = capsys.readouterr().out.strip().splitlines()[-1]
        message = decode_monitor_event_line(output)

        assert isinstance(message, ToolLineMsg)
        assert message.badge_text == "[2.0]"


class TestCombinedUi:
    def test_secondary_call_timeout_does_not_block(self, monkeypatch: pytest.MonkeyPatch):
        class Primary:
            def __init__(self) -> None:
                self.called = False

            def phase_note(self, text: str) -> None:
                self.called = True

        class Secondary:
            def __init__(self) -> None:
                self.started = threading.Event()
                self.release = threading.Event()

            def phase_note(self, text: str) -> None:
                self.started.set()
                self.release.wait(timeout=1.0)

        primary = Primary()
        secondary = Secondary()
        ui = _CombinedUI(primary, secondary)
        monkeypatch.setattr(ui, "_SECONDARY_CALL_TIMEOUT_SECONDS", 0.01)

        started_at = time.monotonic()
        ui.phase_note("review summary")
        elapsed = time.monotonic() - started_at

        assert primary.called is True
        assert secondary.started.wait(timeout=0.2)
        assert elapsed < 0.2

        secondary.release.set()

    def test_daily_digest_posts_top_three(self, daemon_instance: Daemon):
        daemon_instance.daemon_config = DaemonConfig(digest_hour_utc=0)
        daemon_instance._queue_state.items = [
            QueueItem(id="slack-1", source_type="slack", source_value="a", summary="Slack request", status=QueueItemStatus.PENDING, priority=0),
            QueueItem(id="issue-1", source_type="issue", source_value="1", summary="Issue request", status=QueueItemStatus.PENDING, priority=1),
            QueueItem(id="ceo-1", source_type="ceo", source_value="x", summary="CEO request", status=QueueItemStatus.PENDING, priority=2),
        ]
        with patch.object(daemon_instance, "_post_slack_message") as mock_post:
            daemon_instance._post_daily_digest_if_due()

        assert mock_post.called
        digest = mock_post.call_args.args[0]
        assert "Daily ColonyOS Queue Digest" in digest
        assert "Top 3 pending" in digest
        assert "Slack request" in digest

    def test_load_or_create_daemon_watch_state_reuses_persisted_state(self, tmp_repo: Path, config: ColonyConfig):
        persisted = SlackWatchState(watch_id="daemon")
        persisted.mark_processed("C1", "1.0", "slack-1")
        save_watch_state(tmp_repo, persisted)

        daemon = Daemon(tmp_repo, config, dry_run=True)
        state = daemon._load_or_create_daemon_watch_state()

        assert state.watch_id == "daemon"
        assert state.is_processed("C1", "1.0")


class TestOutcomePolling:
    """Tests for FR-8: automatic PR outcome polling in _tick()."""

    def test_tick_polls_outcomes_on_interval(self, daemon_instance: Daemon):
        """_tick() calls _poll_pr_outcomes when interval has elapsed."""
        daemon_instance._last_outcome_poll_time = 0.0
        daemon_instance.daemon_config = DaemonConfig(
            outcome_poll_interval_minutes=0,  # Trigger immediately
        )
        with patch.object(daemon_instance, "_poll_pr_outcomes") as mock_poll, \
             patch.object(daemon_instance, "_poll_github_issues"), \
             patch.object(daemon_instance, "_post_heartbeat"), \
             patch.object(daemon_instance, "_schedule_cleanup"):
            daemon_instance._tick()
            assert mock_poll.called

    def test_tick_skips_outcomes_when_interval_not_elapsed(self, daemon_instance: Daemon):
        """_tick() does NOT call _poll_pr_outcomes when interval hasn't elapsed."""
        daemon_instance._last_outcome_poll_time = time.monotonic()
        daemon_instance.daemon_config = DaemonConfig(
            outcome_poll_interval_minutes=60,  # Far in the future
        )
        with patch.object(daemon_instance, "_poll_pr_outcomes") as mock_poll, \
             patch.object(daemon_instance, "_poll_github_issues"), \
             patch.object(daemon_instance, "_post_heartbeat"), \
             patch.object(daemon_instance, "_schedule_cleanup"):
            daemon_instance._tick()
            assert not mock_poll.called

    def test_poll_pr_outcomes_handles_exceptions(self, daemon_instance: Daemon):
        """_poll_pr_outcomes swallows exceptions so the daemon keeps running."""
        with patch("colonyos.outcomes.poll_outcomes", side_effect=RuntimeError("gh failed")):
            # Should not raise
            daemon_instance._poll_pr_outcomes()

    def test_poll_pr_outcomes_calls_poll_outcomes(self, daemon_instance: Daemon):
        """_poll_pr_outcomes delegates to outcomes.poll_outcomes."""
        with patch("colonyos.outcomes.poll_outcomes") as mock_poll:
            daemon_instance._poll_pr_outcomes()
            mock_poll.assert_called_once_with(daemon_instance.repo_root)

    def test_configurable_interval(self, tmp_repo: Path):
        """outcome_poll_interval_minutes from DaemonConfig is respected."""
        config = ColonyConfig(daemon=DaemonConfig(outcome_poll_interval_minutes=15))
        d = Daemon(tmp_repo, config, dry_run=True)
        assert d.daemon_config.outcome_poll_interval_minutes == 15


class TestPipelineWatchdog:
    """Tests for the pipeline-level timeout watchdog in _run_pipeline_for_item."""

    def test_watchdog_raises_on_timeout(self, tmp_repo: Path):
        """Pipeline that exceeds the timeout should raise RuntimeError."""
        config = ColonyConfig(
            daemon=DaemonConfig(pipeline_timeout_seconds=60),
        )
        d = Daemon(tmp_repo, config, dry_run=False)

        item = QueueItem(
            id="item-timeout",
            source_type="prompt",
            source_value="slow task",
            status=QueueItemStatus.PENDING,
            priority=1,
        )

        def fake_pipeline(**kwargs: object) -> RunLog:
            time.sleep(3)
            return RunLog(
                run_id="run-slow",
                prompt="slow task",
                status=RunStatus.COMPLETED,
                total_cost_usd=0.0,
            )

        with patch.object(d, "daemon_config") as mock_cfg:
            mock_cfg.pipeline_timeout_seconds = 1
            mock_cfg.auto_recover_dirty_worktree = False

            with patch(
                "colonyos.cli.run_pipeline_for_queue_item",
                side_effect=fake_pipeline,
            ), pytest.raises(RuntimeError, match="exceeded.*wall-clock timeout"):
                d._run_pipeline_for_item(item)

    def test_watchdog_cancelled_on_fast_success(self, tmp_repo: Path):
        """Fast pipeline should complete without the watchdog firing."""
        config = ColonyConfig(
            daemon=DaemonConfig(pipeline_timeout_seconds=300),
        )
        d = Daemon(tmp_repo, config, dry_run=False)

        item = QueueItem(
            id="item-fast",
            source_type="prompt",
            source_value="quick task",
            status=QueueItemStatus.PENDING,
            priority=1,
        )

        def fast_pipeline(**kwargs: object) -> RunLog:
            return RunLog(
                run_id="run-fast",
                prompt="quick task",
                status=RunStatus.COMPLETED,
                total_cost_usd=0.0,
            )

        with patch(
            "colonyos.cli.run_pipeline_for_queue_item",
            side_effect=fast_pipeline,
        ):
            log = d._run_pipeline_for_item(item)

        assert log.status == RunStatus.COMPLETED


class TestCeoCleanupGating:
    """CEO and cleanup scheduling should be blocked when the daemon is degraded."""

    def test_tick_skips_ceo_when_circuit_breaker_active(self, daemon_instance: Daemon):
        daemon_instance.daemon_config.ceo_cooldown_minutes = 0
        daemon_instance._state.activate_circuit_breaker(30)
        daemon_instance._pipeline_running = False
        daemon_instance._last_ceo_time = 0.0
        daemon_instance._last_github_poll_time = time.monotonic()
        daemon_instance._last_cleanup_time = time.monotonic()
        daemon_instance._last_reprioritize_time = time.monotonic()
        daemon_instance._last_heartbeat_time = time.monotonic()
        daemon_instance._last_outcome_poll_time = time.monotonic()
        with patch.object(daemon_instance, "_try_execute_next", return_value=False), \
             patch.object(daemon_instance, "_schedule_ceo") as mock_ceo, \
             patch.object(daemon_instance, "_poll_github_issues"), \
             patch.object(daemon_instance, "_post_daily_digest_if_due"):
            daemon_instance._tick()
        mock_ceo.assert_not_called()

    def test_tick_skips_cleanup_when_circuit_breaker_active(self, daemon_instance: Daemon):
        daemon_instance.daemon_config.cleanup_interval_hours = 0
        daemon_instance._state.activate_circuit_breaker(30)
        daemon_instance._pipeline_running = False
        daemon_instance._last_cleanup_time = 0.0
        daemon_instance._last_github_poll_time = time.monotonic()
        daemon_instance._last_ceo_time = time.monotonic()
        daemon_instance._last_reprioritize_time = time.monotonic()
        daemon_instance._last_heartbeat_time = time.monotonic()
        daemon_instance._last_outcome_poll_time = time.monotonic()
        with patch.object(daemon_instance, "_try_execute_next", return_value=False), \
             patch.object(daemon_instance, "_schedule_cleanup") as mock_cleanup, \
             patch.object(daemon_instance, "_poll_github_issues"), \
             patch.object(daemon_instance, "_post_daily_digest_if_due"):
            daemon_instance._tick()
        mock_cleanup.assert_not_called()

    def test_tick_skips_ceo_when_paused(self, daemon_instance: Daemon):
        daemon_instance.daemon_config.ceo_cooldown_minutes = 0
        daemon_instance._state.paused = True
        daemon_instance._pipeline_running = False
        daemon_instance._last_ceo_time = 0.0
        daemon_instance._last_github_poll_time = time.monotonic()
        daemon_instance._last_cleanup_time = time.monotonic()
        daemon_instance._last_reprioritize_time = time.monotonic()
        daemon_instance._last_heartbeat_time = time.monotonic()
        daemon_instance._last_outcome_poll_time = time.monotonic()
        with patch.object(daemon_instance, "_try_execute_next", return_value=False), \
             patch.object(daemon_instance, "_schedule_ceo") as mock_ceo, \
             patch.object(daemon_instance, "_poll_github_issues"), \
             patch.object(daemon_instance, "_post_daily_digest_if_due"):
            daemon_instance._tick()
        mock_ceo.assert_not_called()

    def test_tick_allows_ceo_when_healthy(self, daemon_instance: Daemon):
        daemon_instance.daemon_config.ceo_cooldown_minutes = 0
        daemon_instance._pipeline_running = False
        daemon_instance._last_ceo_time = 0.0
        daemon_instance._last_github_poll_time = time.monotonic()
        daemon_instance._last_cleanup_time = time.monotonic()
        daemon_instance._last_reprioritize_time = time.monotonic()
        daemon_instance._last_heartbeat_time = time.monotonic()
        daemon_instance._last_outcome_poll_time = time.monotonic()
        with patch.object(daemon_instance, "_try_execute_next", return_value=False), \
             patch.object(daemon_instance, "_schedule_ceo") as mock_ceo, \
             patch.object(daemon_instance, "_pending_count", return_value=0), \
             patch.object(daemon_instance, "_poll_github_issues"), \
             patch.object(daemon_instance, "_post_daily_digest_if_due"):
            daemon_instance._tick()
        mock_ceo.assert_called_once()


class TestSystemicFailureDetection:
    """Daemon should auto-pause when all recent failures share the same error code."""

    def test_is_systemic_failure_all_same_code(self, daemon_instance: Daemon):
        daemon_instance.daemon_config.max_consecutive_failures = 3
        daemon_instance._recent_failure_codes = ["dirty_worktree", "dirty_worktree", "dirty_worktree"]
        assert daemon_instance._is_systemic_failure() is True

    def test_is_systemic_failure_mixed_codes(self, daemon_instance: Daemon):
        daemon_instance.daemon_config.max_consecutive_failures = 3
        daemon_instance._recent_failure_codes = ["dirty_worktree", "auth_error", "dirty_worktree"]
        assert daemon_instance._is_systemic_failure() is False

    def test_is_systemic_failure_not_enough_codes(self, daemon_instance: Daemon):
        daemon_instance.daemon_config.max_consecutive_failures = 3
        daemon_instance._recent_failure_codes = ["dirty_worktree", "dirty_worktree"]
        assert daemon_instance._is_systemic_failure() is False

    def test_auto_pauses_on_systemic_failure(self, daemon_instance: Daemon):
        daemon_instance.dry_run = False
        daemon_instance.daemon_config.max_consecutive_failures = 3
        daemon_instance.daemon_config.auto_recover_dirty_worktree = False
        item = QueueItem(
            id="item-sys",
            source_type="prompt",
            source_value="test",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]
        daemon_instance._state.consecutive_failures = 2
        daemon_instance._recent_failure_codes = ["dirty_worktree", "dirty_worktree"]

        dirty_error = PreflightError(
            "Uncommitted changes detected",
            code="dirty_worktree",
            details={"dirty_output": " M src/dirty.py"},
        )

        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("clean", "")), \
             patch("colonyos.cli.run_pipeline_for_queue_item", side_effect=dirty_error), \
             patch.object(daemon_instance, "_post_execution_failure"), \
             patch.object(daemon_instance, "_post_systemic_failure_alert") as mock_sys, \
             patch.object(daemon_instance, "_post_circuit_breaker_escalation_pause_alert") as mock_esc:
            daemon_instance._try_execute_next()

        assert daemon_instance._state.paused is True
        mock_sys.assert_called_once_with("dirty_worktree", 3)
        mock_esc.assert_not_called()

    def test_circuit_breaker_on_non_systemic_failure(self, daemon_instance: Daemon):
        daemon_instance.dry_run = False
        daemon_instance.daemon_config.max_consecutive_failures = 3
        daemon_instance.daemon_config.auto_recover_dirty_worktree = False
        item = QueueItem(
            id="item-varied",
            source_type="prompt",
            source_value="test",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]
        daemon_instance._state.consecutive_failures = 2
        daemon_instance._recent_failure_codes = ["auth_error", "timeout"]

        error = RuntimeError("connection_reset")

        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("clean", "")), \
             patch("colonyos.cli.run_pipeline_for_queue_item", side_effect=error), \
             patch.object(daemon_instance, "_post_execution_failure"), \
             patch.object(daemon_instance, "_post_systemic_failure_alert"), \
             patch.object(daemon_instance, "_post_circuit_breaker_cooldown_notice") as mock_cooldown:
            daemon_instance._try_execute_next()

        assert daemon_instance._state.paused is False
        assert daemon_instance._state.is_circuit_breaker_active() is True
        mock_cooldown.assert_called_once()

    def test_escalating_cb_auto_pauses_after_three_activations(self, daemon_instance: Daemon):
        """After 3 CB activations without a success, the daemon should auto-pause."""
        daemon_instance.dry_run = False
        daemon_instance.daemon_config.max_consecutive_failures = 3
        daemon_instance.daemon_config.auto_recover_dirty_worktree = False

        for cycle in range(3):
            daemon_instance._state.consecutive_failures = 2
            daemon_instance._state.circuit_breaker_until = None
            daemon_instance._recent_failure_codes = [f"err_{cycle}", f"other_{cycle}"]
            item = QueueItem(
                id=f"item-esc-{cycle}",
                source_type="prompt",
                source_value="test",
                status=QueueItemStatus.PENDING,
                priority=1,
            )
            daemon_instance._queue_state.items = [item]

            with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("clean", "")), \
                 patch("colonyos.cli.run_pipeline_for_queue_item", side_effect=RuntimeError("fail")), \
                 patch.object(daemon_instance, "_post_execution_failure"), \
                 patch.object(daemon_instance, "_post_systemic_failure_alert") as mock_sys, \
                 patch.object(daemon_instance, "_post_circuit_breaker_cooldown_notice") as mock_cool, \
                 patch.object(
                     daemon_instance, "_post_circuit_breaker_escalation_pause_alert"
                 ) as mock_esc:
                daemon_instance._try_execute_next()
                if cycle < 2:
                    mock_sys.assert_not_called()
                    mock_esc.assert_not_called()
                    mock_cool.assert_called_once()
                else:
                    mock_sys.assert_not_called()
                    mock_esc.assert_called_once_with(3, 3)
                    mock_cool.assert_not_called()

        assert daemon_instance._state.circuit_breaker_activations == 3
        assert daemon_instance._state.paused is True

    def test_success_clears_recent_failure_codes(self, daemon_instance: Daemon):
        daemon_instance.dry_run = False
        daemon_instance._recent_failure_codes = ["dirty_worktree", "dirty_worktree"]
        item = QueueItem(
            id="item-ok",
            source_type="prompt",
            source_value="test",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]

        fake_log = RunLog(
            run_id="run-ok",
            prompt="test",
            status=RunStatus.COMPLETED,
            total_cost_usd=0.1,
        )

        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("clean", "")), \
             patch("colonyos.cli.run_pipeline_for_queue_item", return_value=fake_log):
            daemon_instance._try_execute_next()

        assert daemon_instance._recent_failure_codes == []


class TestPostExecutionFailureSlack:
    def test_falls_back_when_notification_thread_unavailable(self, daemon_instance: Daemon):
        item = QueueItem(
            id="item-fail",
            source_type="prompt",
            source_value="do thing",
            status=QueueItemStatus.FAILED,
            priority=1,
        )
        with patch.object(daemon_instance, "_ensure_notification_thread", return_value=None), \
             patch.object(daemon_instance, "_post_slack_message") as mock_slack:
            daemon_instance._post_execution_failure(
                item,
                failure_message="something broke",
                incident_path=".colonyos/incidents/x.md",
            )
        mock_slack.assert_called_once()
        body = mock_slack.call_args.args[0]
        assert "item-fail" in body
        assert "something broke" in body
        assert "x.md" in body


class TestPreExecWorktreeCheck:
    """Pre-execution dirty worktree check should prevent item-level failures."""

    def test_preexec_worktree_state_indeterminate_on_preflight_error(self, daemon_instance: Daemon):
        with patch(
            "colonyos.orchestrator._check_working_tree_clean",
            side_effect=PreflightError("git status timed out after 30s."),
        ):
            state, detail = daemon_instance._preexec_worktree_state()
        assert state == "indeterminate"
        assert "timed out" in detail

    def test_systemic_failure_alert_uses_slack_resume_guidance(
        self, daemon_instance: Daemon
    ):
        with patch.object(daemon_instance, "_post_slack_message") as mock_slack:
            daemon_instance._post_systemic_failure_alert("dirty_worktree", 3)

        text = mock_slack.call_args.args[0]
        assert "colonyos daemon resume" not in text
        assert "Send `resume` in this channel to unpause." in text

    def test_skips_execution_when_dirty_and_no_auto_recover(self, daemon_instance: Daemon):
        daemon_instance.daemon_config.auto_recover_dirty_worktree = False
        item = QueueItem(
            id="item",
            source_type="prompt",
            source_value="x",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]
        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("dirty", "")), \
             patch.object(daemon_instance, "_post_slack_message") as mock_slack:
            result = daemon_instance._try_execute_next()
        assert result is False
        assert item.status == QueueItemStatus.PENDING
        assert daemon_instance._state.paused is True
        posted = "\n".join(str(c.args[0]) for c in mock_slack.call_args_list if c.args)
        assert "auto-paused before execution" in posted
        assert "daemon.auto_recover_dirty_worktree" in posted
        assert "clean" in posted.lower()
        assert "colonyos daemon resume" not in posted

    def test_recovers_and_proceeds_when_dirty_and_auto_recover(self, daemon_instance: Daemon):
        daemon_instance.daemon_config.auto_recover_dirty_worktree = True
        item = QueueItem(
            id="item",
            source_type="prompt",
            source_value="x",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]

        fake_log = RunLog(
            run_id="run-1",
            prompt="x",
            status=RunStatus.COMPLETED,
            total_cost_usd=0.0,
        )

        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("dirty", "")), \
             patch.object(daemon_instance, "_recover_dirty_worktree_preemptive") as mock_recover, \
             patch("colonyos.cli.run_pipeline_for_queue_item", return_value=fake_log):
            result = daemon_instance._try_execute_next()

        assert result is True
        mock_recover.assert_called_once()
        assert item.status == QueueItemStatus.COMPLETED

    def test_skips_execution_when_recovery_fails(self, daemon_instance: Daemon):
        daemon_instance.daemon_config.auto_recover_dirty_worktree = True
        item = QueueItem(
            id="item",
            source_type="prompt",
            source_value="x",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]
        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("dirty", "")), \
             patch.object(daemon_instance, "_recover_dirty_worktree_preemptive", return_value=False), \
             patch.object(daemon_instance, "_post_slack_message") as mock_slack:
            result = daemon_instance._try_execute_next()
        assert result is False
        assert item.status == QueueItemStatus.PENDING
        assert daemon_instance._state.paused is True
        posted = "\n".join(str(c.args[0]) for c in mock_slack.call_args_list if c.args)
        assert "auto-paused before execution" in posted
        assert "auto-recovery failed" in posted
        assert "colonyos daemon resume" not in posted

    def test_preexec_blocker_noops_when_already_paused(self, daemon_instance: Daemon):
        daemon_instance._state.paused = True
        item = QueueItem(
            id="item",
            source_type="prompt",
            source_value="x",
            status=QueueItemStatus.PENDING,
            priority=1,
        )

        with patch.object(daemon_instance, "_record_runtime_incident") as mock_incident, \
             patch.object(daemon_instance, "_post_slack_message") as mock_slack:
            daemon_instance._pause_for_pre_execution_blocker(
                item,
                "Dirty worktree detected before execution.",
            )

        mock_incident.assert_not_called()
        mock_slack.assert_not_called()

    def test_proceeds_when_worktree_clean(self, daemon_instance: Daemon):
        item = QueueItem(
            id="item",
            source_type="prompt",
            source_value="x",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]

        fake_log = RunLog(
            run_id="run-1",
            prompt="x",
            status=RunStatus.COMPLETED,
            total_cost_usd=0.0,
        )

        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("clean", "")), \
             patch("colonyos.cli.run_pipeline_for_queue_item", return_value=fake_log):
            result = daemon_instance._try_execute_next()

        assert result is True
        assert item.status == QueueItemStatus.COMPLETED

    def test_blocks_when_worktree_state_indeterminate(self, daemon_instance: Daemon):
        """Fail-closed: unknown git status blocks execution and posts remediation to Slack."""
        item = QueueItem(
            id="item",
            source_type="prompt",
            source_value="x",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]
        detail = "git status exited with code 128: fatal: not a git repository"
        with patch.object(
            daemon_instance,
            "_preexec_worktree_state",
            return_value=("indeterminate", detail),
        ), patch.object(daemon_instance, "_post_slack_message") as mock_slack:
            result = daemon_instance._try_execute_next()
        assert result is False
        assert item.status == QueueItemStatus.PENDING
        assert daemon_instance._state.paused is True
        posted = "\n".join(str(c.args[0]) for c in mock_slack.call_args_list if c.args)
        assert "auto-paused before execution" in posted
        assert "git status" in posted.lower()
        assert "fail-closed" in posted.lower()
        assert detail in posted
        assert "git status --porcelain" in posted

    def test_skips_worktree_check_while_paused(self, daemon_instance: Daemon):
        daemon_instance._state.paused = True
        daemon_instance._queue_state.items = [
            QueueItem(id="item", source_type="prompt", source_value="x", status=QueueItemStatus.PENDING, priority=1),
        ]

        with patch.object(daemon_instance, "_preexec_worktree_state") as mock_state:
            result = daemon_instance._try_execute_next()

        assert result is False
        mock_state.assert_not_called()

    def test_skips_worktree_check_when_queue_is_empty(self, daemon_instance: Daemon):
        with patch.object(daemon_instance, "_preexec_worktree_state") as mock_state:
            result = daemon_instance._try_execute_next()

        assert result is False
        mock_state.assert_not_called()


class TestNotificationLockCleanup:
    """Tests for _notification_thread_locks cleanup to prevent unbounded growth."""

    def test_lock_created_on_first_access(self, daemon_instance: Daemon):
        lock = daemon_instance._notification_thread_lock_for("item-1")
        assert isinstance(lock, type(threading.Lock()))
        assert "item-1" in daemon_instance._notification_thread_locks

    def test_same_lock_returned_for_same_item(self, daemon_instance: Daemon):
        lock1 = daemon_instance._notification_thread_lock_for("item-1")
        lock2 = daemon_instance._notification_thread_lock_for("item-1")
        assert lock1 is lock2

    def test_cleanup_removes_lock(self, daemon_instance: Daemon):
        daemon_instance._notification_thread_lock_for("item-1")
        assert "item-1" in daemon_instance._notification_thread_locks

        daemon_instance._cleanup_notification_lock("item-1")
        assert "item-1" not in daemon_instance._notification_thread_locks

    def test_cleanup_is_idempotent(self, daemon_instance: Daemon):
        daemon_instance._notification_thread_lock_for("item-1")
        daemon_instance._cleanup_notification_lock("item-1")
        # Second cleanup should not raise
        daemon_instance._cleanup_notification_lock("item-1")
        assert "item-1" not in daemon_instance._notification_thread_locks

    def test_cleanup_does_not_affect_other_locks(self, daemon_instance: Daemon):
        daemon_instance._notification_thread_lock_for("item-1")
        daemon_instance._notification_thread_lock_for("item-2")
        assert len(daemon_instance._notification_thread_locks) == 2

        daemon_instance._cleanup_notification_lock("item-1")
        assert "item-1" not in daemon_instance._notification_thread_locks
        assert "item-2" in daemon_instance._notification_thread_locks


class TestPRSync:
    """Tests for PR sync daemon integration (concern #7)."""

    def test_sync_called_on_interval(self, daemon_instance: Daemon):
        """sync_stale_prs is called when the pr_sync interval elapses."""
        daemon_instance.config.daemon.pr_sync.enabled = True
        daemon_instance.config.daemon.pr_sync.interval_minutes = 1
        daemon_instance._last_pr_sync_time = 0.0  # force elapsed

        with patch.object(daemon_instance, "_try_execute_next", return_value=False), \
             patch.object(daemon_instance, "_poll_github_issues"), \
             patch.object(daemon_instance, "_schedule_ceo"), \
             patch.object(daemon_instance, "_schedule_cleanup"), \
             patch.object(daemon_instance, "_reprioritize_queue"), \
             patch.object(daemon_instance, "_post_heartbeat"), \
             patch.object(daemon_instance, "_poll_pr_outcomes"), \
             patch.object(daemon_instance, "_post_daily_digest_if_due"), \
             patch.object(daemon_instance, "_sync_stale_prs") as mock_sync:
            daemon_instance._tick()

        mock_sync.assert_called_once()

    def test_sync_not_called_when_disabled(self, daemon_instance: Daemon):
        """sync is not called when pr_sync.enabled is False."""
        daemon_instance.config.daemon.pr_sync.enabled = False
        daemon_instance._last_pr_sync_time = 0.0

        with patch.object(daemon_instance, "_try_execute_next", return_value=False), \
             patch.object(daemon_instance, "_poll_github_issues"), \
             patch.object(daemon_instance, "_schedule_ceo"), \
             patch.object(daemon_instance, "_schedule_cleanup"), \
             patch.object(daemon_instance, "_reprioritize_queue"), \
             patch.object(daemon_instance, "_post_heartbeat"), \
             patch.object(daemon_instance, "_poll_pr_outcomes"), \
             patch.object(daemon_instance, "_post_daily_digest_if_due"), \
             patch.object(daemon_instance, "_sync_stale_prs") as mock_sync:
            daemon_instance._tick()

        mock_sync.assert_not_called()

    def test_sync_not_called_when_paused(self, daemon_instance: Daemon):
        """sync is skipped when daemon is paused."""
        daemon_instance.config.daemon.pr_sync.enabled = True
        daemon_instance.config.daemon.pr_sync.interval_minutes = 1
        daemon_instance._last_pr_sync_time = 0.0
        daemon_instance._state.paused = True

        with patch.object(daemon_instance, "_try_execute_next", return_value=False), \
             patch.object(daemon_instance, "_poll_github_issues"), \
             patch.object(daemon_instance, "_schedule_ceo"), \
             patch.object(daemon_instance, "_schedule_cleanup"), \
             patch.object(daemon_instance, "_reprioritize_queue"), \
             patch.object(daemon_instance, "_post_heartbeat"), \
             patch.object(daemon_instance, "_poll_pr_outcomes"), \
             patch.object(daemon_instance, "_post_daily_digest_if_due"), \
             patch.object(daemon_instance, "_sync_stale_prs") as mock_sync:
            daemon_instance._tick()

        mock_sync.assert_not_called()

    def test_sync_not_called_during_pipeline(self, daemon_instance: Daemon):
        """sync is skipped when _pipeline_running is True."""
        daemon_instance.config.daemon.pr_sync.enabled = True
        daemon_instance.config.daemon.pr_sync.interval_minutes = 1
        daemon_instance._last_pr_sync_time = 0.0
        daemon_instance._pipeline_running = True

        with patch.object(daemon_instance, "_try_execute_next", return_value=False), \
             patch.object(daemon_instance, "_poll_github_issues"), \
             patch.object(daemon_instance, "_schedule_ceo"), \
             patch.object(daemon_instance, "_schedule_cleanup"), \
             patch.object(daemon_instance, "_reprioritize_queue"), \
             patch.object(daemon_instance, "_post_heartbeat"), \
             patch.object(daemon_instance, "_poll_pr_outcomes"), \
             patch.object(daemon_instance, "_post_daily_digest_if_due"), \
             patch.object(daemon_instance, "_sync_stale_prs") as mock_sync:
            daemon_instance._tick()

        mock_sync.assert_not_called()

    def test_sync_exception_caught(self, daemon_instance: Daemon):
        """Exceptions in _sync_stale_prs do not crash the daemon."""
        daemon_instance.config.daemon.pr_sync.enabled = True
        daemon_instance.config.daemon.pr_sync.interval_minutes = 1
        daemon_instance._last_pr_sync_time = 0.0

        with patch("colonyos.pr_sync.sync_stale_prs", side_effect=RuntimeError("boom")), \
             patch.object(daemon_instance, "_post_slack_message"):
            # Should not raise
            daemon_instance._sync_stale_prs()

    def test_sync_passes_write_enabled(self, daemon_instance: Daemon):
        """_sync_stale_prs passes the dashboard_write_enabled config value."""
        daemon_instance.config.daemon.pr_sync.enabled = True
        daemon_instance.config.daemon.dashboard_write_enabled = True

        with patch("colonyos.pr_sync.sync_stale_prs") as mock_sync:
            daemon_instance._sync_stale_prs()

        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args[1]
        assert call_kwargs["write_enabled"] is True


class TestPipelineStartedAtTracking:
    """Tests for _pipeline_started_at monotonic timestamp tracking (task 3.0)."""

    def test_pipeline_started_at_is_none_initially(self, daemon_instance: Daemon):
        """_pipeline_started_at should be None when no pipeline is running."""
        assert daemon_instance._pipeline_started_at is None

    def test_pipeline_started_at_set_when_pipeline_starts(self, daemon_instance: Daemon):
        """_pipeline_started_at should be set to a monotonic timestamp when a pipeline starts."""
        daemon_instance.dry_run = False
        item = QueueItem(
            id="item-start",
            source_type="prompt",
            source_value="do stuff",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]

        before = time.monotonic()

        fake_log = RunLog(
            run_id="run-1",
            prompt="do stuff",
            status=RunStatus.COMPLETED,
            total_cost_usd=0.01,
        )

        captured_started_at: list[float | None] = []

        original_execute = daemon_instance._execute_item

        def spy_execute(i: QueueItem) -> RunLog:
            captured_started_at.append(daemon_instance._pipeline_started_at)
            return fake_log

        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("clean", "")), \
             patch.object(daemon_instance, "_execute_item", side_effect=spy_execute):
            daemon_instance._try_execute_next()

        after = time.monotonic()

        # During execution, _pipeline_started_at should have been set
        assert len(captured_started_at) == 1
        assert captured_started_at[0] is not None
        assert before <= captured_started_at[0] <= after

    def test_pipeline_started_at_reset_on_success(self, daemon_instance: Daemon):
        """_pipeline_started_at should be reset to None after successful pipeline completion."""
        daemon_instance.dry_run = False
        item = QueueItem(
            id="item-ok",
            source_type="prompt",
            source_value="go",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]

        fake_log = RunLog(
            run_id="run-ok",
            prompt="go",
            status=RunStatus.COMPLETED,
            total_cost_usd=0.01,
        )

        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("clean", "")), \
             patch.object(daemon_instance, "_execute_item", return_value=fake_log):
            daemon_instance._try_execute_next()

        assert daemon_instance._pipeline_started_at is None

    def test_pipeline_started_at_reset_on_failure(self, daemon_instance: Daemon):
        """_pipeline_started_at should be reset to None after pipeline failure (exception)."""
        daemon_instance.dry_run = False
        item = QueueItem(
            id="item-fail",
            source_type="prompt",
            source_value="crash",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]

        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("clean", "")), \
             patch.object(daemon_instance, "_execute_item", side_effect=RuntimeError("boom")):
            daemon_instance._try_execute_next()

        assert daemon_instance._pipeline_started_at is None
        assert daemon_instance._pipeline_running is False

    def test_pipeline_started_at_reset_on_keyboard_interrupt(self, daemon_instance: Daemon):
        """_pipeline_started_at should be reset to None after KeyboardInterrupt."""
        daemon_instance.dry_run = False
        item = QueueItem(
            id="item-int",
            source_type="prompt",
            source_value="stop",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]

        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("clean", "")), \
             patch.object(daemon_instance, "_execute_item", side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                daemon_instance._try_execute_next()

        assert daemon_instance._pipeline_started_at is None
        assert daemon_instance._pipeline_running is False


class TestWatchdogThread:
    """Tests for watchdog thread with stall detection and auto-recovery (task 4.0)."""

    def test_watchdog_thread_starts_and_stops(self, tmp_repo: Path, config: ColonyConfig):
        """Watchdog thread should start when daemon starts and stop when daemon stops."""
        daemon = Daemon(tmp_repo, config, dry_run=True)
        daemon._stop_event = threading.Event()

        # Start the watchdog thread
        daemon._start_watchdog_thread()
        assert daemon._watchdog_thread is not None
        assert daemon._watchdog_thread.is_alive()
        assert daemon._watchdog_thread.daemon is True

        # Stop it
        daemon._stop_event.set()
        daemon._watchdog_thread.join(timeout=5)
        assert not daemon._watchdog_thread.is_alive()

    def test_stall_detection_triggers_cancel(self, tmp_repo: Path):
        """When pipeline is stuck and heartbeat is stale, watchdog calls request_active_phase_cancel."""
        config = ColonyConfig(daemon=DaemonConfig(
            daily_budget_usd=50.0,
            watchdog_stall_seconds=120,
        ))
        daemon = Daemon(tmp_repo, config, dry_run=True)

        # Simulate a running pipeline that started long ago
        item = QueueItem(
            id="stuck-item",
            source_type="prompt",
            source_value="do stuff",
            status=QueueItemStatus.RUNNING,
            priority=1,
        )
        daemon._queue_state.items = [item]
        daemon._pipeline_running = True
        daemon._pipeline_started_at = time.monotonic() - 300  # 5 min ago
        daemon._current_running_item = item

        # Create a stale heartbeat file
        hb_dir = tmp_repo / ".colonyos" / "runs"
        hb_dir.mkdir(parents=True, exist_ok=True)
        hb_file = hb_dir / "heartbeat"
        hb_file.touch()
        # Set mtime to 300 seconds ago
        old_mtime = time.time() - 300
        os.utime(hb_file, (old_mtime, old_mtime))

        with patch("colonyos.daemon.request_active_phase_cancel", return_value=1) as mock_cancel, \
             patch.object(daemon, "_watchdog_recover") as mock_recover:
            daemon._watchdog_check()

        mock_recover.assert_called_once()

    def test_auto_recovery_resets_state(self, tmp_repo: Path):
        """After stall detection, pipeline_running should be False and item marked FAILED."""
        config = ColonyConfig(daemon=DaemonConfig(
            daily_budget_usd=50.0,
            watchdog_stall_seconds=120,
        ))
        daemon = Daemon(tmp_repo, config, dry_run=True)

        item = QueueItem(
            id="stuck-item-2",
            source_type="prompt",
            source_value="hang forever",
            status=QueueItemStatus.RUNNING,
            priority=1,
        )
        daemon._queue_state.items = [item]
        daemon._pipeline_running = True
        daemon._pipeline_started_at = time.monotonic() - 300
        daemon._current_running_item = item

        with patch("colonyos.daemon.request_active_phase_cancel", return_value=1), \
             patch("colonyos.daemon.request_cancel", return_value=1), \
             patch.object(daemon, "_stop_event") as mock_stop:
            mock_stop.wait.return_value = False
            mock_stop.is_set.return_value = False
            daemon._watchdog_recover(stall_duration=300.0)

        assert daemon._pipeline_running is False
        assert daemon._pipeline_started_at is None
        assert daemon._current_running_item is None
        assert item.status == QueueItemStatus.FAILED
        assert "watchdog" in item.error.lower()

    def test_no_false_positive_with_fresh_heartbeat(self, tmp_repo: Path):
        """Watchdog should NOT fire when heartbeat file is fresh."""
        config = ColonyConfig(daemon=DaemonConfig(
            daily_budget_usd=50.0,
            watchdog_stall_seconds=120,
        ))
        daemon = Daemon(tmp_repo, config, dry_run=True)

        item = QueueItem(
            id="healthy-item",
            source_type="prompt",
            source_value="work fine",
            status=QueueItemStatus.RUNNING,
            priority=1,
        )
        daemon._queue_state.items = [item]
        daemon._pipeline_running = True
        daemon._pipeline_started_at = time.monotonic() - 30  # only 30s ago
        daemon._current_running_item = item

        # Create a fresh heartbeat file
        hb_dir = tmp_repo / ".colonyos" / "runs"
        hb_dir.mkdir(parents=True, exist_ok=True)
        hb_file = hb_dir / "heartbeat"
        hb_file.touch()  # mtime = now

        with patch.object(daemon, "_watchdog_recover") as mock_recover:
            daemon._watchdog_check()

        mock_recover.assert_not_called()

    def test_watchdog_inactive_when_no_pipeline(self, tmp_repo: Path, config: ColonyConfig):
        """Watchdog should do nothing when no pipeline is running."""
        daemon = Daemon(tmp_repo, config, dry_run=True)
        assert daemon._pipeline_running is False

        with patch.object(daemon, "_watchdog_recover") as mock_recover:
            daemon._watchdog_check()

        mock_recover.assert_not_called()

    def test_grace_period_fallback_cancel(self, tmp_repo: Path):
        """After initial cancel, if still stuck after grace period, request_cancel is called."""
        config = ColonyConfig(daemon=DaemonConfig(
            daily_budget_usd=50.0,
            watchdog_stall_seconds=120,
        ))
        daemon = Daemon(tmp_repo, config, dry_run=True)

        item = QueueItem(
            id="really-stuck",
            source_type="prompt",
            source_value="deadlock",
            status=QueueItemStatus.RUNNING,
            priority=1,
        )
        daemon._queue_state.items = [item]
        daemon._pipeline_running = True
        daemon._pipeline_started_at = time.monotonic() - 300
        daemon._current_running_item = item

        # Simulate: request_active_phase_cancel succeeds but pipeline stays stuck
        # _watchdog_recover should call request_cancel as fallback
        with patch("colonyos.daemon.request_active_phase_cancel", return_value=1) as mock_phase_cancel, \
             patch("colonyos.daemon.request_cancel", return_value=1) as mock_cancel, \
             patch.object(daemon, "_stop_event") as mock_stop:
            # Make wait() return immediately (simulating 30s passing)
            mock_stop.wait.return_value = False
            mock_stop.is_set.return_value = False
            # Keep _pipeline_running True after first cancel to trigger fallback
            daemon._watchdog_recover(stall_duration=300.0)

        mock_phase_cancel.assert_called_once()
        mock_cancel.assert_called_once()
        assert "fallback" in mock_cancel.call_args[0][0].lower() or "grace" in mock_cancel.call_args[0][0].lower()

    def test_current_running_item_tracking(self, daemon_instance: Daemon):
        """_current_running_item should be set during pipeline execution and cleared after."""
        daemon_instance.dry_run = False
        assert daemon_instance._current_running_item is None

        item = QueueItem(
            id="track-item",
            source_type="prompt",
            source_value="track me",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon_instance._queue_state.items = [item]

        fake_log = RunLog(
            run_id="run-track",
            prompt="track me",
            status=RunStatus.COMPLETED,
            total_cost_usd=0.01,
        )

        captured_item: list[QueueItem | None] = []

        def spy_execute(i: QueueItem) -> RunLog:
            captured_item.append(daemon_instance._current_running_item)
            return fake_log

        with patch.object(daemon_instance, "_preexec_worktree_state", return_value=("clean", "")), \
             patch.object(daemon_instance, "_execute_item", side_effect=spy_execute):
            daemon_instance._try_execute_next()

        # During execution, _current_running_item should have been set
        assert len(captured_item) == 1
        assert captured_item[0] is item

        # After execution, it should be cleared
        assert daemon_instance._current_running_item is None

    def test_watchdog_included_in_start_threads(self, tmp_repo: Path, config: ColonyConfig):
        """_start_threads should include the watchdog thread."""
        daemon = Daemon(tmp_repo, config, dry_run=True)
        threads = daemon._start_threads()
        # Find the watchdog thread
        watchdog_threads = [t for t in threads if t.name == "daemon-watchdog"]
        assert len(watchdog_threads) == 1
        assert watchdog_threads[0].daemon is True
        # Clean up
        daemon._stop_event.set()
        for t in threads:
            t.join(timeout=5)
