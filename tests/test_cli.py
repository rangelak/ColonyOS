from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from colonyos.cli import app
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
