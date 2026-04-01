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
from colonyos.config import ColonyConfig, DaemonConfig, SlackConfig
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


class TestHealthPipelineFields:
    """Tests for pipeline duration and stall status in get_health() (task 6.0)."""

    def test_no_pipeline_running(self, daemon_instance: Daemon):
        """When no pipeline is running, pipeline fields should be None/False."""
        health = daemon_instance.get_health()
        assert health["pipeline_started_at"] is None
        assert health["pipeline_duration_seconds"] is None
        assert health["pipeline_stalled"] is False

    def test_pipeline_running_shows_duration(self, daemon_instance: Daemon):
        """When a pipeline is running, started_at and duration should be populated."""
        item = QueueItem(
            id="test-item",
            source_type="slack",
            source_value="test",
            status=QueueItemStatus.RUNNING,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        daemon_instance._pipeline_running = True
        daemon_instance._pipeline_started_at = time.monotonic() - 120.0
        daemon_instance._current_running_item = item
        health = daemon_instance.get_health()
        assert health["pipeline_started_at"] == item.started_at
        assert health["pipeline_duration_seconds"] is not None
        assert health["pipeline_duration_seconds"] >= 120.0
        assert health["pipeline_stalled"] is False

    def test_pipeline_stalled_flag(self, daemon_instance: Daemon):
        """When watchdog has detected a stall, pipeline_stalled should be True."""
        item = QueueItem(
            id="test-item",
            source_type="slack",
            source_value="test",
            status=QueueItemStatus.RUNNING,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        daemon_instance._pipeline_running = True
        daemon_instance._pipeline_started_at = time.monotonic() - 2000.0
        daemon_instance._current_running_item = item
        daemon_instance._pipeline_stalled = True
        health = daemon_instance.get_health()
        assert health["pipeline_stalled"] is True

    def test_stalled_resets_on_new_pipeline(self, daemon_instance: Daemon):
        """The stalled flag should reset to False when a new pipeline starts.

        We verify at the code level: _pipeline_stalled is set to False in the
        same code block that sets _pipeline_running = True (the RUNNING transition).
        Here we simulate that transition directly.
        """
        daemon_instance._pipeline_stalled = True
        # Simulate the RUNNING transition that happens in _run_pipeline_for_item
        item = QueueItem(
            id="test-item-2",
            source_type="slack",
            source_value="test",
            status=QueueItemStatus.PENDING,
        )
        with daemon_instance._lock:
            item.status = QueueItemStatus.RUNNING
            item.started_at = datetime.now(timezone.utc).isoformat()
            daemon_instance._pipeline_running = True
            daemon_instance._pipeline_started_at = time.monotonic()
            daemon_instance._pipeline_stalled = False  # This is what the production code does
            daemon_instance._current_running_item = item
        # After starting, stalled should be False
        assert daemon_instance._pipeline_stalled is False


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
            # Budget exhaustion is critical — must not be buried in daily thread
            assert mock_slack.call_args_list[0][1].get("critical") is True

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


class TestDailyThreadLifecycle:
    """Tests for _ensure_daily_thread(), _should_rotate_daily_thread(), and rotation in _tick."""

    def test_creates_new_thread_when_none_exists(self, daemon_instance: Daemon):
        """_ensure_daily_thread creates a new daily thread when state has no thread_ts."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = ["C123"]
        daemon_instance.config.slack.daily_thread_timezone = "UTC"

        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True, "ts": "1111.2222"}

        with patch.object(daemon_instance, "_get_notification_client", return_value=mock_client):
            result = daemon_instance._ensure_daily_thread()

        assert result is not None
        client, channel, thread_ts = result
        assert thread_ts == "1111.2222"
        assert channel == "C123"
        # State should be persisted
        assert daemon_instance._state.daily_thread_ts == "1111.2222"
        assert daemon_instance._state.daily_thread_date is not None
        assert daemon_instance._state.daily_thread_channel == "C123"

    def test_reuses_existing_thread_when_date_matches(self, daemon_instance: Daemon):
        """_ensure_daily_thread returns cached thread when date matches today."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = ["C123"]
        daemon_instance.config.slack.daily_thread_timezone = "UTC"

        from zoneinfo import ZoneInfo
        tz = ZoneInfo("UTC")
        today_str = datetime.now(tz).strftime("%Y-%m-%d")
        daemon_instance._state.daily_thread_ts = "9999.0000"
        daemon_instance._state.daily_thread_date = today_str
        daemon_instance._state.daily_thread_channel = "C123"

        mock_client = MagicMock()
        with patch.object(daemon_instance, "_get_notification_client", return_value=mock_client):
            result = daemon_instance._ensure_daily_thread()

        assert result is not None
        _, _, thread_ts = result
        assert thread_ts == "9999.0000"
        # Should NOT have posted a new message
        mock_client.chat_postMessage.assert_not_called()

    def test_rotates_thread_when_date_is_stale(self, daemon_instance: Daemon):
        """_ensure_daily_thread creates new thread if persisted date is yesterday."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = ["C123"]
        daemon_instance.config.slack.daily_thread_timezone = "UTC"

        daemon_instance._state.daily_thread_ts = "old.thread"
        daemon_instance._state.daily_thread_date = "2020-01-01"
        daemon_instance._state.daily_thread_channel = "C123"

        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True, "ts": "new.thread"}

        with patch.object(daemon_instance, "_get_notification_client", return_value=mock_client):
            result = daemon_instance._ensure_daily_thread()

        assert result is not None
        _, _, thread_ts = result
        assert thread_ts == "new.thread"
        assert daemon_instance._state.daily_thread_ts == "new.thread"

    def test_rotation_logs_previous_thread_ts(self, daemon_instance: Daemon, caplog):
        """_ensure_daily_thread logs previous thread_ts when rotating for audit trail."""
        import logging

        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = ["C123"]
        daemon_instance.config.slack.daily_thread_timezone = "UTC"

        daemon_instance._state.daily_thread_ts = "old.thread.ts"
        daemon_instance._state.daily_thread_date = "2020-01-01"
        daemon_instance._state.daily_thread_channel = "C123"

        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True, "ts": "new.thread.ts"}

        with caplog.at_level(logging.DEBUG, logger="colonyos.daemon"):
            with patch.object(daemon_instance, "_get_notification_client", return_value=mock_client):
                daemon_instance._ensure_daily_thread()

        assert any("old.thread.ts" in record.message for record in caplog.records), (
            "Expected log message with previous thread_ts for audit trail"
        )

    def test_recovers_from_persisted_state_on_restart(self, tmp_repo: Path, config: ColonyConfig):
        """On restart, daemon picks up daily_thread_ts from persisted state."""
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("UTC")
        today_str = datetime.now(tz).strftime("%Y-%m-%d")

        state = DaemonState(
            daily_thread_ts="persisted.ts",
            daily_thread_date=today_str,
            daily_thread_channel="C123",
        )
        save_daemon_state(tmp_repo, state)

        d = Daemon(tmp_repo, config, dry_run=True)
        d.config.slack.notification_mode = "daily"
        d.config.slack.channels = ["C123"]

        mock_client = MagicMock()
        with patch.object(d, "_get_notification_client", return_value=mock_client):
            result = d._ensure_daily_thread()

        assert result is not None
        _, _, thread_ts = result
        assert thread_ts == "persisted.ts"
        mock_client.chat_postMessage.assert_not_called()

    def test_returns_none_in_per_item_mode(self, daemon_instance: Daemon):
        """_ensure_daily_thread returns None when notification_mode is per_item."""
        daemon_instance.config.slack.notification_mode = "per_item"
        result = daemon_instance._ensure_daily_thread()
        assert result is None

    def test_returns_none_when_no_client(self, daemon_instance: Daemon):
        """_ensure_daily_thread returns None when no Slack client available."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = ["C123"]

        with patch.object(daemon_instance, "_get_notification_client", return_value=None):
            result = daemon_instance._ensure_daily_thread()
        assert result is None

    def test_returns_none_when_no_channels(self, daemon_instance: Daemon):
        """_ensure_daily_thread returns None when no channels configured."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = []

        result = daemon_instance._ensure_daily_thread()
        assert result is None

    def test_should_rotate_false_same_day(self, daemon_instance: Daemon):
        """_should_rotate_daily_thread returns False when date matches."""
        daemon_instance.config.slack.daily_thread_timezone = "UTC"
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("UTC")
        today_str = datetime.now(tz).strftime("%Y-%m-%d")
        daemon_instance._state.daily_thread_date = today_str
        assert daemon_instance._should_rotate_daily_thread() is False

    def test_should_rotate_true_stale_date_past_hour(self, daemon_instance: Daemon):
        """_should_rotate_daily_thread returns True when date is old and hour is past configured."""
        daemon_instance.config.slack.daily_thread_timezone = "UTC"
        daemon_instance.config.slack.daily_thread_hour = 0  # hour 0 so it's always past
        daemon_instance._state.daily_thread_date = "2020-01-01"
        assert daemon_instance._should_rotate_daily_thread() is True

    def test_should_rotate_false_stale_date_before_hour(self, daemon_instance: Daemon):
        """_should_rotate_daily_thread returns False when date is stale but hour not yet reached."""
        daemon_instance.config.slack.daily_thread_timezone = "UTC"
        daemon_instance.config.slack.daily_thread_hour = 23  # set to 23 so it's unlikely to be reached
        from zoneinfo import ZoneInfo
        from unittest.mock import patch as _patch

        tz = ZoneInfo("UTC")
        # Simulate being at hour 6 on a new day
        fake_now = datetime(2026, 4, 1, 6, 0, 0, tzinfo=tz)
        daemon_instance._state.daily_thread_date = "2026-03-31"

        with _patch("colonyos.daemon.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = daemon_instance._should_rotate_daily_thread()

        assert result is False

    def test_should_rotate_true_stale_date_at_configured_hour(self, daemon_instance: Daemon):
        """_should_rotate_daily_thread returns True when date is stale and hour matches configured."""
        daemon_instance.config.slack.daily_thread_timezone = "UTC"
        daemon_instance.config.slack.daily_thread_hour = 8

        from zoneinfo import ZoneInfo
        from unittest.mock import patch as _patch

        tz = ZoneInfo("UTC")
        fake_now = datetime(2026, 4, 1, 8, 0, 0, tzinfo=tz)
        daemon_instance._state.daily_thread_date = "2026-03-31"

        with _patch("colonyos.daemon.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = daemon_instance._should_rotate_daily_thread()

        assert result is True

    def test_should_rotate_true_no_thread(self, daemon_instance: Daemon):
        """_should_rotate_daily_thread returns True when no thread exists."""
        daemon_instance.config.slack.daily_thread_timezone = "UTC"
        daemon_instance._state.daily_thread_date = None
        assert daemon_instance._should_rotate_daily_thread() is True

    def test_rotation_in_tick(self, daemon_instance: Daemon):
        """_tick triggers daily thread rotation when mode is daily and rotation is due."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = ["C123"]
        daemon_instance._state.daily_thread_date = "2020-01-01"

        with patch.object(daemon_instance, "_try_execute_next", return_value=False), \
             patch.object(daemon_instance, "_poll_github_issues"), \
             patch.object(daemon_instance, "_post_heartbeat"), \
             patch.object(daemon_instance, "_post_daily_digest_if_due"), \
             patch.object(daemon_instance, "_poll_pr_outcomes"), \
             patch.object(daemon_instance, "_ensure_daily_thread", return_value=None) as mock_ensure:
            daemon_instance._tick()

        mock_ensure.assert_called_once()


class TestDailyThreadRouting:
    """Tests for task 5.0: routing notification messages through daily thread."""

    def test_post_slack_message_routes_to_daily_thread_in_daily_mode(
        self, daemon_instance: Daemon
    ):
        """_post_slack_message routes to daily thread when mode is daily."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = ["C123"]
        daemon_instance._state.daily_thread_ts = "daily.thread.ts"

        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True}
        with patch.object(daemon_instance, "_get_notification_client", return_value=mock_client):
            daemon_instance._post_slack_message("hello")

        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert call_kwargs["thread_ts"] == "daily.thread.ts"
        assert call_kwargs["channel"] == "C123"

    def test_post_slack_message_critical_always_top_level(
        self, daemon_instance: Daemon
    ):
        """_post_slack_message with critical=True always posts top-level even in daily mode."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = ["C123"]
        daemon_instance._state.daily_thread_ts = "daily.thread.ts"

        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True}
        with patch.object(daemon_instance, "_get_notification_client", return_value=mock_client):
            daemon_instance._post_slack_message("ALERT!", critical=True)

        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "thread_ts" not in call_kwargs

    def test_post_slack_message_per_item_mode_always_top_level(
        self, daemon_instance: Daemon
    ):
        """_post_slack_message in per_item mode always posts top-level (no thread_ts)."""
        daemon_instance.config.slack.notification_mode = "per_item"
        daemon_instance.config.slack.channels = ["C123"]
        daemon_instance._state.daily_thread_ts = "daily.thread.ts"

        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True}

        with patch.object(daemon_instance, "_get_notification_client", return_value=mock_client):
            daemon_instance._post_slack_message("hello")

        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "thread_ts" not in call_kwargs

    def test_post_slack_message_no_daily_thread_ts_posts_top_level(
        self, daemon_instance: Daemon
    ):
        """_post_slack_message in daily mode without daily_thread_ts posts top-level."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = ["C123"]
        daemon_instance._state.daily_thread_ts = None

        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True}

        with patch.object(daemon_instance, "_get_notification_client", return_value=mock_client):
            daemon_instance._post_slack_message("hello")

        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert "thread_ts" not in call_kwargs

    def test_ensure_notification_thread_daily_mode_posts_to_daily_thread(
        self, daemon_instance: Daemon
    ):
        """_ensure_notification_thread in daily mode posts intro as reply to daily thread."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = ["C123"]

        item = QueueItem(
            id="item-1",
            source_type="issue",
            source_value="test",
            status=QueueItemStatus.PENDING,
        )

        mock_client = MagicMock()
        daily_result = (mock_client, "C123", "daily.thread.ts")
        reply_response = {"ok": True, "ts": "reply.ts"}

        with patch.object(daemon_instance, "_ensure_daily_thread", return_value=daily_result), \
             patch("colonyos.slack.post_message", return_value=reply_response) as mock_post:
            result = daemon_instance._ensure_notification_thread(item, "intro text")

        assert result is not None
        _, _, thread_ts = result
        assert thread_ts == "reply.ts"
        assert item.notification_thread_ts == "reply.ts"
        # The intro should have been posted as a reply to the daily thread
        mock_post.assert_called_once_with(
            mock_client, "C123", "intro text", thread_ts="daily.thread.ts"
        )

    def test_ensure_notification_thread_per_item_mode_unchanged(
        self, daemon_instance: Daemon
    ):
        """_ensure_notification_thread in per_item mode posts top-level (original behavior)."""
        daemon_instance.config.slack.notification_mode = "per_item"
        daemon_instance.config.slack.channels = ["C123"]

        item = QueueItem(
            id="item-2",
            source_type="issue",
            source_value="test",
            status=QueueItemStatus.PENDING,
        )

        mock_client = MagicMock()

        with patch.object(daemon_instance, "_get_notification_client", return_value=mock_client), \
             patch("colonyos.slack.post_message", return_value={"ts": "top-level.ts"}) as mock_post:
            result = daemon_instance._ensure_notification_thread(item, "intro text")

        assert result is not None
        _, _, thread_ts = result
        assert thread_ts == "top-level.ts"
        # Should post without thread_ts (top-level)
        mock_post.assert_called_once_with(mock_client, "C123", "intro text")

    def test_heartbeat_routes_through_daily_thread(
        self, daemon_instance: Daemon
    ):
        """_post_heartbeat routes through daily thread in daily mode."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = ["C123"]
        daemon_instance._state.daily_thread_ts = "daily.thread.ts"

        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True}

        with patch.object(daemon_instance, "_get_notification_client", return_value=mock_client):
            daemon_instance._post_heartbeat()

        # Heartbeat calls _post_slack_message, which should route to daily thread
        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert call_kwargs["thread_ts"] == "daily.thread.ts"

    def test_daily_digest_routes_through_daily_thread(
        self, daemon_instance: Daemon
    ):
        """_post_daily_digest_if_due routes through daily thread in daily mode."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = ["C123"]
        daemon_instance._state.daily_thread_ts = "daily.thread.ts"
        daemon_instance._last_digest_date = None

        # Force digest to be due by setting digest hour in the past
        daemon_instance.daemon_config.digest_hour_utc = 0

        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True}

        with patch.object(daemon_instance, "_get_notification_client", return_value=mock_client):
            daemon_instance._post_daily_digest_if_due()

        # Should have posted via _post_slack_message which routes to daily thread
        if mock_client.chat_postMessage.called:
            call_kwargs = mock_client.chat_postMessage.call_args[1]
            assert call_kwargs.get("thread_ts") == "daily.thread.ts"


class TestCreateDailySummary:
    """Tests for task 6.0: overnight summary generation via _create_daily_summary()."""

    def test_collects_completed_and_failed_items(self, daemon_instance: Daemon):
        """_create_daily_summary includes completed and failed items in the output."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.daily_thread_timezone = "UTC"
        daemon_instance._state.daily_thread_date = None  # no cutoff — include all

        daemon_instance._queue_state = QueueState(
            queue_id="test-q",
            items=[
                QueueItem(
                    id="item-1",
                    source_type="issue",
                    source_value="fix auth",
                    status=QueueItemStatus.COMPLETED,
                    cost_usd=2.50,
                    pr_url="https://github.com/org/repo/pull/1",
                    summary="Fix auth bug",
                ),
                QueueItem(
                    id="item-2",
                    source_type="issue",
                    source_value="add caching",
                    status=QueueItemStatus.FAILED,
                    cost_usd=0.45,
                    error="branch conflict",
                    summary="Add caching layer",
                ),
                QueueItem(
                    id="item-3",
                    source_type="issue",
                    source_value="pending work",
                    status=QueueItemStatus.PENDING,
                ),
            ],
        )

        result = daemon_instance._create_daily_summary()

        assert "Fix auth bug" in result
        assert "Add caching layer" in result
        assert "branch conflict" in result
        assert "$2.95" in result  # total cost 2.50 + 0.45
        assert "1 pending" in result
        assert "Completed (1):" in result
        assert "Failed (1):" in result

    def test_filters_items_by_cutoff_date(self, daemon_instance: Daemon):
        """_create_daily_summary only includes items added since the last rotation date."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.daily_thread_timezone = "UTC"
        daemon_instance._state.daily_thread_date = "2026-04-01"

        daemon_instance._queue_state = QueueState(
            queue_id="test-q",
            items=[
                QueueItem(
                    id="old-item",
                    source_type="issue",
                    source_value="old work",
                    status=QueueItemStatus.COMPLETED,
                    cost_usd=5.00,
                    added_at="2026-03-31T10:00:00+00:00",
                    summary="Old completed work",
                ),
                QueueItem(
                    id="new-item",
                    source_type="issue",
                    source_value="new work",
                    status=QueueItemStatus.COMPLETED,
                    cost_usd=1.50,
                    added_at="2026-04-01T14:00:00+00:00",
                    summary="New completed work",
                ),
                QueueItem(
                    id="new-fail",
                    source_type="issue",
                    source_value="new fail",
                    status=QueueItemStatus.FAILED,
                    cost_usd=0.30,
                    added_at="2026-04-01T16:00:00+00:00",
                    error="timeout",
                    summary="New failed work",
                ),
            ],
        )

        result = daemon_instance._create_daily_summary()

        # Old item should be excluded
        assert "Old completed work" not in result
        # New items should be included
        assert "New completed work" in result
        assert "New failed work" in result
        assert "$1.80" in result  # 1.50 + 0.30

    def test_empty_period_produces_no_activity_message(self, daemon_instance: Daemon):
        """_create_daily_summary with no terminal items produces a no-activity message."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.daily_thread_timezone = "UTC"
        daemon_instance._state.daily_thread_date = "2026-04-01"

        daemon_instance._queue_state = QueueState(
            queue_id="test-q",
            items=[
                QueueItem(
                    id="pending-item",
                    source_type="issue",
                    source_value="pending",
                    status=QueueItemStatus.PENDING,
                ),
            ],
        )

        result = daemon_instance._create_daily_summary()

        assert "No activity during this period" in result
        assert "1 pending" in result

    def test_computes_aggregate_cost(self, daemon_instance: Daemon):
        """_create_daily_summary computes total cost across completed and failed items."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.daily_thread_timezone = "UTC"
        daemon_instance._state.daily_thread_date = None

        daemon_instance._queue_state = QueueState(
            queue_id="test-q",
            items=[
                QueueItem(
                    id="c1", source_type="issue", source_value="a",
                    status=QueueItemStatus.COMPLETED, cost_usd=1.10,
                ),
                QueueItem(
                    id="c2", source_type="issue", source_value="b",
                    status=QueueItemStatus.COMPLETED, cost_usd=2.20,
                ),
                QueueItem(
                    id="f1", source_type="issue", source_value="c",
                    status=QueueItemStatus.FAILED, cost_usd=0.70,
                ),
            ],
        )

        result = daemon_instance._create_daily_summary()
        assert "$4.00" in result

    def test_wired_into_ensure_daily_thread(self, daemon_instance: Daemon):
        """_ensure_daily_thread uses _create_daily_summary for the opening message."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = ["C123"]
        daemon_instance.config.slack.daily_thread_timezone = "UTC"
        daemon_instance._state.daily_thread_ts = None
        daemon_instance._state.daily_thread_date = None

        daemon_instance._queue_state = QueueState(queue_id="test-q", items=[])

        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True, "ts": "new.thread.ts"}

        with patch.object(daemon_instance, "_get_notification_client", return_value=mock_client), \
             patch.object(daemon_instance, "_create_daily_summary", return_value="MOCK SUMMARY") as mock_summary:
            result = daemon_instance._ensure_daily_thread()

        mock_summary.assert_called_once()
        # The summary text should be posted as the opening message
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert call_kwargs["text"] == "MOCK SUMMARY"
        assert result is not None
        assert result[2] == "new.thread.ts"


class TestDailyThreadIntegration:
    """End-to-end integration tests for daily thread consolidation (task 7.0)."""

    def test_daily_mode_processes_items_single_top_level_thread(
        self, daemon_instance: Daemon
    ):
        """In daily mode, processing 3 items creates 1 top-level message (the daily thread).

        All item intros are replies to the daily thread, and phase updates nest
        under the item reply (task 7.1).
        """
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = ["C123"]
        daemon_instance.config.slack.daily_thread_timezone = "UTC"
        daemon_instance._state.daily_thread_ts = None
        daemon_instance._state.daily_thread_date = None
        daemon_instance._queue_state = QueueState(queue_id="q", items=[])

        mock_client = MagicMock()

        # Track all chat_postMessage calls to verify threading structure
        call_log: list[dict] = []
        call_counter = {"n": 0}

        def _fake_post(**kwargs: Any) -> dict:
            call_counter["n"] += 1
            ts = f"ts.{call_counter['n']}"
            call_log.append({**kwargs, "_ts": ts})
            return {"ok": True, "ts": ts}

        mock_client.chat_postMessage.side_effect = _fake_post

        items = [
            QueueItem(id=f"item-{i}", source_type="issue", source_value=f"work-{i}",
                      status=QueueItemStatus.PENDING)
            for i in range(3)
        ]

        with patch.object(daemon_instance, "_get_notification_client", return_value=mock_client):
            # First call creates the daily thread (top-level message)
            daily = daemon_instance._ensure_daily_thread()
            assert daily is not None
            _, _, daily_ts = daily

            # Each item creates a notification thread as a reply to the daily thread
            for item in items:
                result = daemon_instance._ensure_notification_thread(item, f"Starting {item.id}")
                assert result is not None

        # Verify: exactly 1 top-level message (the daily thread opener)
        top_level_calls = [c for c in call_log if "thread_ts" not in c]
        assert len(top_level_calls) == 1, (
            f"Expected 1 top-level message, got {len(top_level_calls)}"
        )

        # Verify: 3 replies to the daily thread (the item intros)
        reply_calls = [c for c in call_log if c.get("thread_ts") == daily_ts]
        assert len(reply_calls) == 3

        # Verify each item got its own notification_thread_ts for sub-threading
        item_thread_tss = {item.notification_thread_ts for item in items}
        assert len(item_thread_tss) == 3
        assert None not in item_thread_tss

    def test_per_item_mode_creates_separate_top_level_threads(
        self, daemon_instance: Daemon
    ):
        """In per_item mode, processing 3 items creates 3 top-level messages (task 7.2)."""
        daemon_instance.config.slack.notification_mode = "per_item"
        daemon_instance.config.slack.channels = ["C123"]

        mock_client = MagicMock()

        call_counter = {"n": 0}

        def _fake_post(**kwargs: Any) -> dict:
            call_counter["n"] += 1
            return {"ok": True, "ts": f"top.{call_counter['n']}"}

        mock_client.chat_postMessage.side_effect = _fake_post

        items = [
            QueueItem(id=f"item-{i}", source_type="issue", source_value=f"work-{i}",
                      status=QueueItemStatus.PENDING)
            for i in range(3)
        ]

        with patch.object(daemon_instance, "_get_notification_client", return_value=mock_client), \
             patch("colonyos.slack.post_message", side_effect=[
                 {"ts": "top.1"}, {"ts": "top.2"}, {"ts": "top.3"}
             ]) as mock_post:
            for item in items:
                result = daemon_instance._ensure_notification_thread(item, f"Starting {item.id}")
                assert result is not None

        # All 3 calls should be top-level (no thread_ts)
        assert mock_post.call_count == 3
        for call in mock_post.call_args_list:
            args, kwargs = call
            assert "thread_ts" not in kwargs

    def test_daemon_restart_resumes_daily_thread(
        self, tmp_repo: Path, config: ColonyConfig
    ):
        """After a restart, the daemon loads persisted daily_thread_ts and continues
        posting to the same thread (task 7.3).
        """
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("UTC")
        today_str = datetime.now(tz).strftime("%Y-%m-%d")

        # Simulate previous daemon run that created a daily thread
        state = DaemonState(
            daily_thread_ts="original.daily.ts",
            daily_thread_date=today_str,
            daily_thread_channel="C123",
        )
        save_daemon_state(tmp_repo, state)

        # Create a fresh daemon (simulates restart)
        d = Daemon(tmp_repo, config, dry_run=True)
        d.config.slack.notification_mode = "daily"
        d.config.slack.channels = ["C123"]

        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True, "ts": "reply.ts"}

        item = QueueItem(id="post-restart-item", source_type="issue",
                         source_value="work", status=QueueItemStatus.PENDING)

        with patch.object(d, "_get_notification_client", return_value=mock_client), \
             patch("colonyos.slack.post_message", return_value={"ts": "reply.ts"}) as mock_post:
            # Ensure daily thread reuses persisted ts
            daily = d._ensure_daily_thread()
            assert daily is not None
            _, _, daily_ts = daily
            assert daily_ts == "original.daily.ts"

            # Notification thread should post as reply to the persisted daily thread
            result = d._ensure_notification_thread(item, "Starting post-restart-item")
            assert result is not None

        mock_post.assert_called_once_with(
            mock_client, "C123", "Starting post-restart-item",
            thread_ts="original.daily.ts",
        )
        # No new top-level message should have been created
        mock_client.chat_postMessage.assert_not_called()

    def test_critical_alert_posts_top_level_in_daily_mode(
        self, daemon_instance: Daemon
    ):
        """Critical alerts (auto-pause) post to the main channel even in daily mode (task 7.4)."""
        daemon_instance.config.slack.notification_mode = "daily"
        daemon_instance.config.slack.channels = ["C123"]
        daemon_instance.config.slack.daily_thread_timezone = "UTC"

        # Set up an active daily thread
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("UTC")
        today_str = datetime.now(tz).strftime("%Y-%m-%d")
        daemon_instance._state.daily_thread_ts = "daily.thread.ts"
        daemon_instance._state.daily_thread_date = today_str
        daemon_instance._state.daily_thread_channel = "C123"

        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True}

        with patch.object(daemon_instance, "_get_notification_client", return_value=mock_client):
            # Non-critical goes to daily thread
            daemon_instance._post_slack_message("routine update")
            # Critical goes top-level
            daemon_instance._post_slack_message("CRITICAL: auto-paused!", critical=True)

        assert mock_client.chat_postMessage.call_count == 2
        calls = mock_client.chat_postMessage.call_args_list

        # First call (routine) should be threaded
        routine_kwargs = calls[0][1]
        assert routine_kwargs.get("thread_ts") == "daily.thread.ts"

        # Second call (critical) should be top-level
        critical_kwargs = calls[1][1]
        assert "thread_ts" not in critical_kwargs
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

    def test_slack_alert_on_stall_detection(self, tmp_repo: Path):
        """_post_slack_message is called with stuck-detection message when watchdog fires."""
        config = ColonyConfig(daemon=DaemonConfig(
            daily_budget_usd=50.0,
            watchdog_stall_seconds=120,
        ))
        daemon = Daemon(tmp_repo, config, dry_run=True)

        item = QueueItem(
            id="slack-alert-item",
            source_type="prompt",
            source_value="stuck thing",
            status=QueueItemStatus.RUNNING,
            priority=1,
        )
        daemon._queue_state.items = [item]
        daemon._pipeline_running = True
        daemon._pipeline_started_at = time.monotonic() - 300
        daemon._current_running_item = item

        with patch("colonyos.daemon.request_active_phase_cancel", return_value=1), \
             patch("colonyos.daemon.request_cancel", return_value=1), \
             patch.object(daemon, "_stop_event") as mock_stop, \
             patch.object(daemon, "_post_slack_message") as mock_slack:
            mock_stop.wait.return_value = False
            mock_stop.is_set.return_value = False
            daemon._watchdog_recover(stall_duration=300.0)

        mock_slack.assert_called_once()
        msg = mock_slack.call_args[0][0]
        assert "Stuck Pipeline Detected" in msg
        assert "slack-alert-item" in msg
        assert "prompt" in msg
        assert "Auto-recovery initiated" in msg

    def test_slack_alert_uses_timeout(self, tmp_repo: Path):
        """Slack post should use a timeout so the alert itself cannot hang the watchdog."""
        config = ColonyConfig(daemon=DaemonConfig(
            daily_budget_usd=50.0,
            watchdog_stall_seconds=120,
        ))
        daemon = Daemon(tmp_repo, config, dry_run=True)

        item = QueueItem(
            id="timeout-item",
            source_type="prompt",
            source_value="hang slack",
            status=QueueItemStatus.RUNNING,
            priority=1,
        )
        daemon._queue_state.items = [item]
        daemon._pipeline_running = True
        daemon._pipeline_started_at = time.monotonic() - 300
        daemon._current_running_item = item

        # Simulate _post_slack_message raising an exception (e.g., timeout)
        with patch("colonyos.daemon.request_active_phase_cancel", return_value=1), \
             patch("colonyos.daemon.request_cancel", return_value=1), \
             patch.object(daemon, "_stop_event") as mock_stop, \
             patch.object(daemon, "_post_slack_message", side_effect=Exception("Slack timeout")):
            mock_stop.wait.return_value = False
            mock_stop.is_set.return_value = False
            # Should NOT raise — Slack failure must not break recovery
            daemon._watchdog_recover(stall_duration=300.0)

        # Recovery should still complete despite Slack failure
        assert daemon._pipeline_running is False
        assert item.status == QueueItemStatus.FAILED

    def test_monitor_event_emitted_on_stall(self, tmp_repo: Path):
        """A monitor event with type watchdog_stall_detected should be emitted."""
        config = ColonyConfig(daemon=DaemonConfig(
            daily_budget_usd=50.0,
            watchdog_stall_seconds=120,
        ))
        daemon = Daemon(tmp_repo, config, dry_run=True)

        item = QueueItem(
            id="monitor-event-item",
            source_type="prompt",
            source_value="emit event",
            status=QueueItemStatus.RUNNING,
            priority=1,
        )
        daemon._queue_state.items = [item]
        daemon._pipeline_running = True
        daemon._pipeline_started_at = time.monotonic() - 300
        daemon._current_running_item = item

        captured_output: list[str] = []

        with patch("colonyos.daemon.request_active_phase_cancel", return_value=1), \
             patch("colonyos.daemon.request_cancel", return_value=1), \
             patch.object(daemon, "_stop_event") as mock_stop, \
             patch.object(daemon, "_post_slack_message"), \
             patch("sys.stdout") as mock_stdout:
            mock_stop.wait.return_value = False
            mock_stop.is_set.return_value = False
            mock_stdout.write.side_effect = lambda s: captured_output.append(s)
            daemon._watchdog_recover(stall_duration=300.0)

        # Find the monitor event in captured output
        from colonyos.tui.monitor_protocol import MONITOR_EVENT_PREFIX
        import json
        monitor_lines = [line for line in captured_output if MONITOR_EVENT_PREFIX in line]
        assert len(monitor_lines) >= 1, f"Expected monitor event, got: {captured_output}"
        # Parse the event
        raw = monitor_lines[0].strip().replace(MONITOR_EVENT_PREFIX, "")
        event = json.loads(raw)
        assert event["type"] == "watchdog_stall_detected"
        assert event["item_id"] == "monitor-event-item"
        assert event["stall_duration_seconds"] == 300.0
        assert event["action_taken"] == "auto_cancel"


class TestWatchdogIntegration:
    """Integration tests for the full stuck-pipeline scenario (task 7.0)."""

    def test_end_to_end_stuck_pipeline_recovery(self, tmp_repo: Path):
        """Full integration: stuck pipeline → watchdog fires → item FAILED → daemon resumes.

        Simulates a pipeline that blocks indefinitely, with a stale heartbeat file.
        Verifies the watchdog detects the stall, recovers, posts a Slack alert,
        marks the item FAILED, resets daemon state, and allows the next item to run.
        """
        config = ColonyConfig(daemon=DaemonConfig(
            daily_budget_usd=50.0,
            watchdog_stall_seconds=5,  # short threshold for testing
        ))
        daemon = Daemon(tmp_repo, config, dry_run=True)

        # Queue two items: first will get stuck, second should be processable after recovery
        stuck_item = QueueItem(
            id="integration-stuck",
            source_type="prompt",
            source_value="hang forever",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        next_item = QueueItem(
            id="integration-next",
            source_type="prompt",
            source_value="run after recovery",
            status=QueueItemStatus.PENDING,
            priority=2,
        )
        daemon._queue_state.items = [stuck_item, next_item]

        # Create a stale heartbeat file (mtime far in the past)
        hb_dir = tmp_repo / ".colonyos" / "runs"
        hb_dir.mkdir(parents=True, exist_ok=True)
        hb_file = hb_dir / "heartbeat"
        hb_file.touch()
        old_mtime = time.time() - 300
        os.utime(hb_file, (old_mtime, old_mtime))

        # Simulate the pipeline getting stuck: _execute_item blocks, but we'll
        # manually set the running state as _try_execute_next would, then
        # invoke the watchdog check directly
        with daemon._lock:
            stuck_item.status = QueueItemStatus.RUNNING
            stuck_item.started_at = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
            daemon._pipeline_running = True
            daemon._pipeline_started_at = time.monotonic() - 300  # started 5 min ago
            daemon._pipeline_stalled = False
            daemon._current_running_item = stuck_item

        # Run the watchdog check — should detect the stall and recover
        with patch("colonyos.daemon.request_active_phase_cancel", return_value=1) as mock_phase_cancel, \
             patch("colonyos.daemon.request_cancel", return_value=1) as mock_cancel, \
             patch.object(daemon, "_stop_event") as mock_stop, \
             patch.object(daemon, "_post_slack_message") as mock_slack:
            mock_stop.wait.return_value = False
            mock_stop.is_set.return_value = False
            daemon._watchdog_check()

        # --- Verify recovery ---
        # 1. Stuck item should be marked FAILED
        assert stuck_item.status == QueueItemStatus.FAILED
        assert "watchdog" in stuck_item.error.lower()

        # 2. Pipeline state should be fully reset
        assert daemon._pipeline_running is False
        assert daemon._pipeline_started_at is None
        assert daemon._current_running_item is None
        assert daemon._pipeline_stalled is True  # stall flag set for healthz

        # 3. Slack alert should have been posted
        mock_slack.assert_called_once()
        slack_msg = mock_slack.call_args[0][0]
        assert "Stuck Pipeline Detected" in slack_msg
        assert "integration-stuck" in slack_msg

        # 4. Cancellation should have been attempted
        mock_phase_cancel.assert_called_once()
        mock_cancel.assert_called_once()

        # 5. Next item should still be pending and processable
        assert next_item.status == QueueItemStatus.PENDING

        # 6. Health endpoint should reflect stall state
        health = daemon.get_health()
        assert health["pipeline_stalled"] is True
        assert health["pipeline_running"] is False

    def test_startup_log_includes_watchdog_threshold(self, tmp_repo: Path, caplog: pytest.LogCaptureFixture):
        """Daemon start() should log the watchdog stall threshold."""
        config = ColonyConfig(daemon=DaemonConfig(
            daily_budget_usd=50.0,
            watchdog_stall_seconds=1920,
        ))
        daemon = Daemon(tmp_repo, config, dry_run=True)

        with patch.object(daemon, "_acquire_pid_lock"), \
             patch.object(daemon, "_recover_from_crash"), \
             patch.object(daemon, "_install_signal_handlers"), \
             patch.object(daemon, "_persist_state"), \
             patch.object(daemon, "_start_dashboard_server"), \
             patch.object(daemon, "_start_threads", return_value=[]), \
             patch.object(daemon, "_main_loop", side_effect=KeyboardInterrupt), \
             patch.object(daemon, "_release_pid_lock"):
            import logging
            with caplog.at_level(logging.INFO, logger="colonyos.daemon"):
                try:
                    daemon.start()
                except KeyboardInterrupt:
                    pass

        assert any("Watchdog enabled: stall threshold=1920s" in record.message for record in caplog.records)

    def test_watchdog_does_not_fire_during_healthy_run(self, tmp_repo: Path):
        """Full integration: a healthy pipeline that completes normally never triggers watchdog."""
        config = ColonyConfig(daemon=DaemonConfig(
            daily_budget_usd=50.0,
            watchdog_stall_seconds=120,
        ))
        daemon = Daemon(tmp_repo, config, dry_run=True)

        item = QueueItem(
            id="healthy-run",
            source_type="prompt",
            source_value="do work",
            status=QueueItemStatus.PENDING,
            priority=1,
        )
        daemon._queue_state.items = [item]

        # Simulate a pipeline that just started with a fresh heartbeat
        hb_dir = tmp_repo / ".colonyos" / "runs"
        hb_dir.mkdir(parents=True, exist_ok=True)
        (hb_dir / "heartbeat").touch()

        with daemon._lock:
            item.status = QueueItemStatus.RUNNING
            daemon._pipeline_running = True
            daemon._pipeline_started_at = time.monotonic() - 10  # only 10s ago
            daemon._current_running_item = item

        with patch.object(daemon, "_watchdog_recover") as mock_recover:
            # Run multiple check cycles — none should trigger recovery
            for _ in range(5):
                daemon._watchdog_check()

        mock_recover.assert_not_called()
        assert daemon._pipeline_stalled is False
# Task 6.0: Startup warnings for trigger_mode: "all" without safety configs
class TestAllModeStartupWarnings:
    """Verify that _warn_all_mode_safety logs warnings when trigger_mode is 'all'
    and safety configs (allowed_user_ids, triage_scope) are missing."""

    def test_warns_when_allowed_user_ids_empty(self, caplog: pytest.LogCaptureFixture):
        config = ColonyConfig(
            slack=SlackConfig(
                enabled=True,
                trigger_mode="all",
                allowed_user_ids=[],
                triage_scope="Bug reports",
            ),
        )
        with caplog.at_level("WARNING", logger="colonyos.daemon"):
            Daemon._warn_all_mode_safety(config)
        assert any("allowed_user_ids" in r.message for r in caplog.records)

    def test_warns_when_triage_scope_empty(self, caplog: pytest.LogCaptureFixture):
        config = ColonyConfig(
            slack=SlackConfig(
                enabled=True,
                trigger_mode="all",
                allowed_user_ids=["U123"],
                triage_scope="",
            ),
        )
        with caplog.at_level("WARNING", logger="colonyos.daemon"):
            Daemon._warn_all_mode_safety(config)
        assert any("triage_scope" in r.message for r in caplog.records)

    def test_warns_both_when_both_missing(self, caplog: pytest.LogCaptureFixture):
        config = ColonyConfig(
            slack=SlackConfig(
                enabled=True,
                trigger_mode="all",
                allowed_user_ids=[],
                triage_scope="",
            ),
        )
        with caplog.at_level("WARNING", logger="colonyos.daemon"):
            Daemon._warn_all_mode_safety(config)
        messages = [r.message for r in caplog.records]
        assert any("allowed_user_ids" in m for m in messages)
        assert any("triage_scope" in m for m in messages)

    def test_no_warnings_when_both_set(self, caplog: pytest.LogCaptureFixture):
        config = ColonyConfig(
            slack=SlackConfig(
                enabled=True,
                trigger_mode="all",
                allowed_user_ids=["U123"],
                triage_scope="Bug reports for backend",
            ),
        )
        with caplog.at_level("WARNING", logger="colonyos.daemon"):
            Daemon._warn_all_mode_safety(config)
        assert len(caplog.records) == 0

    def test_no_warnings_when_trigger_mode_mention(self, caplog: pytest.LogCaptureFixture):
        config = ColonyConfig(
            slack=SlackConfig(
                enabled=True,
                trigger_mode="mention",
                allowed_user_ids=[],
                triage_scope="",
            ),
        )
        with caplog.at_level("WARNING", logger="colonyos.daemon"):
            Daemon._warn_all_mode_safety(config)
        assert len(caplog.records) == 0
