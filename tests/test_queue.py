"""Tests for the colonyos queue command and related data models."""
from __future__ import annotations

import json
import os
import signal
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from colonyos.cli import (
    app,
    _load_queue_state,
    _save_queue_state,
)
from colonyos.config import ColonyConfig, BudgetConfig, save_config
from colonyos.models import (
    Phase,
    PhaseResult,
    ProjectInfo,
    QueueItem,
    QueueItemStatus,
    QueueState,
    QueueStatus,
    RunLog,
    RunStatus,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def configured_repo(tmp_path: Path):
    """Create a minimal configured ColonyOS repo."""
    config = ColonyConfig(
        project=ProjectInfo(name="test", description="test", stack="python"),
        model="sonnet",
        budget=BudgetConfig(per_phase=5.0, per_run=15.0, max_duration_hours=8.0, max_total_usd=500.0),
    )
    save_config(tmp_path, config)
    return tmp_path


def _make_queue_item(
    source_type: str = "prompt",
    source_value: str = "Add feature X",
    status: QueueItemStatus = QueueItemStatus.PENDING,
    **kwargs,
) -> QueueItem:
    return QueueItem(
        id=kwargs.get("id", str(uuid.uuid4())),
        source_type=source_type,
        source_value=source_value,
        status=status,
        added_at=kwargs.get("added_at", datetime.now(timezone.utc).isoformat()),
        run_id=kwargs.get("run_id"),
        cost_usd=kwargs.get("cost_usd", 0.0),
        duration_ms=kwargs.get("duration_ms", 0),
        pr_url=kwargs.get("pr_url"),
        error=kwargs.get("error"),
        issue_title=kwargs.get("issue_title"),
    )


def _make_successful_runlog(run_id: str = "run-001", cost: float = 1.50) -> RunLog:
    log = RunLog(
        run_id=run_id,
        prompt="test prompt",
        status=RunStatus.COMPLETED,
        phases=[
            PhaseResult(phase=Phase.PLAN, success=True, cost_usd=0.50, duration_ms=10000),
            PhaseResult(phase=Phase.IMPLEMENT, success=True, cost_usd=0.50, duration_ms=20000),
            PhaseResult(
                phase=Phase.DELIVER,
                success=True,
                cost_usd=0.50,
                duration_ms=5000,
                artifacts={"pr_url": "https://github.com/test/repo/pull/42"},
            ),
        ],
        total_cost_usd=cost,
        branch_name="colonyos/test-feature",
    )
    log.mark_finished()
    return log


def _make_failed_runlog(run_id: str = "run-002", cost: float = 0.50) -> RunLog:
    log = RunLog(
        run_id=run_id,
        prompt="test prompt",
        status=RunStatus.FAILED,
        phases=[
            PhaseResult(phase=Phase.PLAN, success=True, cost_usd=0.50, duration_ms=10000),
        ],
        total_cost_usd=cost,
    )
    log.mark_finished()
    return log


def _make_rejected_runlog(run_id: str = "run-003", cost: float = 1.00) -> RunLog:
    """A run that completed but got a NO-GO verdict (status=FAILED in orchestrator)."""
    log = RunLog(
        run_id=run_id,
        prompt="test prompt",
        status=RunStatus.FAILED,
        phases=[
            PhaseResult(phase=Phase.PLAN, success=True, cost_usd=0.30, duration_ms=10000),
            PhaseResult(phase=Phase.IMPLEMENT, success=True, cost_usd=0.30, duration_ms=20000),
            PhaseResult(
                phase=Phase.DECISION,
                success=True,
                cost_usd=0.40,
                duration_ms=5000,
                artifacts={"result": "VERDICT: NO-GO\nThis feature is not ready."},
            ),
        ],
        total_cost_usd=cost,
    )
    log.mark_finished()
    return log


# ===========================================================================
# Task 1: Data model tests
# ===========================================================================


class TestQueueItemStatus:
    def test_enum_values(self):
        assert QueueItemStatus.PENDING.value == "pending"
        assert QueueItemStatus.RUNNING.value == "running"
        assert QueueItemStatus.COMPLETED.value == "completed"
        assert QueueItemStatus.FAILED.value == "failed"
        assert QueueItemStatus.REJECTED.value == "rejected"

    def test_from_string(self):
        assert QueueItemStatus("pending") == QueueItemStatus.PENDING
        assert QueueItemStatus("completed") == QueueItemStatus.COMPLETED


class TestQueueItem:
    def test_to_dict_roundtrip(self):
        item = _make_queue_item(
            id="item-1",
            source_type="prompt",
            source_value="Add a login page",
            cost_usd=1.50,
            duration_ms=30000,
            pr_url="https://github.com/test/repo/pull/1",
            run_id="run-abc",
        )
        d = item.to_dict()
        restored = QueueItem.from_dict(d)
        assert restored.id == item.id
        assert restored.source_type == item.source_type
        assert restored.source_value == item.source_value
        assert restored.status == item.status
        assert restored.cost_usd == item.cost_usd
        assert restored.duration_ms == item.duration_ms
        assert restored.pr_url == item.pr_url
        assert restored.run_id == item.run_id

    def test_from_dict_defaults(self):
        item = QueueItem.from_dict({"id": "x"})
        assert item.source_type == "prompt"
        assert item.source_value == ""
        assert item.status == QueueItemStatus.PENDING
        assert item.cost_usd == 0.0

    def test_from_dict_unknown_status(self):
        item = QueueItem.from_dict({"id": "x", "status": "bogus"})
        assert item.status == QueueItemStatus.PENDING

    def test_issue_item_roundtrip(self):
        item = _make_queue_item(
            source_type="issue",
            source_value="42",
            issue_title="Fix login bug",
        )
        d = item.to_dict()
        restored = QueueItem.from_dict(d)
        assert restored.source_type == "issue"
        assert restored.source_value == "42"
        assert restored.issue_title == "Fix login bug"


class TestQueueState:
    def test_to_dict_roundtrip(self):
        state = QueueState(
            queue_id="q-1",
            items=[
                _make_queue_item(id="i1"),
                _make_queue_item(id="i2", status=QueueItemStatus.COMPLETED),
            ],
            aggregate_cost_usd=3.50,
            start_time_iso="2026-03-18T12:00:00+00:00",
            status=QueueStatus.RUNNING,
        )
        d = state.to_dict()
        restored = QueueState.from_dict(d)
        assert restored.queue_id == "q-1"
        assert len(restored.items) == 2
        assert restored.items[0].id == "i1"
        assert restored.items[1].status == QueueItemStatus.COMPLETED
        assert restored.aggregate_cost_usd == 3.50
        assert restored.status == QueueStatus.RUNNING

    def test_from_dict_defaults(self):
        state = QueueState.from_dict({"queue_id": "q-x"})
        assert state.items == []
        assert state.aggregate_cost_usd == 0.0
        assert state.start_time_iso is None
        assert state.status == QueueStatus.PENDING

    def test_from_dict_unknown_status(self):
        state = QueueState.from_dict({"queue_id": "q-x", "status": "bogus"})
        assert state.status == QueueStatus.PENDING


# ===========================================================================
# Task 2: Persistence tests
# ===========================================================================


class TestQueuePersistence:
    def test_save_and_load_roundtrip(self, tmp_path: Path):
        state = QueueState(
            queue_id="q-test",
            items=[_make_queue_item(id="i1")],
        )
        _save_queue_state(tmp_path, state)
        loaded = _load_queue_state(tmp_path)
        assert loaded is not None
        assert loaded.queue_id == "q-test"
        assert len(loaded.items) == 1

    def test_load_no_file(self, tmp_path: Path):
        loaded = _load_queue_state(tmp_path)
        assert loaded is None

    def test_save_creates_directory(self, tmp_path: Path):
        state = QueueState(queue_id="q-dir-test", items=[])
        _save_queue_state(tmp_path, state)
        assert (tmp_path / ".colonyos" / "queue.json").exists()

    def test_atomic_write(self, tmp_path: Path):
        """Saving overwrites without leaving temp files."""
        state1 = QueueState(queue_id="q-1", items=[_make_queue_item(id="i1")])
        _save_queue_state(tmp_path, state1)

        state2 = QueueState(queue_id="q-1", items=[_make_queue_item(id="i2")])
        _save_queue_state(tmp_path, state2)

        loaded = _load_queue_state(tmp_path)
        assert loaded is not None
        assert loaded.items[0].id == "i2"

        # No .tmp files left behind
        colonyos_dir = tmp_path / ".colonyos"
        tmp_files = list(colonyos_dir.glob("*.tmp"))
        assert len(tmp_files) == 0


# ===========================================================================
# Task 3: Queue add command tests
# ===========================================================================


class TestQueueAdd:
    def test_add_prompts(self, runner: CliRunner, configured_repo: Path):
        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            result = runner.invoke(app, ["queue", "add", "Add feature X", "Fix bug Y"])
        assert result.exit_code == 0
        assert "2" in result.output  # 2 items added

        state = _load_queue_state(configured_repo)
        assert state is not None
        assert len(state.items) == 2
        assert state.items[0].source_type == "prompt"
        assert state.items[0].source_value == "Add feature X"
        assert state.items[1].source_value == "Fix bug Y"

    def test_add_issue(self, runner: CliRunner, configured_repo: Path):
        mock_issue = MagicMock()
        mock_issue.number = 42
        mock_issue.title = "Fix login bug"
        mock_issue.url = "https://github.com/test/repo/issues/42"

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.github.fetch_issue", return_value=mock_issue),
        ):
            result = runner.invoke(app, ["queue", "add", "--issue", "42"])
        assert result.exit_code == 0

        state = _load_queue_state(configured_repo)
        assert state is not None
        assert len(state.items) == 1
        assert state.items[0].source_type == "issue"
        assert state.items[0].source_value == "42"
        assert state.items[0].issue_title == "Fix login bug"

    def test_add_mixed(self, runner: CliRunner, configured_repo: Path):
        mock_issue = MagicMock()
        mock_issue.number = 57
        mock_issue.title = "Add OAuth"
        mock_issue.url = "https://github.com/test/repo/issues/57"

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.github.fetch_issue", return_value=mock_issue),
        ):
            result = runner.invoke(app, ["queue", "add", "Add feature X", "--issue", "57"])
        assert result.exit_code == 0

        state = _load_queue_state(configured_repo)
        assert state is not None
        assert len(state.items) == 2
        # One prompt, one issue
        types = {item.source_type for item in state.items}
        assert types == {"prompt", "issue"}

    def test_add_appends_to_existing(self, runner: CliRunner, configured_repo: Path):
        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            runner.invoke(app, ["queue", "add", "Feature A"])
            result = runner.invoke(app, ["queue", "add", "Feature B"])
        assert result.exit_code == 0

        state = _load_queue_state(configured_repo)
        assert state is not None
        assert len(state.items) == 2

    def test_add_no_input(self, runner: CliRunner, configured_repo: Path):
        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            result = runner.invoke(app, ["queue", "add"])
        assert result.exit_code != 0

    def test_add_invalid_issue(self, runner: CliRunner, configured_repo: Path):
        import click

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.github.fetch_issue", side_effect=click.ClickException("Issue not found")),
        ):
            result = runner.invoke(app, ["queue", "add", "--issue", "99999"])
        assert result.exit_code != 0


# ===========================================================================
# Task 5: Queue status command tests
# ===========================================================================


class TestQueueStatus:
    def test_empty_queue(self, runner: CliRunner, configured_repo: Path):
        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            result = runner.invoke(app, ["queue", "status"])
        assert result.exit_code == 0
        assert "No queue" in result.output or "empty" in result.output.lower()

    def test_mixed_statuses(self, runner: CliRunner, configured_repo: Path):
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", source_value="Feature A", status=QueueItemStatus.COMPLETED, cost_usd=1.0, duration_ms=30000, pr_url="https://github.com/test/repo/pull/1"),
                _make_queue_item(id="i2", source_value="Feature B", status=QueueItemStatus.FAILED, error="Crash"),
                _make_queue_item(id="i3", source_value="Feature C", status=QueueItemStatus.PENDING),
                _make_queue_item(id="i4", source_type="issue", source_value="42", status=QueueItemStatus.REJECTED, issue_title="Fix login"),
            ],
            aggregate_cost_usd=2.50,
        )
        _save_queue_state(configured_repo, state)

        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            result = runner.invoke(app, ["queue", "status"])
        assert result.exit_code == 0
        # Should display item info
        assert "Feature A" in result.output or "Feature" in result.output

    def test_prompt_truncation(self, runner: CliRunner, configured_repo: Path):
        long_prompt = "A" * 200
        state = QueueState(
            queue_id="q-test",
            items=[_make_queue_item(id="i1", source_value=long_prompt)],
        )
        _save_queue_state(configured_repo, state)

        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            result = runner.invoke(app, ["queue", "status"])
        assert result.exit_code == 0
        # Full 200 chars should not appear; it should be truncated
        assert long_prompt not in result.output

    def test_issue_title_display(self, runner: CliRunner, configured_repo: Path):
        state = QueueState(
            queue_id="q-test",
            items=[_make_queue_item(id="i1", source_type="issue", source_value="42", issue_title="Fix login bug")],
        )
        _save_queue_state(configured_repo, state)

        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            result = runner.invoke(app, ["queue", "status"])
        assert result.exit_code == 0
        assert "#42" in result.output or "Fix login bug" in result.output


# ===========================================================================
# Task 6: Queue clear command tests
# ===========================================================================


class TestQueueClear:
    def test_clear_pending(self, runner: CliRunner, configured_repo: Path):
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", status=QueueItemStatus.PENDING),
                _make_queue_item(id="i2", status=QueueItemStatus.COMPLETED),
                _make_queue_item(id="i3", status=QueueItemStatus.PENDING),
            ],
        )
        _save_queue_state(configured_repo, state)

        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            result = runner.invoke(app, ["queue", "clear"])
        assert result.exit_code == 0
        assert "2" in result.output  # 2 items cleared

        loaded = _load_queue_state(configured_repo)
        assert loaded is not None
        assert len(loaded.items) == 1
        assert loaded.items[0].id == "i2"

    def test_clear_preserves_non_pending(self, runner: CliRunner, configured_repo: Path):
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", status=QueueItemStatus.COMPLETED),
                _make_queue_item(id="i2", status=QueueItemStatus.FAILED),
                _make_queue_item(id="i3", status=QueueItemStatus.REJECTED),
                _make_queue_item(id="i4", status=QueueItemStatus.RUNNING),
            ],
        )
        _save_queue_state(configured_repo, state)

        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            result = runner.invoke(app, ["queue", "clear"])
        assert result.exit_code == 0

        loaded = _load_queue_state(configured_repo)
        assert loaded is not None
        assert len(loaded.items) == 4

    def test_clear_empty(self, runner: CliRunner, configured_repo: Path):
        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            result = runner.invoke(app, ["queue", "clear"])
        assert result.exit_code == 0


# ===========================================================================
# Task 4: Queue start command tests
# ===========================================================================


class TestQueueStart:
    def test_start_processes_pending(self, runner: CliRunner, configured_repo: Path):
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", source_value="Feature A"),
                _make_queue_item(id="i2", source_value="Feature B"),
            ],
        )
        _save_queue_state(configured_repo, state)

        mock_log = _make_successful_runlog()

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", return_value=mock_log),
        ):
            result = runner.invoke(app, ["queue", "start"])

        assert result.exit_code == 0
        loaded = _load_queue_state(configured_repo)
        assert loaded is not None
        assert all(item.status == QueueItemStatus.COMPLETED for item in loaded.items)

    def test_start_skips_completed(self, runner: CliRunner, configured_repo: Path):
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", source_value="Feature A", status=QueueItemStatus.COMPLETED),
                _make_queue_item(id="i2", source_value="Feature B"),
            ],
        )
        _save_queue_state(configured_repo, state)

        mock_log = _make_successful_runlog()
        call_count = 0

        def counting_orchestrator(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_log

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", side_effect=counting_orchestrator),
        ):
            result = runner.invoke(app, ["queue", "start"])

        assert result.exit_code == 0
        assert call_count == 1  # Only second item was processed

    def test_start_marks_failed(self, runner: CliRunner, configured_repo: Path):
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", source_value="Feature A"),
                _make_queue_item(id="i2", source_value="Feature B"),
            ],
        )
        _save_queue_state(configured_repo, state)

        call_count = 0

        def failing_then_passing(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Pipeline exploded")
            return _make_successful_runlog()

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", side_effect=failing_then_passing),
        ):
            result = runner.invoke(app, ["queue", "start"])

        assert result.exit_code == 0
        loaded = _load_queue_state(configured_repo)
        assert loaded is not None
        assert loaded.items[0].status == QueueItemStatus.FAILED
        assert loaded.items[1].status == QueueItemStatus.COMPLETED

    def test_start_marks_rejected(self, runner: CliRunner, configured_repo: Path):
        """A NO-GO verdict results in 'rejected' status, not 'failed'."""
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", source_value="Feature A"),
                _make_queue_item(id="i2", source_value="Feature B"),
            ],
        )
        _save_queue_state(configured_repo, state)

        call_count = 0

        def rejected_then_passing(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_rejected_runlog()
            return _make_successful_runlog()

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", side_effect=rejected_then_passing),
        ):
            result = runner.invoke(app, ["queue", "start"])

        assert result.exit_code == 0
        loaded = _load_queue_state(configured_repo)
        assert loaded is not None
        assert loaded.items[0].status == QueueItemStatus.REJECTED
        assert loaded.items[1].status == QueueItemStatus.COMPLETED

    def test_budget_cap(self, runner: CliRunner, configured_repo: Path):
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", source_value="Feature A"),
                _make_queue_item(id="i2", source_value="Feature B"),
                _make_queue_item(id="i3", source_value="Feature C"),
            ],
        )
        _save_queue_state(configured_repo, state)

        mock_log = _make_successful_runlog(cost=2.0)

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", return_value=mock_log),
        ):
            result = runner.invoke(app, ["queue", "start", "--max-cost", "3.0"])

        assert result.exit_code == 0
        loaded = _load_queue_state(configured_repo)
        assert loaded is not None
        # First 2 items should process (2.0 each) but after first, cost=2.0 < 3.0,
        # after second, cost=4.0 >= 3.0, so third stays pending
        completed_count = sum(1 for i in loaded.items if i.status == QueueItemStatus.COMPLETED)
        pending_count = sum(1 for i in loaded.items if i.status == QueueItemStatus.PENDING)
        assert completed_count == 2
        assert pending_count == 1
        assert "Budget" in result.output or "budget" in result.output or "cost" in result.output

    def test_time_cap(self, runner: CliRunner, configured_repo: Path):
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", source_value="Feature A"),
                _make_queue_item(id="i2", source_value="Feature B"),
            ],
        )
        _save_queue_state(configured_repo, state)

        mock_log = _make_successful_runlog()

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", return_value=mock_log),
            patch("colonyos.cli._compute_queue_elapsed_hours", return_value=5.0),
        ):
            result = runner.invoke(app, ["queue", "start", "--max-hours", "1.0"])

        assert result.exit_code == 0
        loaded = _load_queue_state(configured_repo)
        assert loaded is not None
        # Time cap should prevent any items from being processed
        pending_count = sum(1 for i in loaded.items if i.status == QueueItemStatus.PENDING)
        assert pending_count == 2

    def test_issue_refetch_at_execution(self, runner: CliRunner, configured_repo: Path):
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", source_type="issue", source_value="42", issue_title="Fix bug"),
            ],
        )
        _save_queue_state(configured_repo, state)

        mock_issue = MagicMock()
        mock_issue.number = 42
        mock_issue.title = "Fix bug (updated)"
        mock_issue.url = "https://github.com/test/repo/issues/42"

        mock_log = _make_successful_runlog()

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", return_value=mock_log) as mock_orch,
            patch("colonyos.github.fetch_issue", return_value=mock_issue),
            patch("colonyos.github.format_issue_as_prompt", return_value="Issue #42: Fix bug (updated)"),
        ):
            result = runner.invoke(app, ["queue", "start"])

        assert result.exit_code == 0
        # Verify orchestrator was called with the formatted issue prompt
        mock_orch.assert_called_once()
        call_args = mock_orch.call_args
        assert "Issue #42" in call_args[0][0]

    def test_no_queue_exists(self, runner: CliRunner, configured_repo: Path):
        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            result = runner.invoke(app, ["queue", "start"])
        assert result.exit_code != 0

    def test_resume_skips_non_pending(self, runner: CliRunner, configured_repo: Path):
        """When resuming, completed/failed/rejected items are skipped."""
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", source_value="Feature A", status=QueueItemStatus.COMPLETED),
                _make_queue_item(id="i2", source_value="Feature B", status=QueueItemStatus.FAILED),
                _make_queue_item(id="i3", source_value="Feature C", status=QueueItemStatus.REJECTED),
                _make_queue_item(id="i4", source_value="Feature D", status=QueueItemStatus.PENDING),
            ],
        )
        _save_queue_state(configured_repo, state)

        mock_log = _make_successful_runlog()
        call_count = 0

        def counting_orchestrator(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_log

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", side_effect=counting_orchestrator),
        ):
            result = runner.invoke(app, ["queue", "start"])

        assert result.exit_code == 0
        assert call_count == 1  # Only the pending item


# ===========================================================================
# Fix iteration 1: Crash recovery and signal handling tests
# ===========================================================================


class TestQueueCrashRecovery:
    def test_running_items_reset_to_pending_on_start(self, runner: CliRunner, configured_repo: Path):
        """Items stuck in RUNNING from a prior crash are reset to PENDING on queue start."""
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", source_value="Feature A", status=QueueItemStatus.RUNNING),
                _make_queue_item(id="i2", source_value="Feature B", status=QueueItemStatus.PENDING),
            ],
        )
        _save_queue_state(configured_repo, state)

        mock_log = _make_successful_runlog()

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", return_value=mock_log),
        ):
            result = runner.invoke(app, ["queue", "start"])

        assert result.exit_code == 0
        assert "Recovered 1 interrupted item(s)" in result.output
        loaded = _load_queue_state(configured_repo)
        assert loaded is not None
        # Both items should now be completed (the RUNNING one was reset to PENDING first)
        assert all(item.status == QueueItemStatus.COMPLETED for item in loaded.items)

    def test_multiple_running_items_recovered(self, runner: CliRunner, configured_repo: Path):
        """Multiple stuck RUNNING items are all recovered."""
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", source_value="Feature A", status=QueueItemStatus.RUNNING),
                _make_queue_item(id="i2", source_value="Feature B", status=QueueItemStatus.RUNNING),
                _make_queue_item(id="i3", source_value="Feature C", status=QueueItemStatus.COMPLETED),
            ],
        )
        _save_queue_state(configured_repo, state)

        mock_log = _make_successful_runlog()

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", return_value=mock_log),
        ):
            result = runner.invoke(app, ["queue", "start"])

        assert result.exit_code == 0
        assert "Recovered 2 interrupted item(s)" in result.output
        loaded = _load_queue_state(configured_repo)
        assert loaded is not None
        assert loaded.items[0].status == QueueItemStatus.COMPLETED
        assert loaded.items[1].status == QueueItemStatus.COMPLETED
        assert loaded.items[2].status == QueueItemStatus.COMPLETED

    def test_keyboard_interrupt_reverts_running_item(self, runner: CliRunner, configured_repo: Path):
        """Ctrl+C during processing reverts the current item to PENDING."""
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", source_value="Feature A"),
                _make_queue_item(id="i2", source_value="Feature B"),
            ],
        )
        _save_queue_state(configured_repo, state)

        def interrupt_on_call(*args, **kwargs):
            raise KeyboardInterrupt()

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", side_effect=interrupt_on_call),
        ):
            result = runner.invoke(app, ["queue", "start"])

        loaded = _load_queue_state(configured_repo)
        assert loaded is not None
        # The interrupted item should be reverted to PENDING
        assert loaded.items[0].status == QueueItemStatus.PENDING
        assert loaded.items[1].status == QueueItemStatus.PENDING
        assert loaded.status == QueueStatus.INTERRUPTED

    def test_error_message_truncated(self, runner: CliRunner, configured_repo: Path):
        """Exception messages stored in queue state are truncated to 500 chars."""
        state = QueueState(
            queue_id="q-test",
            items=[_make_queue_item(id="i1", source_value="Feature A")],
        )
        _save_queue_state(configured_repo, state)

        long_error = "x" * 1000

        def raise_long_error(*args, **kwargs):
            raise RuntimeError(long_error)

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", side_effect=raise_long_error),
        ):
            result = runner.invoke(app, ["queue", "start"])

        assert result.exit_code == 0
        loaded = _load_queue_state(configured_repo)
        assert loaded is not None
        assert loaded.items[0].status == QueueItemStatus.FAILED
        assert len(loaded.items[0].error) == 500


class TestNogoVerdictDetection:
    """Tests for the improved NO-GO verdict regex detection."""

    def test_standard_nogo_format(self):
        """Standard VERDICT: NO-GO is detected."""
        from colonyos.cli import _is_nogo_verdict

        log = _make_rejected_runlog()
        assert _is_nogo_verdict(log) is True

    def test_nogo_with_extra_whitespace(self):
        """VERDICT:  NO-GO (extra space) is detected."""
        from colonyos.cli import _is_nogo_verdict

        log = RunLog(
            run_id="run-test",
            prompt="test",
            status=RunStatus.FAILED,
            phases=[
                PhaseResult(
                    phase=Phase.DECISION,
                    success=True,
                    cost_usd=0.1,
                    artifacts={"result": "VERDICT:  NO-GO\nReason here."},
                ),
            ],
        )
        assert _is_nogo_verdict(log) is True

    def test_go_verdict_not_matched(self):
        """VERDICT: GO should NOT trigger NO-GO detection."""
        from colonyos.cli import _is_nogo_verdict

        log = RunLog(
            run_id="run-test",
            prompt="test",
            status=RunStatus.FAILED,
            phases=[
                PhaseResult(
                    phase=Phase.DECISION,
                    success=True,
                    cost_usd=0.1,
                    artifacts={"result": "VERDICT: GO\nAll good."},
                ),
            ],
        )
        assert _is_nogo_verdict(log) is False

    def test_no_decision_phase(self):
        """Log without a decision phase returns False."""
        from colonyos.cli import _is_nogo_verdict

        log = _make_failed_runlog()
        assert _is_nogo_verdict(log) is False


# ===========================================================================
# Task 7: Summary and status integration tests
# ===========================================================================


class TestQueueSummary:
    def test_summary_printed_after_start(self, runner: CliRunner, configured_repo: Path):
        state = QueueState(
            queue_id="q-test",
            items=[_make_queue_item(id="i1", source_value="Feature A")],
        )
        _save_queue_state(configured_repo, state)

        mock_log = _make_successful_runlog()

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", return_value=mock_log),
        ):
            result = runner.invoke(app, ["queue", "start"])

        assert result.exit_code == 0
        # Summary should contain cost info
        assert "$" in result.output or "cost" in result.output.lower()

    def test_status_command_shows_queue_summary(self, runner: CliRunner, configured_repo: Path):
        """The existing `status` command should show a queue summary line."""
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", status=QueueItemStatus.COMPLETED, cost_usd=1.0),
                _make_queue_item(id="i2", status=QueueItemStatus.PENDING),
            ],
            aggregate_cost_usd=1.0,
        )
        _save_queue_state(configured_repo, state)

        # Create runs dir so status command doesn't bail early
        runs_dir = configured_repo / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)

        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "Queue" in result.output or "queue" in result.output


# ===========================================================================
# Task 8: End-to-end integration tests
# ===========================================================================


class TestQueueE2E:
    def test_add_start_full_lifecycle(self, runner: CliRunner, configured_repo: Path):
        """Add items → start → verify final state and summary."""
        mock_log = _make_successful_runlog()

        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            runner.invoke(app, ["queue", "add", "Feature A", "Feature B"])

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", return_value=mock_log),
        ):
            result = runner.invoke(app, ["queue", "start"])

        assert result.exit_code == 0
        loaded = _load_queue_state(configured_repo)
        assert loaded is not None
        assert all(item.status == QueueItemStatus.COMPLETED for item in loaded.items)
        assert loaded.status == QueueStatus.COMPLETED

    def test_interrupted_queue_resumes(self, runner: CliRunner, configured_repo: Path):
        """Pre-completed items are skipped on resume."""
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", source_value="Feature A", status=QueueItemStatus.COMPLETED, cost_usd=1.0),
                _make_queue_item(id="i2", source_value="Feature B"),
                _make_queue_item(id="i3", source_value="Feature C"),
            ],
            aggregate_cost_usd=1.0,
            status=QueueStatus.INTERRUPTED,
        )
        _save_queue_state(configured_repo, state)

        mock_log = _make_successful_runlog()
        call_count = 0

        def counting_orchestrator(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_log

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", side_effect=counting_orchestrator),
        ):
            result = runner.invoke(app, ["queue", "start"])

        assert result.exit_code == 0
        assert call_count == 2  # Only items 2 and 3

    def test_failed_item_doesnt_block(self, runner: CliRunner, configured_repo: Path):
        """A failed item doesn't block subsequent items."""
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", source_value="Feature A"),
                _make_queue_item(id="i2", source_value="Feature B"),
                _make_queue_item(id="i3", source_value="Feature C"),
            ],
        )
        _save_queue_state(configured_repo, state)

        call_count = 0

        def fail_second(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Boom")
            return _make_successful_runlog()

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", side_effect=fail_second),
        ):
            result = runner.invoke(app, ["queue", "start"])

        assert result.exit_code == 0
        loaded = _load_queue_state(configured_repo)
        assert loaded is not None
        assert loaded.items[0].status == QueueItemStatus.COMPLETED
        assert loaded.items[1].status == QueueItemStatus.FAILED
        assert loaded.items[2].status == QueueItemStatus.COMPLETED
        assert call_count == 3

    def test_rejected_nogo_marked_correctly(self, runner: CliRunner, configured_repo: Path):
        """NO-GO verdict → rejected status, queue continues."""
        state = QueueState(
            queue_id="q-test",
            items=[
                _make_queue_item(id="i1", source_value="Feature A"),
                _make_queue_item(id="i2", source_value="Feature B"),
            ],
        )
        _save_queue_state(configured_repo, state)

        call_count = 0

        def rejected_then_ok(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_rejected_runlog()
            return _make_successful_runlog()

        with (
            patch("colonyos.cli._find_repo_root", return_value=configured_repo),
            patch("colonyos.cli.run_orchestrator", side_effect=rejected_then_ok),
        ):
            result = runner.invoke(app, ["queue", "start"])

        assert result.exit_code == 0
        loaded = _load_queue_state(configured_repo)
        assert loaded is not None
        assert loaded.items[0].status == QueueItemStatus.REJECTED
        assert loaded.items[1].status == QueueItemStatus.COMPLETED


# ===========================================================================
# Queue unpause command tests
# ===========================================================================


class TestQueueUnpause:
    def test_unpause_resets_circuit_breaker(self, runner: CliRunner, configured_repo: Path):
        """unpause command resets queue_paused and consecutive_failures."""
        from colonyos.slack import SlackWatchState, save_watch_state

        state = SlackWatchState(
            watch_id="test-watch",
            queue_paused=True,
            queue_paused_at="2026-03-19T10:00:00+00:00",
            consecutive_failures=5,
        )
        save_watch_state(configured_repo, state)

        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            result = runner.invoke(app, ["queue", "unpause"])
        assert result.exit_code == 0
        assert "unpaused" in result.output.lower()

        from colonyos.slack import load_watch_state
        loaded = load_watch_state(configured_repo, "test-watch")
        assert loaded is not None
        assert loaded.queue_paused is False
        assert loaded.queue_paused_at is None
        assert loaded.consecutive_failures == 0

    def test_unpause_when_not_paused(self, runner: CliRunner, configured_repo: Path):
        """unpause with no paused queue shows appropriate message."""
        from colonyos.slack import SlackWatchState, save_watch_state

        state = SlackWatchState(
            watch_id="test-watch",
            queue_paused=False,
            consecutive_failures=0,
        )
        save_watch_state(configured_repo, state)

        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            result = runner.invoke(app, ["queue", "unpause"])
        assert result.exit_code == 0
        assert "not currently paused" in result.output.lower()

    def test_unpause_no_watch_state(self, runner: CliRunner, configured_repo: Path):
        """unpause with no watch state shows appropriate message."""
        with patch("colonyos.cli._find_repo_root", return_value=configured_repo):
            result = runner.invoke(app, ["queue", "unpause"])
        assert result.exit_code == 0
        assert "no watch state" in result.output.lower()
