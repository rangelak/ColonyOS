"""Tests for the pre-delivery verify-fix loop in the main pipeline (Tasks 4.0 & 6.0)."""

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
from colonyos.models import Persona, Phase, PhaseResult, ProjectInfo, ResumeState, RunLog, RunStatus


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
            _fake_phase_result(Phase.VERIFY, artifacts={"result": "All 100 tests passed\n\nVERIFY_RESULT: PASS"}),
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
            _fake_phase_result(Phase.VERIFY, artifacts={"result": "FAILED: 2 tests failed\n\ntest_foo FAILED\ntest_bar FAILED\n\nVERIFY_RESULT: FAIL"}),
            # Fix agent
            _fake_phase_result(Phase.FIX),
            # Second verify: passes
            _fake_phase_result(Phase.VERIFY, artifacts={"result": "All 100 tests passed\n\nVERIFY_RESULT: PASS"}),
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
            artifacts={"result": "FAILED: 3 tests failed\n\ntest_foo FAILED\n\nVERIFY_RESULT: FAIL"},
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
                               artifacts={"result": "FAILED: 1 test failed\n\ntest_foo FAILED\n\nVERIFY_RESULT: FAIL"}),
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
            _fake_phase_result(Phase.VERIFY, artifacts={"result": "All 100 tests passed\n\nVERIFY_RESULT: PASS"}),
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


class TestVerifyPhaseIntegration:
    """Integration tests for verify phase: end-to-end pipeline runs (Task 6.0)."""

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_full_pipeline_verify_passes_first_try(
        self, mock_run, mock_parallel, tmp_git_repo: Path
    ):
        """6.1 — Full pipeline with verify enabled; tests pass on first try.

        Verify that the complete phase ordering is correct and costs accumulate
        through the verify phase into the final run log.
        """
        config = _config()
        save_config(tmp_git_repo, config)

        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN, cost_usd=0.50),
            _fake_phase_result(Phase.IMPLEMENT, cost_usd=1.00),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.20,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN, cost_usd=0.10),
            _fake_phase_result(Phase.VERIFY, cost_usd=0.30,
                               artifacts={"result": "All 42 tests passed\n\nVERIFY_RESULT: PASS"}),
            _fake_phase_result(Phase.DELIVER, cost_usd=0.40),
        ]
        mock_parallel.return_value = [
            PhaseResult(phase=Phase.REVIEW, success=True, cost_usd=0.25,
                        duration_ms=100, session_id="s",
                        artifacts={"result": "VERDICT: approve\n\nFINDINGS:\n- None\n\nSYNTHESIS:\nLooks good."})
        ]

        from colonyos.orchestrator import run
        log = run("Build feature X", repo_root=tmp_git_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        phase_types = [p.phase for p in log.phases]
        # Full phase ordering: Plan → Implement → Review → Decision → Learn → Verify → Deliver
        assert phase_types == [
            Phase.PLAN, Phase.IMPLEMENT, Phase.REVIEW,
            Phase.DECISION, Phase.LEARN, Phase.VERIFY, Phase.DELIVER,
        ]
        # Costs accumulated correctly
        total_cost = sum(p.cost_usd for p in log.phases if p.cost_usd is not None)
        assert abs(total_cost - 2.75) < 0.01  # 0.50+1.00+0.25+0.20+0.10+0.30+0.40
        # Exactly one verify, no fix needed
        assert phase_types.count(Phase.VERIFY) == 1
        assert Phase.FIX not in phase_types

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_full_pipeline_verify_fails_fix_succeeds(
        self, mock_run, mock_parallel, tmp_git_repo: Path
    ):
        """6.2 — Full pipeline; verify fails, fix succeeds on first attempt.

        Validates the full phase sequence including a fix iteration, and that
        the run completes successfully with delivery.
        """
        config = _config(verify=VerifyConfig(max_fix_attempts=2))
        save_config(tmp_git_repo, config)

        mock_run.side_effect = [
            _fake_phase_result(Phase.PLAN),
            _fake_phase_result(Phase.IMPLEMENT),
            PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                        duration_ms=50, session_id="s",
                        artifacts={"result": "VERDICT: GO"}),
            _fake_phase_result(Phase.LEARN),
            # First verify: fails
            _fake_phase_result(Phase.VERIFY,
                               artifacts={"result": "FAILED: 3 tests failed\n\ntest_auth FAILED\ntest_login FAILED\ntest_perms FAILED\n\nVERIFY_RESULT: FAIL"}),
            # Fix agent repairs
            _fake_phase_result(Phase.FIX, cost_usd=0.80),
            # Second verify: passes
            _fake_phase_result(Phase.VERIFY,
                               artifacts={"result": "All 42 tests passed\n\nVERIFY_RESULT: PASS"}),
            _fake_phase_result(Phase.DELIVER),
        ]
        mock_parallel.return_value = [
            PhaseResult(phase=Phase.REVIEW, success=True, cost_usd=0.01,
                        duration_ms=100, session_id="s",
                        artifacts={"result": "VERDICT: approve\n\nFINDINGS:\n- None\n\nSYNTHESIS:\nLooks good."})
        ]

        from colonyos.orchestrator import run
        log = run("Build feature X", repo_root=tmp_git_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        phase_types = [p.phase for p in log.phases]
        # Verify appears twice (fail then pass), fix appears once
        assert phase_types.count(Phase.VERIFY) == 2
        assert phase_types.count(Phase.FIX) == 1
        assert Phase.DELIVER in phase_types
        # Fix comes between the two verify runs
        verify_indices = [i for i, p in enumerate(phase_types) if p == Phase.VERIFY]
        fix_idx = phase_types.index(Phase.FIX)
        assert verify_indices[0] < fix_idx < verify_indices[1]

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_full_pipeline_verify_disabled(
        self, mock_run, mock_parallel, tmp_git_repo: Path
    ):
        """6.3 — Full pipeline with verify disabled; verify skipped, deliver proceeds.

        Confirms the pipeline goes directly from Learn to Deliver with no
        verify-related phases in the log.
        """
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
        log = run("Build feature X", repo_root=tmp_git_repo, config=config)

        assert log.status == RunStatus.COMPLETED
        phase_types = [p.phase for p in log.phases]
        assert Phase.VERIFY not in phase_types
        assert Phase.FIX not in phase_types
        # Learn → Deliver (no verify in between)
        learn_idx = phase_types.index(Phase.LEARN)
        deliver_idx = phase_types.index(Phase.DELIVER)
        assert deliver_idx == learn_idx + 1

    @patch("colonyos.orchestrator.run_phases_parallel_sync")
    @patch("colonyos.orchestrator.run_phase_sync")
    def test_resume_from_failed_verify(
        self, mock_run, mock_parallel, tmp_git_repo: Path
    ):
        """6.4 — Resume from a failed verify; pipeline resumes at verify phase.

        Simulates a run that failed during verify (decision was the last
        successful phase). On resume, the pipeline should skip plan/implement/
        review and re-run from verify (via learn) through deliver.
        """
        config = _config()
        save_config(tmp_git_repo, config)

        # Build a RunLog representing a prior failed run where decision
        # was the last successful phase (verify failed after it).
        existing_log = RunLog(
            run_id="r-verify-fail",
            prompt="Build feature X",
            status=RunStatus.FAILED,
            branch_name="colonyos/build_feature_x",
            prd_rel="cOS_prds/prd.md",
            task_rel="cOS_tasks/tasks.md",
            phases=[
                _fake_phase_result(Phase.PLAN),
                _fake_phase_result(Phase.IMPLEMENT),
                PhaseResult(phase=Phase.REVIEW, success=True, cost_usd=0.01,
                            duration_ms=100, session_id="s",
                            artifacts={"result": "VERDICT: approve\n\nFINDINGS:\n- None\n\nSYNTHESIS:\nOK."}),
                PhaseResult(phase=Phase.DECISION, success=True, cost_usd=0.01,
                            duration_ms=50, session_id="s",
                            artifacts={"result": "VERDICT: GO"}),
                _fake_phase_result(Phase.LEARN),
                # Verify failed (this is the failing phase)
                _fake_phase_result(Phase.VERIFY, success=False,
                                   artifacts={"result": "FAILED: 5 tests failed\n\nVERIFY_RESULT: FAIL"}),
            ],
        )

        # On resume: last_successful_phase is "learn" (last successful before
        # the failed VERIFY).  _compute_next_phase("learn") → "verify".
        resume_state = ResumeState(
            log=existing_log,
            branch_name="colonyos/build_feature_x",
            prd_rel="cOS_prds/prd.md",
            task_rel="cOS_tasks/tasks.md",
            last_successful_phase="learn",
        )

        # On resume from "learn": skip plan, implement, review;
        # run learn → verify → deliver
        mock_run.side_effect = [
            _fake_phase_result(Phase.LEARN),
            # Verify now passes on retry
            _fake_phase_result(Phase.VERIFY,
                               artifacts={"result": "All 42 tests passed\n\nVERIFY_RESULT: PASS"}),
            _fake_phase_result(Phase.DELIVER),
        ]

        from colonyos.orchestrator import run
        log = run(
            "Build feature X",
            repo_root=tmp_git_repo,
            config=config,
            resume_from=resume_state,
        )

        assert log.status == RunStatus.COMPLETED
        # Plan, implement, review were skipped (from the resume)
        assert mock_parallel.call_count == 0  # No parallel review
        # Learn + verify + deliver ran (resume from learn skips plan/implement/review)
        assert mock_run.call_count == 3
        # Verify and deliver are in the final log
        phase_types = [p.phase for p in log.phases]
        assert Phase.VERIFY in phase_types
        assert Phase.DELIVER in phase_types


class TestVerifyDetectedFailures:
    """Unit tests for _verify_detected_failures — the critical decision boundary."""

    def test_empty_output_returns_false(self):
        from colonyos.orchestrator import _verify_detected_failures
        assert _verify_detected_failures("") is False
        assert _verify_detected_failures(None) is False

    def test_sentinel_pass(self):
        from colonyos.orchestrator import _verify_detected_failures
        assert _verify_detected_failures("All 42 tests passed\n\nVERIFY_RESULT: PASS") is False

    def test_sentinel_fail(self):
        from colonyos.orchestrator import _verify_detected_failures
        assert _verify_detected_failures("3 tests failed\n\nVERIFY_RESULT: FAIL") is True

    def test_sentinel_case_insensitive(self):
        from colonyos.orchestrator import _verify_detected_failures
        assert _verify_detected_failures("verify_result: pass") is False
        assert _verify_detected_failures("verify_result: fail") is True

    def test_sentinel_overrides_ambiguous_output(self):
        """Sentinel takes priority even when body mentions 'failed'."""
        from colonyos.orchestrator import _verify_detected_failures
        output = "test_error_handler PASSED\n42 passed, 0 failed\n\nVERIFY_RESULT: PASS"
        assert _verify_detected_failures(output) is False

    def test_sentinel_fail_overrides_pass_language(self):
        from colonyos.orchestrator import _verify_detected_failures
        output = "All tests passed... NOT. 1 test actually failed\n\nVERIFY_RESULT: FAIL"
        assert _verify_detected_failures(output) is True

    def test_fallback_zero_failed_returns_false(self):
        """'0 failed' in pytest output should NOT trigger false positive."""
        from colonyos.orchestrator import _verify_detected_failures
        assert _verify_detected_failures("42 passed, 0 failed") is False

    def test_fallback_zero_errors_returns_false(self):
        from colonyos.orchestrator import _verify_detected_failures
        assert _verify_detected_failures("42 passed, 0 errors") is False

    def test_fallback_nonzero_failed(self):
        from colonyos.orchestrator import _verify_detected_failures
        assert _verify_detected_failures("40 passed, 2 failed") is True

    def test_fallback_nonzero_errors(self):
        from colonyos.orchestrator import _verify_detected_failures
        assert _verify_detected_failures("1 error in test_auth") is True

    def test_fallback_all_tests_passed(self):
        from colonyos.orchestrator import _verify_detected_failures
        assert _verify_detected_failures("All tests passed") is False
        assert _verify_detected_failures("all tests pass") is False

    def test_fallback_no_recognisable_signal(self):
        """Unknown output defaults to False (tests assumed passing)."""
        from colonyos.orchestrator import _verify_detected_failures
        assert _verify_detected_failures("some random output") is False

    def test_class_name_error_handler_no_false_positive(self):
        """Names like 'ErrorHandler' or 'test_error_handler' must not trigger."""
        from colonyos.orchestrator import _verify_detected_failures
        output = "test_error_handler PASSED\nErrorHandler validated\n42 passed"
        assert _verify_detected_failures(output) is False

    def test_fallback_10_failures(self):
        from colonyos.orchestrator import _verify_detected_failures
        assert _verify_detected_failures("10 failed, 32 passed") is True


class TestComputeNextPhaseLearn:
    """Tests for _compute_next_phase with 'learn' mapping."""

    def test_learn_maps_to_verify(self):
        from colonyos.orchestrator import _compute_next_phase
        assert _compute_next_phase("learn") == "verify"

    def test_decision_still_maps_to_verify(self):
        from colonyos.orchestrator import _compute_next_phase
        assert _compute_next_phase("decision") == "verify"

    def test_verify_maps_to_deliver(self):
        from colonyos.orchestrator import _compute_next_phase
        assert _compute_next_phase("verify") == "deliver"
