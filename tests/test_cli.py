import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml
from click.testing import CliRunner

from colonyos.cli import app, _save_loop_state, _load_latest_loop_state, _compute_elapsed_hours, _print_review_summary
from colonyos.config import ColonyConfig, BudgetConfig, save_config
from colonyos.models import (
    LoopState, LoopStatus, Persona, Phase, PhaseResult,
    ProjectInfo, RunLog, RunStatus,
)
from colonyos.persona_packs import PACKS


@pytest.fixture
def runner():
    return CliRunner()


class TestVersion:
    def test_version_flag(self, runner: CliRunner):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "colonyos" in result.output
        assert "0.1.0" in result.output


class TestStatus:
    def test_no_runs(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "No runs" in result.output


class TestRun:
    def test_no_prompt_no_prd(self, runner: CliRunner):
        result = runner.invoke(app, ["run"])
        assert result.exit_code != 0

    def test_no_config(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["run", "Add feature"])
        assert result.exit_code != 0
        assert "colonyos init" in result.output


def _make_config(tmp_path: Path) -> ColonyConfig:
    config = ColonyConfig(
        project=ProjectInfo(name="Test", description="test", stack="Python"),
        personas=[Persona(role="Engineer", expertise="Backend", perspective="Scale")],
    )
    save_config(tmp_path, config)
    return config


class TestAuto:
    def test_no_config(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["auto"])
        assert result.exit_code != 0
        assert "colonyos init" in result.output

    def test_propose_only_mode(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)

        fake_result = PhaseResult(
            phase=Phase.CEO,
            success=True,
            cost_usd=0.01,
            duration_ms=100,
            session_id="s",
            artifacts={"result": "### Feature Request\nBuild webhooks."},
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", return_value=("Build webhooks.", fake_result)):
            result = runner.invoke(app, ["auto", "--propose-only"])

        assert result.exit_code == 0
        assert "Propose-only mode" in result.output

    def test_no_confirm_triggers_pipeline(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)

        fake_ceo_result = PhaseResult(
            phase=Phase.CEO, success=True, cost_usd=0.01,
            duration_ms=100, session_id="s",
            artifacts={"result": "### Feature Request\nBuild webhooks."},
        )
        fake_log = RunLog(
            run_id="run-test",
            prompt="Build webhooks.",
            status=RunStatus.COMPLETED,
            phases=[],
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", return_value=("Build webhooks.", fake_ceo_result)), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log):
            result = runner.invoke(app, ["auto", "--no-confirm"])

        assert result.exit_code == 0
        assert "completed" in result.output

    def test_auto_approve_config_skips_confirmation(self, runner: CliRunner, tmp_path: Path):
        config = _make_config(tmp_path)
        config.auto_approve = True
        save_config(tmp_path, config)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)

        fake_ceo_result = PhaseResult(
            phase=Phase.CEO, success=True, cost_usd=0.01,
            duration_ms=100, session_id="s",
            artifacts={"result": "### Feature Request\nBuild webhooks."},
        )
        fake_log = RunLog(
            run_id="run-test", prompt="Build webhooks.",
            status=RunStatus.COMPLETED, phases=[],
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", return_value=("Build webhooks.", fake_ceo_result)), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log):
            result = runner.invoke(app, ["auto"])

        assert result.exit_code == 0
        assert "completed" in result.output
        assert "Proceed with this feature?" not in result.output

    def test_auto_approve_false_prompts_user(self, runner: CliRunner, tmp_path: Path):
        config = _make_config(tmp_path)
        config.auto_approve = False
        save_config(tmp_path, config)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)

        fake_result = PhaseResult(
            phase=Phase.CEO, success=True, cost_usd=0.01,
            duration_ms=100, session_id="s",
            artifacts={"result": "### Feature Request\nBuild webhooks."},
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", return_value=("Build webhooks.", fake_result)):
            result = runner.invoke(app, ["auto"], input="n\n")

        assert "Proceed with this feature?" in result.output

    def test_user_rejects_proposal(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)

        fake_result = PhaseResult(
            phase=Phase.CEO, success=True, cost_usd=0.01,
            duration_ms=100, session_id="s",
            artifacts={"result": "### Feature Request\nBuild webhooks."},
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", return_value=("Build webhooks.", fake_result)):
            result = runner.invoke(app, ["auto"], input="n\n")

        assert result.exit_code == 0
        assert "rejected" in result.output.lower()

    def test_ceo_failure_continues_in_loop(self, runner: CliRunner, tmp_path: Path):
        """CEO failure in a loop iteration logs the failure and continues."""
        _make_config(tmp_path)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)

        fake_fail = PhaseResult(
            phase=Phase.CEO, success=False, error="Budget exceeded",
        )
        fake_ok = PhaseResult(
            phase=Phase.CEO, success=True, cost_usd=0.01,
            duration_ms=100, session_id="s",
            artifacts={"result": "### Feature Request\nBuild webhooks."},
        )
        fake_log = RunLog(
            run_id="run-test", prompt="Build webhooks.",
            status=RunStatus.COMPLETED, phases=[],
            total_cost_usd=0.01,
        )

        calls = iter([("", fake_fail), ("Build webhooks.", fake_ok)])

        # Patch _compute_elapsed_hours to return 0 so time cap doesn't fire
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", side_effect=lambda *a, **k: next(calls)), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log), \
             patch("colonyos.cli._compute_elapsed_hours", return_value=0.0):
            result = runner.invoke(app, ["auto", "--no-confirm", "--loop", "2"])

        assert result.exit_code == 0
        assert "failed" in result.output.lower()


class TestInitWithPacks:
    def test_init_with_prebuilt_pack(self, runner: CliRunner, tmp_path: Path):
        """E2E: colonyos init selecting a prebuilt pack produces correct config."""
        # Simulate: project info, then pack selection (1=startup), confirm pack,
        # no custom additions, then model/budget defaults
        user_input = "\n".join([
            "TestProject",           # project name
            "A test project",        # description
            "Python/FastAPI",        # stack
            "1",                     # select pack 1 (Startup Team)
            "y",                     # confirm pack
            "n",                     # no custom additions
            "",                      # vision (skip)
            "sonnet",                # model
            "5.0",                   # budget per phase
            "15.0",                  # budget per run
        ])

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.doctor.subprocess.run", return_value=MagicMock(returncode=0)), \
             patch("colonyos.doctor.sys.version_info", type("V", (), {"major": 3, "minor": 12})()):
            result = runner.invoke(app, ["init"], input=user_input)

        assert result.exit_code == 0, result.output
        assert "Config saved" in result.output

        config_path = tmp_path / ".colonyos" / "config.yaml"
        assert config_path.exists()

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        saved_personas = raw.get("personas", [])
        startup_pack = PACKS[0]

        assert len(saved_personas) == len(startup_pack.personas)
        assert saved_personas[0]["role"] == startup_pack.personas[0].role


class TestResumeFlag:
    """Task 5.1: --resume CLI tests."""

    def test_resume_with_prompt_errors(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["run", "--resume", "some-id", "Add feature"])
        assert result.exit_code != 0
        assert "cannot be combined" in result.output.lower()

    def test_resume_with_plan_only_errors(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["run", "--resume", "some-id", "--plan-only"])
        assert result.exit_code != 0
        assert "cannot be combined" in result.output.lower()

    def test_resume_with_nonexistent_run_id_errors(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        (tmp_path / ".colonyos" / "runs").mkdir(parents=True, exist_ok=True)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["run", "--resume", "nonexistent-id"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_resume_invokes_orchestrator(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        # Create a failed run log
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / "cOS_prds").mkdir(parents=True, exist_ok=True)
        (tmp_path / "cOS_tasks").mkdir(parents=True, exist_ok=True)
        (tmp_path / "cOS_prds" / "prd.md").write_text("# PRD", encoding="utf-8")
        (tmp_path / "cOS_tasks" / "tasks.md").write_text("# Tasks", encoding="utf-8")

        run_data = {
            "run_id": "test-resume-id", "prompt": "Add feature",
            "status": "failed", "total_cost_usd": 0.01,
            "started_at": "2026-01-01T00:00:00", "finished_at": "2026-01-01T00:01:00",
            "branch_name": "colonyos/add_feature",
            "prd_rel": "cOS_prds/prd.md", "task_rel": "cOS_tasks/tasks.md",
            "last_successful_phase": "plan",
            "phases": [{"phase": "plan", "success": True, "cost_usd": 0.01,
                        "duration_ms": 100, "session_id": "s", "error": None}],
        }
        (runs_dir / "test-resume-id.json").write_text(
            json.dumps(run_data), encoding="utf-8"
        )

        fake_log = RunLog(
            run_id="test-resume-id", prompt="Add feature",
            status=RunStatus.COMPLETED, phases=[],
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.orchestrator.subprocess.run",
                   return_value=MagicMock(stdout="  colonyos/add_feature\n")), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log) as mock_orch:
            result = runner.invoke(app, ["run", "--resume", "test-resume-id"])

        assert result.exit_code == 0
        assert mock_orch.call_count == 1
        call_kwargs = mock_orch.call_args.kwargs
        assert call_kwargs["resume_from"] is not None
        assert call_kwargs["resume_from"].last_successful_phase == "plan"


class TestStatusResumable:
    """Task 6.1: [resumable] tag in status output."""

    def test_resumable_shown_for_eligible_failed_run(self, runner: CliRunner, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "r1.json").write_text(json.dumps({
            "run_id": "r1", "prompt": "test", "status": "failed",
            "total_cost_usd": 0.01,
            "branch_name": "feat/x", "prd_rel": "cOS_prds/prd.md",
            "task_rel": "cOS_tasks/tasks.md",
            "phases": [{"phase": "plan", "success": True, "cost_usd": 0.01,
                        "duration_ms": 100, "session_id": "s", "error": None}],
        }), encoding="utf-8")

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "[resumable]" in result.output

    def test_resumable_not_shown_for_old_log_without_fields(self, runner: CliRunner, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "r2.json").write_text(json.dumps({
            "run_id": "r2", "prompt": "test", "status": "failed",
            "total_cost_usd": 0.01,
            "phases": [{"phase": "plan", "success": True, "cost_usd": 0.01,
                        "duration_ms": 100, "session_id": "s", "error": None}],
        }), encoding="utf-8")

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "[resumable]" not in result.output

    def test_resumable_not_shown_for_completed_run(self, runner: CliRunner, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "r3.json").write_text(json.dumps({
            "run_id": "r3", "prompt": "test", "status": "completed",
            "total_cost_usd": 0.01,
            "branch_name": "feat/x", "prd_rel": "cOS_prds/prd.md",
            "task_rel": "cOS_tasks/tasks.md",
            "phases": [{"phase": "plan", "success": True, "cost_usd": 0.01,
                        "duration_ms": 100, "session_id": "s", "error": None}],
        }), encoding="utf-8")

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "[resumable]" not in result.output

    def test_resumable_not_shown_for_failed_run_with_no_success_phases(
        self, runner: CliRunner, tmp_path: Path
    ):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "r4.json").write_text(json.dumps({
            "run_id": "r4", "prompt": "test", "status": "failed",
            "total_cost_usd": 0.0,
            "branch_name": "feat/x", "prd_rel": "cOS_prds/prd.md",
            "task_rel": "cOS_tasks/tasks.md",
            "phases": [{"phase": "plan", "success": False, "cost_usd": 0.01,
                        "duration_ms": 100, "session_id": "s", "error": "err"}],
        }), encoding="utf-8")

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "[resumable]" not in result.output


class TestDoctor:
    """Task 1.1: Tests for the `colonyos doctor` command."""

    def test_all_checks_pass(self, runner: CliRunner, tmp_path: Path):
        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("model: sonnet\n", encoding="utf-8")

        def fake_subprocess(cmd, **kw):
            return MagicMock(returncode=0, stdout="ok")

        fake_vi = type("V", (), {"major": 3, "minor": 12})()

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.doctor.subprocess.run", side_effect=fake_subprocess), \
             patch("colonyos.doctor.sys.version_info", fake_vi):
            result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0

    def test_missing_claude_fails(self, runner: CliRunner, tmp_path: Path):
        def fake_subprocess(cmd, **kw):
            if cmd[0] == "claude":
                raise FileNotFoundError("not found")
            return MagicMock(returncode=0, stdout="ok")

        fake_vi = type("V", (), {"major": 3, "minor": 12})()

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.doctor.subprocess.run", side_effect=fake_subprocess), \
             patch("colonyos.doctor.sys.version_info", fake_vi):
            result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 1

    def test_missing_gh_auth_fails(self, runner: CliRunner, tmp_path: Path):
        def fake_subprocess(cmd, **kw):
            if cmd[0] == "gh":
                return MagicMock(returncode=1, stdout="", stderr="not logged in")
            return MagicMock(returncode=0, stdout="ok")

        fake_vi = type("V", (), {"major": 3, "minor": 12})()

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.doctor.subprocess.run", side_effect=fake_subprocess), \
             patch("colonyos.doctor.sys.version_info", fake_vi):
            result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 1

    def test_output_shows_checkmarks(self, runner: CliRunner, tmp_path: Path):
        def fake_subprocess(cmd, **kw):
            return MagicMock(returncode=0, stdout="ok")

        fake_vi = type("V", (), {"major": 3, "minor": 12})()

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.doctor.subprocess.run", side_effect=fake_subprocess), \
             patch("colonyos.doctor.sys.version_info", fake_vi):
            result = runner.invoke(app, ["doctor"])

        assert "✓" in result.output

    def test_python_version_too_old(self, runner: CliRunner, tmp_path: Path):
        def fake_subprocess(cmd, **kw):
            return MagicMock(returncode=0, stdout="ok")

        fake_vi = type("V", (), {"major": 3, "minor": 9})()

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.doctor.subprocess.run", side_effect=fake_subprocess), \
             patch("colonyos.doctor.sys.version_info", fake_vi):
            result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 1
        assert "✗" in result.output

    def test_no_config_shows_warning(self, runner: CliRunner, tmp_path: Path):
        """Doctor reports missing config but doesn't fail on it alone."""
        def fake_subprocess(cmd, **kw):
            return MagicMock(returncode=0, stdout="ok")

        fake_vi = type("V", (), {"major": 3, "minor": 12})()

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.doctor.subprocess.run", side_effect=fake_subprocess), \
             patch("colonyos.doctor.sys.version_info", fake_vi):
            result = runner.invoke(app, ["doctor"])

        assert "config" in result.output.lower()


class TestAutoLoopCap:
    """Task 5.1: Tests for raised loop cap and new flags."""

    def test_loop_above_old_cap_accepted(self, runner: CliRunner, tmp_path: Path):
        """--loop 20 should NOT be rejected (old cap was 10)."""
        _make_config(tmp_path)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)

        fake_ceo_result = PhaseResult(
            phase=Phase.CEO, success=True, cost_usd=0.01,
            duration_ms=100, session_id="s",
            artifacts={"result": "### Feature Request\nBuild webhooks."},
        )
        fake_log = RunLog(
            run_id="run-test", prompt="Build webhooks.",
            status=RunStatus.COMPLETED, phases=[],
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", return_value=("Build webhooks.", fake_ceo_result)), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log):
            result = runner.invoke(app, ["auto", "--no-confirm", "--loop", "20"])

        assert result.exit_code == 0

    def test_max_hours_flag_accepted(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)

        fake_ceo_result = PhaseResult(
            phase=Phase.CEO, success=True, cost_usd=0.01,
            duration_ms=100, session_id="s",
            artifacts={"result": "### Feature Request\nBuild webhooks."},
        )
        fake_log = RunLog(
            run_id="run-test", prompt="Build webhooks.",
            status=RunStatus.COMPLETED, phases=[],
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", return_value=("Build webhooks.", fake_ceo_result)), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log):
            result = runner.invoke(app, ["auto", "--no-confirm", "--max-hours", "2.0"])

        assert result.exit_code == 0

    def test_max_budget_flag_accepted(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)

        fake_ceo_result = PhaseResult(
            phase=Phase.CEO, success=True, cost_usd=0.01,
            duration_ms=100, session_id="s",
            artifacts={"result": "### Feature Request\nBuild webhooks."},
        )
        fake_log = RunLog(
            run_id="run-test", prompt="Build webhooks.",
            status=RunStatus.COMPLETED, phases=[],
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", return_value=("Build webhooks.", fake_ceo_result)), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log):
            result = runner.invoke(app, ["auto", "--no-confirm", "--max-budget", "100.0"])

        assert result.exit_code == 0

    def test_time_cap_exits_gracefully(self, runner: CliRunner, tmp_path: Path):
        """If max-hours is already exceeded, loop exits gracefully."""
        _make_config(tmp_path)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)

        fake_ceo_result = PhaseResult(
            phase=Phase.CEO, success=True, cost_usd=0.01,
            duration_ms=100, session_id="s",
            artifacts={"result": "### Feature Request\nBuild webhooks."},
        )
        fake_log = RunLog(
            run_id="run-test", prompt="Build webhooks.",
            status=RunStatus.COMPLETED, phases=[],
            total_cost_usd=0.01,
        )

        call_count = 0

        def mock_run_ceo(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return ("Build webhooks.", fake_ceo_result)

        # Mock _compute_elapsed_hours to return a value beyond the cap
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", side_effect=mock_run_ceo), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log), \
             patch("colonyos.cli._compute_elapsed_hours", return_value=999.0):
            result = runner.invoke(app, [
                "auto", "--no-confirm", "--loop", "5", "--max-hours", "0.001",
            ])

        # Should have exited after first iteration due to time cap
        assert "time limit" in result.output.lower() or "duration" in result.output.lower()

    def test_budget_cap_exits_gracefully(self, runner: CliRunner, tmp_path: Path):
        """If max-budget is hit, loop exits gracefully."""
        _make_config(tmp_path)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)

        fake_ceo_result = PhaseResult(
            phase=Phase.CEO, success=True, cost_usd=5.0,
            duration_ms=100, session_id="s",
            artifacts={"result": "### Feature Request\nBuild webhooks."},
        )
        fake_log = RunLog(
            run_id="run-test", prompt="Build webhooks.",
            status=RunStatus.COMPLETED, phases=[],
            total_cost_usd=5.0,
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", return_value=("Build webhooks.", fake_ceo_result)), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log), \
             patch("colonyos.cli._compute_elapsed_hours", return_value=0.0):
            result = runner.invoke(app, [
                "auto", "--no-confirm", "--loop", "5", "--max-budget", "1.0",
            ])

        assert "budget" in result.output.lower()

    def test_continue_on_failure(self, runner: CliRunner, tmp_path: Path):
        """When a single iteration fails, loop continues."""
        _make_config(tmp_path)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)

        fake_ceo_result = PhaseResult(
            phase=Phase.CEO, success=True, cost_usd=0.01,
            duration_ms=100, session_id="s",
            artifacts={"result": "### Feature Request\nBuild webhooks."},
        )
        fake_log_fail = RunLog(
            run_id="run-fail", prompt="Build webhooks.",
            status=RunStatus.FAILED, phases=[],
            total_cost_usd=0.01,
        )
        fake_log_ok = RunLog(
            run_id="run-ok", prompt="Build webhooks.",
            status=RunStatus.COMPLETED, phases=[],
            total_cost_usd=0.01,
        )

        call_count = 0

        def mock_orchestrator(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return fake_log_fail
            return fake_log_ok

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", return_value=("Build webhooks.", fake_ceo_result)), \
             patch("colonyos.cli.run_orchestrator", side_effect=mock_orchestrator), \
             patch("colonyos.cli._compute_elapsed_hours", return_value=0.0):
            result = runner.invoke(app, [
                "auto", "--no-confirm", "--loop", "2",
            ])

        # Both iterations should have run
        assert call_count == 2

    def test_loop_state_file_created(self, runner: CliRunner, tmp_path: Path):
        """Loop state file is created during auto loop."""
        _make_config(tmp_path)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)

        fake_ceo_result = PhaseResult(
            phase=Phase.CEO, success=True, cost_usd=0.01,
            duration_ms=100, session_id="s",
            artifacts={"result": "### Feature Request\nBuild webhooks."},
        )
        fake_log = RunLog(
            run_id="run-test", prompt="Build webhooks.",
            status=RunStatus.COMPLETED, phases=[],
            total_cost_usd=0.01,
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", return_value=("Build webhooks.", fake_ceo_result)), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log), \
             patch("colonyos.cli._compute_elapsed_hours", return_value=0.0):
            result = runner.invoke(app, [
                "auto", "--no-confirm", "--loop", "2",
            ])

        assert result.exit_code == 0
        # Check loop state was persisted
        runs_dir = tmp_path / ".colonyos" / "runs"
        loop_files = list(runs_dir.glob("loop_state_*.json"))
        assert len(loop_files) >= 1

    def test_resume_loop_flag(self, runner: CliRunner, tmp_path: Path):
        """--resume-loop reads existing loop state and continues."""
        _make_config(tmp_path)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)

        # Create a loop state file with timezone-aware ISO timestamp
        loop_state = {
            "loop_id": "loop-test-123",
            "current_iteration": 2,
            "total_iterations": 5,
            "aggregate_cost_usd": 0.05,
            "start_time_iso": "2026-01-01T00:00:00+00:00",
            "completed_run_ids": ["run-1", "run-2"],
            "failed_run_ids": [],
            "status": "interrupted",
        }
        (runs_dir / "loop_state_loop-test-123.json").write_text(
            json.dumps(loop_state), encoding="utf-8"
        )

        fake_ceo_result = PhaseResult(
            phase=Phase.CEO, success=True, cost_usd=0.01,
            duration_ms=100, session_id="s",
            artifacts={"result": "### Feature Request\nBuild webhooks."},
        )
        fake_log = RunLog(
            run_id="run-test", prompt="Build webhooks.",
            status=RunStatus.COMPLETED, phases=[],
            total_cost_usd=0.01,
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", return_value=("Build webhooks.", fake_ceo_result)), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log), \
             patch("colonyos.cli._compute_elapsed_hours", return_value=0.0):
            result = runner.invoke(app, [
                "auto", "--no-confirm", "--resume-loop",
            ])

        assert result.exit_code == 0
        assert "resum" in result.output.lower()


class TestStatusLoopAwareness:
    """Task 7.1: Enhanced status shows loop-level summaries."""

    def test_shows_loop_summary_when_state_exists(self, runner: CliRunner, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)

        loop_state = {
            "loop_id": "loop-abc",
            "current_iteration": 3,
            "total_iterations": 10,
            "aggregate_cost_usd": 1.50,
            "start_time_iso": "2026-01-01T00:00:00+00:00",
            "completed_run_ids": ["r1", "r2", "r3"],
            "failed_run_ids": [],
            "status": "completed",
        }
        (runs_dir / "loop_state_loop-abc.json").write_text(
            json.dumps(loop_state), encoding="utf-8"
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "loop" in result.output.lower()
        assert "3" in result.output

    def test_heartbeat_staleness_warning(self, runner: CliRunner, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)

        # Create a stale heartbeat file
        heartbeat = runs_dir / "heartbeat"
        heartbeat.write_text("", encoding="utf-8")

        # Create loop state with status "running"
        loop_state = {
            "loop_id": "loop-stale",
            "current_iteration": 1,
            "total_iterations": 10,
            "aggregate_cost_usd": 0.0,
            "start_time_iso": "2026-01-01T00:00:00+00:00",
            "completed_run_ids": [],
            "failed_run_ids": [],
            "status": "running",
        }
        (runs_dir / "loop_state_loop-stale.json").write_text(
            json.dumps(loop_state), encoding="utf-8"
        )

        # Set mtime to 10 minutes ago
        old_time = time.time() - 600
        os.utime(heartbeat, (old_time, old_time))

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "stale" in result.output.lower() or "warning" in result.output.lower()


class TestLoopStateAtomicWrite:
    """Tests for atomic loop state persistence."""

    def test_save_creates_valid_json(self, tmp_path: Path):
        state = LoopState(
            loop_id="loop-atomic-test",
            total_iterations=5,
            current_iteration=2,
            aggregate_cost_usd=1.0,
        )
        path = _save_loop_state(tmp_path, state)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["loop_id"] == "loop-atomic-test"
        assert data["current_iteration"] == 2

    def test_save_no_temp_files_left_behind(self, tmp_path: Path):
        state = LoopState(loop_id="loop-clean", total_iterations=3)
        _save_loop_state(tmp_path, state)
        runs_dir = tmp_path / ".colonyos" / "runs"
        tmp_files = list(runs_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_save_cleans_up_on_replace_failure(self, tmp_path: Path):
        """When os.replace raises, the temp file should be removed and fd closed."""
        state = LoopState(loop_id="loop-fail", total_iterations=3)
        with patch("os.replace", side_effect=OSError("mock replace error")):
            with pytest.raises(OSError, match="mock replace error"):
                _save_loop_state(tmp_path, state)
        runs_dir = tmp_path / ".colonyos" / "runs"
        tmp_files = list(runs_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_save_cleans_up_on_write_failure(self, tmp_path: Path):
        """When os.write raises, the fd should still be closed and temp removed."""
        state = LoopState(loop_id="loop-write-fail", total_iterations=3)
        with patch("os.write", side_effect=OSError("mock write error")):
            with pytest.raises(OSError, match="mock write error"):
                _save_loop_state(tmp_path, state)
        runs_dir = tmp_path / ".colonyos" / "runs"
        tmp_files = list(runs_dir.glob("*.tmp"))
        assert len(tmp_files) == 0


class TestLoadLatestLoopStateMtime:
    """Tests for mtime-based loop state loading."""

    def test_loads_most_recently_modified(self, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)

        # Write older file
        older = runs_dir / "loop_state_loop-aaa.json"
        older.write_text(json.dumps({
            "loop_id": "loop-aaa", "current_iteration": 1,
            "total_iterations": 5, "status": "interrupted",
            "start_time_iso": "2026-01-01T00:00:00+00:00",
        }), encoding="utf-8")

        # Make it old
        old_time = time.time() - 3600
        os.utime(older, (old_time, old_time))

        # Write newer file
        newer = runs_dir / "loop_state_loop-zzz.json"
        newer.write_text(json.dumps({
            "loop_id": "loop-zzz", "current_iteration": 3,
            "total_iterations": 10, "status": "running",
            "start_time_iso": "2026-01-01T00:00:00+00:00",
        }), encoding="utf-8")

        result = _load_latest_loop_state(tmp_path)
        assert result is not None
        assert result.loop_id == "loop-zzz"


class TestLoopStatusEnum:
    """Tests for LoopStatus enum usage."""

    def test_loop_state_uses_enum(self):
        state = LoopState(loop_id="test", total_iterations=1)
        assert state.status == LoopStatus.RUNNING
        assert isinstance(state.status, LoopStatus)

    def test_to_dict_serializes_enum_value(self):
        state = LoopState(
            loop_id="test", total_iterations=1,
            status=LoopStatus.INTERRUPTED,
        )
        d = state.to_dict()
        assert d["status"] == "interrupted"

    def test_from_dict_deserializes_to_enum(self):
        d = {
            "loop_id": "test", "total_iterations": 1,
            "status": "completed",
            "start_time_iso": "2026-01-01T00:00:00+00:00",
        }
        state = LoopState.from_dict(d)
        assert state.status == LoopStatus.COMPLETED
        assert isinstance(state.status, LoopStatus)

    def test_from_dict_unknown_status_defaults_to_running(self):
        d = {
            "loop_id": "test", "total_iterations": 1,
            "status": "unknown_status",
            "start_time_iso": "2026-01-01T00:00:00+00:00",
        }
        state = LoopState.from_dict(d)
        assert state.status == LoopStatus.RUNNING

    def test_from_dict_unknown_status_logs_warning(self):
        import logging
        d = {
            "loop_id": "test", "total_iterations": 1,
            "status": "garbage",
            "start_time_iso": "2026-01-01T00:00:00+00:00",
        }
        with patch("colonyos.models.logger") as mock_logger:
            LoopState.from_dict(d)
            mock_logger.warning.assert_called_once()
            assert "garbage" in str(mock_logger.warning.call_args)


class TestComputeElapsedHours:
    """Tests for _compute_elapsed_hours without the dead session_start parameter."""

    def test_computes_from_loop_state_start_time(self):
        start = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        state = LoopState(
            loop_id="test-elapsed",
            total_iterations=5,
            start_time_iso=start,
        )
        hours = _compute_elapsed_hours(state)
        assert 1.9 < hours < 2.1

    def test_recent_start_returns_near_zero(self):
        start = datetime.now(timezone.utc).isoformat()
        state = LoopState(
            loop_id="test-recent",
            total_iterations=5,
            start_time_iso=start,
        )
        hours = _compute_elapsed_hours(state)
        assert hours < 0.01


class TestResumeLoopTimeCap:
    """Tests that --resume-loop uses total elapsed time, not just session time."""

    def test_resume_accounts_for_prior_session_time(self, runner: CliRunner, tmp_path: Path):
        """Resumed loop that started 10 hours ago with a 1-hour cap should stop immediately."""
        _make_config(tmp_path)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)

        # Loop started 10 hours ago
        old_start = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        loop_state = {
            "loop_id": "loop-old",
            "current_iteration": 2,
            "total_iterations": 10,
            "aggregate_cost_usd": 0.05,
            "start_time_iso": old_start,
            "completed_run_ids": ["run-1", "run-2"],
            "failed_run_ids": [],
            "status": "interrupted",
        }
        (runs_dir / "loop_state_loop-old.json").write_text(
            json.dumps(loop_state), encoding="utf-8"
        )

        # With a 1-hour cap, the resumed loop should stop immediately
        # because ~10 hours have already elapsed
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, [
                "auto", "--no-confirm", "--resume-loop", "--max-hours", "1.0",
            ])

        assert "time limit" in result.output.lower() or "duration" in result.output.lower()


class TestInitDoctorPreCheck:
    """Tests that colonyos init runs doctor checks as first action (FR-4)."""

    def test_init_runs_doctor_by_default(self, runner: CliRunner, tmp_path: Path):
        """colonyos init should run doctor checks and refuse on hard failures."""
        def fake_checks(repo_root):
            return [
                ("Python ≥ 3.11", True, ""),
                ("Claude Code CLI", False, "Install claude"),
                ("Git", True, ""),
                ("GitHub CLI auth", True, ""),
                ("ColonyOS config", False, "Run init"),
            ]

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.doctor.run_doctor_checks", fake_checks):
            result = runner.invoke(app, ["init", "--quick", "--name", "Test"])

        # Should fail because Claude Code CLI is missing
        assert result.exit_code != 0
        assert "prerequisite" in result.output.lower()

    def test_init_proceeds_when_doctor_passes(self, runner: CliRunner, tmp_path: Path):
        """colonyos init should proceed normally when all hard prereqs pass."""
        def fake_checks(repo_root):
            return [
                ("Python ≥ 3.11", True, ""),
                ("Claude Code CLI", True, ""),
                ("Git", True, ""),
                ("GitHub CLI auth", True, ""),
                ("ColonyOS config", False, "Run init"),
            ]

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.doctor.run_doctor_checks", fake_checks):
            result = runner.invoke(app, [
                "init", "--quick", "--name", "Test",
                "--description", "test", "--stack", "Python",
            ])

        assert result.exit_code == 0
        assert "Config saved" in result.output


class TestHeartbeatInAutoLoop:
    """Tests that the auto loop touches the heartbeat at each iteration."""

    def test_heartbeat_touched_during_iteration(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)

        fake_ceo_result = PhaseResult(
            phase=Phase.CEO, success=True, cost_usd=0.01,
            duration_ms=100, session_id="s",
            artifacts={"result": "### Feature Request\nBuild webhooks."},
        )
        fake_log = RunLog(
            run_id="run-test", prompt="Build webhooks.",
            status=RunStatus.COMPLETED, phases=[],
            total_cost_usd=0.01,
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", return_value=("Build webhooks.", fake_ceo_result)), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log), \
             patch("colonyos.cli._compute_elapsed_hours", return_value=0.0):
            result = runner.invoke(app, ["auto", "--no-confirm"])

        assert result.exit_code == 0
        heartbeat = tmp_path / ".colonyos" / "runs" / "heartbeat"
        assert heartbeat.exists()


# ===========================================================================
# Tests for standalone review command
# ===========================================================================


class TestReviewCommand:
    """Tests for the `colonyos review` CLI command."""

    def test_branch_argument_required(self, runner: CliRunner):
        result = runner.invoke(app, ["review"])
        assert result.exit_code != 0

    def test_no_config_shows_init_message(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["review", "my-branch"])
        assert result.exit_code != 0
        assert "colonyos init" in result.output

    def test_preflight_error_exits_1(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.detect_base_branch", return_value="main"), \
             patch("colonyos.cli.validate_review_preconditions", return_value="Branch not found"):
            result = runner.invoke(app, ["review", "missing-branch"])

        assert result.exit_code != 0
        assert "Branch not found" in result.output

    def test_exit_0_when_all_approve(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        (tmp_path / "cOS_reviews").mkdir(exist_ok=True)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.detect_base_branch", return_value="main"), \
             patch("colonyos.cli.validate_review_preconditions", return_value=None), \
             patch("colonyos.cli.run_review_loop", return_value="GO"):
            result = runner.invoke(app, ["review", "feat/test", "-q"])

        assert result.exit_code == 0

    def test_exit_1_when_nogo(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        (tmp_path / "cOS_reviews").mkdir(exist_ok=True)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.detect_base_branch", return_value="main"), \
             patch("colonyos.cli.validate_review_preconditions", return_value=None), \
             patch("colonyos.cli.run_review_loop", return_value="NO-GO"):
            result = runner.invoke(app, ["review", "feat/test", "-q"])

        assert result.exit_code != 0

    def test_exit_1_when_request_changes(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        (tmp_path / "cOS_reviews").mkdir(exist_ok=True)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.detect_base_branch", return_value="main"), \
             patch("colonyos.cli.validate_review_preconditions", return_value=None), \
             patch("colonyos.cli.run_review_loop", return_value="request-changes"):
            result = runner.invoke(app, ["review", "feat/test", "-q"])

        assert result.exit_code != 0

    def test_prd_option_accepted(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        (tmp_path / "cOS_reviews").mkdir(exist_ok=True)
        prd_file = tmp_path / "cOS_prds" / "test_prd.md"
        (tmp_path / "cOS_prds").mkdir(exist_ok=True)
        prd_file.write_text("# Test PRD")

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.detect_base_branch", return_value="main"), \
             patch("colonyos.cli.validate_review_preconditions", return_value=None), \
             patch("colonyos.cli.run_review_loop", return_value="GO") as mock_loop:
            result = runner.invoke(app, [
                "review", "feat/test", "--prd", str(prd_file), "-q"
            ])

        assert result.exit_code == 0
        # Verify prd_rel was passed to run_review_loop
        call_kwargs = mock_loop.call_args
        assert call_kwargs.kwargs.get("prd_rel") == str(prd_file)

    def test_fix_flag_passed_through(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        (tmp_path / "cOS_reviews").mkdir(exist_ok=True)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.detect_base_branch", return_value="main"), \
             patch("colonyos.cli.validate_review_preconditions", return_value=None), \
             patch("colonyos.cli.run_review_loop", return_value="GO") as mock_loop:
            result = runner.invoke(app, ["review", "feat/test", "--fix", "-q"])

        assert result.exit_code == 0
        call_kwargs = mock_loop.call_args
        assert call_kwargs.kwargs.get("enable_fix") is True

    def test_base_option_passed_through(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        (tmp_path / "cOS_reviews").mkdir(exist_ok=True)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.detect_base_branch", return_value="develop") as mock_detect, \
             patch("colonyos.cli.validate_review_preconditions", return_value=None), \
             patch("colonyos.cli.run_review_loop", return_value="GO"):
            result = runner.invoke(app, ["review", "feat/test", "--base", "develop", "-q"])

        assert result.exit_code == 0
        mock_detect.assert_called_once_with(tmp_path, override="develop")

    def test_run_log_saved(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        (tmp_path / "cOS_reviews").mkdir(exist_ok=True)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.detect_base_branch", return_value="main"), \
             patch("colonyos.cli.validate_review_preconditions", return_value=None), \
             patch("colonyos.cli.run_review_loop", return_value="GO"):
            result = runner.invoke(app, ["review", "feat/test", "-q"])

        assert result.exit_code == 0
        runs_dir = tmp_path / ".colonyos" / "runs"
        run_files = list(runs_dir.glob("review-*.json"))
        assert len(run_files) == 1

    def test_review_in_welcome_banner(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, [])
        assert "review" in result.output.lower()
