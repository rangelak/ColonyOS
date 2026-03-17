from pathlib import Path
from unittest.mock import patch, call, MagicMock

import pytest
import click
import yaml

from colonyos.config import ColonyConfig, save_config
from colonyos.models import Persona, ProjectInfo
from colonyos.init import select_persona_pack, _collect_personas_with_packs, run_init, _detect_test_command
from colonyos.persona_packs import PACKS


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
             patch("colonyos.init._collect_personas_with_packs") as mock_personas:
            mock_click.prompt.side_effect = [
                "TestApp", "A test app", "Python", "", "sonnet", 5.0, 15.0, ""
            ]
            mock_click.echo = click.echo
            mock_personas.return_value = [
                Persona(role="Engineer", expertise="Backend", perspective="Scale")
            ]
            config = run_init(tmp_path)

        reviews_dir = tmp_path / config.reviews_dir
        assert reviews_dir.exists()
        assert reviews_dir.is_dir()

    def test_gitignore_has_cos_pattern(self, tmp_path: Path):
        """run_init adds cOS_*/ pattern to .gitignore."""
        with patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init._collect_personas_with_packs") as mock_personas:
            mock_click.prompt.side_effect = [
                "TestApp", "A test app", "Python", "", "sonnet", 5.0, 15.0, ""
            ]
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
             patch("colonyos.init._collect_personas_with_packs") as mock_personas:
            mock_click.prompt.side_effect = [
                "TestApp", "A test app", "Python", "", "sonnet", 5.0, 15.0, ""
            ]
            # Use real echo so we can capture stderr output
            mock_click.echo = click.echo
            mock_personas.return_value = [
                Persona(role="Engineer", expertise="Backend", perspective="Scale")
            ]
            run_init(tmp_path)

        captured = capsys.readouterr()
        assert "old 'prds/'" in captured.err
        assert "old 'tasks/'" in captured.err


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
        assert "colonyos run" in captured.out

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


class TestDetectTestCommand:
    def test_makefile_with_test_target(self, tmp_path: Path):
        (tmp_path / "Makefile").write_text("test:\n\tpytest\n")
        assert _detect_test_command(tmp_path) == "make test"

    def test_package_json_with_test_script(self, tmp_path: Path):
        import json
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "jest"}}),
        )
        assert _detect_test_command(tmp_path) == "npm test"

    def test_pyproject_with_pytest(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\naddopts = '-v'\n"
        )
        assert _detect_test_command(tmp_path) == "pytest"

    def test_pytest_ini(self, tmp_path: Path):
        (tmp_path / "pytest.ini").write_text("[pytest]\n")
        assert _detect_test_command(tmp_path) == "pytest"

    def test_cargo_toml(self, tmp_path: Path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "foo"\n')
        assert _detect_test_command(tmp_path) == "cargo test"

    def test_no_test_runner_detected(self, tmp_path: Path):
        assert _detect_test_command(tmp_path) is None

    def test_priority_makefile_over_package_json(self, tmp_path: Path):
        import json
        (tmp_path / "Makefile").write_text("test:\n\tnpm test\n")
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "jest"}}),
        )
        assert _detect_test_command(tmp_path) == "make test"

    def test_priority_package_json_over_pytest(self, tmp_path: Path):
        import json
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "jest"}}),
        )
        (tmp_path / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\naddopts = '-v'\n"
        )
        assert _detect_test_command(tmp_path) == "npm test"


class TestInitVerificationInteractive:
    def test_interactive_saves_verify_command(self, tmp_path: Path):
        with patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init._collect_personas_with_packs") as mock_personas:
            mock_click.prompt.side_effect = [
                "TestApp", "A test app", "Python", "", "sonnet", 5.0, 15.0, "pytest"
            ]
            mock_click.echo = click.echo
            mock_personas.return_value = [
                Persona(role="Engineer", expertise="Backend", perspective="Scale")
            ]
            config = run_init(tmp_path)

        assert config.verification.verify_command == "pytest"

    def test_interactive_blank_input_skips(self, tmp_path: Path):
        with patch("colonyos.init.click") as mock_click, \
             patch("colonyos.init._collect_personas_with_packs") as mock_personas:
            mock_click.prompt.side_effect = [
                "TestApp", "A test app", "Python", "", "sonnet", 5.0, 15.0, ""
            ]
            mock_click.echo = click.echo
            mock_personas.return_value = [
                Persona(role="Engineer", expertise="Backend", perspective="Scale")
            ]
            config = run_init(tmp_path)

        assert config.verification.verify_command is None


class TestQuickInitVerification:
    def test_quick_auto_detects_pytest(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\naddopts = '-v'\n"
        )
        config = run_init(
            tmp_path,
            quick=True,
            project_name="TestProject",
            project_description="test",
            project_stack="Python",
        )
        assert config.verification.verify_command == "pytest"

    def test_quick_no_detection_sets_none(self, tmp_path: Path):
        config = run_init(
            tmp_path,
            quick=True,
            project_name="TestProject",
            project_description="test",
            project_stack="Python",
        )
        assert config.verification.verify_command is None
