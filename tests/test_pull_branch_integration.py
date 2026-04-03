"""Integration tests for auto-pull-on-branch-switch behaviour.

These tests verify end-to-end pull behaviour across the three pipeline
entry points (daemon restore, orchestrator preflight/checkout, CLI
ensure-on-main) and confirm that the thread-fix path and offline mode
are correctly excluded.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch


from colonyos.config import ColonyConfig
from colonyos.models import ProjectInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


# ---------------------------------------------------------------------------
# 5.1a — Daemon queue item: restore_to_branch() pulls before next item
# ---------------------------------------------------------------------------


class TestDaemonRestorePullsIntegration:
    """restore_to_branch() should pull after checkout so the daemon starts
    the next queue item from up-to-date remote state."""

    @patch("colonyos.recovery.pull_branch")
    @patch("colonyos.recovery._git")
    def test_restore_to_branch_calls_pull_after_checkout(
        self, mock_git: MagicMock, mock_pull: MagicMock, tmp_path: Path,
    ) -> None:
        from colonyos.recovery import restore_to_branch

        mock_git.side_effect = [
            _completed("feature-x\n"),  # rev-parse HEAD → current branch
            _completed(""),              # status --porcelain → clean
            _completed(""),              # checkout main
            _completed(""),              # stash list
        ]
        mock_pull.return_value = (True, None)

        desc = restore_to_branch(tmp_path, "main")

        # pull_branch was called exactly once with the repo root
        mock_pull.assert_called_once_with(tmp_path)
        assert desc is not None
        assert "pulled latest" in desc

    @patch("colonyos.recovery.pull_branch")
    @patch("colonyos.recovery._git")
    def test_restore_pull_failure_does_not_block_daemon(
        self, mock_git: MagicMock, mock_pull: MagicMock, tmp_path: Path,
    ) -> None:
        """Even when pull fails, restore_to_branch succeeds so the daemon
        can continue processing the next queue item."""
        from colonyos.recovery import restore_to_branch

        mock_git.side_effect = [
            _completed("feature-x\n"),
            _completed(""),
            _completed(""),
            _completed(""),
        ]
        mock_pull.return_value = (False, "Could not resolve host")

        desc = restore_to_branch(tmp_path, "main")

        # Function returns a description (non-None) indicating success
        assert desc is not None
        assert "Restored to main" in desc


# ---------------------------------------------------------------------------
# 5.1b — Orchestrator run(): main is pulled in preflight and base branch
#         is pulled at checkout
# ---------------------------------------------------------------------------


class TestOrchestratorPullIntegration:
    """The orchestrator must pull in two places: preflight and base-branch
    checkout.  Both must use the shared pull_branch() helper."""

    @staticmethod
    def _make_config() -> ColonyConfig:
        return ColonyConfig(
            project=ProjectInfo(name="test", description="test", stack="python"),
        )

    # --- Preflight pulls current branch ---

    @patch("colonyos.orchestrator.pull_branch", return_value=(True, None))
    @patch("colonyos.orchestrator._get_head_sha", return_value="abc123")
    @patch("colonyos.orchestrator.check_open_pr", return_value=(None, None))
    @patch("colonyos.orchestrator.validate_branch_exists", return_value=(False, ""))
    @patch("colonyos.orchestrator._check_working_tree_clean", return_value=(True, ""))
    @patch("colonyos.orchestrator._get_current_branch", return_value="main")
    def test_preflight_pulls_and_clears_behind_count(
        self, _br, _clean, _exists, _pr, _sha, mock_pull,
    ) -> None:
        from colonyos.orchestrator import _preflight_check

        result = _preflight_check(Path("/tmp/r"), "feat", self._make_config())
        mock_pull.assert_called_once_with(Path("/tmp/r"))
        assert result.main_behind_count == 0

    # --- Base-branch checkout hard-fails on pull failure ---

    def test_base_branch_checkout_raises_on_pull_failure(self, tmp_path: Path) -> None:
        """When pull fails after base-branch checkout in run(), PreflightError
        is raised with a clear message about the pull failure."""
        import inspect
        from colonyos.orchestrator import run as run_fn

        # Verify via source: pull failure in base-branch section raises PreflightError.
        source = inspect.getsource(run_fn)
        assert "pull_ok, pull_err = pull_branch(repo_root)" in source
        assert "if not pull_ok and pull_err is not None:" in source
        assert 'raise PreflightError(' in source
        assert "Failed to pull latest for base branch" in source


# ---------------------------------------------------------------------------
# 5.1c — Thread-fix path: confirm NO pull occurs (SHA integrity)
# ---------------------------------------------------------------------------


class TestThreadFixNoPullIntegration:
    """The thread-fix path must never call pull_branch because pulling would
    change HEAD and break the SHA integrity check used to detect force-pushes."""

    def test_run_thread_fix_source_excludes_pull_branch(self) -> None:
        import inspect
        from colonyos.orchestrator import run_thread_fix

        source = inspect.getsource(run_thread_fix)
        assert "pull_branch" not in source, (
            "run_thread_fix must NOT call pull_branch — "
            "pulling would invalidate the HEAD SHA integrity check"
        )


# ---------------------------------------------------------------------------
# 5.1d — Offline mode: confirm zero network calls across all paths
# ---------------------------------------------------------------------------


class TestOfflineSkipsPullEverywhere:
    """When offline=True, pull_branch must not be called in any code path."""

    @staticmethod
    def _make_config() -> ColonyConfig:
        return ColonyConfig(
            project=ProjectInfo(name="test", description="test", stack="python"),
        )

    # --- Preflight offline ---

    @patch("colonyos.orchestrator.pull_branch")
    @patch("colonyos.orchestrator._get_head_sha", return_value="abc123")
    @patch("colonyos.orchestrator.check_open_pr", return_value=(None, None))
    @patch("colonyos.orchestrator.validate_branch_exists", return_value=(False, ""))
    @patch("colonyos.orchestrator._check_working_tree_clean", return_value=(True, ""))
    @patch("colonyos.orchestrator._get_current_branch", return_value="main")
    def test_preflight_offline_no_pull(
        self, _br, _clean, _exists, _pr, _sha, mock_pull,
    ) -> None:
        from colonyos.orchestrator import _preflight_check

        _preflight_check(Path("/tmp/r"), "feat", self._make_config(), offline=True)
        mock_pull.assert_not_called()

    # --- Base-branch checkout offline (verified via source) ---

    def test_base_branch_checkout_offline_guard_exists(self) -> None:
        """The base-branch pull in run() is gated behind 'if not offline'."""
        import inspect
        from colonyos.orchestrator import run as run_fn

        source = inspect.getsource(run_fn)
        assert "if not offline:" in source
        assert "pull_branch(repo_root)" in source

    # --- CLI _ensure_on_main offline ---

    def test_cli_ensure_on_main_offline_no_pull(self, tmp_path: Path) -> None:
        from colonyos.cli import _ensure_on_main

        checkout_result = MagicMock(returncode=0, stderr="")
        with patch("colonyos.cli.subprocess.run", return_value=checkout_result), \
             patch("colonyos.cli.pull_branch") as mock_pull:
            _ensure_on_main(tmp_path, offline=True)

        mock_pull.assert_not_called()

    # --- Daemon restore_to_branch with pull=False ---

    @patch("colonyos.recovery.pull_branch")
    @patch("colonyos.recovery._git")
    def test_restore_to_branch_pull_false_no_network(
        self, mock_git: MagicMock, mock_pull: MagicMock, tmp_path: Path,
    ) -> None:
        from colonyos.recovery import restore_to_branch

        mock_git.side_effect = [
            _completed("feature-x\n"),
            _completed(""),
            _completed(""),
            _completed(""),
        ]

        restore_to_branch(tmp_path, "main", pull=False)
        mock_pull.assert_not_called()


# ---------------------------------------------------------------------------
# 5.1e — Cross-cutting: pull_branch is the single shared helper
# ---------------------------------------------------------------------------


class TestSharedPullHelper:
    """All three entry points must use the same pull_branch() from recovery."""

    def test_orchestrator_imports_pull_branch_from_recovery(self) -> None:
        import colonyos.orchestrator as mod

        assert hasattr(mod, "pull_branch")
        from colonyos.recovery import pull_branch

        assert mod.pull_branch is pull_branch

    def test_cli_imports_pull_branch_from_recovery(self) -> None:
        import colonyos.cli as mod

        assert hasattr(mod, "pull_branch")
        from colonyos.recovery import pull_branch

        assert mod.pull_branch is pull_branch
