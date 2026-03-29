"""Task 4.1: Tests for LoopState dataclass."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colonyos.models import (
    LoopState,
    LoopStatus,
    Phase,
    PhaseResult,
    QueueItem,
    QueueItemStatus,
    RetryInfo,
    RunLog,
    RunStatus,
)


class TestPhaseResultModel:
    def test_default_model_is_none(self):
        result = PhaseResult(phase=Phase.IMPLEMENT, success=True)
        assert result.model is None

    def test_accepts_model_kwarg(self):
        result = PhaseResult(phase=Phase.IMPLEMENT, success=True, model="opus")
        assert result.model == "opus"

    def test_backward_compat_old_serialized_data(self):
        """Old PhaseResult dicts without 'model' should load gracefully."""
        old_data = {
            "phase": "implement",
            "success": True,
            "cost_usd": 1.5,
            "duration_ms": 60000,
            "session_id": "sess-123",
            "error": None,
            "artifacts": {},
        }
        result = PhaseResult(
            phase=Phase(old_data["phase"]),
            success=old_data["success"],
            cost_usd=old_data.get("cost_usd"),
            duration_ms=old_data.get("duration_ms", 0),
            session_id=old_data.get("session_id", ""),
            model=old_data.get("model"),
            error=old_data.get("error"),
        )
        assert result.model is None
        assert result.success is True


class TestLoopState:
    def test_default_fields(self):
        state = LoopState(
            loop_id="loop-123",
            total_iterations=10,
        )
        assert state.loop_id == "loop-123"
        assert state.current_iteration == 0
        assert state.total_iterations == 10
        assert state.aggregate_cost_usd == 0.0
        assert state.completed_run_ids == []
        assert state.failed_run_ids == []
        assert state.status == LoopStatus.RUNNING

    def test_to_dict(self):
        state = LoopState(
            loop_id="loop-123",
            total_iterations=5,
            current_iteration=2,
            aggregate_cost_usd=1.50,
            completed_run_ids=["r1", "r2"],
            failed_run_ids=["r3"],
            status=LoopStatus.RUNNING,
        )
        d = state.to_dict()
        assert d["loop_id"] == "loop-123"
        assert d["current_iteration"] == 2
        assert d["total_iterations"] == 5
        assert d["aggregate_cost_usd"] == 1.50
        assert d["completed_run_ids"] == ["r1", "r2"]
        assert d["failed_run_ids"] == ["r3"]
        assert d["status"] == "running"
        assert "start_time_iso" in d

    def test_from_dict(self):
        d = {
            "loop_id": "loop-abc",
            "current_iteration": 3,
            "total_iterations": 10,
            "aggregate_cost_usd": 2.0,
            "start_time_iso": "2026-01-01T00:00:00",
            "completed_run_ids": ["r1", "r2", "r3"],
            "failed_run_ids": [],
            "status": "running",
        }
        state = LoopState.from_dict(d)
        assert state.loop_id == "loop-abc"
        assert state.current_iteration == 3
        assert state.aggregate_cost_usd == 2.0

    def test_roundtrip_dict(self):
        state = LoopState(
            loop_id="loop-rt",
            total_iterations=5,
            current_iteration=3,
            aggregate_cost_usd=10.0,
            completed_run_ids=["r1"],
            failed_run_ids=["r2"],
            status=LoopStatus.INTERRUPTED,
        )
        d = state.to_dict()
        restored = LoopState.from_dict(d)
        assert restored.loop_id == state.loop_id
        assert restored.current_iteration == state.current_iteration
        assert restored.aggregate_cost_usd == state.aggregate_cost_usd
        assert restored.completed_run_ids == state.completed_run_ids
        assert restored.status == state.status

    def test_update_iteration(self):
        state = LoopState(loop_id="loop-1", total_iterations=5)
        state.current_iteration = 3
        state.aggregate_cost_usd = 5.0
        state.completed_run_ids.append("run-1")
        assert state.current_iteration == 3
        assert len(state.completed_run_ids) == 1


class TestLoopStatePersistence:
    def test_save_and_load(self, tmp_path: Path):
        state = LoopState(
            loop_id="loop-persist",
            total_iterations=10,
            current_iteration=3,
            aggregate_cost_usd=5.0,
            completed_run_ids=["r1", "r2", "r3"],
        )
        save_path = tmp_path / f"loop_state_{state.loop_id}.json"
        save_path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")

        data = json.loads(save_path.read_text(encoding="utf-8"))
        loaded = LoopState.from_dict(data)
        assert loaded.loop_id == "loop-persist"
        assert loaded.current_iteration == 3

    def test_load_file_not_found(self, tmp_path: Path):
        path = tmp_path / "loop_state_nonexistent.json"
        assert not path.exists()
        # from_dict should handle this gracefully at the caller level


class TestRunLogSourceIssue:
    def test_default_none(self) -> None:
        log = RunLog(run_id="r-1", prompt="test", status=RunStatus.RUNNING)
        assert log.source_issue is None
        assert log.source_issue_url is None

    def test_with_source_issue(self) -> None:
        log = RunLog(
            run_id="r-1",
            prompt="test",
            status=RunStatus.RUNNING,
            source_issue=42,
            source_issue_url="https://github.com/org/repo/issues/42",
        )
        assert log.source_issue == 42
        assert log.source_issue_url == "https://github.com/org/repo/issues/42"

    def test_mark_finished_preserves_fields(self) -> None:
        log = RunLog(
            run_id="r-1",
            prompt="test",
            status=RunStatus.RUNNING,
            source_issue=7,
            source_issue_url="https://github.com/org/repo/issues/7",
        )
        log.mark_finished()
        assert log.source_issue == 7
        assert log.source_issue_url == "https://github.com/org/repo/issues/7"


class TestPhaseCIFix:
    def test_ci_fix_enum_value(self) -> None:
        assert Phase.CI_FIX.value == "ci_fix"

    def test_ci_fix_serialization_roundtrip(self) -> None:
        """Phase('ci_fix') should reconstruct CI_FIX."""
        assert Phase("ci_fix") == Phase.CI_FIX

    def test_ci_fix_phase_result(self) -> None:
        result = PhaseResult(phase=Phase.CI_FIX, success=True, cost_usd=0.5)
        assert result.phase == Phase.CI_FIX
        assert result.success is True

    def test_backward_compat_runlog_without_ci_fix(self) -> None:
        """Existing RunLog JSON without CI_FIX phases loads fine."""
        log = RunLog(
            run_id="r-old",
            prompt="old run",
            status=RunStatus.COMPLETED,
            phases=[
                PhaseResult(phase=Phase.IMPLEMENT, success=True),
                PhaseResult(phase=Phase.DELIVER, success=True),
            ],
        )
        assert all(p.phase != Phase.CI_FIX for p in log.phases)


class TestQueueItemSlackFields:
    """Tests for new QueueItem fields: base_branch, slack_ts, slack_channel, source_type='slack'."""

    def test_new_fields_default_none(self) -> None:
        item = QueueItem(
            id="q-1",
            source_type="prompt",
            source_value="fix the bug",
            status=QueueItemStatus.PENDING,
        )
        assert item.base_branch is None
        assert item.slack_ts is None
        assert item.slack_channel is None

    def test_slack_source_type(self) -> None:
        item = QueueItem(
            id="q-2",
            source_type="slack",
            source_value="fix CSV export",
            status=QueueItemStatus.PENDING,
            slack_ts="1234567890.123456",
            slack_channel="C12345",
            base_branch="colonyos/feature-x",
        )
        assert item.source_type == "slack"
        assert item.slack_ts == "1234567890.123456"
        assert item.slack_channel == "C12345"
        assert item.base_branch == "colonyos/feature-x"

    def test_to_dict_includes_new_fields(self) -> None:
        item = QueueItem(
            id="q-3",
            source_type="slack",
            source_value="fix bug",
            status=QueueItemStatus.PENDING,
            slack_ts="123.456",
            slack_channel="C999",
            base_branch="colonyos/auth",
        )
        d = item.to_dict()
        assert d["source_type"] == "slack"
        assert d["slack_ts"] == "123.456"
        assert d["slack_channel"] == "C999"
        assert d["base_branch"] == "colonyos/auth"

    def test_from_dict_with_new_fields(self) -> None:
        d = {
            "id": "q-4",
            "source_type": "slack",
            "source_value": "fix it",
            "status": "pending",
            "slack_ts": "111.222",
            "slack_channel": "C555",
            "base_branch": "colonyos/feat",
        }
        item = QueueItem.from_dict(d)
        assert item.source_type == "slack"
        assert item.slack_ts == "111.222"
        assert item.slack_channel == "C555"
        assert item.base_branch == "colonyos/feat"

    def test_from_dict_backward_compat(self) -> None:
        """Old QueueItem dicts without new fields should load with None defaults."""
        d = {
            "id": "q-old",
            "source_type": "prompt",
            "source_value": "old item",
            "status": "pending",
        }
        item = QueueItem.from_dict(d)
        assert item.base_branch is None
        assert item.slack_ts is None
        assert item.slack_channel is None

    def test_roundtrip(self) -> None:
        item = QueueItem(
            id="q-rt",
            source_type="slack",
            source_value="roundtrip test",
            status=QueueItemStatus.COMPLETED,
            slack_ts="999.888",
            slack_channel="C123",
            base_branch="colonyos/test",
            cost_usd=2.50,
            pr_url="https://github.com/org/repo/pull/42",
        )
        d = item.to_dict()
        restored = QueueItem.from_dict(d)
        assert restored.source_type == item.source_type
        assert restored.slack_ts == item.slack_ts
        assert restored.slack_channel == item.slack_channel
        assert restored.base_branch == item.base_branch
        assert restored.pr_url == item.pr_url


class TestQueueItemThreadFixFields:
    """Tests for thread-fix fields: branch_name, fix_rounds, parent_item_id."""

    def test_new_fields_default_values(self) -> None:
        item = QueueItem(
            id="q-tf-1",
            source_type="prompt",
            source_value="fix the bug",
            status=QueueItemStatus.PENDING,
        )
        assert item.branch_name is None
        assert item.fix_rounds == 0
        assert item.parent_item_id is None

    def test_slack_fix_source_type(self) -> None:
        item = QueueItem(
            id="q-tf-2",
            source_type="slack_fix",
            source_value="fix the test",
            status=QueueItemStatus.PENDING,
            branch_name="colonyos/feature-x",
            fix_rounds=1,
            parent_item_id="q-parent-1",
        )
        assert item.source_type == "slack_fix"
        assert item.branch_name == "colonyos/feature-x"
        assert item.fix_rounds == 1
        assert item.parent_item_id == "q-parent-1"

    def test_to_dict_includes_thread_fix_fields(self) -> None:
        item = QueueItem(
            id="q-tf-3",
            source_type="slack_fix",
            source_value="fix it",
            status=QueueItemStatus.PENDING,
            branch_name="colonyos/auth",
            fix_rounds=2,
            parent_item_id="q-orig",
        )
        d = item.to_dict()
        assert d["branch_name"] == "colonyos/auth"
        assert d["fix_rounds"] == 2
        assert d["parent_item_id"] == "q-orig"
        assert d["source_type"] == "slack_fix"

    def test_from_dict_with_thread_fix_fields(self) -> None:
        d = {
            "id": "q-tf-4",
            "source_type": "slack_fix",
            "source_value": "fix it",
            "status": "pending",
            "branch_name": "colonyos/feat",
            "fix_rounds": 3,
            "parent_item_id": "q-parent-2",
        }
        item = QueueItem.from_dict(d)
        assert item.branch_name == "colonyos/feat"
        assert item.fix_rounds == 3
        assert item.parent_item_id == "q-parent-2"

    def test_from_dict_backward_compat_missing_thread_fix_fields(self) -> None:
        """Old QueueItem dicts without thread-fix fields load with defaults."""
        d = {
            "id": "q-old-tf",
            "source_type": "slack",
            "source_value": "old item",
            "status": "completed",
        }
        item = QueueItem.from_dict(d)
        assert item.branch_name is None
        assert item.fix_rounds == 0
        assert item.parent_item_id is None

    def test_roundtrip_thread_fix(self) -> None:
        item = QueueItem(
            id="q-tf-rt",
            source_type="slack_fix",
            source_value="fix roundtrip",
            status=QueueItemStatus.COMPLETED,
            slack_ts="999.888",
            slack_channel="C123",
            branch_name="colonyos/test-fix",
            fix_rounds=2,
            parent_item_id="q-parent-rt",
            cost_usd=1.50,
            pr_url="https://github.com/org/repo/pull/42",
        )
        d = item.to_dict()
        restored = QueueItem.from_dict(d)
        assert restored.source_type == item.source_type
        assert restored.branch_name == item.branch_name
        assert restored.fix_rounds == item.fix_rounds
        assert restored.parent_item_id == item.parent_item_id
        assert restored.slack_ts == item.slack_ts
        assert restored.pr_url == item.pr_url

    def test_fix_rounds_increment(self) -> None:
        """fix_rounds is mutable and can be incremented."""
        item = QueueItem(
            id="q-tf-inc",
            source_type="slack",
            source_value="some run",
            status=QueueItemStatus.COMPLETED,
        )
        assert item.fix_rounds == 0
        item.fix_rounds += 1
        assert item.fix_rounds == 1

    def test_head_sha_propagation_to_parent(self) -> None:
        """After a fix, the parent's head_sha must be updated so the next fix
        round inherits the correct expected SHA (multi-round fix support)."""
        parent = QueueItem(
            id="q-parent",
            source_type="slack",
            source_value="build feature X",
            status=QueueItemStatus.COMPLETED,
            head_sha="aaa111",
            branch_name="colonyos/feature-x",
        )
        new_sha = "bbb222"
        # Simulate the fix executor updating parent's head_sha
        parent.head_sha = new_sha
        assert parent.head_sha == new_sha

        # A subsequent fix item inheriting from parent gets the updated SHA
        fix_item = QueueItem(
            id="q-fix-2",
            source_type="slack_fix",
            source_value="fix item 2",
            status=QueueItemStatus.PENDING,
            parent_item_id=parent.id,
            head_sha=parent.head_sha,
        )
        assert fix_item.head_sha == new_sha


class TestQueueItemSchemaVersion:
    """Tests for QueueItem schema_version evolution tracking."""

    def test_to_dict_includes_schema_version(self) -> None:
        item = QueueItem(
            id="q-sv-1", source_type="slack", source_value="test",
            status=QueueItemStatus.PENDING,
        )
        d = item.to_dict()
        assert "schema_version" in d
        assert d["schema_version"] == QueueItem.SCHEMA_VERSION

    def test_from_dict_handles_missing_schema_version(self) -> None:
        """Old items without schema_version load gracefully."""
        d = {
            "id": "q-old",
            "source_type": "slack",
            "source_value": "test",
            "status": "pending",
        }
        item = QueueItem.from_dict(d)
        assert item.id == "q-old"

    def test_roundtrip_preserves_schema_version(self) -> None:
        item = QueueItem(
            id="q-sv-rt", source_type="slack", source_value="test",
            status=QueueItemStatus.COMPLETED,
        )
        d = item.to_dict()
        restored = QueueItem.from_dict(d)
        assert restored.id == item.id
        assert d["schema_version"] == QueueItem.SCHEMA_VERSION


class TestRunLogPrUrl:
    """Tests for pr_url field on RunLog."""

    def test_default_none(self) -> None:
        log = RunLog(run_id="r-1", prompt="test", status=RunStatus.RUNNING)
        assert log.pr_url is None

    def test_set_pr_url(self) -> None:
        log = RunLog(
            run_id="r-1",
            prompt="test",
            status=RunStatus.COMPLETED,
            pr_url="https://github.com/org/repo/pull/42",
        )
        assert log.pr_url == "https://github.com/org/repo/pull/42"

    def test_mark_finished_preserves_pr_url(self) -> None:
        log = RunLog(
            run_id="r-1",
            prompt="test",
            status=RunStatus.RUNNING,
            pr_url="https://github.com/org/repo/pull/99",
        )
        log.mark_finished()
        assert log.pr_url == "https://github.com/org/repo/pull/99"


class TestPhaseResultTaskId:
    """Tests for task_id in PhaseResult.artifacts (Task 4.1)."""

    def test_task_id_in_artifacts(self) -> None:
        result = PhaseResult(
            phase=Phase.IMPLEMENT,
            success=True,
            cost_usd=0.85,
            artifacts={"task_id": "3.0", "result": "Completed rate limiting"},
        )
        assert result.artifacts["task_id"] == "3.0"
        assert result.artifacts["result"] == "Completed rate limiting"

    def test_artifacts_default_empty(self) -> None:
        result = PhaseResult(phase=Phase.IMPLEMENT, success=True)
        assert result.artifacts == {}

    def test_backward_compat_no_task_id(self) -> None:
        """Old PhaseResults without task_id in artifacts load fine."""
        result = PhaseResult(
            phase=Phase.IMPLEMENT,
            success=True,
            artifacts={"pr_url": "https://github.com/..."},
        )
        assert "task_id" not in result.artifacts
        assert result.artifacts["pr_url"] == "https://github.com/..."


class TestRunLogGetTaskResults:
    """Tests for RunLog.get_task_results() helper method (Task 4.3)."""

    def test_get_task_results_single_match(self) -> None:
        log = RunLog(
            run_id="r-1",
            prompt="test",
            status=RunStatus.COMPLETED,
            phases=[
                PhaseResult(
                    phase=Phase.IMPLEMENT,
                    success=True,
                    artifacts={"task_id": "1.0"},
                ),
                PhaseResult(
                    phase=Phase.IMPLEMENT,
                    success=True,
                    artifacts={"task_id": "2.0"},
                ),
            ],
        )
        results = log.get_task_results("1.0")
        assert len(results) == 1
        assert results[0].artifacts["task_id"] == "1.0"

    def test_get_task_results_multiple_matches(self) -> None:
        """A task may have multiple phase results (e.g., retry)."""
        log = RunLog(
            run_id="r-1",
            prompt="test",
            status=RunStatus.COMPLETED,
            phases=[
                PhaseResult(
                    phase=Phase.IMPLEMENT,
                    success=False,
                    artifacts={"task_id": "1.0"},
                ),
                PhaseResult(
                    phase=Phase.IMPLEMENT,
                    success=True,
                    artifacts={"task_id": "1.0"},
                ),
            ],
        )
        results = log.get_task_results("1.0")
        assert len(results) == 2

    def test_get_task_results_no_match(self) -> None:
        log = RunLog(
            run_id="r-1",
            prompt="test",
            status=RunStatus.COMPLETED,
            phases=[
                PhaseResult(
                    phase=Phase.IMPLEMENT,
                    success=True,
                    artifacts={"task_id": "1.0"},
                ),
            ],
        )
        results = log.get_task_results("nonexistent")
        assert results == []

    def test_get_task_results_empty_phases(self) -> None:
        log = RunLog(run_id="r-1", prompt="test", status=RunStatus.RUNNING)
        results = log.get_task_results("1.0")
        assert results == []


class TestRunLogParallelMetadata:
    """Tests for parallel implement metadata (Task 4.4)."""

    def test_parallel_metadata_fields(self) -> None:
        log = RunLog(
            run_id="r-1",
            prompt="test",
            status=RunStatus.COMPLETED,
            parallel_tasks=4,
            wall_time_ms=120000,
            agent_time_ms=360000,
        )
        assert log.parallel_tasks == 4
        assert log.wall_time_ms == 120000
        assert log.agent_time_ms == 360000

    def test_parallel_metadata_defaults(self) -> None:
        log = RunLog(run_id="r-1", prompt="test", status=RunStatus.RUNNING)
        assert log.parallel_tasks is None
        assert log.wall_time_ms is None
        assert log.agent_time_ms is None

    def test_parallelism_ratio(self) -> None:
        log = RunLog(
            run_id="r-1",
            prompt="test",
            status=RunStatus.COMPLETED,
            wall_time_ms=100000,
            agent_time_ms=300000,
        )
        # Ratio is agent_time / wall_time = 3.0x
        ratio = log.get_parallelism_ratio()
        assert ratio == 3.0

    def test_parallelism_ratio_zero_wall_time(self) -> None:
        log = RunLog(run_id="r-1", prompt="test", status=RunStatus.RUNNING)
        ratio = log.get_parallelism_ratio()
        assert ratio == 1.0  # Default to 1.0 for sequential

    def test_mark_finished_preserves_parallel_metadata(self) -> None:
        log = RunLog(
            run_id="r-1",
            prompt="test",
            status=RunStatus.RUNNING,
            parallel_tasks=3,
            wall_time_ms=60000,
            agent_time_ms=150000,
        )
        log.mark_finished()
        assert log.parallel_tasks == 3
        assert log.wall_time_ms == 60000
        assert log.agent_time_ms == 150000


class TestPhaseConflictResolve:
    """Tests for Phase.CONFLICT_RESOLVE enum value (Task 7.5 prereq)."""

    def test_conflict_resolve_enum_value(self) -> None:
        assert Phase.CONFLICT_RESOLVE.value == "conflict_resolve"

    def test_conflict_resolve_serialization_roundtrip(self) -> None:
        assert Phase("conflict_resolve") == Phase.CONFLICT_RESOLVE

    def test_conflict_resolve_phase_result(self) -> None:
        result = PhaseResult(
            phase=Phase.CONFLICT_RESOLVE,
            success=True,
            cost_usd=0.25,
        )
        assert result.phase == Phase.CONFLICT_RESOLVE


class TestTaskStatus:
    """Tests for TaskStatus enum (Task 10.4)."""

    def test_task_status_values(self) -> None:
        from colonyos.models import TaskStatus
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.BLOCKED.value == "blocked"

    def test_task_status_serialization(self) -> None:
        from colonyos.models import TaskStatus
        assert TaskStatus("pending") == TaskStatus.PENDING
        assert TaskStatus("blocked") == TaskStatus.BLOCKED


class TestPhaseResultRetryInfo:
    """Tests for retry_info field on PhaseResult (FR-9)."""

    def test_retry_info_default_none(self) -> None:
        """retry_info defaults to None when not provided."""
        result = PhaseResult(phase=Phase.IMPLEMENT, success=True)
        assert result.retry_info is None

    def test_retry_info_accepts_populated_dataclass(self) -> None:
        """retry_info can be set to a RetryInfo with retry metadata."""
        info = RetryInfo(
            attempts=3,
            transient_errors=2,
            fallback_model_used=None,
            total_retry_delay_seconds=25.5,
        )
        result = PhaseResult(
            phase=Phase.IMPLEMENT,
            success=True,
            cost_usd=1.0,
            retry_info=info,
        )
        assert result.retry_info is not None
        assert result.retry_info.attempts == 3
        assert result.retry_info.transient_errors == 2
        assert result.retry_info.fallback_model_used is None
        assert result.retry_info.total_retry_delay_seconds == 25.5

    def test_retry_info_with_fallback_model(self) -> None:
        """retry_info records which fallback model was used."""
        info = RetryInfo(
            attempts=5,
            transient_errors=4,
            fallback_model_used="sonnet",
            total_retry_delay_seconds=60.0,
        )
        result = PhaseResult(
            phase=Phase.IMPLEMENT,
            success=True,
            retry_info=info,
        )
        assert result.retry_info.fallback_model_used == "sonnet"

    def test_backward_compat_old_data_without_retry_info(self) -> None:
        """Old PhaseResult dicts without retry_info should load gracefully."""
        old_data = {
            "phase": "implement",
            "success": True,
            "cost_usd": 1.5,
            "duration_ms": 60000,
            "session_id": "sess-123",
            "model": "opus",
            "error": None,
            "artifacts": {},
        }
        raw_retry = old_data.get("retry_info")
        result = PhaseResult(
            phase=Phase(old_data["phase"]),
            success=old_data["success"],
            cost_usd=old_data.get("cost_usd"),
            duration_ms=old_data.get("duration_ms", 0),
            session_id=old_data.get("session_id", ""),
            model=old_data.get("model"),
            error=old_data.get("error"),
            retry_info=RetryInfo(**raw_retry) if raw_retry else None,
        )
        assert result.retry_info is None
        assert result.success is True
        assert result.model == "opus"

    def test_retry_info_roundtrip_none(self) -> None:
        """Serialization round-trip preserves None retry_info."""
        result = PhaseResult(phase=Phase.REVIEW, success=True)
        # Simulate serialization (as done in orchestrator._save_run_log)
        serialized = {
            "phase": result.phase.value,
            "success": result.success,
            "cost_usd": result.cost_usd,
            "duration_ms": result.duration_ms,
            "session_id": result.session_id,
            "model": result.model,
            "error": result.error,
            "artifacts": result.artifacts,
            "retry_info": {
                "attempts": result.retry_info.attempts,
                "transient_errors": result.retry_info.transient_errors,
                "fallback_model_used": result.retry_info.fallback_model_used,
                "total_retry_delay_seconds": result.retry_info.total_retry_delay_seconds,
            } if result.retry_info else None,
        }
        # Simulate deserialization (as done in orchestrator._load_run_log)
        raw_retry = serialized.get("retry_info")
        restored = PhaseResult(
            phase=Phase(serialized["phase"]),
            success=serialized["success"],
            cost_usd=serialized.get("cost_usd"),
            duration_ms=serialized.get("duration_ms", 0),
            session_id=serialized.get("session_id", ""),
            model=serialized.get("model"),
            error=serialized.get("error"),
            artifacts=serialized.get("artifacts", {}),
            retry_info=RetryInfo(**raw_retry) if raw_retry else None,
        )
        assert restored.retry_info is None

    def test_retry_info_roundtrip_populated(self) -> None:
        """Serialization round-trip preserves populated retry_info."""
        info = RetryInfo(
            attempts=2,
            transient_errors=1,
            fallback_model_used=None,
            total_retry_delay_seconds=12.3,
        )
        result = PhaseResult(
            phase=Phase.IMPLEMENT,
            success=True,
            cost_usd=0.85,
            retry_info=info,
        )
        # Simulate serialization
        serialized = {
            "phase": result.phase.value,
            "success": result.success,
            "cost_usd": result.cost_usd,
            "duration_ms": result.duration_ms,
            "session_id": result.session_id,
            "model": result.model,
            "error": result.error,
            "artifacts": result.artifacts,
            "retry_info": {
                "attempts": result.retry_info.attempts,
                "transient_errors": result.retry_info.transient_errors,
                "fallback_model_used": result.retry_info.fallback_model_used,
                "total_retry_delay_seconds": result.retry_info.total_retry_delay_seconds,
            } if result.retry_info else None,
        }
        # Simulate deserialization
        raw_retry = serialized.get("retry_info")
        restored = PhaseResult(
            phase=Phase(serialized["phase"]),
            success=serialized["success"],
            cost_usd=serialized.get("cost_usd"),
            duration_ms=serialized.get("duration_ms", 0),
            session_id=serialized.get("session_id", ""),
            model=serialized.get("model"),
            error=serialized.get("error"),
            artifacts=serialized.get("artifacts", {}),
            retry_info=RetryInfo(**raw_retry) if raw_retry else None,
        )
        assert restored.retry_info == info
        assert restored.retry_info.attempts == 2
        assert restored.retry_info.total_retry_delay_seconds == 12.3

    def test_retry_info_frozen(self) -> None:
        """RetryInfo is immutable (frozen dataclass)."""
        info = RetryInfo(attempts=2, transient_errors=1)
        with pytest.raises(AttributeError):
            info.attempts = 5  # type: ignore[misc]


class TestPhaseQA:
    """Tests for Phase.QA enum value (Task 2.1 - Intent Router Agent)."""

    def test_qa_enum_value(self) -> None:
        """Phase.QA should have value 'qa'."""
        assert Phase.QA.value == "qa"

    def test_qa_serialization_roundtrip(self) -> None:
        """Phase('qa') should reconstruct Phase.QA."""
        assert Phase("qa") == Phase.QA

    def test_qa_phase_result(self) -> None:
        """PhaseResult can be created with Phase.QA."""
        result = PhaseResult(
            phase=Phase.QA,
            success=True,
            cost_usd=0.25,
        )
        assert result.phase == Phase.QA
        assert result.success is True
        assert result.cost_usd == 0.25

    def test_qa_is_string_enum(self) -> None:
        """Phase.QA should be usable as a string via inheritance from str."""
        # Phase inherits from str, so comparison with string works
        assert Phase.QA == "qa"
        # The .value property returns the string value
        assert Phase.QA.value == "qa"

    def test_qa_in_phase_list(self) -> None:
        """Phase.QA should be a member of the Phase enum."""
        all_phases = list(Phase)
        assert Phase.QA in all_phases

    def test_backward_compat_runlog_without_qa(self) -> None:
        """Existing RunLog JSON without QA phases loads fine."""
        log = RunLog(
            run_id="r-old",
            prompt="old run",
            status=RunStatus.COMPLETED,
            phases=[
                PhaseResult(phase=Phase.IMPLEMENT, success=True),
                PhaseResult(phase=Phase.DELIVER, success=True),
            ],
        )
        assert all(p.phase != Phase.QA for p in log.phases)

    def test_qa_distinct_from_triage(self) -> None:
        """Phase.QA and Phase.TRIAGE are distinct phases."""
        assert Phase.QA != Phase.TRIAGE
        assert Phase.QA.value != Phase.TRIAGE.value
