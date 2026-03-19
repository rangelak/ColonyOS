"""Tests for the git state pre-flight check."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import click
import pytest

from colonyos.models import PreflightError, PreflightResult


# ---------------------------------------------------------------------------
# PreflightResult dataclass
# ---------------------------------------------------------------------------


class TestPreflightError:
    def test_is_click_exception_subclass(self) -> None:
        assert issubclass(PreflightError, click.ClickException)

    def test_message(self) -> None:
        err = PreflightError("test error")
        assert err.format_message() == "test error"


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

    def test_from_dict_missing_required_keys_raises(self) -> None:
        with pytest.raises(ValueError, match="missing required key"):
            PreflightResult.from_dict({})
        with pytest.raises(ValueError, match="'current_branch'"):
            PreflightResult.from_dict({"is_clean": True, "branch_exists": False})
        with pytest.raises(ValueError, match="'is_clean'"):
            PreflightResult.from_dict({"current_branch": "main", "branch_exists": False})
        with pytest.raises(ValueError, match="'branch_exists'"):
            PreflightResult.from_dict({"current_branch": "main", "is_clean": True})

    def test_from_dict_with_head_sha(self) -> None:
        data = {
            "current_branch": "main",
            "is_clean": True,
            "branch_exists": False,
            "head_sha": "abc123",
        }
        result = PreflightResult.from_dict(data)
        assert result.head_sha == "abc123"

    def test_to_dict_includes_head_sha(self) -> None:
        result = PreflightResult(
            current_branch="main",
            is_clean=True,
            branch_exists=False,
            head_sha="def456",
        )
        d = result.to_dict()
        assert d["head_sha"] == "def456"

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

    @patch("colonyos.orchestrator.check_open_pr", return_value=(None, None))
    @patch("colonyos.orchestrator.subprocess.run")
    def test_existing_branch_no_pr_refuses(self, mock_run, mock_check_pr, tmp_path: Path) -> None:
        from colonyos.orchestrator import _preflight_check
        from colonyos.config import ColonyConfig

        def side_effect(cmd, **kwargs):
            if cmd[1] == "rev-parse" and "--abbrev-ref" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main\n", stderr="")
            if cmd[1] == "rev-parse" and "HEAD" in cmd and "--abbrev-ref" not in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="abc123\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[1] == "branch":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="  colonyos/test-feature\n", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        config = ColonyConfig()
        with pytest.raises(click.ClickException, match="already exists locally"):
            _preflight_check(tmp_path, "colonyos/test-feature", config)

    @patch("colonyos.orchestrator.check_open_pr", return_value=(42, "https://github.com/org/repo/pull/42"))
    @patch("colonyos.orchestrator.subprocess.run")
    def test_existing_branch_with_open_pr_refuses_with_url(self, mock_run, mock_check_pr, tmp_path: Path) -> None:
        from colonyos.orchestrator import _preflight_check
        from colonyos.config import ColonyConfig

        def side_effect(cmd, **kwargs):
            if cmd[1] == "rev-parse" and "--abbrev-ref" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main\n", stderr="")
            if cmd[1] == "rev-parse" and "HEAD" in cmd and "--abbrev-ref" not in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="abc123\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[1] == "branch":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="  colonyos/test-feature\n", stderr="")
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

    @patch("colonyos.orchestrator.check_open_pr", return_value=(99, "https://github.com/org/repo/pull/99"))
    @patch("colonyos.orchestrator.subprocess.run")
    def test_force_bypasses_all_checks(self, mock_run, mock_check_pr, tmp_path: Path) -> None:
        from colonyos.orchestrator import _preflight_check
        from colonyos.config import ColonyConfig

        def side_effect(cmd, **kwargs):
            if cmd[1] == "rev-parse" and "--abbrev-ref" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main\n", stderr="")
            if cmd[1] == "rev-parse" and "HEAD" in cmd and "--abbrev-ref" not in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="abc123\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=" M dirty.py\n", stderr="")
            if cmd[1] == "branch":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="  colonyos/test-feature\n", stderr="")
            if cmd[1] == "fetch":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[1] == "rev-list":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="0\n", stderr="")
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

        calls_made = []

        def side_effect(cmd, **kwargs):
            calls_made.append(cmd[1])
            if cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[1] == "branch":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if cmd[1] == "fetch":
                raise subprocess.TimeoutExpired(cmd="git", timeout=5)
            if cmd[1] == "rev-list":
                raise AssertionError("rev-list should not be called when fetch fails")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        config = ColonyConfig()
        result = _preflight_check(tmp_path, "colonyos/test-feature", config)
        assert result.action_taken == "proceed"
        assert any("Failed to fetch" in w for w in result.warnings)
        assert "rev-list" not in calls_made

    @patch("colonyos.orchestrator.subprocess.run")
    def test_dirty_tree_raises_preflight_error(self, mock_run, tmp_path: Path) -> None:
        """Dirty tree raises PreflightError (not generic ClickException)."""
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
        with pytest.raises(PreflightError, match="Uncommitted changes"):
            _preflight_check(tmp_path, "colonyos/test-feature", config)

    @patch("colonyos.orchestrator.subprocess.run")
    def test_git_status_nonzero_is_fail_closed(self, mock_run, tmp_path: Path) -> None:
        """git status returning non-zero exit code raises PreflightError (fail-closed)."""
        from colonyos.orchestrator import _preflight_check
        from colonyos.config import ColonyConfig

        def side_effect(cmd, **kwargs):
            if cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="main\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=128, stdout="", stderr="fatal: bad")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        config = ColonyConfig()
        with pytest.raises(PreflightError, match="git status exited with code 128"):
            _preflight_check(tmp_path, "colonyos/test-feature", config)


# ---------------------------------------------------------------------------
# _resume_preflight
# ---------------------------------------------------------------------------


class TestResumePreflight:
    @patch("colonyos.orchestrator.subprocess.run")
    def test_clean_tree_proceeds(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _resume_preflight

        def side_effect(cmd, **kwargs):
            if cmd[1] == "rev-parse" and "--abbrev-ref" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="feature\n", stderr="")
            if cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="abc123\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        result = _resume_preflight(tmp_path, "colonyos/feature")
        assert result.is_clean is True
        assert result.action_taken == "proceed"
        assert result.head_sha == "abc123"

    @patch("colonyos.orchestrator.subprocess.run")
    def test_dirty_tree_raises(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _resume_preflight

        def side_effect(cmd, **kwargs):
            if cmd[1] == "rev-parse" and "--abbrev-ref" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="feature\n", stderr="")
            if cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="abc123\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=" M file.py\n", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        with pytest.raises(click.ClickException, match="Uncommitted changes"):
            _resume_preflight(tmp_path, "colonyos/feature")

    @patch("colonyos.orchestrator.subprocess.run")
    def test_head_sha_divergence_raises(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _resume_preflight

        def side_effect(cmd, **kwargs):
            if cmd[1] == "rev-parse" and "--abbrev-ref" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="feature\n", stderr="")
            if cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="new_sha\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        with pytest.raises(click.ClickException, match="HEAD SHA has diverged"):
            _resume_preflight(tmp_path, "colonyos/feature", expected_head_sha="old_sha")

    @patch("colonyos.orchestrator.subprocess.run")
    def test_head_sha_matches_proceeds(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _resume_preflight

        def side_effect(cmd, **kwargs):
            if cmd[1] == "rev-parse" and "--abbrev-ref" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="feature\n", stderr="")
            if cmd[1] == "rev-parse":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="same_sha\n", stderr="")
            if cmd[1] == "status":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        result = _resume_preflight(tmp_path, "colonyos/feature", expected_head_sha="same_sha")
        assert result.action_taken == "proceed"
        assert result.head_sha == "same_sha"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestGetCurrentBranch:
    @patch("colonyos.orchestrator.subprocess.run")
    def test_returns_branch_name(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _get_current_branch

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="feature-branch\n", stderr=""
        )
        assert _get_current_branch(tmp_path) == "feature-branch"

    @patch("colonyos.orchestrator.subprocess.run")
    def test_empty_output_raises(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _get_current_branch

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with pytest.raises(click.ClickException, match="Could not determine current branch"):
            _get_current_branch(tmp_path)

    @patch("colonyos.orchestrator.subprocess.run", side_effect=OSError("no git"))
    def test_oserror_raises(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _get_current_branch

        with pytest.raises(click.ClickException, match="Failed to run git"):
            _get_current_branch(tmp_path)


class TestCheckWorkingTreeClean:
    @patch("colonyos.orchestrator.subprocess.run")
    def test_clean_tree(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _check_working_tree_clean

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        is_clean, dirty = _check_working_tree_clean(tmp_path)
        assert is_clean is True
        assert dirty == ""

    @patch("colonyos.orchestrator.subprocess.run")
    def test_dirty_tree(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _check_working_tree_clean

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=" M file.py\n", stderr=""
        )
        is_clean, dirty = _check_working_tree_clean(tmp_path)
        assert is_clean is False
        assert "file.py" in dirty

    @patch("colonyos.orchestrator.subprocess.run", side_effect=OSError("no git"))
    def test_oserror_raises(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _check_working_tree_clean

        with pytest.raises(PreflightError, match="Failed to run git status"):
            _check_working_tree_clean(tmp_path)

    @patch("colonyos.orchestrator.subprocess.run")
    def test_nonzero_returncode_raises(self, mock_run, tmp_path: Path) -> None:
        """Fail-closed: non-zero returncode from git status raises PreflightError."""
        from colonyos.orchestrator import _check_working_tree_clean

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="fatal: not a git repository"
        )
        with pytest.raises(PreflightError, match="git status exited with code 128"):
            _check_working_tree_clean(tmp_path)

    @patch("colonyos.orchestrator.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30))
    def test_timeout_raises(self, mock_run, tmp_path: Path) -> None:
        """git status timeout raises PreflightError."""
        from colonyos.orchestrator import _check_working_tree_clean

        with pytest.raises(PreflightError, match="timed out"):
            _check_working_tree_clean(tmp_path)


class TestGetHeadSha:
    @patch("colonyos.orchestrator.subprocess.run")
    def test_returns_sha(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _get_head_sha

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="abc123def456\n", stderr=""
        )
        assert _get_head_sha(tmp_path) == "abc123def456"

    @patch("colonyos.orchestrator.subprocess.run")
    def test_failure_returns_empty(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _get_head_sha

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        assert _get_head_sha(tmp_path) == ""

    @patch("colonyos.orchestrator.subprocess.run", side_effect=OSError("no git"))
    def test_oserror_returns_empty(self, mock_run, tmp_path: Path) -> None:
        from colonyos.orchestrator import _get_head_sha

        assert _get_head_sha(tmp_path) == ""


class TestEnsureOnMain:
    @patch("colonyos.cli.subprocess.run")
    def test_checkout_and_pull_success(self, mock_run, tmp_path: Path) -> None:
        from colonyos.cli import _ensure_on_main

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        _ensure_on_main(tmp_path)  # should not raise
        assert mock_run.call_count == 2

    @patch("colonyos.cli.subprocess.run", side_effect=OSError("no git"))
    def test_checkout_oserror_raises(self, mock_run, tmp_path: Path) -> None:
        from colonyos.cli import _ensure_on_main

        with pytest.raises(click.ClickException, match="Failed to checkout main"):
            _ensure_on_main(tmp_path)

    @patch("colonyos.cli.subprocess.run")
    def test_checkout_nonzero_returncode_raises(self, mock_run, tmp_path: Path) -> None:
        """Non-zero returncode from git checkout raises ClickException."""
        from colonyos.cli import _ensure_on_main

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error: pathspec 'main' did not match"
        )
        with pytest.raises(click.ClickException, match="Failed to checkout main"):
            _ensure_on_main(tmp_path)

    @patch("colonyos.cli.subprocess.run")
    def test_pull_failure_warns_but_proceeds(self, mock_run, tmp_path: Path, capsys) -> None:
        from colonyos.cli import _ensure_on_main

        def side_effect(cmd, **kwargs):
            if "checkout" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if "pull" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="conflict")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        _ensure_on_main(tmp_path)  # should not raise
        captured = capsys.readouterr()
        assert "git pull --ff-only failed" in captured.err
