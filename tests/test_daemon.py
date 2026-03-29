"""Tests for daemon orchestration."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colonyos.config import ColonyConfig, DaemonConfig
from colonyos.daemon import Daemon, DaemonError
from colonyos.daemon_state import DaemonState, save_daemon_state
from colonyos.models import QueueItem, QueueItemStatus, QueueState


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
        assert item.priority == 2  # Promoted from 3 to 2


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
        assert pid_path.exists()
        d._release_pid_lock()

    def test_second_instance_fails(self, tmp_repo: Path, config: ColonyConfig):
        d1 = Daemon(tmp_repo, config, dry_run=True)
        d1._acquire_pid_lock()
        try:
            d2 = Daemon(tmp_repo, config, dry_run=True)
            with pytest.raises(DaemonError, match="Another daemon instance"):
                d2._acquire_pid_lock()
        finally:
            d1._release_pid_lock()


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
