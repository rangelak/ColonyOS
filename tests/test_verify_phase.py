"""Tests for the pre-delivery verify-fix loop in the main pipeline (Task 4.0)."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from colonyos.config import (
    BudgetConfig,
    ColonyConfig,
    PhasesConfig,
    VerifyConfig,
    save_config,
)
from colonyos.models import Persona, Phase, PhaseResult, ProjectInfo, RunStatus


REVIEWER_PERSONA = Persona(
    role="Engineer", expertise="Backend", perspective="Scale", reviewer=True
)


def _mock_git(*args, **kwargs):
    """Stub for subprocess.run — returns plausible defaults for git commands."""
    cmd = args[0] if args else kwargs.get("args", [])
    m = MagicMock()
    m.returncode = 0
    m.stderr = ""
    if "rev-parse" in cmd and "--abbrev-ref" in cmd:
        m.stdout = "main"
    elif "rev-parse" in cmd and "HEAD" in cmd:
        m.stdout = "abc123"
    elif "rev-parse" in cmd and "--verify" in cmd:
        m.returncode = 1
        m.stdout = ""
    elif "status" in cmd and "--porcelain" in cmd:
        m.stdout = ""
    elif "rev-list" in cmd:
        m.stdout = "0"
    elif "diff" in cmd:
        m.stdout = ""
    elif "branch" in cmd and "--list" in cmd:
        m.stdout = ""
    else:
        m.stdout = ""
    return m


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    (tmp_path / "cOS_prds").mkdir()
    (tmp_path / "cOS_tasks").mkdir()
    (tmp_path / "cOS_reviews").mkdir()
    (tmp_path / ".colonyos").mkdir()
    with patch("colonyos.orchestrator.subprocess.run", side_effect=_mock_git):
        yield tmp_path


def _fake_phase_result(phase: Phase, success: bool = True, **kwargs) -> PhaseResult:
    return PhaseResult(
        phase=phase,
        success=success,
        cost_usd=kwargs.get("cost_usd", 0.01),
        duration_ms=100,
        session_id="test-session",
        artifacts=kwargs.get("artifacts", {"result": "done"}),
    )


def _config(**overrides) -> ColonyConfig:
    defaults = dict(
        project=ProjectInfo(name="Test", description="test", stack="Python"),
        personas=[REVIEWER_PERSONA],
        model="test-model",
        budget=BudgetConfig(per_phase=1.0, per_run=15.0),
        phases=PhasesConfig(plan=True, implement=True, review=True, deliver=True, verify=True),
        verify=VerifyConfig(max_fix_attempts=2),
    )
    defaults.update(overrides)
    return ColonyConfig(**defaults)


class TestVerifyPhaseInMainPipeline:
    """Tests for verify-fix loop inserted between Learn and Deliver in _run_pipeline()."""

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_verify_passes_proceeds_to_deliver(
        self, mock_run, mock_parallel, tmp_git_repo: Path
    ):
        """(a) Verify passes on first try → deliver runs normally."""
        config = _config()
        save_config(tmp_git_repo, config)

        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            # Decision gate
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            # Verify passes
            _fake_phase_result(Phase.VERIFY, artifacts={"result": "All 100 tests passed"}),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [
            PhaseResult(phase=Phase.REVIEW, success=True, cost_usd=0.01,
                        duration_ms=100, session_id="s",
                        artifacts={"result": "VERDICT: approve\n\nFINDINGS:\n- None\n\nSYNTHESIS:\nLooks good."})
        ]

        from colonyos.orchestrator import run
        log = run("Add tests", repo_root=tmp_git_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        phase_types = [p.phase for p in log.phases]
        assert Phase.VERIFY in phase_types
        assert Phase.DELIVER in phase_types
        # Verify must come after Learn and before Deliver
        verify_idx = phase_types.index(Phase.VERIFY)
        deliver_idx = phase_types.index(Phase.DELIVER)
        assert verify_idx < deliver_idx

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_verify_fails_fix_succeeds_then_delivers(
        self, mock_run, mock_parallel, tmp_git_repo: Path
    ):
        """(b) Verify fails → fix runs → re-verify passes → deliver proceeds."""
        config = _config()
        save_config(tmp_git_repo, config)

        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            # First verify: fails
            _fake_phase_result(Phase.VERIFY, artifacts={"result": "FAILED: 2 tests failed\n\ntest_foo FAILED\ntest_bar FAILED"}),
            # Fix agent
            _fake_phase_result(Phase.FIX),
            # Second verify: passes
            _fake_phase_result(Phase.VERIFY, artifacts={"result": "All 100 tests passed"}),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [
            PhaseResult(phase=Phase.REVIEW, success=True, cost_usd=0.01,
                        duration_ms=100, session_id="s",
                        artifacts={"result": "VERDICT: approve\n\nFINDINGS:\n- None\n\nSYNTHESIS:\nLooks good."})
        ]

        from colonyos.orchestrator import run
        log = run("Add tests", repo_root=tmp_git_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        phase_types = [p.phase for p in log.phases]
        assert phase_types.count(Phase.VERIFY) == 2  # Two verify runs
        assert Phase.FIX in phase_types
        assert Phase.DELIVER in phase_types

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_verify_fails_exhausts_retries_blocks_delivery(
        self, mock_run, mock_parallel, tmp_git_repo: Path
    ):
        """(c) Verify fails → fix exhausts retries → FAILED, no delivery."""
        config = _config(verify=VerifyConfig(max_fix_attempts=2))
        save_config(tmp_git_repo, config)

        fail_verify = _fake_phase_result(
            Phase.VERIFY,
            artifacts={"result": "FAILED: 3 tests failed\n\ntest_foo FAILED"},
        )
        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            # Verify 1: fail
            fail_verify,
            _fake_phase_result(Phase.FIX),
            # Verify 2: fail
            fail_verify,
            _fake_phase_result(Phase.FIX),
            # Verify 3 (final check): fail
            fail_verify,
        ]
        mock_parallel.return_value = [
            PhaseResult(phase=Phase.REVIEW, success=True, cost_usd=0.01,
                        duration_ms=100, session_id="s",
                        artifacts={"result": "VERDICT: approve\n\nFINDINGS:\n- None\n\nSYNTHESIS:\nLooks good."})
        ]

        from colonyos.orchestrator import run
        log = run("Add tests", repo_root=tmp_git_repo, config=config)

        assert log.status == RunStatus.FAILED
        phase_types = [p.phase for p in log.phases]
        assert Phase.DELIVER not in phase_types
        # Should have 3 verify attempts (initial + 2 re-verifies after fixes)
        assert phase_types.count(Phase.VERIFY) == 3
        assert phase_types.count(Phase.FIX) == 2

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_budget_guard_stops_verify_loop(
        self, mock_run, mock_parallel, tmp_git_repo: Path
    ):
        """(d) Budget guard prevents fix loop when budget exhausted."""
        config = _config(
            budget=BudgetConfig(per_phase=1.0, per_run=5.5),
            verify=VerifyConfig(max_fix_attempts=2),
        )
        save_config(tmp_git_repo, config)

        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN, cost_usd=1.0),
            _fake_phase_result(Phase.IMPLEMENT, cost_usd=1.0),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=1.0,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN, cost_usd=0.5),
            # Verify fails but budget is almost gone (4.5 spent, 1.0 remaining < per_phase)
            _fake_phase_result(Phase.VERIFY, cost_usd=1.0,
                               artifacts={"result": "FAILED: test_foo FAILED"}),
            # No budget left for fix — loop should stop
        ]
        mock_parallel.return_value = [
            PhaseResult(phase=Phase.REVIEW, success=True, cost_usd=0.01,
                        duration_ms=100, session_id="s",
                        artifacts={"result": "VERDICT: approve\n\nFINDINGS:\n- None\n\nSYNTHESIS:\nLooks good."})
        ]

        from colonyos.orchestrator import run
        log = run("Add tests", repo_root=tmp_git_repo, config=config)

        assert log.status == RunStatus.FAILED
        phase_types = [p.phase for p in log.phases]
        # Only one verify call, no fix (budget exhausted)
        assert phase_types.count(Phase.VERIFY) == 1
        assert Phase.FIX not in phase_types
        assert Phase.DELIVER not in phase_types

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_verify_skipped_when_disabled(
        self, mock_run, mock_parallel, tmp_git_repo: Path
    ):
        """(e) Verify skipped when config.phases.verify is False."""
        config = _config(
            phases=PhasesConfig(plan=True, implement=True, review=True, deliver=True, verify=False),
        )
        save_config(tmp_git_repo, config)

        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [
            PhaseResult(phase=Phase.REVIEW, success=True, cost_usd=0.01,
                        duration_ms=100, session_id="s",
                        artifacts={"result": "VERDICT: approve\n\nFINDINGS:\n- None\n\nSYNTHESIS:\nLooks good."})
        ]

        from colonyos.orchestrator import run
        log = run("Add tests", repo_root=tmp_git_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        phase_types = [p.phase for p in log.phases]
        assert Phase.VERIFY not in phase_types
        assert Phase.DELIVER in phase_types

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_heartbeat_touched_before_verify(
        self, mock_run, mock_parallel, tmp_git_repo: Path
    ):
        """(f) Heartbeat file is touched before verify phase runs."""
        config = _config()
        save_config(tmp_git_repo, config)

        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            _fake_phase_result(Phase.VERIFY, artifacts={"result": "All 100 tests passed"}),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [
            PhaseResult(phase=Phase.REVIEW, success=True, cost_usd=0.01,
                        duration_ms=100, session_id="s",
                        artifacts={"result": "VERDICT: approve\n\nFINDINGS:\n- None\n\nSYNTHESIS:\nLooks good."})
        ]

        from colonyos.orchestrator import run
        log = run("Add tests", repo_root=tmp_git_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        # Heartbeat file should exist (touched by verify phase and others)
        from colonyos.orchestrator import runs_dir_path
        heartbeat = runs_dir_path(tmp_git_repo) / "heartbeat"
        assert heartbeat.exists()
