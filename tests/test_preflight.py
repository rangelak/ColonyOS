"""Tests for the git state pre-flight check."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import click
import pytest

from colonyos.models import PreflightResult


# ---------------------------------------------------------------------------
# PreflightResult dataclass
# ---------------------------------------------------------------------------


class TestPreflightResult:
    def test_defaults(self) -> None:
        result = PreflightResult(
            current_branch="main",
            is_clean=True,
            branch_exists=False,
        )
        assert result.action_taken == "proceed"
        assert result.warnings == []
        assert result.open_pr_number is None
        assert result.open_pr_url is None
        assert result.main_behind_count is None

    def test_to_dict(self) -> None:
        result = PreflightResult(
            current_branch="main",
            is_clean=True,
            branch_exists=False,
            open_pr_number=42,
            open_pr_url="https://github.com/org/repo/pull/42",
            main_behind_count=3,
            action_taken="proceed",
            warnings=["main is behind"],
        )
        d = result.to_dict()
        assert d["current_branch"] == "main"
        assert d["is_clean"] is True
        assert d["branch_exists"] is False
        assert d["open_pr_number"] == 42
        assert d["open_pr_url"] == "https://github.com/org/repo/pull/42"
        assert d["main_behind_count"] == 3
        assert d["action_taken"] == "proceed"
        assert d["warnings"] == ["main is behind"]

    def test_from_dict(self) -> None:
        data = {
            "current_branch": "feature",
            "is_clean": False,
            "branch_exists": True,
            "open_pr_number": 7,
            "open_pr_url": "https://github.com/org/repo/pull/7",
            "main_behind_count": 10,
            "action_taken": "forced",
            "warnings": ["dirty tree"],
        }
        result = PreflightResult.from_dict(data)
        assert result.current_branch == "feature"
        assert result.is_clean is False
        assert result.branch_exists is True
        assert result.open_pr_number == 7
        assert result.main_behind_count == 10
        assert result.action_taken == "forced"
        assert result.warnings == ["dirty tree"]

    def test_roundtrip(self) -> None:
        original = PreflightResult(
            current_branch="main",
            is_clean=True,
            branch_exists=True,
            open_pr_number=5,
            open_pr_url="https://github.com/org/repo/pull/5",
            main_behind_count=0,
            action_taken="proceed",
            warnings=["warning 1", "warning 2"],
        )
        restored = PreflightResult.from_dict(original.to_dict())
        assert restored.current_branch == original.current_branch
        assert restored.is_clean == original.is_clean
        assert restored.branch_exists == original.branch_exists
        assert restored.open_pr_number == original.open_pr_number
        assert restored.open_pr_url == original.open_pr_url
        assert restored.main_behind_count == original.main_behind_count
        assert restored.action_taken == original.action_taken
        assert restored.warnings == original.warnings

    def test_from_dict_with_defaults(self) -> None:
        result = PreflightResult.from_dict({})
        assert result.current_branch == ""
        assert result.is_clean is True
        assert result.branch_exists is False
        assert result.action_taken == "proceed"
        assert result.warnings == []

    def test_warnings_list_is_independent_copy(self) -> None:
        original = PreflightResult(
            current_branch="main", is_clean=True, branch_exists=False,
            warnings=["w1"],
        )
        d = original.to_dict()
        d["warnings"].append("w2")
        assert original.warnings == ["w1"]


# ---------------------------------------------------------------------------
# _preflight_check
# ---------------------------------------------------------------------------


class TestPreflightCheck:
    """Tests for _preflight_check using mocked subprocess calls."""

    @patch("colonyos.orchestrator.subprocess.run")
    def test_clean_repo_on_main_proceeds(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _preflight_check
        from colonyos.config import ColonyConfig

        def side_effect(cmd, **kwargs):
            if cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[1] == "branch":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[1] == "fetch":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[1] == "rev-list":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="0\n", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        config = ColonyConfig()
        result = _preflight_check(tmp_path, "colonyos/test-feature", config)
        assert result.is_clean is True
        assert result.branch_exists is False
        assert result.action_taken == "proceed"

    @patch("colonyos.orchestrator.subprocess.run")
    def test_dirty_tree_raises(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _preflight_check
        from colonyos.config import ColonyConfig

        def side_effect(cmd, **kwargs):
            if cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=" M file.py\n", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        config = ColonyConfig()
        with pytest.raises(click.ClickException, match="Uncommitted changes"):
            _preflight_check(tmp_path, "colonyos/test-feature", config)

    @patch("subprocess.run")
    def test_existing_branch_no_pr_refuses(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _preflight_check
        from colonyos.config import ColonyConfig

        def side_effect(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main\n", stderr="")
            if cmd[0] == "git" and cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[0] == "git" and cmd[1] == "branch":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="  colonyos/test-feature\n", stderr="")
            if cmd[0] == "gh":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="[]", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        config = ColonyConfig()
        with pytest.raises(click.ClickException, match="already exists locally"):
            _preflight_check(tmp_path, "colonyos/test-feature", config)

    @patch("subprocess.run")
    def test_existing_branch_with_open_pr_refuses_with_url(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _preflight_check
        from colonyos.config import ColonyConfig

        def side_effect(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main\n", stderr="")
            if cmd[0] == "git" and cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[0] == "git" and cmd[1] == "branch":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="  colonyos/test-feature\n", stderr="")
            if cmd[0] == "gh":
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0,
                    stdout=json.dumps([{"number": 42, "url": "https://github.com/org/repo/pull/42"}]),
                    stderr="",
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        config = ColonyConfig()
        with pytest.raises(click.ClickException, match="PR #42"):
            _preflight_check(tmp_path, "colonyos/test-feature", config)

    @patch("colonyos.orchestrator.subprocess.run")
    def test_main_behind_warns(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _preflight_check
        from colonyos.config import ColonyConfig

        def side_effect(cmd, **kwargs):
            if cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[1] == "branch":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[1] == "fetch":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[1] == "rev-list":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="5\n", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        config = ColonyConfig()
        result = _preflight_check(tmp_path, "colonyos/test-feature", config)
        assert result.main_behind_count == 5
        assert any("behind" in w for w in result.warnings)

    @patch("colonyos.orchestrator.subprocess.run")
    def test_offline_skips_network(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _preflight_check
        from colonyos.config import ColonyConfig

        def side_effect(cmd, **kwargs):
            if cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[1] == "branch":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            # fetch and rev-list should NOT be called in offline mode
            if cmd[1] in ("fetch", "rev-list"):
                raise AssertionError("Network call should not be made in offline mode")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        config = ColonyConfig()
        result = _preflight_check(tmp_path, "colonyos/test-feature", config, offline=True)
        assert result.main_behind_count is None

    @patch("subprocess.run")
    def test_force_bypasses_all_checks(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _preflight_check
        from colonyos.config import ColonyConfig

        def side_effect(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main\n", stderr="")
            if cmd[0] == "git" and cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=" M dirty.py\n", stderr="")
            if cmd[0] == "git" and cmd[1] == "branch":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="  colonyos/test-feature\n", stderr="")
            if cmd[0] == "git" and cmd[1] == "fetch":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[0] == "git" and cmd[1] == "rev-list":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="0\n", stderr="")
            if cmd[0] == "gh":
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0,
                    stdout=json.dumps([{"number": 99, "url": "https://github.com/org/repo/pull/99"}]),
                    stderr="",
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        config = ColonyConfig()
        result = _preflight_check(tmp_path, "colonyos/test-feature", config, force=True)
        assert result.action_taken == "forced"
        assert result.is_clean is False
        assert result.branch_exists is True

    @patch("colonyos.orchestrator.subprocess.run")
    def test_fetch_timeout_degrades_gracefully(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _preflight_check
        from colonyos.config import ColonyConfig

        call_count = 0

        def side_effect(cmd, **kwargs):
            nonlocal call_count
            if cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[1] == "branch":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[1] == "fetch":
                raise subprocess.TimeoutExpired(cmd="git", timeout=5)
            if cmd[1] == "rev-list":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="0\n", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        config = ColonyConfig()
        result = _preflight_check(tmp_path, "colonyos/test-feature", config)
        assert result.action_taken == "proceed"
        assert any("Failed to fetch" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# _resume_preflight
# ---------------------------------------------------------------------------


class TestResumePreflight:
    @patch("colonyos.orchestrator.subprocess.run")
    def test_clean_tree_proceeds(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _resume_preflight

        def side_effect(cmd, **kwargs):
            if cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="feature\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        result = _resume_preflight(tmp_path, "colonyos/feature")
        assert result.is_clean is True
        assert result.action_taken == "proceed"

    @patch("colonyos.orchestrator.subprocess.run")
    def test_dirty_tree_raises(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _resume_preflight

        def side_effect(cmd, **kwargs):
            if cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="feature\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=" M file.py\n", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        with pytest.raises(click.ClickException, match="Uncommitted changes"):
            _resume_preflight(tmp_path, "colonyos/feature")
