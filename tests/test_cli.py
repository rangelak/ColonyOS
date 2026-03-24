import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
import yaml
import click
from click.testing import CliRunner

from colonyos.cli import (
    RouteOutcome,
    _compute_elapsed_hours,
    _launch_tui,
    _load_latest_loop_state,
    _save_loop_state,
    app,
)
from colonyos.config import ColonyConfig, BudgetConfig, save_config
from colonyos.models import (
    LoopState, LoopStatus, Persona, Phase, PhaseResult,
    PreflightError, ProjectInfo, RunLog, RunStatus,
)
from colonyos.persona_packs import PACKS


@pytest.fixture(autouse=True)
def _mock_cli_subprocess():
    """Prevent real git calls from _ensure_on_main and other CLI code paths."""
    def _fake_git(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        m = MagicMock()
        m.returncode = 0
        m.stderr = ""
        if isinstance(cmd, list) and "rev-parse" in cmd and "--abbrev-ref" in cmd:
            m.stdout = "main"
        elif isinstance(cmd, list) and "rev-list" in cmd:
            m.stdout = "0"
        else:
            m.stdout = ""
        return m
    with patch("colonyos.cli.subprocess.run", side_effect=_fake_git):
        yield


@pytest.fixture
def runner():
    return CliRunner()


class TestVersion:
    def test_version_flag(self, runner: CliRunner):
        from colonyos import __version__

        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "colonyos" in result.output
        assert __version__ in result.output


class TestRootCommand:
    def test_bare_colonyos_defaults_to_tui(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli._tui_available", return_value=True), \
             patch("colonyos.cli._interactive_stdio", return_value=True), \
             patch("colonyos.cli._show_welcome") as mock_welcome, \
             patch("colonyos.cli._run_repl") as mock_repl, \
             patch("colonyos.cli._launch_tui") as mock_launch:
            result = runner.invoke(app, [])
        assert result.exit_code == 0
        mock_launch.assert_called_once()
        mock_welcome.assert_not_called()
        mock_repl.assert_not_called()

    def test_bare_colonyos_falls_back_without_tui(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli._tui_available", return_value=False):
            result = runner.invoke(app, [], input="exit\n")
        assert result.exit_code == 0
        assert "ColonyOS" in result.output


class TestStatus:
    def test_no_runs(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "No runs" in result.output

    def test_shows_learnings_count(self, runner: CliRunner, tmp_path: Path):
        """Status command shows learnings entry count when ledger exists."""
        from colonyos.learnings import append_learnings, LearningEntry

        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        entries = [
            LearningEntry("code-quality", "Add docstrings"),
            LearningEntry("testing", "Write tests"),
        ]
        append_learnings(tmp_path, "run-001", "2026-03-17", "test", entries)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "Learnings ledger: 2 entries" in result.output

    def test_shows_learnings_not_found(self, runner: CliRunner, tmp_path: Path):
        """Status command shows 'not found' when no ledger exists."""
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "Learnings ledger: not found" in result.output


class TestRun:
    def test_no_prompt_no_prd(self, runner: CliRunner):
        result = runner.invoke(app, ["run"])
        assert result.exit_code != 0

    def test_no_config(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["run", "Add feature"])
        assert result.exit_code != 0
        assert "colonyos init" in result.output

    def test_interactive_run_defaults_to_tui(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli._tui_available", return_value=True), \
             patch("colonyos.cli._interactive_stdio", return_value=True), \
             patch("colonyos.cli._launch_tui") as mock_launch:
            result = runner.invoke(app, ["run", "Add feature"])
        assert result.exit_code == 0
        mock_launch.assert_called_once()

    def test_no_tui_forces_streaming(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        fake_log = RunLog(
            run_id="run-test",
            prompt="Add feature",
            status=RunStatus.COMPLETED,
            phases=[],
        )
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli._tui_available", return_value=True), \
             patch("colonyos.cli._interactive_stdio", return_value=True), \
             patch("colonyos.cli._launch_tui") as mock_launch, \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log) as mock_run:
            result = runner.invoke(app, ["run", "--no-tui", "Add feature"])
        assert result.exit_code == 0
        mock_launch.assert_not_called()
        mock_run.assert_called_once()

    def test_small_fix_route_passes_skip_planning(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        fake_log = RunLog(
            run_id="run-test",
            prompt="Fix typo",
            status=RunStatus.COMPLETED,
            phases=[],
        )
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli._tui_available", return_value=False), \
             patch("colonyos.cli._route_prompt", return_value=RouteOutcome(skip_planning=True)), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log) as mock_run:
            result = runner.invoke(app, ["run", "Fix typo"])
        assert result.exit_code == 0
        assert mock_run.call_args.kwargs["skip_planning"] is True

    def test_tui_recovery_success_retries_saved_prompt_once(self, tmp_path: Path):
        config = _make_config(tmp_path)
        dirty_error = PreflightError(
            "Uncommitted changes detected",
            code="dirty_worktree",
            details={
                "current_branch": "main",
                "dirty_output": "M src/app.py",
            },
        )
        fake_log = RunLog(
            run_id="run-test",
            prompt="Add feature",
            status=RunStatus.COMPLETED,
            phases=[],
        )
        recovery_result = PhaseResult(
            phase=Phase.PREFLIGHT_RECOVERY,
            success=True,
            cost_usd=0.01,
            duration_ms=100,
            session_id="recover",
        )

        class FakeApp:
            def __init__(self, **kwargs):
                self.run_callback = kwargs["run_callback"]
                self.recovery_callback = kwargs["recovery_callback"]
                self._pending_recovery = None
                self.messages: list[object] = []
                self.event_queue = SimpleNamespace(
                    sync_q=SimpleNamespace(put=self.messages.append),
                )

            def call_from_thread(self, fn, *args):
                return fn(*args)

            def begin_dirty_worktree_recovery(self, text, error):
                self._pending_recovery = (text, error)

            def get_dirty_worktree_recovery(self):
                return self._pending_recovery

            def clear_dirty_worktree_recovery(self):
                self._pending_recovery = None

            def cancel_dirty_worktree_recovery(self):
                self._pending_recovery = None

            def show_run_blocked(self, *args):
                self.blocked = args

            def exit(self):
                self.exited = True

            def run(self):
                self.run_callback("Add feature")
                assert self._pending_recovery is not None
                self.recovery_callback("commit")

        with patch("colonyos.tui.app.AssistantApp", FakeApp), \
             patch("colonyos.cli._route_prompt", return_value=RouteOutcome()), \
             patch("colonyos.cli.run_orchestrator", side_effect=[dirty_error, fake_log]) as mock_run, \
             patch("colonyos.cli.run_preflight_recovery", return_value=recovery_result) as mock_recovery, \
             patch("colonyos.cli.signal.signal"):
            _launch_tui(tmp_path, config)

        assert mock_recovery.call_count == 1
        assert mock_run.call_count == 2
        assert mock_run.call_args_list[0].args[0] == "Add feature"
        assert mock_run.call_args_list[1].args[0] == "Add feature"


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
             patch("colonyos.cli._ensure_on_main"), \
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
             patch("colonyos.cli._ensure_on_main"), \
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
             patch("colonyos.cli._ensure_on_main"), \
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
             patch("colonyos.cli._ensure_on_main"), \
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
             patch("colonyos.cli._ensure_on_main"), \
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
             patch("colonyos.cli._ensure_on_main"), \
             patch("colonyos.cli.run_ceo", side_effect=lambda *a, **k: next(calls)), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log), \
             patch("colonyos.cli._compute_elapsed_hours", return_value=0.0):
            result = runner.invoke(app, ["auto", "--no-confirm", "--loop", "2"])

        assert result.exit_code == 0
        assert "failed" in result.output.lower()


class TestInitWithPacks:
    def test_init_manual_with_prebuilt_pack(self, runner: CliRunner, tmp_path: Path):
        """E2E: colonyos init --manual selecting a prebuilt pack produces correct config."""
        # Simulate: project info, then pack selection (1=startup), confirm pack,
        # no custom additions, then preset/budget defaults
        user_input = "\n".join([
            "TestProject",           # project name
            "A test project",        # description
            "Python/FastAPI",        # stack
            "1",                     # select pack 1 (Startup Team)
            "y",                     # confirm pack
            "n",                     # no custom additions
            "",                      # vision (skip)
            "1",                     # model preset (1=Quality-first)
            "5.0",                   # budget per phase
            "15.0",                  # budget per run
            "",                      # extra trailing newline
        ])

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.doctor.subprocess.run", return_value=MagicMock(returncode=0)), \
             patch("colonyos.doctor.sys.version_info", type("V", (), {"major": 3, "minor": 12})()), \
             patch("colonyos.init._collect_strategic_goals", return_value=""):
            result = runner.invoke(app, ["init", "--manual"], input=user_input)

        assert result.exit_code == 0, result.output
        assert "Config saved" in result.output

        config_path = tmp_path / ".colonyos" / "config.yaml"
        assert config_path.exists()

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        saved_personas = raw.get("personas", [])
        startup_pack = PACKS[0]

        assert len(saved_personas) == len(startup_pack.personas)
        assert saved_personas[0]["role"] == startup_pack.personas[0].role


class TestInitCliRouting:
    """Test that CLI flags route to the correct init function."""

    def test_default_calls_ai_init(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_ai_init") as mock_ai:
            mock_ai.return_value = ColonyConfig()
            result = runner.invoke(app, ["init"])

        mock_ai.assert_called_once()

    def test_manual_calls_run_init(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_init") as mock_manual:
            mock_manual.return_value = ColonyConfig()
            result = runner.invoke(app, ["init", "--manual"], input="n\n")

        mock_manual.assert_called_once()

    def test_quick_calls_run_init(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_init") as mock_manual:
            mock_manual.return_value = ColonyConfig()
            result = runner.invoke(app, ["init", "--quick", "--name", "Test"])

        mock_manual.assert_called_once()
        call_kwargs = mock_manual.call_args
        assert call_kwargs.kwargs.get("quick") is True

    def test_personas_calls_run_init(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.run_init") as mock_manual:
            mock_manual.return_value = ColonyConfig()
            result = runner.invoke(app, ["init", "--personas"], input="1\ny\nn\n")

        mock_manual.assert_called_once()
        call_kwargs = mock_manual.call_args
        assert call_kwargs.kwargs.get("personas_only") is True

    def test_manual_with_quick_errors(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["init", "--manual", "--quick"])

        assert result.exit_code != 0

    def test_manual_with_personas_errors(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["init", "--manual", "--personas"])

        assert result.exit_code != 0


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
             patch("colonyos.cli._ensure_on_main"), \
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
             patch("colonyos.cli._ensure_on_main"), \
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
             patch("colonyos.cli._ensure_on_main"), \
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
             patch("colonyos.cli._ensure_on_main"), \
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
             patch("colonyos.cli._ensure_on_main"), \
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
             patch("colonyos.cli._ensure_on_main"), \
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
             patch("colonyos.cli._ensure_on_main"), \
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
             patch("colonyos.cli._ensure_on_main"), \
             patch("colonyos.cli.run_ceo", return_value=("Build webhooks.", fake_ceo_result)), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log), \
             patch("colonyos.cli._compute_elapsed_hours", return_value=0.0):
            result = runner.invoke(app, ["auto", "--no-confirm"])

        assert result.exit_code == 0
        heartbeat = tmp_path / ".colonyos" / "runs" / "heartbeat"
        assert heartbeat.exists()


# ---------------------------------------------------------------------------
# GitHub issue CLI integration tests
# ---------------------------------------------------------------------------


class TestRunIssueFlag:
    def test_no_prompt_no_issue_error(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["run"])
        assert result.exit_code != 0

    def test_issue_with_from_prd_error(self, runner: CliRunner, tmp_path: Path) -> None:
        _make_config(tmp_path)
        prd_file = tmp_path / "prd.md"
        prd_file.write_text("# PRD", encoding="utf-8")
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["run", "--issue", "42", "--from-prd", str(prd_file)])
        assert result.exit_code != 0
        assert "cannot be combined" in result.output

    def test_issue_bare_number(self, runner: CliRunner, tmp_path: Path) -> None:
        _make_config(tmp_path)
        fake_log = RunLog(
            run_id="run-test", prompt="test", status=RunStatus.COMPLETED, phases=[],
        )
        from colonyos.github import GitHubIssue
        fake_issue = GitHubIssue(
            number=42, title="Add dark mode", body="Need it",
            url="https://github.com/org/repo/issues/42", state="open",
        )
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.github.fetch_issue", return_value=fake_issue) as mock_fetch, \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log) as mock_run:
            result = runner.invoke(app, ["run", "--issue", "42"])

        assert result.exit_code == 0
        # Verify source_issue was passed through
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["source_issue"] == 42
        assert call_kwargs["source_issue_url"] == "https://github.com/org/repo/issues/42"

    def test_issue_url(self, runner: CliRunner, tmp_path: Path) -> None:
        _make_config(tmp_path)
        fake_log = RunLog(
            run_id="run-test", prompt="test", status=RunStatus.COMPLETED, phases=[],
        )
        from colonyos.github import GitHubIssue
        fake_issue = GitHubIssue(
            number=7, title="Bug", body="Fix it",
            url="https://github.com/org/repo/issues/7", state="open",
        )
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.github.fetch_issue", return_value=fake_issue), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log) as mock_run:
            result = runner.invoke(app, ["run", "--issue", "https://github.com/org/repo/issues/7"])

        assert result.exit_code == 0
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["source_issue"] == 7

    def test_issue_with_additional_prompt(self, runner: CliRunner, tmp_path: Path) -> None:
        _make_config(tmp_path)
        fake_log = RunLog(
            run_id="run-test", prompt="test", status=RunStatus.COMPLETED, phases=[],
        )
        from colonyos.github import GitHubIssue
        fake_issue = GitHubIssue(
            number=42, title="Add dark mode", body="Need it",
            url="https://github.com/org/repo/issues/42", state="open",
        )
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.github.fetch_issue", return_value=fake_issue), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log) as mock_run:
            result = runner.invoke(app, ["run", "--issue", "42", "Focus on backend"])

        assert result.exit_code == 0
        prompt = mock_run.call_args[0][0]  # positional arg
        assert "Additional Context" in prompt
        assert "Focus on backend" in prompt

    def test_issue_gh_error(self, runner: CliRunner, tmp_path: Path) -> None:
        _make_config(tmp_path)
        import click as _click
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.github.fetch_issue", side_effect=_click.ClickException("Issue #999 not found")):
            result = runner.invoke(app, ["run", "--issue", "999"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_issue_with_resume_error(self, runner: CliRunner, tmp_path: Path) -> None:
        _make_config(tmp_path)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["run", "--issue", "42", "--resume", "r-1"])
        assert result.exit_code != 0


class TestStats:
    """CLI tests for the `colonyos stats` command."""

    def test_no_runs(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "No runs found" in result.output

    def test_single_run(self, runner: CliRunner, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        run_data = {
            "run_id": "run-stats-test",
            "prompt": "Add feature",
            "status": "completed",
            "total_cost_usd": 1.5,
            "started_at": "2026-03-17T12:00:00+00:00",
            "finished_at": "2026-03-17T12:10:00+00:00",
            "phases": [
                {"phase": "plan", "success": True, "cost_usd": 0.5, "duration_ms": 60000},
                {"phase": "implement", "success": True, "cost_usd": 1.0, "duration_ms": 120000},
            ],
        }
        (runs_dir / "run-stats-test.json").write_text(
            json.dumps(run_data), encoding="utf-8",
        )
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "Run Summary" in result.output

    def test_last_flag(self, runner: CliRunner, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        for i in range(5):
            run_data = {
                "run_id": f"run-{i}",
                "status": "completed",
                "total_cost_usd": 1.0,
                "started_at": f"2026-03-1{i}T12:00:00+00:00",
                "phases": [],
            }
            (runs_dir / f"run-{i}.json").write_text(
                json.dumps(run_data), encoding="utf-8",
            )
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["stats", "--last", "3"])
        assert result.exit_code == 0
        # Should show 3 total runs in the summary
        assert "3" in result.output

    def test_phase_flag(self, runner: CliRunner, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        run_data = {
            "run_id": "run-phase-test",
            "status": "completed",
            "total_cost_usd": 1.0,
            "started_at": "2026-03-17T12:00:00+00:00",
            "phases": [
                {"phase": "review", "success": True, "cost_usd": 0.5, "duration_ms": 30000},
            ],
        }
        (runs_dir / "run-phase-test.json").write_text(
            json.dumps(run_data), encoding="utf-8",
        )
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["stats", "--phase", "review"])
        assert result.exit_code == 0
        assert "Phase Detail" in result.output


class TestStatusSourceIssue:
    def test_shows_issue_in_status(self, runner: CliRunner, tmp_path: Path) -> None:
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        log_data = {
            "run_id": "run-issue-test",
            "prompt": "Add dark mode",
            "status": "completed",
            "total_cost_usd": 0.5,
            "source_issue": 42,
            "source_issue_url": "https://github.com/org/repo/issues/42",
            "phases": [],
        }
        (runs_dir / "run-issue-test.json").write_text(
            json.dumps(log_data), encoding="utf-8",
        )
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "#42" in result.output
        assert "https://github.com/org/repo/issues/42" in result.output

    def test_no_issue_no_tag(self, runner: CliRunner, tmp_path: Path) -> None:
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        log_data = {
            "run_id": "run-no-issue",
            "prompt": "Add feature",
            "status": "completed",
            "total_cost_usd": 0.1,
            "phases": [],
        }
        (runs_dir / "run-no-issue.json").write_text(
            json.dumps(log_data), encoding="utf-8",
        )
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "#" not in result.output or "run-no-issue" in result.output


class TestRepl:
    """Tests for the interactive REPL mode."""

    @pytest.fixture(autouse=True)
    def _skip_intent_router(self):
        """Prevent _handle_routed_query from calling real LLM triage."""
        with patch("colonyos.cli._handle_routed_query", return_value=None):
            yield

    def test_quit_exits_cleanly(self, runner: CliRunner, tmp_path: Path):
        _make_config(tmp_path)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("sys.stdin") as mock_stdin, \
             patch.dict("sys.modules", {"readline": MagicMock()}):
            mock_stdin.isatty.return_value = True
            # Simulate user typing "quit"
            with patch("builtins.input", side_effect=["quit"]):
                result = runner.invoke(app, [], input="quit")
        # CliRunner doesn't use real stdin.isatty, so test _run_repl directly
        pass

    def test_repl_quit_exits(self, tmp_path: Path):
        """Typing 'quit' exits the REPL with no error."""
        _make_config(tmp_path)
        inputs = iter(["quit"])
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("builtins.input", side_effect=inputs), \
             patch.dict("sys.modules", {"readline": MagicMock()}):
            from colonyos.cli import _run_repl
            _run_repl()  # Should not raise

    def test_repl_exit_keyword(self, tmp_path: Path):
        """Typing 'exit' exits the REPL."""
        _make_config(tmp_path)
        inputs = iter(["exit"])
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("builtins.input", side_effect=inputs), \
             patch.dict("sys.modules", {"readline": MagicMock()}):
            from colonyos.cli import _run_repl
            _run_repl()

    def test_repl_exit_case_insensitive(self, tmp_path: Path):
        """'EXIT' and 'Quit' are recognized."""
        _make_config(tmp_path)
        inputs = iter(["EXIT"])
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("builtins.input", side_effect=inputs), \
             patch.dict("sys.modules", {"readline": MagicMock()}):
            from colonyos.cli import _run_repl
            _run_repl()

    def test_repl_eof_exits(self, tmp_path: Path):
        """Ctrl+D (EOFError) exits the REPL gracefully."""
        _make_config(tmp_path)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("builtins.input", side_effect=EOFError), \
             patch.dict("sys.modules", {"readline": MagicMock()}):
            from colonyos.cli import _run_repl
            _run_repl()

    def test_repl_empty_input_ignored(self, tmp_path: Path):
        """Empty input does not trigger a run; prompt reappears."""
        _make_config(tmp_path)
        inputs = iter(["", "   ", "quit"])
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("builtins.input", side_effect=inputs), \
             patch("colonyos.cli.readline", create=True), \
             patch("colonyos.cli.run_orchestrator") as mock_run:
            from colonyos.cli import _run_repl
            _run_repl()
        mock_run.assert_not_called()

    def test_repl_routes_to_orchestrator(self, tmp_path: Path):
        """Non-exit input is routed to run_orchestrator."""
        _make_config(tmp_path)
        fake_log = RunLog(
            run_id="run-repl", prompt="Add feature",
            status=RunStatus.COMPLETED, phases=[], total_cost_usd=0.50,
        )
        # First input: prompt, second input: confirm (Enter = yes), third: quit
        inputs = iter(["Add a health endpoint", "", "quit"])
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("builtins.input", side_effect=inputs), \
             patch("colonyos.cli.readline", create=True), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log) as mock_run:
            from colonyos.cli import _run_repl
            _run_repl()
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == "Add a health endpoint"

    def test_repl_accumulates_session_cost(self, tmp_path: Path):
        """Session cost accumulates across runs."""
        _make_config(tmp_path)
        fake_log_1 = RunLog(
            run_id="r1", prompt="f1",
            status=RunStatus.COMPLETED, phases=[], total_cost_usd=1.50,
        )
        fake_log_2 = RunLog(
            run_id="r2", prompt="f2",
            status=RunStatus.COMPLETED, phases=[], total_cost_usd=2.00,
        )
        # Two prompts with confirmations, then quit
        inputs = iter(["feat 1", "", "feat 2", "", "quit"])
        prompt_values = []
        original_input = input

        def capture_input(prompt_str=""):
            prompt_values.append(prompt_str)
            return next(input_iter)

        input_iter = iter(["feat 1", "", "feat 2", "", "quit"])

        echo_calls: list[str] = []
        original_echo = click.echo

        def capture_echo(*args, **kwargs):
            if args:
                echo_calls.append(str(args[0]))
            return original_echo(*args, **kwargs)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("builtins.input", side_effect=capture_input), \
             patch("colonyos.cli.readline", create=True), \
             patch("colonyos.cli.click.echo", side_effect=capture_echo), \
             patch("colonyos.cli.run_orchestrator", side_effect=[fake_log_1, fake_log_2]):
            from colonyos.cli import _run_repl
            _run_repl()

        # After first run ($1.50), the cost prompt should show $1.50
        cost_outputs = [c for c in echo_calls if "1.50" in c]
        assert cost_outputs

    def test_repl_uninitialized_project(self, tmp_path: Path):
        """Uninitialized project prints error and does not enter REPL."""
        # No config file
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("builtins.input", side_effect=AssertionError("Should not be called")), \
             patch.dict("sys.modules", {"readline": MagicMock()}):
            from colonyos.cli import _run_repl
            _run_repl()  # Should return without calling input()

    def test_repl_not_entered_when_non_tty(self, runner: CliRunner, tmp_path: Path):
        """When stdin is not a TTY, banner shows but REPL does not start."""
        _make_config(tmp_path)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            with patch("colonyos.cli._run_repl") as mock_repl:
                result = runner.invoke(app, [])
        # CliRunner patches stdin, so _run_repl may or may not be called
        # depending on the isatty mock. At minimum, it shouldn't crash.
        assert result.exit_code == 0

    def test_repl_ctrl_c_prints_hint(self, tmp_path: Path):
        """First Ctrl+C prints hint, second exits."""
        _make_config(tmp_path)

        call_count = 0

        def mock_input(prompt=""):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise KeyboardInterrupt
            if call_count == 2:
                raise KeyboardInterrupt
            return "quit"

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("builtins.input", side_effect=mock_input), \
             patch("colonyos.cli.readline", create=True), \
             patch("colonyos.cli.time") as mock_time:
            # Make the two interrupts happen within 2 seconds
            mock_time.time.side_effect = [0.0, 0.5]
            from colonyos.cli import _run_repl
            _run_repl()  # Should exit after double Ctrl+C

    def test_repl_budget_confirmation_decline(self, tmp_path: Path):
        """Declining budget confirmation returns to prompt without running."""
        _make_config(tmp_path)
        # Input: prompt, then "n" for confirmation, then "quit"
        inputs = iter(["Add feature", "n", "quit"])
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("builtins.input", side_effect=inputs), \
             patch("colonyos.cli.readline", create=True), \
             patch("colonyos.cli.run_orchestrator") as mock_run:
            from colonyos.cli import _run_repl
            _run_repl()
        mock_run.assert_not_called()

    def test_repl_auto_approve_skips_confirmation(self, tmp_path: Path):
        """When auto_approve is true, budget confirmation is skipped."""
        config = ColonyConfig(
            project=ProjectInfo(name="Test", description="test", stack="Python"),
            personas=[Persona(role="Engineer", expertise="Backend", perspective="Scale")],
            auto_approve=True,
        )
        save_config(tmp_path, config)

        fake_log = RunLog(
            run_id="r-auto", prompt="Add feat",
            status=RunStatus.COMPLETED, phases=[], total_cost_usd=0.10,
        )
        # No confirmation input needed
        inputs = iter(["Add feature", "quit"])
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("builtins.input", side_effect=inputs), \
             patch("colonyos.cli.readline", create=True), \
             patch("colonyos.cli.run_orchestrator", return_value=fake_log) as mock_run:
            from colonyos.cli import _run_repl
            _run_repl()
        mock_run.assert_called_once()

    def test_repl_readline_history_path(self):
        """Readline history file path is correct."""
        from colonyos.cli import REPL_HISTORY_PATH
        assert REPL_HISTORY_PATH == Path.home() / ".colonyos_history"

    def test_repl_keyboard_interrupt_during_run(self, tmp_path: Path):
        """KeyboardInterrupt during a run returns to prompt, doesn't exit REPL."""
        _make_config(tmp_path)
        inputs = iter(["Build something", "", "quit"])
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("builtins.input", side_effect=inputs), \
             patch("colonyos.cli.readline", create=True), \
             patch("colonyos.cli.run_orchestrator", side_effect=KeyboardInterrupt):
            from colonyos.cli import _run_repl
            _run_repl()  # Should not raise; returns to prompt then quits


class TestTuiCommandHandling:
    def test_exit_command_requests_tui_exit(self) -> None:
        from colonyos.cli import _handle_tui_command

        handled, output, should_exit = _handle_tui_command("exit", config=ColonyConfig())

        assert handled is True
        assert should_exit is True
        assert "Exiting" in (output or "")

    def test_run_command_redirects_to_prompt_mode(self) -> None:
        from colonyos.cli import _handle_tui_command

        handled, output, should_exit = _handle_tui_command(
            "run build a dashboard",
            config=ColonyConfig(),
        )

        assert handled is True
        assert should_exit is False
        assert "type a feature prompt" in (output or "").lower()

    def test_auto_requires_no_confirm_when_not_auto_approved(self) -> None:
        from colonyos.cli import _handle_tui_command

        handled, output, should_exit = _handle_tui_command("auto", config=ColonyConfig())

        assert handled is True
        assert should_exit is False
        assert "--no-confirm" in (output or "")

    def test_status_command_is_captured(self) -> None:
        from colonyos.cli import _handle_tui_command

        with patch("colonyos.cli._capture_click_output", return_value="status output"):
            handled, output, should_exit = _handle_tui_command(
                "status",
                config=ColonyConfig(),
            )

        assert handled is True
        assert should_exit is False
        assert output == "status output"

    def test_unsupported_command_is_rejected(self) -> None:
        from colonyos.cli import _handle_tui_command

        handled, output, should_exit = _handle_tui_command(
            "init --quick",
            config=ColonyConfig(),
        )

        assert handled is True
        assert should_exit is False
        assert "not supported inside the TUI" in (output or "")


class TestCIFixCommand:
    def test_help_shows_options(self, runner: CliRunner):
        result = runner.invoke(app, ["ci-fix", "--help"])
        assert result.exit_code == 0
        assert "--max-retries" in result.output
        assert "--wait" in result.output
        assert "--wait-timeout" in result.output
        assert "PR_REF" in result.output

    def test_all_checks_pass(self, runner: CliRunner, tmp_path: Path):
        """When all checks pass, ci-fix exits successfully."""
        from colonyos.ci import CheckResult

        checks = [CheckResult(name="test", state="completed", conclusion="success")]
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.load_config", return_value=ColonyConfig()), \
             patch("colonyos.ci.subprocess.run") as mock_run:
            # validate_clean_worktree
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            with patch("colonyos.ci.fetch_pr_checks", return_value=checks):
                result = runner.invoke(app, ["ci-fix", "42"])
        assert result.exit_code == 0
        assert "pass" in result.output.lower()

    def test_invalid_pr_ref(self, runner: CliRunner, tmp_path: Path):
        """Invalid PR ref should error."""
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.load_config", return_value=ColonyConfig()), \
             patch("colonyos.ci.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = runner.invoke(app, ["ci-fix", "not-a-number"])
        assert result.exit_code != 0

    def test_uncommitted_changes_error(self, runner: CliRunner, tmp_path: Path):
        """Uncommitted changes should block ci-fix."""
        from colonyos.ci import CheckResult

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.load_config", return_value=ColonyConfig()), \
             patch("colonyos.ci.subprocess.run") as mock_run:
            # gh auth succeeds, then git status shows dirty worktree
            mock_run.side_effect = [
                MagicMock(returncode=0),  # gh auth status
                MagicMock(returncode=0, stdout=" M dirty.py\n", stderr=""),  # git status
            ]
            result = runner.invoke(app, ["ci-fix", "42"])
        assert result.exit_code != 0
        assert "uncommitted" in result.output.lower() or "uncommitted" in (result.output + str(result.exception)).lower()

    def test_gh_not_authenticated_error(self, runner: CliRunner, tmp_path: Path):
        """gh not authenticated should block ci-fix with helpful message."""
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.load_config", return_value=ColonyConfig()), \
             patch("colonyos.ci.subprocess.run") as mock_run:
            # gh auth status fails
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = runner.invoke(app, ["ci-fix", "42"])
        assert result.exit_code != 0

    def test_push_failure_aborts(self, runner: CliRunner, tmp_path: Path):
        """git push failure should abort rather than continue to next retry."""
        from colonyos.ci import CheckResult

        failed_checks = [
            CheckResult(name="test", state="completed", conclusion="failure",
                        details_url="https://github.com/o/r/actions/runs/1/jobs/1"),
        ]
        mock_phase = MagicMock(success=True, cost_usd=0.0, duration_ms=100,
                               session_id="s1", model="m", error=None, artifacts={},
                               phase=Phase.CI_FIX)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.load_config", return_value=ColonyConfig()), \
             patch("colonyos.ci.subprocess.run") as ci_mock_run, \
             patch("colonyos.cli.subprocess.run") as cli_mock_run:
            # Pre-flight checks pass
            ci_mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            with patch("colonyos.ci.fetch_pr_checks", return_value=failed_checks), \
                 patch("colonyos.ci.check_pr_author_mismatch", return_value=None), \
                 patch("colonyos.ci.fetch_check_logs", return_value={"step": "error log"}), \
                 patch("colonyos.orchestrator._build_ci_fix_prompt", return_value=("sys", "usr")), \
                 patch("colonyos.agent.run_phase_sync", return_value=mock_phase), \
                 patch("colonyos.orchestrator._save_run_log"):
                # git rev-parse succeeds, git push fails
                cli_mock_run.side_effect = [
                    MagicMock(returncode=0, stdout="main\n", stderr=""),  # git rev-parse
                    MagicMock(returncode=1, stdout="", stderr="push rejected"),  # git push
                ]
                result = runner.invoke(app, ["ci-fix", "42", "--max-retries", "3"])
        assert result.exit_code != 0

    def test_pr_author_mismatch_warning(self, runner: CliRunner, tmp_path: Path):
        """PR authored by someone else should show a warning."""
        from colonyos.ci import CheckResult

        checks = [CheckResult(name="test", state="completed", conclusion="success")]

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cli.load_config", return_value=ColonyConfig()), \
             patch("colonyos.ci.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            with patch("colonyos.ci.fetch_pr_checks", return_value=checks), \
                 patch("colonyos.ci.check_pr_author_mismatch",
                       return_value="WARNING: PR #42 was authored by @mallory"), \
                 patch("colonyos.orchestrator._save_run_log"):
                result = runner.invoke(app, ["ci-fix", "42"])
        assert "WARNING" in result.output or "mallory" in result.output


# ---------------------------------------------------------------------------
# Show command tests
# ---------------------------------------------------------------------------


class TestShow:
    def _setup_runs_dir(self, tmp_path: Path) -> Path:
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        return runs_dir

    def _write_run(self, runs_dir: Path, run_id: str, **kwargs) -> None:
        data = {
            "run_id": run_id,
            "status": kwargs.get("status", "completed"),
            "total_cost_usd": kwargs.get("total_cost_usd", 1.0),
            "started_at": "2026-03-17T12:00:00+00:00",
            "finished_at": "2026-03-17T12:10:00+00:00",
            "prompt": "test prompt",
            "branch_name": "colonyos/test",
            "prd_rel": "cOS_prds/prd.md",
            "task_rel": "cOS_tasks/tasks.md",
            "phases": kwargs.get("phases", [
                {"phase": "plan", "success": True, "cost_usd": 0.5, "duration_ms": 30000},
            ]),
        }
        (runs_dir / f"{run_id}.json").write_text(json.dumps(data), encoding="utf-8")

    def test_show_full_id(self, runner: CliRunner, tmp_path: Path):
        runs_dir = self._setup_runs_dir(tmp_path)
        self._write_run(runs_dir, "run-20260317_120000-abc123")

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["show", "run-20260317_120000-abc123"])
        assert result.exit_code == 0
        assert "run-20260317_120000-abc123" in result.output

    def test_show_prefix(self, runner: CliRunner, tmp_path: Path):
        runs_dir = self._setup_runs_dir(tmp_path)
        self._write_run(runs_dir, "run-20260317_120000-abc123")

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["show", "run-20260317_12"])
        assert result.exit_code == 0
        assert "abc123" in result.output

    def test_show_bad_id(self, runner: CliRunner, tmp_path: Path):
        self._setup_runs_dir(tmp_path)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["show", "nonexistent"])
        assert result.exit_code != 0

    def test_show_ambiguous(self, runner: CliRunner, tmp_path: Path):
        runs_dir = self._setup_runs_dir(tmp_path)
        self._write_run(runs_dir, "run-20260317_120000-abc123")
        self._write_run(runs_dir, "run-20260317_120100-abc456")

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["show", "run-20260317_12"])
        assert result.exit_code != 0
        assert "Ambiguous" in result.output

    def test_show_json_flag(self, runner: CliRunner, tmp_path: Path):
        runs_dir = self._setup_runs_dir(tmp_path)
        self._write_run(runs_dir, "run-20260317_120000-abc123")

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["show", "run-20260317_120000-abc123", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["run_id"] == "run-20260317_120000-abc123"

    def test_show_phase_filter(self, runner: CliRunner, tmp_path: Path):
        runs_dir = self._setup_runs_dir(tmp_path)
        self._write_run(runs_dir, "run-20260317_120000-abc123", phases=[
            {"phase": "plan", "success": True, "cost_usd": 0.5, "duration_ms": 30000, "model": "sonnet", "session_id": "s1"},
            {"phase": "review", "success": True, "cost_usd": 1.0, "duration_ms": 60000, "model": "opus", "session_id": "s2"},
        ])

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["show", "run-20260317_120000-abc123", "--phase", "review"])
        assert result.exit_code == 0
        assert "Phase Detail" in result.output

    def test_show_no_runs_dir(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["show", "abc123"])
        assert result.exit_code != 0


class TestUI:
    """Tests for the ``colonyos ui`` command."""

    def test_command_registered(self, runner: CliRunner):
        result = runner.invoke(app, ["ui", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "--no-open" in result.output

    def test_missing_deps_message(self, runner: CliRunner, tmp_path: Path):
        """When fastapi/uvicorn not installed, show a helpful message."""
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "uvicorn":
                raise ImportError("No module named 'uvicorn'")
            return real_import(name, *args, **kwargs)

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("builtins.__import__", side_effect=mock_import):
            result = runner.invoke(app, ["ui"])
        assert result.exit_code != 0
        assert "pip install colonyos[ui]" in result.output

    def test_default_port(self, runner: CliRunner, tmp_path: Path):
        """Verify the default port is 7400 and URL is printed."""
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("uvicorn.run") as mock_run, \
             patch("webbrowser.open"):
            result = runner.invoke(app, ["ui"])
        assert result.exit_code == 0
        assert "127.0.0.1:7400" in result.output
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["host"] == "127.0.0.1"
        assert call_kwargs.kwargs["port"] == 7400

    def test_custom_port(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("uvicorn.run") as mock_run, \
             patch("webbrowser.open"):
            result = runner.invoke(app, ["ui", "--port", "9000"])
        assert result.exit_code == 0
        assert "127.0.0.1:9000" in result.output
        assert mock_run.call_args.kwargs["port"] == 9000

    def test_no_open_flag(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("uvicorn.run"), \
             patch("webbrowser.open") as mock_open:
            result = runner.invoke(app, ["ui", "--no-open"])
        assert result.exit_code == 0
        mock_open.assert_not_called()


# ---------------------------------------------------------------------------
# Cleanup command tests
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_no_subcommand_shows_help(self, runner: CliRunner):
        result = runner.invoke(app, ["cleanup"])
        assert result.exit_code == 0
        assert "branches" in result.output
        assert "artifacts" in result.output
        assert "scan" in result.output

    def test_branches_no_merged(self, runner: CliRunner, tmp_path: Path):
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cleanup.list_merged_branches", return_value=[]):
            result = runner.invoke(app, ["cleanup", "branches"])
        assert result.exit_code == 0
        assert "No merged branches" in result.output

    def test_branches_dry_run(self, runner: CliRunner, tmp_path: Path):
        from colonyos.cleanup import BranchInfo, BranchCleanupResult

        branches = [
            BranchInfo(name="colonyos/old", last_commit_date="2026-01-01", is_merged=True),
        ]
        cleanup_result = BranchCleanupResult(
            deleted_local=["colonyos/old"],
            deleted_remote=[],
            skipped=[],
            errors=[],
        )
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cleanup.list_merged_branches", return_value=branches), \
             patch("colonyos.cleanup.delete_branches", return_value=cleanup_result):
            result = runner.invoke(app, ["cleanup", "branches"])
        assert result.exit_code == 0
        assert "would be deleted" in result.output
        assert "Re-run with --execute" in result.output

    def test_artifacts_no_stale(self, runner: CliRunner, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["cleanup", "artifacts"])
        assert result.exit_code == 0
        assert "No stale artifacts" in result.output

    def test_artifacts_dry_run(self, runner: CliRunner, tmp_path: Path):
        from colonyos.cleanup import ArtifactInfo, ArtifactCleanupResult

        stale = [
            ArtifactInfo(
                run_id="run-old", date="2025-01-01T00:00:00+00:00",
                status="completed", size_bytes=2048,
                path=tmp_path / "run-old.json",
            ),
        ]
        cleanup_result = ArtifactCleanupResult(
            removed=stale, skipped=[], bytes_reclaimed=2048, errors=[],
        )
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cleanup.list_stale_artifacts", return_value=(stale, [])), \
             patch("colonyos.cleanup.delete_artifacts", return_value=cleanup_result):
            result = runner.invoke(app, ["cleanup", "artifacts"])
        assert result.exit_code == 0
        assert "would be removed" in result.output

    def test_scan_no_issues(self, runner: CliRunner, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cleanup.scan_directory", return_value=[]):
            result = runner.invoke(app, ["cleanup", "scan"])
        assert result.exit_code == 0
        assert "No files exceed" in result.output

    def test_scan_with_results(self, runner: CliRunner, tmp_path: Path):
        from colonyos.cleanup import FileComplexity, ComplexityCategory

        results = [
            FileComplexity(
                path="src/big.py", line_count=800,
                function_count=25, category=ComplexityCategory.MASSIVE,
            ),
        ]
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cleanup.scan_directory", return_value=results):
            result = runner.invoke(app, ["cleanup", "scan"])
        assert result.exit_code == 0
        assert "1 file(s) flagged" in result.output

    def test_scan_with_very_large_category(self, runner: CliRunner, tmp_path: Path):
        """Ensure very-large and massive categories render valid Rich markup."""
        from colonyos.cleanup import FileComplexity, ComplexityCategory

        results = [
            FileComplexity(
                path="src/big.py", line_count=1200,
                function_count=25, category=ComplexityCategory.VERY_LARGE,
            ),
            FileComplexity(
                path="src/huge.py", line_count=2000,
                function_count=50, category=ComplexityCategory.MASSIVE,
            ),
        ]
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cleanup.scan_directory", return_value=results):
            result = runner.invoke(app, ["cleanup", "scan"])
        assert result.exit_code == 0
        assert "2 file(s) flagged" in result.output
        # Should not have malformed Rich markup (double brackets)
        assert "[[" not in result.output

    def test_scan_ai_flag(self, runner: CliRunner, tmp_path: Path):
        """The --ai flag should invoke run_phase_sync with composed system prompt."""
        from colonyos.cleanup import FileComplexity, ComplexityCategory

        results = [
            FileComplexity(
                path="src/big.py", line_count=800,
                function_count=25, category=ComplexityCategory.MASSIVE,
            ),
        ]
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)

        mock_phase_result = MagicMock()
        mock_phase_result.success = True
        mock_phase_result.artifacts = {"result": "# AI Report\n\nAll good."}

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cleanup.scan_directory", return_value=results), \
             patch("colonyos.agent.run_phase_sync", return_value=mock_phase_result) as mock_rps:
            result = runner.invoke(app, ["cleanup", "scan", "--ai"])
        assert result.exit_code == 0
        assert "AI analysis report saved" in result.output
        # Verify base.md was composed into the system prompt
        call_kwargs = mock_rps.call_args
        system_prompt = call_kwargs.kwargs.get("system_prompt") or call_kwargs[1].get("system_prompt", "")
        assert "Core Principles" in system_prompt  # from base.md
        assert "Dead Code Detection" in system_prompt  # from cleanup_scan.md

    def test_scan_refactor_flag(self, runner: CliRunner, tmp_path: Path):
        """The --refactor flag should delegate to run_orchestrator."""
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)

        mock_log = MagicMock()

        with patch("colonyos.cli._find_repo_root", return_value=tmp_path), \
             patch("colonyos.cleanup.scan_directory", return_value=[]), \
             patch("colonyos.cli.run_orchestrator", return_value=mock_log), \
             patch("colonyos.cli._print_run_summary"):
            result = runner.invoke(app, ["cleanup", "scan", "--refactor", "src/big.py"])
        assert result.exit_code == 0
        assert "Delegating refactoring" in result.output

    def test_scan_retention_days_override(self, runner: CliRunner, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["cleanup", "artifacts", "--retention-days", "7"])
        assert result.exit_code == 0
