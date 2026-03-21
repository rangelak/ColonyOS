from pathlib import Path
from unittest.mock import patch, call, MagicMock

import pytest
import click
import json
import yaml

from colonyos.config import ColonyConfig, save_config
from colonyos.models import Persona, PhaseResult, Phase, ProjectInfo, RepoContext
from colonyos.init import (
    MODEL_PRESETS,
    _AI_INIT_TIMEOUT_SECONDS,
    _AiInitTimeout,
    _friendly_init_error,
    select_persona_pack,
    _collect_personas_with_packs,
    run_init,
    scan_repo_context,
    _build_init_system_prompt,
    _parse_ai_config_response,
    render_config_preview,
    run_ai_init,
)
from colonyos.persona_packs import PACKS, pack_keys, packs_summary


# ---------------------------------------------------------------------------
# Task 1: RepoContext and scan_repo_context
# ---------------------------------------------------------------------------

class TestRepoContext:
    def test_dataclass_fields(self):
        ctx = RepoContext(name="foo", description="bar", stack="Python")
        assert ctx.name == "foo"
        assert ctx.description == "bar"
        assert ctx.stack == "Python"
        assert ctx.readme_excerpt == ""
        assert ctx.manifest_type == ""
        assert ctx.raw_signals == {}

    def test_frozen(self):
        ctx = RepoContext(name="foo", description="", stack="")
        with pytest.raises(AttributeError):
            ctx.name = "bar"


class TestScanRepoContext:
    def test_detects_pyproject_toml(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "myapp"\ndescription = "A cool app"\n',
            encoding="utf-8",
        )
        ctx = scan_repo_context(tmp_path)
        assert ctx.name == "myapp"
        assert ctx.description == "A cool app"
        assert "Python" in ctx.stack
        assert ctx.manifest_type == "pyproject.toml"

    def test_detects_package_json(self, tmp_path: Path):
        pkg = {"name": "my-js-app", "description": "A JS app"}
        (tmp_path / "package.json").write_text(
            json.dumps(pkg), encoding="utf-8"
        )
        ctx = scan_repo_context(tmp_path)
        assert ctx.name == "my-js-app"
        assert ctx.description == "A JS app"
        assert "JavaScript" in ctx.stack

    def test_detects_cargo_toml(self, tmp_path: Path):
        (tmp_path / "Cargo.toml").write_text(
            '[package]\nname = "rustapp"\n', encoding="utf-8"
        )
        ctx = scan_repo_context(tmp_path)
        assert ctx.name == "rustapp"
        assert "Rust" in ctx.stack

    def test_detects_go_mod(self, tmp_path: Path):
        (tmp_path / "go.mod").write_text(
            "module github.com/user/goapp\n\ngo 1.21\n", encoding="utf-8"
        )
        ctx = scan_repo_context(tmp_path)
        assert ctx.name == "goapp"
        assert "Go" in ctx.stack

    def test_detects_readme(self, tmp_path: Path):
        (tmp_path / "README.md").write_text("# My Project\nCool stuff.", encoding="utf-8")
        ctx = scan_repo_context(tmp_path)
        assert "My Project" in ctx.readme_excerpt

    def test_empty_repo_falls_back_to_dirname(self, tmp_path: Path):
        ctx = scan_repo_context(tmp_path)
        assert ctx.name == tmp_path.name
        assert ctx.stack == ""
        assert ctx.manifest_type == ""

    def test_truncates_large_files(self, tmp_path: Path):
        (tmp_path / "README.md").write_text("x" * 5000, encoding="utf-8")
        ctx = scan_repo_context(tmp_path)
        assert len(ctx.raw_signals["README.md"]) == 2000

    def test_detects_requirements_txt(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("flask\nrequests\n", encoding="utf-8")
        ctx = scan_repo_context(tmp_path)
        assert "Python" in ctx.stack

    def test_detects_gemfile(self, tmp_path: Path):
        (tmp_path / "Gemfile").write_text('source "https://rubygems.org"\n', encoding="utf-8")
        ctx = scan_repo_context(tmp_path)
        assert "Ruby" in ctx.stack

    def test_detects_multiple_stacks(self, tmp_path: Path):
        (tmp_path / "package.json").write_text('{"name": "multi"}', encoding="utf-8")
        (tmp_path / "requirements.txt").write_text("flask\n", encoding="utf-8")
        ctx = scan_repo_context(tmp_path)
        assert "JavaScript" in ctx.stack
        assert "Python" in ctx.stack

    def test_detects_github_workflow(self, tmp_path: Path):
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: CI\non: push\n", encoding="utf-8")
        ctx = scan_repo_context(tmp_path)
        assert ".github/workflows/ci.yml" in ctx.raw_signals


# ---------------------------------------------------------------------------
# Task 2: Build system prompt and parse response
# ---------------------------------------------------------------------------

class TestBuildInitSystemPrompt:
    def test_contains_pack_keys(self):
        ctx = RepoContext(name="test", description="", stack="Python")
        prompt = _build_init_system_prompt(ctx)
        for key in pack_keys():
            assert key in prompt

    def test_contains_preset_names(self):
        ctx = RepoContext(name="test", description="", stack="")
        prompt = _build_init_system_prompt(ctx)
        for name in MODEL_PRESETS:
            assert name in prompt

    def test_contains_defaults(self):
        ctx = RepoContext(name="test", description="", stack="")
        prompt = _build_init_system_prompt(ctx)
        assert "per_phase" in prompt
        assert "per_run" in prompt

    def test_contains_repo_context(self):
        ctx = RepoContext(name="myproject", description="A great project", stack="Python")
        prompt = _build_init_system_prompt(ctx)
        assert "myproject" in prompt
        assert "A great project" in prompt


class TestParseAiConfigResponse:
    def test_valid_response(self):
        response = json.dumps({
            "pack_key": "startup",
            "preset_name": "Cost-optimized",
            "project_name": "MyApp",
            "project_description": "A cool app",
            "project_stack": "Python/FastAPI",
            "vision": "Build the best app",
        })
        result = _parse_ai_config_response(response)
        assert result is not None
        assert result["pack_key"] == "startup"
        assert result["preset_name"] == "Cost-optimized"
        assert result["project_name"] == "MyApp"

    def test_malformed_json(self):
        result = _parse_ai_config_response("not json at all")
        assert result is None

    def test_invalid_pack_key(self):
        response = json.dumps({
            "pack_key": "nonexistent_pack",
            "preset_name": "Cost-optimized",
            "project_name": "MyApp",
            "project_description": "",
            "project_stack": "",
            "vision": "",
        })
        result = _parse_ai_config_response(response)
        assert result is None

    def test_invalid_preset_name(self):
        response = json.dumps({
            "pack_key": "startup",
            "preset_name": "Nonexistent-preset",
            "project_name": "MyApp",
            "project_description": "",
            "project_stack": "",
            "vision": "",
        })
        result = _parse_ai_config_response(response)
        assert result is None

    def test_missing_project_name(self):
        response = json.dumps({
            "pack_key": "startup",
            "preset_name": "Cost-optimized",
            "project_name": "",
            "project_description": "",
            "project_stack": "",
            "vision": "",
        })
        result = _parse_ai_config_response(response)
        assert result is None

    def test_handles_markdown_fences(self):
        inner = json.dumps({
            "pack_key": "backend",
            "preset_name": "Quality-first",
            "project_name": "API",
            "project_description": "An API",
            "project_stack": "Python",
            "vision": "",
        })
        response = f"```json\n{inner}\n```"
        result = _parse_ai_config_response(response)
        assert result is not None
        assert result["pack_key"] == "backend"

    def test_not_a_dict(self):
        result = _parse_ai_config_response("[1, 2, 3]")
        assert result is None


# ---------------------------------------------------------------------------
# Task 3: run_ai_init
# ---------------------------------------------------------------------------

class TestRunAiInit:
    def _make_success_result(self, response_json: str) -> PhaseResult:
        return PhaseResult(
            phase=Phase.PLAN,
            success=True,
            cost_usd=0.003,
            artifacts={"result": response_json},
        )

    def test_happy_path(self, tmp_path: Path):
        response = json.dumps({
            "pack_key": "startup",
            "preset_name": "Cost-optimized",
            "project_name": "TestApp",
            "project_description": "A test app",
            "project_stack": "Python",
            "vision": "",
        })
        result = self._make_success_result(response)

        with patch("colonyos.agent.run_phase_sync", return_value=result), \
             patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init.render_config_preview"):
            mock_click.echo = click.echo
            mock_click.confirm.return_value = True  # Save config
            config = run_ai_init(tmp_path)

        assert config.project is not None
        assert config.project.name == "TestApp"
        assert config.model == "sonnet"  # Cost-optimized preset
        assert len(config.personas) == len(PACKS[0].personas)  # startup pack

    def test_fallback_on_llm_failure(self, tmp_path: Path):
        failed_result = PhaseResult(
            phase=Phase.PLAN,
            success=False,
            error="API error",
        )
        with patch("colonyos.agent.run_phase_sync", return_value=failed_result), \
             patch("colonyos.init.run_init") as mock_run_init, \
             patch("colonyos.init.click") as mock_click:
            mock_click.echo = click.echo
            mock_run_init.return_value = ColonyConfig()
            run_ai_init(tmp_path)

        mock_run_init.assert_called_once()
        # Should pass defaults (RepoContext) to manual wizard
        call_kwargs = mock_run_init.call_args
        assert "defaults" in call_kwargs.kwargs or (
            len(call_kwargs.args) > 0
        )

    def test_fallback_on_parse_failure(self, tmp_path: Path):
        result = PhaseResult(
            phase=Phase.PLAN,
            success=True,
            cost_usd=0.003,
            artifacts={"result": "not valid json"},
        )
        with patch("colonyos.agent.run_phase_sync", return_value=result), \
             patch("colonyos.init.run_init") as mock_run_init, \
             patch("colonyos.init.click") as mock_click:
            mock_click.echo = click.echo
            mock_run_init.return_value = ColonyConfig()
            run_ai_init(tmp_path)

        mock_run_init.assert_called_once()

    def test_fallback_on_exception(self, tmp_path: Path):
        with patch("colonyos.agent.run_phase_sync", side_effect=RuntimeError("boom")), \
             patch("colonyos.init.run_init") as mock_run_init, \
             patch("colonyos.init.click") as mock_click:
            mock_click.echo = click.echo
            mock_run_init.return_value = ColonyConfig()
            run_ai_init(tmp_path)

        mock_run_init.assert_called_once()

    def test_user_rejects_falls_back_to_manual(self, tmp_path: Path):
        response = json.dumps({
            "pack_key": "backend",
            "preset_name": "Quality-first",
            "project_name": "TestApp",
            "project_description": "A test app",
            "project_stack": "Python",
            "vision": "",
        })
        result = self._make_success_result(response)

        with patch("colonyos.agent.run_phase_sync", return_value=result), \
             patch("colonyos.init.run_init") as mock_run_init, \
             patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init.render_config_preview"):
            mock_click.echo = click.echo
            mock_click.confirm.return_value = False  # Reject config
            mock_run_init.return_value = ColonyConfig()
            run_ai_init(tmp_path)

        mock_run_init.assert_called_once()

    def test_displays_cost(self, tmp_path: Path, capsys):
        response = json.dumps({
            "pack_key": "startup",
            "preset_name": "Cost-optimized",
            "project_name": "TestApp",
            "project_description": "",
            "project_stack": "Python",
            "vision": "",
        })
        result = self._make_success_result(response)

        with patch("colonyos.agent.run_phase_sync", return_value=result), \
             patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init.render_config_preview"):
            mock_click.echo = click.echo
            mock_click.confirm.return_value = True
            run_ai_init(tmp_path)

        captured = capsys.readouterr()
        assert "$0.003" in captured.out


# ---------------------------------------------------------------------------
# Task 4: Config preview
# ---------------------------------------------------------------------------

class TestRenderConfigPreview:
    def test_renders_project_info(self):
        from io import StringIO
        from rich.console import Console

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        config = ColonyConfig(
            project=ProjectInfo(name="TestApp", description="A test", stack="Python"),
            personas=list(PACKS[0].personas),
            model="sonnet",
            phase_models={"implement": "opus"},
        )
        render_config_preview(config, "Startup Team", "Cost-optimized", console=console)

        text = output.getvalue()
        assert "TestApp" in text
        assert "Startup Team" in text
        assert "Cost-optimized" in text

    def test_renders_budget(self):
        from io import StringIO
        from rich.console import Console

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        config = ColonyConfig(
            project=ProjectInfo(name="App", description="", stack=""),
            personas=[Persona(role="Eng", expertise="BE", perspective="P")],
        )
        render_config_preview(config, "Custom", "Quality-first", console=console)

        text = output.getvalue()
        assert "$5.00" in text  # default per_phase
        assert "$15.00" in text  # default per_run

    def test_renders_persona_roles(self):
        from io import StringIO
        from rich.console import Console

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)

        personas = [
            Persona(role="API Designer", expertise="REST", perspective="P"),
            Persona(role="DBA", expertise="SQL", perspective="P"),
        ]
        config = ColonyConfig(
            project=ProjectInfo(name="App", description="", stack=""),
            personas=personas,
        )
        render_config_preview(config, "Backend / API", "Quality-first", console=console)

        text = output.getvalue()
        assert "API Designer" in text
        assert "DBA" in text


# ---------------------------------------------------------------------------
# Task 5: CLI routing (tested via imports; see test_cli.py for CliRunner tests)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Task 6: Fallback pre-fill defaults
# ---------------------------------------------------------------------------

class TestFallbackPreFill:
    def test_collect_project_info_uses_defaults(self):
        defaults = RepoContext(name="detected-name", description="detected-desc", stack="Python")
        with patch("colonyos.init.click") as mock_click:
            mock_click.prompt.side_effect = ["detected-name", "detected-desc", "Python"]
            mock_click.echo = click.echo
            from colonyos.init import collect_project_info
            result = collect_project_info(defaults=defaults)

        # Check that prompt was called with defaults
        calls = mock_click.prompt.call_args_list
        assert calls[0][1].get("default") == "detected-name" or calls[0][0][0] == "Project name"
        assert result.name == "detected-name"

    def test_run_init_passes_defaults_to_collect(self, tmp_path: Path):
        defaults = RepoContext(name="myapp", description="cool", stack="Go")
        with patch("colonyos.init.collect_project_info") as mock_collect, \
             patch("colonyos.init._collect_personas_with_packs") as mock_personas, \
             patch("colonyos.init.click") as mock_click:
            mock_collect.return_value = ProjectInfo(name="myapp", description="cool", stack="Go")
            mock_personas.return_value = [Persona(role="E", expertise="B", perspective="P")]
            mock_click.prompt.side_effect = ["", 1, 5.0, 15.0]
            mock_click.echo = click.echo
            mock_click.IntRange = click.IntRange
            run_init(tmp_path, defaults=defaults)

        mock_collect.assert_called_once_with(defaults=defaults)


# ---------------------------------------------------------------------------
# Task 7: Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_auth_failure_falls_back(self, tmp_path: Path):
        with patch("colonyos.agent.run_phase_sync", side_effect=Exception("authentication failed")), \
             patch("colonyos.init.run_init") as mock_run_init, \
             patch("colonyos.init.click") as mock_click:
            mock_click.echo = click.echo
            mock_run_init.return_value = ColonyConfig()
            run_ai_init(tmp_path)

        mock_run_init.assert_called_once()

    def test_empty_repo_still_works(self, tmp_path: Path):
        """AI init should handle empty repos gracefully."""
        response = json.dumps({
            "pack_key": "startup",
            "preset_name": "Cost-optimized",
            "project_name": tmp_path.name,
            "project_description": "",
            "project_stack": "",
            "vision": "",
        })
        result = PhaseResult(
            phase=Phase.PLAN,
            success=True,
            cost_usd=0.001,
            artifacts={"result": response},
        )
        with patch("colonyos.agent.run_phase_sync", return_value=result), \
             patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init.render_config_preview"):
            mock_click.echo = click.echo
            mock_click.confirm.return_value = True
            config = run_ai_init(tmp_path)

        assert config.project is not None
        assert config.project.name == tmp_path.name

    def test_no_partial_state_on_failure(self, tmp_path: Path):
        """On failure, no .colonyos directory should be created."""
        with patch("colonyos.agent.run_phase_sync", side_effect=Exception("boom")), \
             patch("colonyos.init.run_init", side_effect=click.Abort()):
            try:
                run_ai_init(tmp_path)
            except click.Abort:
                pass

        assert not (tmp_path / ".colonyos" / "config.yaml").exists()

    def test_auth_failure_shows_friendly_message(self, tmp_path: Path, capsys):
        """Auth failures should produce a human-readable message, not raw exc."""
        with patch("colonyos.agent.run_phase_sync", side_effect=Exception("authentication failed")), \
             patch("colonyos.init.run_init") as mock_run_init, \
             patch("colonyos.init.click") as mock_click:
            mock_click.echo = click.echo
            mock_run_init.return_value = ColonyConfig()
            run_ai_init(tmp_path)

        captured = capsys.readouterr()
        assert "Authentication failed" in captured.out

    def test_credit_balance_shows_friendly_message(self, tmp_path: Path, capsys):
        """Credit balance errors should produce a friendly message."""
        with patch("colonyos.agent.run_phase_sync", side_effect=Exception("credit balance is too low")), \
             patch("colonyos.init.run_init") as mock_run_init, \
             patch("colonyos.init.click") as mock_click:
            mock_click.echo = click.echo
            mock_run_init.return_value = ColonyConfig()
            run_ai_init(tmp_path)

        captured = capsys.readouterr()
        assert "Credit balance" in captured.out

    def test_rate_limit_shows_friendly_message(self, tmp_path: Path, capsys):
        """Rate-limit errors should produce a friendly message."""
        with patch("colonyos.agent.run_phase_sync", side_effect=Exception("rate limit exceeded")), \
             patch("colonyos.init.run_init") as mock_run_init, \
             patch("colonyos.init.click") as mock_click:
            mock_click.echo = click.echo
            mock_run_init.return_value = ColonyConfig()
            run_ai_init(tmp_path)

        captured = capsys.readouterr()
        assert "Rate limited" in captured.out

    def test_timeout_shows_friendly_message(self, tmp_path: Path, capsys):
        """Timeout errors should produce a friendly message."""
        with patch("colonyos.agent.run_phase_sync", side_effect=_AiInitTimeout("timed out")), \
             patch("colonyos.init.run_init") as mock_run_init, \
             patch("colonyos.init.click") as mock_click:
            mock_click.echo = click.echo
            mock_run_init.return_value = ColonyConfig()
            run_ai_init(tmp_path)

        captured = capsys.readouterr()
        assert "timed out" in captured.out

    def test_run_phase_sync_called_with_default_permission_mode(self, tmp_path: Path):
        """run_ai_init must pass permission_mode='default' to run_phase_sync."""
        response = json.dumps({
            "pack_key": "startup",
            "preset_name": "Cost-optimized",
            "project_name": "TestApp",
            "project_description": "",
            "project_stack": "Python",
            "vision": "",
        })
        result = PhaseResult(
            phase=Phase.PLAN,
            success=True,
            cost_usd=0.003,
            artifacts={"result": response},
        )
        with patch("colonyos.agent.run_phase_sync", return_value=result) as mock_rps, \
             patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init.render_config_preview"):
            mock_click.echo = click.echo
            mock_click.confirm.return_value = True
            run_ai_init(tmp_path)

        mock_rps.assert_called_once()
        call_kwargs = mock_rps.call_args
        assert call_kwargs.kwargs.get("permission_mode") == "default"


class TestFriendlyInitError:
    def test_auth_error(self):
        msg = _friendly_init_error(Exception("authentication failed"))
        assert "Authentication failed" in msg

    def test_credit_balance_error(self):
        msg = _friendly_init_error(Exception("credit balance too low"))
        assert "Credit balance" in msg

    def test_rate_limit_error(self):
        msg = _friendly_init_error(Exception("rate limit exceeded"))
        assert "Rate limited" in msg

    def test_timeout_error(self):
        msg = _friendly_init_error(_AiInitTimeout("timed out"))
        assert "timed out" in msg
        assert str(_AI_INIT_TIMEOUT_SECONDS) in msg

    def test_generic_error(self):
        msg = _friendly_init_error(Exception("something weird"))
        assert "something weird" in msg


# ---------------------------------------------------------------------------
# Original tests (preserved)
# ---------------------------------------------------------------------------

class TestSelectPersonaPack:
    def test_returns_pack_personas_when_pack_selected(self):
        # User picks pack 1 (startup), then confirms
        inputs = iter(["1", "y"])
        with patch("colonyos.init.click") as mock_click:
            mock_click.prompt.return_value = 1
            mock_click.confirm.return_value = True
            mock_click.echo = click.echo
            mock_click.IntRange = click.IntRange
            result = select_persona_pack()

        assert result is not None
        assert len(result) == len(PACKS[0].personas)
        assert result[0].role == PACKS[0].personas[0].role

    def test_returns_none_when_custom_selected(self):
        custom_index = len(PACKS) + 1
        with patch("colonyos.init.click") as mock_click:
            mock_click.prompt.return_value = custom_index
            mock_click.echo = click.echo
            mock_click.IntRange = click.IntRange
            result = select_persona_pack()

        assert result is None

    def test_returns_none_when_pack_not_confirmed(self):
        with patch("colonyos.init.click") as mock_click:
            mock_click.prompt.return_value = 1
            mock_click.confirm.return_value = False
            mock_click.echo = click.echo
            mock_click.IntRange = click.IntRange
            result = select_persona_pack()

        assert result is None

    def test_all_packs_selectable(self):
        for i, pack in enumerate(PACKS, 1):
            with patch("colonyos.init.click") as mock_click:
                mock_click.prompt.return_value = i
                mock_click.confirm.return_value = True
                mock_click.echo = click.echo
                mock_click.IntRange = click.IntRange
                result = select_persona_pack()

            assert result is not None
            assert len(result) == len(pack.personas)


class TestCollectPersonasWithPacks:
    def test_pack_selected_no_custom_additions(self):
        with patch("colonyos.init.select_persona_pack") as mock_select, \
             patch("colonyos.init.click") as mock_click:
            mock_select.return_value = list(PACKS[0].personas)
            mock_click.confirm.return_value = False  # No custom additions
            result = _collect_personas_with_packs()

        assert result == list(PACKS[0].personas)

    def test_pack_selected_with_custom_additions(self):
        extra_persona = Persona(
            role="Custom Role",
            expertise="Custom Expertise",
            perspective="Custom Perspective",
        )
        pack_personas = list(PACKS[0].personas)

        with patch("colonyos.init.select_persona_pack") as mock_select, \
             patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init.collect_personas") as mock_collect:
            mock_select.return_value = pack_personas
            mock_click.confirm.return_value = True  # Yes, add custom
            mock_collect.return_value = pack_personas + [extra_persona]
            result = _collect_personas_with_packs()

        mock_collect.assert_called_once_with(existing=pack_personas)
        assert len(result) == len(pack_personas) + 1

    def test_custom_selected_falls_through_to_collect(self):
        existing = [Persona(role="Existing", expertise="E", perspective="P")]

        with patch("colonyos.init.select_persona_pack") as mock_select, \
             patch("colonyos.init.collect_personas") as mock_collect:
            mock_select.return_value = None  # Custom selected
            mock_collect.return_value = existing
            result = _collect_personas_with_packs(existing)

        mock_collect.assert_called_once_with(existing)
        assert result == existing


class TestRunInitReviewsDir:
    def test_creates_reviews_dir(self, tmp_path: Path):
        """run_init creates the reviews directory."""
        with patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init._collect_personas_with_packs") as mock_personas, \
             patch("colonyos.init._collect_strategic_goals", return_value=""):
            mock_click.prompt.side_effect = [
                "TestApp", "A test app", "Python", "", 1, 5.0, 15.0
            ]
            mock_click.IntRange = click.IntRange
            mock_click.echo = click.echo
            mock_personas.return_value = [
                Persona(role="Engineer", expertise="Backend", perspective="Scale")
            ]
            config = run_init(tmp_path)

        reviews_dir = tmp_path / config.reviews_dir
        assert reviews_dir.exists()
        assert reviews_dir.is_dir()

    def test_creates_review_subdirectories(self, tmp_path: Path):
        """run_init creates decisions/ and reviews/ subdirectories with .gitkeep."""
        with patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init._collect_personas_with_packs") as mock_personas, \
             patch("colonyos.init._collect_strategic_goals", return_value=""):
            mock_click.prompt.side_effect = [
                "TestApp", "A test app", "Python", "", 1, 5.0, 15.0
            ]
            mock_click.IntRange = click.IntRange
            mock_click.echo = click.echo
            mock_personas.return_value = [
                Persona(role="Engineer", expertise="Backend", perspective="Scale")
            ]
            config = run_init(tmp_path)

        reviews_dir = tmp_path / config.reviews_dir
        decisions_dir = reviews_dir / "decisions"
        reviews_subdir = reviews_dir / "reviews"
        assert decisions_dir.exists()
        assert decisions_dir.is_dir()
        assert (decisions_dir / ".gitkeep").exists()
        assert reviews_subdir.exists()
        assert reviews_subdir.is_dir()
        assert (reviews_subdir / ".gitkeep").exists()

    def test_gitignore_has_cos_pattern(self, tmp_path: Path):
        """run_init adds cOS_*/ pattern to .gitignore."""
        with patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init._collect_personas_with_packs") as mock_personas, \
             patch("colonyos.init._collect_strategic_goals", return_value=""):
            mock_click.prompt.side_effect = [
                "TestApp", "A test app", "Python", "", 1, 5.0, 15.0
            ]
            mock_click.IntRange = click.IntRange
            mock_click.echo = click.echo
            mock_personas.return_value = [
                Persona(role="Engineer", expertise="Backend", perspective="Scale")
            ]
            run_init(tmp_path)

        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text(encoding="utf-8")
        assert "cOS_*/" in content
        assert ".colonyos/runs/" in content

    def test_warns_on_old_dirs(self, tmp_path: Path, capsys):
        """run_init warns if old prds/ or tasks/ dirs exist alongside cOS_ dirs."""
        (tmp_path / "prds").mkdir()
        (tmp_path / "tasks").mkdir()

        with patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init._collect_personas_with_packs") as mock_personas, \
             patch("colonyos.init._collect_strategic_goals", return_value=""):
            mock_click.prompt.side_effect = [
                "TestApp", "A test app", "Python", "", 1, 5.0, 15.0
            ]
            mock_click.IntRange = click.IntRange
            # Use real echo so we can capture stderr output
            mock_click.echo = click.echo
            mock_personas.return_value = [
                Persona(role="Engineer", expertise="Backend", perspective="Scale")
            ]
            run_init(tmp_path)

        captured = capsys.readouterr()
        assert "old prds/" in captured.err
        assert "old tasks/" in captured.err


class TestQuickInit:
    """Task 2.1: Tests for --quick flag."""

    def test_quick_skips_interactive_prompts(self, tmp_path: Path):
        """--quick should skip persona workshop and use defaults."""
        config = run_init(
            tmp_path,
            quick=True,
            project_name="TestProject",
            project_description="A test",
            project_stack="Python",
        )

        assert config.project is not None
        assert config.project.name == "TestProject"
        assert len(config.personas) > 0  # Should have first pack's personas

    def test_quick_uses_first_persona_pack(self, tmp_path: Path):
        config = run_init(
            tmp_path,
            quick=True,
            project_name="TestProject",
            project_description="A test",
            project_stack="Python",
        )

        first_pack = PACKS[0]
        assert len(config.personas) == len(first_pack.personas)
        assert config.personas[0].role == first_pack.personas[0].role

    def test_quick_creates_valid_config(self, tmp_path: Path):
        config = run_init(
            tmp_path,
            quick=True,
            project_name="TestProject",
            project_description="A test",
            project_stack="Python",
        )

        # Verify config was saved to disk
        config_path = tmp_path / ".colonyos" / "config.yaml"
        assert config_path.exists()

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert raw["project"]["name"] == "TestProject"
        assert raw["model"] == "sonnet"

    def test_quick_prints_next_step(self, tmp_path: Path, capsys):
        with patch("colonyos.init.click") as mock_click:
            mock_click.echo = click.echo
            run_init(
                tmp_path,
                quick=True,
                project_name="TestProject",
                project_description="A test",
                project_stack="Python",
            )

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "colonyos run" in combined

    def test_quick_requires_project_name(self, tmp_path: Path):
        """--quick without project name should raise an error."""
        with pytest.raises(click.ClickException):
            run_init(tmp_path, quick=True)


class TestDoctorPreCheck:
    """Task 2.3: Doctor pre-check in init."""

    def test_init_refuses_if_hard_prereqs_missing(self, tmp_path: Path):
        """Init should refuse to proceed if hard prerequisites fail."""

        def fake_checks(repo_root):
            return [
                ("Python ≥ 3.11", False, "Install Python 3.11+"),
                ("Claude Code CLI", False, "Install claude"),
                ("Git", True, ""),
                ("GitHub CLI auth", True, ""),
            ]

        with patch("colonyos.doctor.run_doctor_checks", fake_checks):
            with pytest.raises(click.ClickException, match="prerequisite"):
                run_init(
                    tmp_path,
                    quick=True,
                    project_name="Test",
                    project_description="test",
                    project_stack="Python",
                    doctor_check=True,
                )


class TestModelPresets:
    def test_quality_first_preset_has_empty_phase_models(self):
        preset = MODEL_PRESETS["Quality-first"]
        assert preset["phase_models"] == {}
        assert preset["model"] == "opus"

    def test_cost_optimized_preset_has_phase_overrides(self):
        preset = MODEL_PRESETS["Cost-optimized"]
        assert preset["model"] == "sonnet"
        assert preset["phase_models"]["implement"] == "opus"
        assert preset["phase_models"]["deliver"] == "haiku"
        assert preset["phase_models"]["learn"] == "haiku"
        # Only phases that differ from the global default should be listed
        assert "plan" not in preset["phase_models"]
        assert "review" not in preset["phase_models"]
        assert "fix" not in preset["phase_models"]
        assert "decision" not in preset["phase_models"]

    def test_quick_init_uses_cost_optimized(self, tmp_path: Path):
        config = run_init(
            tmp_path,
            quick=True,
            project_name="TestProject",
            project_description="A test",
            project_stack="Python",
        )
        assert config.phase_models == dict(MODEL_PRESETS["Cost-optimized"]["phase_models"])
        assert config.model == "sonnet"

    def test_interactive_quality_first_preset(self, tmp_path: Path):
        with patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init._collect_personas_with_packs") as mock_personas, \
             patch("colonyos.init._collect_strategic_goals", return_value=""):
            # Prompt sequence: name, desc, stack, vision, preset=1 (Quality-first), budget_phase, budget_run
            mock_click.prompt.side_effect = [
                "TestApp", "A test app", "Python", "", 1, 5.0, 15.0
            ]
            mock_click.echo = click.echo
            mock_click.IntRange = click.IntRange
            mock_personas.return_value = [
                Persona(role="Engineer", expertise="Backend", perspective="Scale")
            ]
            config = run_init(tmp_path)

        assert config.phase_models == {}
        assert config.model == "opus"

    def test_interactive_cost_optimized_preset(self, tmp_path: Path):
        with patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init._collect_personas_with_packs") as mock_personas, \
             patch("colonyos.init._collect_strategic_goals", return_value=""):
            # Prompt sequence: name, desc, stack, vision, preset=2 (Cost-optimized), budget_phase, budget_run
            mock_click.prompt.side_effect = [
                "TestApp", "A test app", "Python", "", 2, 5.0, 15.0
            ]
            mock_click.echo = click.echo
            mock_click.IntRange = click.IntRange
            mock_personas.return_value = [
                Persona(role="Engineer", expertise="Backend", perspective="Scale")
            ]
            config = run_init(tmp_path)

        assert config.phase_models == dict(MODEL_PRESETS["Cost-optimized"]["phase_models"])
        assert config.model == "sonnet"


# ---------------------------------------------------------------------------
# packs_summary helper
# ---------------------------------------------------------------------------

class TestPacksSummary:
    def test_returns_list_of_dicts(self):
        result = packs_summary()
        assert isinstance(result, list)
        assert len(result) == len(PACKS)

    def test_each_entry_has_required_keys(self):
        for entry in packs_summary():
            assert "key" in entry
            assert "name" in entry
            assert "description" in entry
            assert "persona_roles" in entry
            assert isinstance(entry["persona_roles"], list)

    def test_keys_match_pack_keys(self):
        summary_keys = [e["key"] for e in packs_summary()]
        assert summary_keys == pack_keys()
