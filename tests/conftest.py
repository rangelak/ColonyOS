"""Shared test fixtures for ColonyOS server tests."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml


def _make_fake_git_subprocess_run():
    """Return a subprocess.run replacement that simulates git without invoking it."""

    def fake_run(cmd, cwd=None, capture_output=False, text=False, check=False, **kwargs):
        args = list(cmd)
        mock = MagicMock()
        mock.returncode = 0
        mock.stderr = ""
        mock.stdout = ""

        if not args or args[0] != "git":
            return mock

        rest = args[1:]

        if rest[:2] == ["rev-parse", "--is-shallow-repository"]:
            mock.stdout = "false\n"
            return mock

        if rest == ["--version"]:
            mock.stdout = "git version 2.43.0\n"
            return mock

        if rest[:2] == ["worktree", "add"]:
            wt_path = Path(rest[2])
            wt_path.mkdir(parents=True, exist_ok=True)
            (wt_path / ".git").write_text("gitdir: ../../.git\n", encoding="utf-8")
            return mock

        if rest[:3] == ["worktree", "remove", "--force"]:
            path = Path(rest[3])
            if path.exists():
                shutil.rmtree(path)
            return mock

        if rest[:2] == ["worktree", "prune"]:
            return mock

        if rest[:3] == ["worktree", "list", "--porcelain"]:
            mock.stdout = ""
            return mock

        if rest[:2] == ["branch", "--list"]:
            mock.stdout = "  main\n  task-1.0\n"
            return mock

        if rest and rest[0] == "merge":
            return mock

        return mock

    return fake_run


@pytest.fixture
def mock_git_subprocess():
    """Patch subprocess.run in modules that call git — NOT the global one."""
    from unittest.mock import patch
    fake = _make_fake_git_subprocess_run()
    targets = [
        "colonyos.orchestrator.subprocess.run",
        "colonyos.parallel_preflight.subprocess.run",
        "colonyos.worktree.subprocess.run",
    ]
    patches = [patch(t, side_effect=fake) for t in targets]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture(autouse=True)
def _strip_git_env_vars(monkeypatch):
    """Prevent pre-commit's GIT_INDEX_FILE (and friends) from leaking into
    test subprocesses.  When pytest runs as a pre-commit hook, git sets
    GIT_INDEX_FILE to a temp index — any subprocess.run(["git", ...]) in
    tests or source code inherits it and corrupts the parent repo's index."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)


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
