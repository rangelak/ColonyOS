from pathlib import Path

import pytest
import yaml

from colonyos.config import (
    ColonyConfig,
    BudgetConfig,
    PhasesConfig,
    load_config,
    save_config,
)
from colonyos.models import Persona, ProjectInfo


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    return tmp_path


class TestLoadConfig:
    def test_returns_defaults_when_no_config(self, tmp_repo: Path):
        config = load_config(tmp_repo)
        assert config.model == "sonnet"
        assert config.budget.per_phase == 5.0
        assert config.budget.per_run == 15.0
        assert config.phases.plan is True
        assert config.phases.implement is True
        assert config.phases.deliver is True
        assert config.prds_dir == "prds"
        assert config.tasks_dir == "tasks"
        assert config.personas == []
        assert config.project is None

    def test_loads_from_yaml(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "project": {
                    "name": "TestApp",
                    "description": "A test",
                    "stack": "Python",
                },
                "personas": [
                    {
                        "role": "Engineer",
                        "expertise": "Backend",
                        "perspective": "Thinks about scale",
                    }
                ],
                "model": "claude-opus-4-20250514",
                "budget": {"per_phase": 10.0, "per_run": 30.0},
                "phases": {"plan": True, "implement": True, "deliver": False},
                "branch_prefix": "feat/",
                "prds_dir": "docs/prds",
                "tasks_dir": "docs/tasks",
            }),
            encoding="utf-8",
        )

        config = load_config(tmp_repo)
        assert config.project is not None
        assert config.project.name == "TestApp"
        assert config.project.stack == "Python"
        assert len(config.personas) == 1
        assert config.personas[0].role == "Engineer"
        assert config.model == "claude-opus-4-20250514"
        assert config.budget.per_phase == 10.0
        assert config.phases.deliver is False
        assert config.prds_dir == "docs/prds"

    def test_ignores_personas_without_role(self, tmp_repo: Path):
        config_dir = tmp_repo / ".colonyos"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "personas": [
                    {"role": "", "expertise": "x", "perspective": "y"},
                    {"role": "Valid", "expertise": "x", "perspective": "y"},
                ]
            }),
            encoding="utf-8",
        )
        config = load_config(tmp_repo)
        assert len(config.personas) == 1
        assert config.personas[0].role == "Valid"


class TestSaveConfig:
    def test_roundtrip(self, tmp_repo: Path):
        original = ColonyConfig(
            project=ProjectInfo(name="MyApp", description="desc", stack="Go"),
            personas=[
                Persona(role="Lead", expertise="Arch", perspective="Big picture")
            ],
            model="test-model",
            budget=BudgetConfig(per_phase=2.0, per_run=6.0),
            phases=PhasesConfig(plan=True, implement=False, deliver=True),
            branch_prefix="test/",
            prds_dir="p",
            tasks_dir="t",
        )

        save_config(tmp_repo, original)
        loaded = load_config(tmp_repo)

        assert loaded.project is not None
        assert loaded.project.name == "MyApp"
        assert loaded.personas[0].role == "Lead"
        assert loaded.model == "test-model"
        assert loaded.budget.per_phase == 2.0
        assert loaded.phases.implement is False
        assert loaded.prds_dir == "p"
