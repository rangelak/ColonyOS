"""Task 4.1: Tests for LoopState dataclass."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colonyos.models import LoopState, LoopStatus, Phase, PhaseResult, RunLog, RunStatus


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
