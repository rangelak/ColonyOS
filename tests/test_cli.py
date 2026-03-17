import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml
from click.testing import CliRunner

from colonyos.cli import app
from colonyos.config import ColonyConfig, save_config
from colonyos.models import Persona, Phase, PhaseResult, ProjectInfo, RunLog, RunStatus
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

    def test_ceo_failure_exits(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        (tmp_path / "cOS_proposals").mkdir(exist_ok=True)

        fake_result = PhaseResult(
            phase=Phase.CEO, success=False, error="Budget exceeded",
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ceo", return_value=("", fake_result)):
            result = runner.invoke(app, ["auto"])

        assert result.exit_code != 0
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

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
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
        assert call_kwargs["resume_from"]["last_successful_phase"] == "plan"


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
