"""Tests for daemon orchestration."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colonyos.cleanup import ComplexityCategory, FileComplexity
from colonyos.config import ColonyConfig, DaemonConfig
from colonyos.daemon import Daemon, DaemonError
from colonyos.daemon_state import DaemonState, save_daemon_state
from colonyos.models import (
    Phase,
    PhaseResult,
    QueueItem,
    QueueItemStatus,
    QueueState,
    RunLog,
    RunStatus,
)
from colonyos.recovery import PreservationResult
from colonyos.runtime_lock import RuntimeBusyError
from colonyos.slack import SlackWatchState, save_watch_state


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
             patch.object(daemon_instance, "_post_daily_digest_if_due") as mock_digest:
            daemon_instance._tick()

        mock_execute.assert_called_once()
        mock_ceo.assert_not_called()
        mock_poll.assert_called_once()
        mock_cleanup.assert_called_once()
        mock_reprioritize.assert_called_once()
        mock_heartbeat.assert_called_once()
        mock_outcomes.assert_called_once()
        mock_digest.assert_called_once()


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
        result = d._handle_control_command("U12345", "resume")
        assert result is not None
        assert d._state.paused is False

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
        with patch.object(daemon_instance, "_post_slack_message") as mock_slack:
            daemon_instance._try_execute_next()
            # Should have posted 80% warning
            assert mock_slack.called
            args = mock_slack.call_args_list[0][0][0]
            assert "80%" in args or "warning" in args.lower()

        assert daemon_instance._budget_80_alerted is True

        # Second call should NOT fire again
        with patch.object(daemon_instance, "_post_slack_message") as mock_slack2:
            daemon_instance._try_execute_next()
            # Should not fire the 80% alert again (already alerted)
            for call in mock_slack2.call_args_list:
                assert "80%" not in call[0][0] or "warning" not in call[0][0].lower()

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
        with patch.object(daemon_instance, "_execute_item", side_effect=RuntimeError("boom")), \
             patch("colonyos.slack.post_message", return_value={"ts": "1234.5"}) as mock_post:
            daemon_instance._try_execute_next()

        item = daemon_instance._queue_state.items[0]
        assert item.status == QueueItemStatus.FAILED
        assert mock_post.called
        assert any(
            "execution failed" in str(call)
            for call in mock_post.call_args_list
        )

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
