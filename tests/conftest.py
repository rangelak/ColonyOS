"""Shared test fixtures for ColonyOS server tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a temporary repo root with .colonyos/runs/ directory."""
    runs_dir = tmp_path / ".colonyos" / "runs"
    runs_dir.mkdir(parents=True)
    return tmp_path


def write_config(repo_root: Path) -> None:
    """Write a minimal config.yaml for testing."""
    config_dir = repo_root / ".colonyos"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "model": "sonnet",
        "project": {"name": "test-project", "description": "A test", "stack": "python"},
        "personas": [
            {
                "role": "Security Engineer",
                "expertise": "AppSec",
                "perspective": "defensive",
                "reviewer": True,
            }
        ],
        "budget": {"per_phase": 5.0, "per_run": 15.0},
        "phases": {"plan": True, "implement": True, "review": True, "deliver": True},
    }
    (config_dir / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False), encoding="utf-8"
    )
