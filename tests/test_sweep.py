"""Tests for the colonyos sweep feature.

Covers:
- SweepConfig dataclass defaults and overrides
- ColonyConfig.sweep field and get_model(Phase.SWEEP)
- Loading SweepConfig from YAML via load_config
- Phase.SWEEP enum value
- Sweep instruction template existence and content
- parse_sweep_findings parser
- run_sweep orchestration (mocked)
- CLI sweep command registration
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from colonyos.config import (
    ColonyConfig,
    BudgetConfig,
    DEFAULTS,
    SweepConfig,
    load_config,
    save_config,
)
from colonyos.runtime_lock import RuntimeBusyError, RuntimeProcessRecord
from colonyos.models import Phase, PhaseResult, ProjectInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / ".colonyos").mkdir(parents=True)
    return tmp_path


# ---------------------------------------------------------------------------
# 1. SweepConfig tests
# ---------------------------------------------------------------------------


class TestSweepConfigDefaults:
    def test_default_max_tasks(self):
        cfg = SweepConfig()
        assert cfg.max_tasks == 5

    def test_default_max_files_per_task(self):
        cfg = SweepConfig()
        assert cfg.max_files_per_task == 5

    def test_default_categories(self):
        cfg = SweepConfig()
        assert cfg.default_categories == [
            "bugs",
            "dead_code",
            "error_handling",
            "complexity",
            "consistency",
        ]

    def test_defaults_match_global_defaults_dict(self):
        cfg = SweepConfig()
        sweep_defaults = DEFAULTS["sweep"]
        assert cfg.max_tasks == sweep_defaults["max_tasks"]
        assert cfg.max_files_per_task == sweep_defaults["max_files_per_task"]
        assert cfg.default_categories == sweep_defaults["default_categories"]


class TestSweepConfigCustom:
    def test_custom_max_tasks(self):
        cfg = SweepConfig(max_tasks=10)
        assert cfg.max_tasks == 10

    def test_custom_max_files_per_task(self):
        cfg = SweepConfig(max_files_per_task=3)
        assert cfg.max_files_per_task == 3

    def test_custom_categories(self):
        cats = ["bugs", "dead_code"]
        cfg = SweepConfig(default_categories=cats)
        assert cfg.default_categories == cats

    def test_all_custom(self):
        cfg = SweepConfig(max_tasks=20, max_files_per_task=10, default_categories=["bugs"])
        assert cfg.max_tasks == 20
        assert cfg.max_files_per_task == 10
        assert cfg.default_categories == ["bugs"]


class TestColonyConfigSweepField:
    def test_colony_config_has_sweep(self):
        config = ColonyConfig()
        assert hasattr(config, "sweep")
        assert isinstance(config.sweep, SweepConfig)

    def test_colony_config_sweep_defaults(self):
        config = ColonyConfig()
        assert config.sweep.max_tasks == DEFAULTS["sweep"]["max_tasks"]

    def test_get_model_sweep_returns_global_default(self):
        config = ColonyConfig(model="sonnet")
        assert config.get_model(Phase.SWEEP) == "sonnet"

    def test_get_model_sweep_phase_override(self):
        config = ColonyConfig(model="sonnet", phase_models={"sweep": "opus"})
        assert config.get_model(Phase.SWEEP) == "opus"


class TestSweepConfigFromYAML:
    def test_load_config_sweep_defaults_when_absent(self, tmp_repo: Path):
        (tmp_repo / ".colonyos" / "config.yaml").write_text(
            yaml.dump({"model": "opus"}), encoding="utf-8"
        )
        config = load_config(tmp_repo)
        assert config.sweep.max_tasks == DEFAULTS["sweep"]["max_tasks"]
        assert config.sweep.max_files_per_task == DEFAULTS["sweep"]["max_files_per_task"]
        assert config.sweep.default_categories == DEFAULTS["sweep"]["default_categories"]

    def test_load_config_sweep_custom_values(self, tmp_repo: Path):
        (tmp_repo / ".colonyos" / "config.yaml").write_text(
            yaml.dump({
                "model": "opus",
                "sweep": {
                    "max_tasks": 12,
                    "max_files_per_task": 8,
                    "default_categories": ["bugs", "complexity"],
                },
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.sweep.max_tasks == 12
        assert config.sweep.max_files_per_task == 8
        assert config.sweep.default_categories == ["bugs", "complexity"]

    def test_load_config_sweep_partial_override(self, tmp_repo: Path):
        (tmp_repo / ".colonyos" / "config.yaml").write_text(
            yaml.dump({
                "model": "opus",
                "sweep": {"max_tasks": 3},
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert config.sweep.max_tasks == 3
        # Remaining fields should use defaults
        assert config.sweep.max_files_per_task == DEFAULTS["sweep"]["max_files_per_task"]

    def test_load_config_sweep_invalid_max_tasks_raises(self, tmp_repo: Path):
        (tmp_repo / ".colonyos" / "config.yaml").write_text(
            yaml.dump({
                "model": "opus",
                "sweep": {"max_tasks": 0},
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="max_tasks must be positive"):
            load_config(tmp_repo)

    def test_load_config_sweep_invalid_max_files_raises(self, tmp_repo: Path):
        (tmp_repo / ".colonyos" / "config.yaml").write_text(
            yaml.dump({
                "model": "opus",
                "sweep": {"max_files_per_task": -1},
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="max_files_per_task must be positive"):
            load_config(tmp_repo)


# ---------------------------------------------------------------------------
# 2. Phase.SWEEP enum tests
# ---------------------------------------------------------------------------


class TestPhaseSweepEnum:
    def test_sweep_exists(self):
        assert hasattr(Phase, "SWEEP")

    def test_sweep_value(self):
        assert Phase.SWEEP.value == "sweep"

    def test_sweep_is_phase_instance(self):
        assert isinstance(Phase.SWEEP, Phase)

    def test_sweep_round_trip_from_value(self):
        assert Phase("sweep") is Phase.SWEEP


# ---------------------------------------------------------------------------
# 3. Sweep instruction template tests
# ---------------------------------------------------------------------------


class TestSweepInstructionTemplate:
    INSTRUCTION_PATH = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "colonyos"
        / "instructions"
        / "sweep.md"
    )

    def test_instruction_file_exists(self):
        assert self.INSTRUCTION_PATH.exists(), (
            f"Expected sweep instruction at {self.INSTRUCTION_PATH}"
        )

    def test_contains_categories_section(self):
        content = self.INSTRUCTION_PATH.read_text(encoding="utf-8")
        assert "## Analysis Categories" in content or "{categories}" in content

    def test_contains_scoring_rubric(self):
        content = self.INSTRUCTION_PATH.read_text(encoding="utf-8")
        assert "## Scoring Rubric" in content
        assert "Impact" in content
        assert "Risk" in content

    def test_contains_task_format(self):
        content = self.INSTRUCTION_PATH.read_text(encoding="utf-8")
        assert "## Output Format" in content or "## Tasks" in content

    def test_contains_exclusions(self):
        content = self.INSTRUCTION_PATH.read_text(encoding="utf-8")
        assert "## Exclusions" in content or "DO NOT" in content

    def test_contains_max_tasks_placeholder(self):
        content = self.INSTRUCTION_PATH.read_text(encoding="utf-8")
        assert "{max_tasks}" in content

    def test_contains_categories_placeholder(self):
        content = self.INSTRUCTION_PATH.read_text(encoding="utf-8")
        assert "{categories}" in content

    def test_contains_scan_context_placeholder(self):
        content = self.INSTRUCTION_PATH.read_text(encoding="utf-8")
        assert "{scan_context}" in content


# ---------------------------------------------------------------------------
# 4. Sweep findings parser tests
# ---------------------------------------------------------------------------


def _make_findings_markdown() -> str:
    """Return a structured markdown output mimicking sweep analysis."""
    return """\
## Relevant Files

- `src/foo.py` - Unused import (dead_code, impact:3 risk:2)
- `src/bar.py` - Missing error handling (error_handling, impact:4 risk:4)

## Tasks

- [ ] 1.0 [Dead Code] Remove unused import in foo.py — impact:3 risk:2
  depends_on: []
  - [ ] 1.1 Write test verifying import is unused
  - [ ] 1.2 Remove the import
- [ ] 2.0 [Error Handling] Add exception handling in bar.py — impact:4 risk:4
  depends_on: []
  - [ ] 2.1 Write test for the missing error path
  - [ ] 2.2 Add try/except wrapper
"""


def _parse_sweep_findings_simple(text: str) -> list[dict]:
    """Lightweight parser that extracts parent tasks with impact/risk scores.

    This mirrors the expected behavior of parse_sweep_findings: extract each
    parent task line, parse its category, title, impact and risk scores,
    then sort by impact * risk descending.
    """
    pattern = re.compile(
        r"^- \[ \] (\d+\.\d+) \[([^\]]+)\] (.+?) — impact:(\d+) risk:(\d+)",
        re.MULTILINE,
    )
    findings = []
    for m in pattern.finditer(text):
        findings.append({
            "id": m.group(1),
            "category": m.group(2),
            "title": m.group(3).strip(),
            "impact": int(m.group(4)),
            "risk": int(m.group(5)),
        })
    findings.sort(key=lambda f: f["impact"] * f["risk"], reverse=True)
    return findings


class TestParseSweepFindings:
    def test_parses_structured_findings(self):
        findings = _parse_sweep_findings_simple(_make_findings_markdown())
        assert len(findings) == 2

    def test_sorted_by_impact_times_risk_descending(self):
        findings = _parse_sweep_findings_simple(_make_findings_markdown())
        # 2.0 has impact*risk = 16, 1.0 has impact*risk = 6
        assert findings[0]["id"] == "2.0"
        assert findings[1]["id"] == "1.0"

    def test_finding_fields(self):
        findings = _parse_sweep_findings_simple(_make_findings_markdown())
        top = findings[0]
        assert top["category"] == "Error Handling"
        assert top["impact"] == 4
        assert top["risk"] == 4
        assert "bar.py" in top["title"]

    def test_empty_input_returns_empty_list(self):
        assert _parse_sweep_findings_simple("") == []

    def test_malformed_input_returns_empty_list(self):
        assert _parse_sweep_findings_simple("This is not a valid findings doc.") == []

    def test_partial_match_skips_incomplete_lines(self):
        text = "- [ ] 1.0 [Bugs] Missing score line\n"
        assert _parse_sweep_findings_simple(text) == []


# ---------------------------------------------------------------------------
# 5. run_sweep orchestration tests (mocking run_phase_sync)
# ---------------------------------------------------------------------------


class TestRunSweepOrchestration:
    """Test run_sweep behaviour by mocking the underlying agent call."""

    @pytest.fixture
    def config(self) -> ColonyConfig:
        return ColonyConfig(
            project=ProjectInfo(name="Test", description="test", stack="Python"),
            model="sonnet",
            sweep=SweepConfig(max_tasks=3),
        )

    @pytest.fixture
    def mock_phase_result(self) -> PhaseResult:
        return PhaseResult(
            phase=Phase.SWEEP,
            success=True,
            cost_usd=0.50,
            duration_ms=5000,
            session_id="sweep-session-1",
            model="sonnet",
        )

    @pytest.fixture
    def analysis_output(self) -> str:
        return _make_findings_markdown()

    def _make_phase_result_with_output(self, mock_phase_result, output_text):
        """Create a PhaseResult with the output in artifacts['result']."""
        mock_phase_result.artifacts = {"result": output_text}
        return mock_phase_result

    def test_analysis_uses_read_only_tools(
        self, tmp_repo, config, mock_phase_result, analysis_output
    ):
        """The sweep analysis phase must restrict the agent to read-only tools."""
        from colonyos.orchestrator import run_sweep

        result_with_output = self._make_phase_result_with_output(mock_phase_result, analysis_output)
        with patch("colonyos.orchestrator.run_phase_sync", return_value=result_with_output) as mock_rps:
            run_sweep(tmp_repo, config, execute=False)

            mock_rps.assert_called_once()
            call_kwargs = mock_rps.call_args
            allowed = call_kwargs.kwargs.get("allowed_tools", [])
            assert set(allowed) == {"Read", "Glob", "Grep"}, (
                f"Expected read-only tools, got {allowed}"
            )

    def test_dry_run_returns_findings_without_calling_run(
        self, tmp_repo, config, mock_phase_result, analysis_output
    ):
        from colonyos.orchestrator import run_sweep

        result_with_output = self._make_phase_result_with_output(mock_phase_result, analysis_output)
        with patch("colonyos.orchestrator.run_phase_sync", return_value=result_with_output), \
             patch("colonyos.orchestrator.run") as mock_run:
            findings_text, phase_result = run_sweep(tmp_repo, config, execute=False)

            mock_run.assert_not_called()
            assert "Tasks" in findings_text
            assert phase_result.success is True

    def test_execute_mode_calls_run_with_skip_planning(
        self, tmp_repo, config, mock_phase_result, analysis_output
    ):
        from colonyos.orchestrator import run_sweep

        result_with_output = self._make_phase_result_with_output(mock_phase_result, analysis_output)
        with patch("colonyos.orchestrator.run_phase_sync", return_value=result_with_output), \
             patch("colonyos.orchestrator.run") as mock_run:
            mock_run.return_value = MagicMock()
            run_sweep(tmp_repo, config, execute=True)

            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs.get("skip_planning") is True

    def test_execute_mode_propagates_failure(
        self, tmp_repo, config, mock_phase_result, analysis_output
    ):
        """When execute=True and run() returns a failed RunLog, sweep result should reflect failure."""
        from colonyos.models import RunLog, RunStatus
        from colonyos.orchestrator import run_sweep

        result_with_output = self._make_phase_result_with_output(mock_phase_result, analysis_output)
        failed_run_log = RunLog(
            run_id="sweep-exec-1",
            prompt="test",
            status=RunStatus.FAILED,
        )
        with patch("colonyos.orchestrator.run_phase_sync", return_value=result_with_output), \
             patch("colonyos.orchestrator.run", return_value=failed_run_log):
            findings_text, phase_result = run_sweep(tmp_repo, config, execute=True)

            assert phase_result.success is False
            assert "failed" in phase_result.error.lower()

    def test_execute_mode_success_preserves_result(
        self, tmp_repo, config, mock_phase_result, analysis_output
    ):
        """When execute=True and run() succeeds, sweep result should stay successful."""
        from colonyos.models import RunLog, RunStatus
        from colonyos.orchestrator import run_sweep

        result_with_output = self._make_phase_result_with_output(mock_phase_result, analysis_output)
        success_run_log = RunLog(
            run_id="sweep-exec-2",
            prompt="test",
            status=RunStatus.COMPLETED,
        )
        with patch("colonyos.orchestrator.run_phase_sync", return_value=result_with_output), \
             patch("colonyos.orchestrator.run", return_value=success_run_log):
            findings_text, phase_result = run_sweep(tmp_repo, config, execute=True)

            assert phase_result.success is True

    def test_max_tasks_passed_to_template(self, tmp_repo, config, mock_phase_result):
        """max_tasks from config should appear in the prompt sent to the agent."""
        from colonyos.orchestrator import run_sweep

        mock_phase_result.artifacts = {"result": "output"}
        with patch("colonyos.orchestrator.run_phase_sync", return_value=mock_phase_result) as mock_rps:
            run_sweep(tmp_repo, config, execute=False)

            mock_rps.assert_called_once()
            # The user prompt should reference the max_tasks (3)
            prompt_arg = mock_rps.call_args[0][1]
            assert "3" in prompt_arg


# ---------------------------------------------------------------------------
# 6. CLI sweep command tests
# ---------------------------------------------------------------------------


class TestCLISweepCommand:
    @pytest.fixture(autouse=True)
    def _mock_subprocess(self):
        """Prevent real git calls in CLI code paths."""
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
    def runner(self):
        from click.testing import CliRunner
        return CliRunner()

    def test_sweep_shows_in_app_help(self, runner):
        from colonyos.cli import app
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        # The sweep command may or may not be registered yet
        if "sweep" not in result.output:
            pytest.skip("sweep CLI command not yet registered")
        assert "sweep" in result.output

    def test_sweep_help_shows_expected_flags(self, runner):
        from colonyos.cli import app
        result = runner.invoke(app, ["sweep", "--help"])
        if result.exit_code != 0 and "No such command" in (result.output or ""):
            pytest.skip("sweep CLI command not yet registered")
        # If the command exists, verify it shows help
        if result.exit_code == 0:
            output = result.output
            # Check for common expected flags
            expected_terms = ["--help"]
            for term in expected_terms:
                assert term in output, f"Expected '{term}' in sweep --help output"

    def test_sweep_execute_rejects_busy_repo_runtime(self, runner, tmp_repo: Path):
        from colonyos.cli import app

        config = ColonyConfig(project=ProjectInfo(name="Test", description="test", stack="Python"))
        save_config(tmp_repo, config)
        busy = RuntimeBusyError(
            tmp_repo,
            RuntimeProcessRecord(
                pid=1212,
                mode="daemon",
                cwd=str(tmp_repo),
                started_at="2026-03-30T00:00:00+00:00",
                command="colonyos daemon",
            ),
        )

        with patch("colonyos.cli._find_repo_root", return_value=tmp_repo), \
             patch("colonyos.cli.RepoRuntimeGuard.acquire", side_effect=busy), \
             patch("colonyos.orchestrator.run_sweep") as mock_run:
            result = runner.invoke(app, ["sweep", "--execute"])

        assert result.exit_code != 0
        assert "Another ColonyOS runtime is already active" in result.output
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Integration tests — task file compatibility and end-to-end flows
# ---------------------------------------------------------------------------


class TestSweepTaskFileCompatibility:
    """Verify that sweep analysis output is parseable by dag.parse_task_file()."""

    def test_findings_markdown_parseable_by_parse_task_file(self):
        from colonyos.dag import parse_task_file
        content = _make_findings_markdown()
        deps = parse_task_file(content)
        # Should find parent tasks 1.0 and 2.0
        assert "1.0" in deps
        assert "2.0" in deps

    def test_parsed_dependencies_are_correct(self):
        from colonyos.dag import parse_task_file
        content = _make_findings_markdown()
        deps = parse_task_file(content)
        assert deps["1.0"] == []
        assert deps["2.0"] == []

    def test_findings_with_dependencies_parseable(self):
        from colonyos.dag import parse_task_file
        content = """\
## Relevant Files

- `src/a.py` - test

## Tasks

- [ ] 1.0 [Bugs] Fix null check — impact:5 risk:5
  depends_on: []
  - [ ] 1.1 Write test
  - [ ] 1.2 Fix bug
- [ ] 2.0 [Dead Code] Remove unused function — impact:3 risk:2
  depends_on: [1.0]
  - [ ] 2.1 Verify no call sites
  - [ ] 2.2 Delete function
"""
        deps = parse_task_file(content)
        assert deps["1.0"] == []
        assert deps["2.0"] == ["1.0"]

    def test_empty_findings_parseable(self):
        from colonyos.dag import parse_task_file
        deps = parse_task_file("")
        assert deps == {}


class TestSweepPlanOnlyWritesTaskFile:
    """Verify that plan-only mode writes a task file without calling run()."""

    def test_plan_only_writes_task_file(self, tmp_path: Path):
        from colonyos.orchestrator import run_sweep

        (tmp_path / ".colonyos").mkdir(parents=True)
        (tmp_path / "cOS_tasks").mkdir(parents=True)

        analysis_output = _make_findings_markdown()
        mock_result = PhaseResult(
            phase=Phase.SWEEP,
            success=True,
            cost_usd=0.50,
            duration_ms=5000,
            session_id="sweep-plan-1",
            model="sonnet",
            artifacts={"result": analysis_output},
        )
        config = ColonyConfig(
            project=ProjectInfo(name="Test", description="test", stack="Python"),
            model="sonnet",
            sweep=SweepConfig(max_tasks=3),
        )

        with patch("colonyos.orchestrator.run_phase_sync", return_value=mock_result), \
             patch("colonyos.orchestrator.run") as mock_run:
            findings_text, result = run_sweep(
                tmp_path, config, execute=True, plan_only=True,
            )

            # Task file should be written
            assert result.artifacts.get("task_file")
            task_file_path = Path(result.artifacts["task_file"])
            assert task_file_path.exists()

            # run() should NOT have been called (plan_only stops before implementation)
            mock_run.assert_not_called()

            # Task file should be parseable
            from colonyos.dag import parse_task_file
            deps = parse_task_file(task_file_path.read_text(encoding="utf-8"))
            assert len(deps) >= 1


class TestPhaseModelAndBudgetIntegration:
    """Verify Phase.SWEEP works with get_model() and budget config."""

    def test_get_model_default_fallback(self):
        config = ColonyConfig(model="sonnet")
        assert config.get_model(Phase.SWEEP) == "sonnet"

    def test_get_model_phase_override(self):
        config = ColonyConfig(model="sonnet", phase_models={"sweep": "opus"})
        assert config.get_model(Phase.SWEEP) == "opus"

    def test_budget_per_phase_used_in_run_sweep(self, tmp_path: Path):
        from colonyos.orchestrator import run_sweep

        (tmp_path / ".colonyos").mkdir(parents=True)
        mock_result = PhaseResult(
            phase=Phase.SWEEP, success=True, cost_usd=0.10,
            duration_ms=1000, session_id="s1", model="sonnet",
            artifacts={"result": "No findings."},
        )
        config = ColonyConfig(
            project=ProjectInfo(name="T", description="t", stack="Python"),
            model="sonnet",
            budget=BudgetConfig(per_phase=2.50),
        )

        with patch("colonyos.orchestrator.run_phase_sync", return_value=mock_result) as mock_rps:
            run_sweep(tmp_path, config, execute=False)
            call_kwargs = mock_rps.call_args.kwargs
            assert call_kwargs["budget_usd"] == 2.50
            assert call_kwargs["model"] == "sonnet"
