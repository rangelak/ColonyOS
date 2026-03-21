"""Tests for the CEO directions module."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from colonyos.config import ColonyConfig, BudgetConfig, PhasesConfig
from colonyos.models import Persona, Phase, PhaseResult, ProjectInfo
from colonyos.directions import (
    DIRECTIONS_FILE,
    _MAX_DIRECTIONS_LEN,
    directions_path,
    load_directions,
    save_directions,
    build_directions_update_prompt,
    parse_iteration_from_directions,
)

_SDK_AVAILABLE = True
try:
    from colonyos.orchestrator import _build_ceo_prompt, update_directions_after_ceo
except ImportError:
    _SDK_AVAILABLE = False

needs_sdk = pytest.mark.skipif(not _SDK_AVAILABLE, reason="claude_agent_sdk not installed")


SAMPLE_DIRECTIONS = """\
# Strategic Directions

_Generated: 2026-03-21 | Iteration: 3_

## The Landscape

CLI dev tools are converging on composable plugin architectures. The best ones ship with --json output.

## Projects Worth Studying

- **Click** ([github.com/pallets/click](https://github.com/pallets/click)): Gold standard for CLI UX
- **Typer** ([github.com/tiangolo/typer](https://github.com/tiangolo/typer)): Type hints as CLI interface

## Patterns & Ideas

- Progressive disclosure: start simple, reveal complexity on demand
- Every successful dev tool has a plugin/extension system after v1

## User's North Star

Make it the most intuitive CLI in the space.

## Watch Out For

- Scope creep into GUI territory — stay focused on terminal UX
"""


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / ".colonyos").mkdir()
    return tmp_path


@pytest.fixture
def config() -> ColonyConfig:
    return ColonyConfig(
        project=ProjectInfo(name="TestApp", description="A test app", stack="Python"),
        personas=[
            Persona(role="Engineer", expertise="Backend", perspective="Scale", reviewer=True)
        ],
        model="sonnet",
        budget=BudgetConfig(per_phase=1.0, per_run=10.0),
        phases=PhasesConfig(),
        vision="Build the best CLI tool",
    )


class TestDirectionsPath:
    def test_returns_correct_path(self, tmp_repo: Path):
        assert directions_path(tmp_repo) == tmp_repo / ".colonyos" / DIRECTIONS_FILE

    def test_file_constant(self):
        assert DIRECTIONS_FILE == "directions.md"


class TestLoadDirections:
    def test_returns_empty_when_no_file(self, tmp_repo: Path):
        assert load_directions(tmp_repo) == ""

    def test_returns_content_when_file_exists(self, tmp_repo: Path):
        path = directions_path(tmp_repo)
        path.write_text(SAMPLE_DIRECTIONS, encoding="utf-8")
        result = load_directions(tmp_repo)
        assert "Strategic Directions" in result
        assert "Click" in result

    def test_truncates_long_content(self, tmp_repo: Path):
        path = directions_path(tmp_repo)
        long_content = "x" * (_MAX_DIRECTIONS_LEN + 500)
        path.write_text(long_content, encoding="utf-8")

        result = load_directions(tmp_repo)
        assert len(result) < len(long_content)
        assert "_(truncated)_" in result

    def test_no_truncation_for_short_content(self, tmp_repo: Path):
        path = directions_path(tmp_repo)
        path.write_text(SAMPLE_DIRECTIONS, encoding="utf-8")
        result = load_directions(tmp_repo)
        assert "_(truncated)_" not in result


class TestSaveDirections:
    def test_creates_file(self, tmp_repo: Path):
        result_path = save_directions(tmp_repo, SAMPLE_DIRECTIONS)
        assert result_path.exists()
        assert result_path.read_text(encoding="utf-8") == SAMPLE_DIRECTIONS

    def test_creates_parent_directory(self, tmp_path: Path):
        save_directions(tmp_path, "test content")
        assert (tmp_path / ".colonyos" / DIRECTIONS_FILE).exists()

    def test_overwrites_existing(self, tmp_repo: Path):
        save_directions(tmp_repo, "old content")
        save_directions(tmp_repo, "new content")
        content = directions_path(tmp_repo).read_text(encoding="utf-8")
        assert content == "new content"


class TestParseIterationFromDirections:
    def test_extracts_iteration_number(self):
        assert parse_iteration_from_directions(SAMPLE_DIRECTIONS) == 3

    def test_returns_zero_for_iteration_zero(self):
        content = "# Strategic Directions\n\n_Generated: 2026-03-21 | Iteration: 0_\n"
        assert parse_iteration_from_directions(content) == 0

    def test_returns_zero_when_no_iteration(self):
        assert parse_iteration_from_directions("# No iteration here") == 0

    def test_returns_zero_for_empty(self):
        assert parse_iteration_from_directions("") == 0

    def test_handles_large_iteration(self):
        content = "_Generated: 2026-03-21 | Iteration: 42_\n"
        assert parse_iteration_from_directions(content) == 42


class TestBuildDirectionsGenPrompt:
    """Tests for build_directions_gen_prompt.

    Now that directions.py has its own _load_instruction, these don't
    need the orchestrator or claude_agent_sdk at all.
    """

    def test_system_prompt_loads_template(self, tmp_repo: Path, config: ColonyConfig):
        from colonyos.directions import build_directions_gen_prompt
        system, user = build_directions_gen_prompt(config, "focus on performance", tmp_repo)
        assert "landscape" in system.lower() or "inspiration" in system.lower()

    def test_user_prompt_contains_project_context(self, tmp_repo: Path, config: ColonyConfig):
        from colonyos.directions import build_directions_gen_prompt
        system, user = build_directions_gen_prompt(config, "goals", tmp_repo)
        assert "TestApp" in user
        assert "A test app" in user
        assert "Python" in user

    def test_user_prompt_contains_vision(self, tmp_repo: Path, config: ColonyConfig):
        from colonyos.directions import build_directions_gen_prompt
        system, user = build_directions_gen_prompt(config, "goals", tmp_repo)
        assert "Build the best CLI tool" in user

    def test_user_prompt_contains_user_goals(self, tmp_repo: Path, config: ColonyConfig):
        from colonyos.directions import build_directions_gen_prompt
        system, user = build_directions_gen_prompt(config, "improve developer experience", tmp_repo)
        assert "improve developer experience" in user
        assert "North Star" in user

    def test_user_prompt_skips_empty_goals(self, tmp_repo: Path, config: ColonyConfig):
        from colonyos.directions import build_directions_gen_prompt
        system, user = build_directions_gen_prompt(config, "  ", tmp_repo)
        assert "North Star" not in user

    def test_user_prompt_includes_readme(self, tmp_repo: Path, config: ColonyConfig):
        from colonyos.directions import build_directions_gen_prompt
        (tmp_repo / "README.md").write_text("# My Project\nA great project.")
        system, user = build_directions_gen_prompt(config, "goals", tmp_repo)
        assert "My Project" in user

    def test_user_prompt_includes_changelog(self, tmp_repo: Path, config: ColonyConfig):
        from colonyos.directions import build_directions_gen_prompt
        (tmp_repo / "CHANGELOG.md").write_text("# Changelog\n\n## Added auth system")
        system, user = build_directions_gen_prompt(config, "goals", tmp_repo)
        assert "auth system" in user

    def test_user_prompt_without_readme_or_changelog(self, tmp_repo: Path, config: ColonyConfig):
        from colonyos.directions import build_directions_gen_prompt
        system, user = build_directions_gen_prompt(config, "goals", tmp_repo)
        assert "landscape" in user.lower()

    def test_handles_missing_project(self, tmp_repo: Path):
        from colonyos.directions import build_directions_gen_prompt
        config = ColonyConfig()
        system, user = build_directions_gen_prompt(config, "goals", tmp_repo)
        assert "Unknown" in user


class TestBuildDirectionsUpdatePrompt:
    def test_contains_current_directions(self, tmp_repo: Path, config: ColonyConfig):
        system, user = build_directions_update_prompt(
            config, SAMPLE_DIRECTIONS, "Build a plugin system", 4, tmp_repo,
        )
        assert "Click" in user
        assert "Typer" in user
        assert "iteration 3" in user

    def test_contains_proposal(self, tmp_repo: Path, config: ColonyConfig):
        system, user = build_directions_update_prompt(
            config, SAMPLE_DIRECTIONS, "Build a plugin system", 4, tmp_repo,
        )
        assert "plugin system" in user

    def test_contains_iteration_number(self, tmp_repo: Path, config: ColonyConfig):
        system, user = build_directions_update_prompt(
            config, SAMPLE_DIRECTIONS, "proposal", 7, tmp_repo,
        )
        assert "iteration 7" in user.lower() or "Set iteration to 7" in user

    def test_system_prompt_is_landscape_focused(self, tmp_repo: Path, config: ColonyConfig):
        system, user = build_directions_update_prompt(
            config, SAMPLE_DIRECTIONS, "proposal", 1, tmp_repo,
        )
        assert "landscape" in system.lower()
        assert "task list" in system.lower()

    def test_contains_project_name(self, tmp_repo: Path, config: ColonyConfig):
        system, user = build_directions_update_prompt(
            config, SAMPLE_DIRECTIONS, "proposal", 1, tmp_repo,
        )
        assert "TestApp" in user


@needs_sdk
class TestCeoPromptDirectionsInjection:
    """Verify that _build_ceo_prompt injects directions into the CEO system prompt."""

    def test_injects_directions_when_present(self, tmp_repo: Path, config: ColonyConfig):
        save_directions(tmp_repo, SAMPLE_DIRECTIONS)
        system, user = _build_ceo_prompt(config, "test.md", tmp_repo)
        assert "Click" in system
        assert "Typer" in system
        assert "Landscape" in system or "landscape" in system

    def test_shows_placeholder_when_no_directions(self, tmp_repo: Path, config: ColonyConfig):
        system, user = _build_ceo_prompt(config, "test.md", tmp_repo)
        assert "No directions configured" in system

    def test_directions_in_system_not_user_prompt(self, tmp_repo: Path, config: ColonyConfig):
        save_directions(tmp_repo, SAMPLE_DIRECTIONS)
        system, user = _build_ceo_prompt(config, "test.md", tmp_repo)
        assert "Click" in system
        assert "Click" not in user


@needs_sdk
class TestUpdateDirectionsAfterCeo:
    """Verify update_directions_after_ceo calls the agent and saves output."""

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_updates_directions_on_success(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        save_directions(tmp_repo, SAMPLE_DIRECTIONS)
        updated = SAMPLE_DIRECTIONS.replace("Iteration: 3", "Iteration: 4")
        mock_run.return_value = PhaseResult(
            phase=Phase.CEO,
            success=True,
            cost_usd=0.01,
            artifacts={"result": updated},
        )

        cost = update_directions_after_ceo(tmp_repo, config, "Build plugin system", 4)

        content = directions_path(tmp_repo).read_text(encoding="utf-8")
        assert "Iteration: 4" in content
        assert cost == 0.01

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_skips_when_no_directions_exist(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        cost = update_directions_after_ceo(tmp_repo, config, "proposal", 1)
        mock_run.assert_not_called()
        assert cost == 0.0

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_skips_when_output_missing_header(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        save_directions(tmp_repo, SAMPLE_DIRECTIONS)
        mock_run.return_value = PhaseResult(
            phase=Phase.CEO,
            success=True,
            cost_usd=0.05,
            artifacts={"result": "just some random text"},
        )

        cost = update_directions_after_ceo(tmp_repo, config, "proposal", 2)

        content = directions_path(tmp_repo).read_text(encoding="utf-8")
        assert "Iteration: 3" in content  # unchanged
        assert cost == 0.05  # cost still incurred even though output was rejected

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_survives_agent_failure(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        save_directions(tmp_repo, SAMPLE_DIRECTIONS)
        mock_run.side_effect = RuntimeError("agent exploded")

        cost = update_directions_after_ceo(tmp_repo, config, "proposal", 2)

        content = directions_path(tmp_repo).read_text(encoding="utf-8")
        assert "Iteration: 3" in content  # unchanged
        assert cost == 0.0

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_skips_on_failed_result(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        save_directions(tmp_repo, SAMPLE_DIRECTIONS)
        mock_run.return_value = PhaseResult(
            phase=Phase.CEO,
            success=False,
            cost_usd=0.03,
            error="Budget exceeded",
            artifacts={"result": ""},
        )

        cost = update_directions_after_ceo(tmp_repo, config, "proposal", 2)

        content = directions_path(tmp_repo).read_text(encoding="utf-8")
        assert "Iteration: 3" in content  # unchanged
        assert cost == 0.03  # cost incurred even on failure

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_uses_capped_budget(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        save_directions(tmp_repo, SAMPLE_DIRECTIONS)
        updated = SAMPLE_DIRECTIONS.replace("Iteration: 3", "Iteration: 4")
        mock_run.return_value = PhaseResult(
            phase=Phase.CEO,
            success=True,
            cost_usd=0.01,
            artifacts={"result": updated},
        )

        update_directions_after_ceo(tmp_repo, config, "proposal", 4)

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["budget_usd"] <= 1.0

    @patch("colonyos.orchestrator.run_phase_sync")
    def test_uses_no_tools(self, mock_run, tmp_repo: Path, config: ColonyConfig):
        save_directions(tmp_repo, SAMPLE_DIRECTIONS)
        updated = SAMPLE_DIRECTIONS.replace("Iteration: 3", "Iteration: 4")
        mock_run.return_value = PhaseResult(
            phase=Phase.CEO,
            success=True,
            cost_usd=0.01,
            artifacts={"result": updated},
        )

        update_directions_after_ceo(tmp_repo, config, "proposal", 4)

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["allowed_tools"] == []
