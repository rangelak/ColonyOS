"""Tests for the post-implement verification gate."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from colonyos.config import ColonyConfig, BudgetConfig, VerificationConfig
from colonyos.models import Phase, PhaseResult, ProjectInfo, RunLog, RunStatus
from colonyos.orchestrator import (
    _run_verify_command,
    _build_verify_fix_prompt,
    run_verify_loop,
    _VERIFY_TRUNCATE_LIMIT,
)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / "cOS_prds").mkdir()
    (tmp_path / "cOS_tasks").mkdir()
    (tmp_path / ".colonyos").mkdir()
    return tmp_path


@pytest.fixture
def config_with_verify() -> ColonyConfig:
    return ColonyConfig(
        project=ProjectInfo(name="Test", description="test", stack="Python"),
        model="test-model",
        budget=BudgetConfig(per_phase=1.0, per_run=10.0),
        verification=VerificationConfig(
            verify_command="pytest",
            max_verify_retries=2,
            verify_timeout=300,
        ),
    )


@pytest.fixture
def config_no_verify() -> ColonyConfig:
    return ColonyConfig(
        project=ProjectInfo(name="Test", description="test", stack="Python"),
        model="test-model",
        budget=BudgetConfig(per_phase=1.0, per_run=10.0),
    )


def _make_log() -> RunLog:
    return RunLog(run_id="test-run", prompt="test", status=RunStatus.RUNNING)


class TestRunVerifyCommand:
    def test_subprocess_called_with_correct_args(self, tmp_path):
        with patch("colonyos.orchestrator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="OK", stderr=""
            )
            _run_verify_command("pytest", tmp_path, 300)

            mock_run.assert_called_once_with(
                "pytest",
                shell=True,
                capture_output=True,
                text=True,
                cwd=tmp_path,
                timeout=300,
            )

    def test_exit_code_zero_returns_success(self, tmp_path):
        with patch("colonyos.orchestrator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="All tests passed", stderr=""
            )
            passed, output, code = _run_verify_command("pytest", tmp_path, 300)

        assert passed is True
        assert code == 0
        assert "All tests passed" in output

    def test_exit_code_nonzero_returns_failure(self, tmp_path):
        with patch("colonyos.orchestrator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="FAILED test_foo.py"
            )
            passed, output, code = _run_verify_command("pytest", tmp_path, 300)

        assert passed is False
        assert code == 1
        assert "FAILED" in output

    def test_timeout_treated_as_failure(self, tmp_path):
        with patch("colonyos.orchestrator.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("pytest", 300)
            passed, output, code = _run_verify_command("pytest", tmp_path, 300)

        assert passed is False
        assert code == -1
        assert "timed out" in output

    def test_output_truncated_to_last_4000_chars(self, tmp_path):
        long_output = "x" * 10000
        with patch("colonyos.orchestrator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout=long_output, stderr=""
            )
            passed, output, code = _run_verify_command("pytest", tmp_path, 300)

        assert len(output) == _VERIFY_TRUNCATE_LIMIT
        assert output == long_output[-_VERIFY_TRUNCATE_LIMIT:]


class TestBuildVerifyFixPrompt:
    def test_returns_tuple(self, config_with_verify):
        system, user = _build_verify_fix_prompt(
            config_with_verify,
            "cOS_prds/prd.md",
            "cOS_tasks/tasks.md",
            "colonyos/feat",
            "FAILED test_foo",
            1,
        )
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_contains_prd_and_task(self, config_with_verify):
        system, _ = _build_verify_fix_prompt(
            config_with_verify,
            "cOS_prds/prd.md",
            "cOS_tasks/tasks.md",
            "colonyos/feat",
            "FAILED test_foo",
            1,
        )
        assert "cOS_prds/prd.md" in system
        assert "cOS_tasks/tasks.md" in system

    def test_system_contains_test_output(self, config_with_verify):
        system, _ = _build_verify_fix_prompt(
            config_with_verify,
            "cOS_prds/prd.md",
            "cOS_tasks/tasks.md",
            "colonyos/feat",
            "FAILED test_foo::test_bar",
            1,
        )
        assert "FAILED test_foo::test_bar" in system

    def test_system_contains_fix_instructions(self, config_with_verify):
        system, _ = _build_verify_fix_prompt(
            config_with_verify,
            "cOS_prds/prd.md",
            "cOS_tasks/tasks.md",
            "colonyos/feat",
            "error",
            1,
        )
        assert "fix" in system.lower()
        assert "rewrite" in system.lower()  # "do NOT rewrite from scratch"

    def test_user_prompt_contains_context(self, config_with_verify):
        _, user = _build_verify_fix_prompt(
            config_with_verify,
            "cOS_prds/prd.md",
            "cOS_tasks/tasks.md",
            "colonyos/feat",
            "error",
            1,
        )
        assert "colonyos/feat" in user
        assert "cOS_prds/prd.md" in user


class TestRunVerifyLoop:
    def test_skipped_when_no_verify_command(self, tmp_repo, config_no_verify):
        log = _make_log()
        result = run_verify_loop(
            tmp_repo, config_no_verify, log,
            "cOS_prds/prd.md", "cOS_tasks/tasks.md", "colonyos/feat",
            quiet=True,
        )
        assert result is True
        # No phases should be added
        assert len(log.phases) == 0

    def test_passes_on_first_try(self, tmp_repo, config_with_verify):
        log = _make_log()
        with patch("colonyos.orchestrator._run_verify_command") as mock_verify:
            mock_verify.return_value = (True, "OK", 0)
            result = run_verify_loop(
                tmp_repo, config_with_verify, log,
                "cOS_prds/prd.md", "cOS_tasks/tasks.md", "colonyos/feat",
                quiet=True,
            )

        assert result is True
        assert len(log.phases) == 1
        assert log.phases[0].phase == Phase.VERIFY
        assert log.phases[0].success is True
        assert log.phases[0].cost_usd == 0.0

    def test_retry_on_failure_then_pass(self, tmp_repo, config_with_verify):
        log = _make_log()
        with patch("colonyos.orchestrator._run_verify_command") as mock_verify, \
             patch("colonyos.orchestrator.run_phase_sync") as mock_run:
            # First verify fails, implement retry succeeds, second verify passes
            mock_verify.side_effect = [
                (False, "FAILED test_foo", 1),
                (True, "OK", 0),
            ]
            mock_run.return_value = PhaseResult(
                phase=Phase.IMPLEMENT, success=True, cost_usd=0.5,
            )
            result = run_verify_loop(
                tmp_repo, config_with_verify, log,
                "cOS_prds/prd.md", "cOS_tasks/tasks.md", "colonyos/feat",
                quiet=True,
            )

        assert result is True
        # Should have: verify(fail) + implement(retry) + verify(pass)
        assert len(log.phases) == 3
        assert log.phases[0].phase == Phase.VERIFY
        assert log.phases[0].success is False
        assert log.phases[1].phase == Phase.IMPLEMENT
        assert log.phases[2].phase == Phase.VERIFY
        assert log.phases[2].success is True

    def test_all_retries_exhausted_returns_false(self, tmp_repo, config_with_verify):
        log = _make_log()
        with patch("colonyos.orchestrator._run_verify_command") as mock_verify, \
             patch("colonyos.orchestrator.run_phase_sync") as mock_run:
            mock_verify.return_value = (False, "FAILED", 1)
            mock_run.return_value = PhaseResult(
                phase=Phase.IMPLEMENT, success=True, cost_usd=0.5,
            )
            result = run_verify_loop(
                tmp_repo, config_with_verify, log,
                "cOS_prds/prd.md", "cOS_tasks/tasks.md", "colonyos/feat",
                quiet=True,
            )

        assert result is False
        # 3 verify attempts (initial + 2 retries) + 2 implement retries
        verify_phases = [p for p in log.phases if p.phase == Phase.VERIFY]
        impl_phases = [p for p in log.phases if p.phase == Phase.IMPLEMENT]
        assert len(verify_phases) == 3
        assert len(impl_phases) == 2

    def test_budget_guard_stops_retries(self, tmp_repo):
        """Retry loop stops when budget would be exceeded."""
        config = ColonyConfig(
            model="test-model",
            budget=BudgetConfig(per_phase=1.0, per_run=2.0),
            verification=VerificationConfig(
                verify_command="pytest",
                max_verify_retries=5,
            ),
        )
        log = _make_log()
        # Simulate existing cost that nearly exhausts budget
        log.phases.append(PhaseResult(
            phase=Phase.IMPLEMENT, success=True, cost_usd=1.5,
        ))

        with patch("colonyos.orchestrator._run_verify_command") as mock_verify:
            mock_verify.return_value = (False, "FAILED", 1)
            result = run_verify_loop(
                tmp_repo, config, log,
                "cOS_prds/prd.md", "cOS_tasks/tasks.md", "colonyos/feat",
                quiet=True,
            )

        assert result is False
        # Should have only 1 verify attempt (no retries due to budget)
        verify_phases = [p for p in log.phases if p.phase == Phase.VERIFY]
        impl_retry_phases = [
            p for p in log.phases
            if p.phase == Phase.IMPLEMENT and p != log.phases[0]
        ]
        assert len(verify_phases) == 1
        assert len(impl_retry_phases) == 0

    def test_verify_result_has_zero_cost(self, tmp_repo, config_with_verify):
        log = _make_log()
        with patch("colonyos.orchestrator._run_verify_command") as mock_verify:
            mock_verify.return_value = (True, "OK", 0)
            run_verify_loop(
                tmp_repo, config_with_verify, log,
                "cOS_prds/prd.md", "cOS_tasks/tasks.md", "colonyos/feat",
                quiet=True,
            )

        assert log.phases[0].cost_usd == 0.0

    def test_verify_artifacts_contain_test_output(self, tmp_repo, config_with_verify):
        log = _make_log()
        with patch("colonyos.orchestrator._run_verify_command") as mock_verify:
            mock_verify.return_value = (False, "some test output", 1)
            # Will exhaust with 0 retries
            config_with_verify.verification = VerificationConfig(
                verify_command="pytest", max_verify_retries=0,
            )
            run_verify_loop(
                tmp_repo, config_with_verify, log,
                "cOS_prds/prd.md", "cOS_tasks/tasks.md", "colonyos/feat",
                quiet=True,
            )

        assert log.phases[0].artifacts["test_output"] == "some test output"
        assert log.phases[0].artifacts["exit_code"] == "1"
