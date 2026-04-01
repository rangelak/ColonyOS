"""Tests for maintenance.py — self-update detection and installation (Task 2.0)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from colonyos.maintenance import (
    pull_and_check_update,
    read_last_good_commit,
    record_last_good_commit,
    run_self_update,
    should_rollback,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _completed(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# pull_and_check_update
# ---------------------------------------------------------------------------


class TestPullAndCheckUpdate:
    """Task 2.1 — pull_and_check_update returns (changed, old_sha, new_sha)."""

    @patch("colonyos.maintenance._git")
    def test_no_change(self, mock_git: patch, tmp_path: Path) -> None:
        sha = "abc1234"
        mock_git.side_effect = [
            _completed(stdout=f"{sha}\n"),   # rev-parse HEAD (before)
            _completed(),                     # pull --ff-only
            _completed(stdout=f"{sha}\n"),   # rev-parse HEAD (after)
        ]
        changed, old, new = pull_and_check_update(tmp_path)
        assert changed is False
        assert old == sha
        assert new == sha

    @patch("colonyos.maintenance._git")
    def test_fast_forward_success(self, mock_git: patch, tmp_path: Path) -> None:
        old_sha = "aaa1111"
        new_sha = "bbb2222"
        mock_git.side_effect = [
            _completed(stdout=f"{old_sha}\n"),
            _completed(),
            _completed(stdout=f"{new_sha}\n"),
        ]
        changed, old, new = pull_and_check_update(tmp_path)
        assert changed is True
        assert old == old_sha
        assert new == new_sha

    @patch("colonyos.maintenance._git")
    def test_pull_failure_returns_false(self, mock_git: patch, tmp_path: Path) -> None:
        sha = "ccc3333"
        mock_git.side_effect = [
            _completed(stdout=f"{sha}\n"),
            _completed(returncode=1, stderr="fatal: not possible to fast-forward"),
        ]
        changed, old, new = pull_and_check_update(tmp_path)
        assert changed is False
        assert old == sha
        assert new is None

    @patch("colonyos.maintenance._git")
    def test_no_tracking_branch(self, mock_git: patch, tmp_path: Path) -> None:
        sha = "ddd4444"
        mock_git.side_effect = [
            _completed(stdout=f"{sha}\n"),
            _completed(returncode=128, stderr="fatal: no tracking information"),
        ]
        changed, old, new = pull_and_check_update(tmp_path)
        assert changed is False
        assert old == sha
        assert new is None

    @patch("colonyos.maintenance._git")
    def test_initial_rev_parse_failure(self, mock_git: patch, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _completed(returncode=128, stderr="fatal: not a git repository"),
        ]
        changed, old, new = pull_and_check_update(tmp_path)
        assert changed is False
        assert old is None
        assert new is None

    @patch("colonyos.maintenance._git")
    def test_timeout_during_pull(self, mock_git: patch, tmp_path: Path) -> None:
        sha = "eee5555"
        mock_git.side_effect = [
            _completed(stdout=f"{sha}\n"),
            subprocess.TimeoutExpired(cmd="git pull", timeout=30),
        ]
        changed, old, new = pull_and_check_update(tmp_path)
        assert changed is False
        assert old == sha
        assert new is None


# ---------------------------------------------------------------------------
# run_self_update
# ---------------------------------------------------------------------------


class TestRunSelfUpdate:
    """Task 2.2 — run_self_update runs install command and returns success/failure."""

    @patch("colonyos.maintenance.subprocess.run")
    def test_success(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.return_value = _completed()
        assert run_self_update(tmp_path, "uv pip install .") is True
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["cwd"] == tmp_path
        assert call_kwargs.kwargs["shell"] is True

    @patch("colonyos.maintenance.subprocess.run")
    def test_nonzero_exit(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.return_value = _completed(returncode=1, stderr="error")
        assert run_self_update(tmp_path, "uv pip install .") is False

    @patch("colonyos.maintenance.subprocess.run")
    def test_timeout(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="uv pip install .", timeout=120)
        assert run_self_update(tmp_path, "uv pip install .") is False

    @patch("colonyos.maintenance.subprocess.run")
    def test_file_not_found(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.side_effect = FileNotFoundError("uv not found")
        assert run_self_update(tmp_path, "uv pip install .") is False

    @patch("colonyos.maintenance.subprocess.run")
    def test_custom_command(self, mock_run: patch, tmp_path: Path) -> None:
        mock_run.return_value = _completed()
        run_self_update(tmp_path, "pip install -e .")
        assert mock_run.call_args.args[0] == "pip install -e ."


# ---------------------------------------------------------------------------
# record_last_good_commit / read_last_good_commit
# ---------------------------------------------------------------------------


class TestLastGoodCommit:
    """Task 2.3 — file I/O to .colonyos/last_good_commit."""

    def test_roundtrip(self, tmp_path: Path) -> None:
        sha = "abc123def456"
        record_last_good_commit(tmp_path, sha)
        assert read_last_good_commit(tmp_path) == sha

    def test_read_missing_file(self, tmp_path: Path) -> None:
        assert read_last_good_commit(tmp_path) is None

    def test_overwrite(self, tmp_path: Path) -> None:
        record_last_good_commit(tmp_path, "old_sha")
        record_last_good_commit(tmp_path, "new_sha")
        assert read_last_good_commit(tmp_path) == "new_sha"

    def test_creates_colonyos_dir(self, tmp_path: Path) -> None:
        record_last_good_commit(tmp_path, "abc")
        assert (tmp_path / ".colonyos" / "last_good_commit").is_file()

    def test_strips_whitespace(self, tmp_path: Path) -> None:
        commit_file = tmp_path / ".colonyos" / "last_good_commit"
        commit_file.parent.mkdir(parents=True, exist_ok=True)
        commit_file.write_text("  abc123  \n", encoding="utf-8")
        assert read_last_good_commit(tmp_path) == "abc123"

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        commit_file = tmp_path / ".colonyos" / "last_good_commit"
        commit_file.parent.mkdir(parents=True, exist_ok=True)
        commit_file.write_text("", encoding="utf-8")
        assert read_last_good_commit(tmp_path) is None


# ---------------------------------------------------------------------------
# should_rollback
# ---------------------------------------------------------------------------


class TestShouldRollback:
    """Task 2.4 — checks last_good_commit vs HEAD + startup recency."""

    @patch("colonyos.maintenance._git")
    def test_rollback_when_sha_differs_and_recent_start(
        self, mock_git: patch, tmp_path: Path,
    ) -> None:
        record_last_good_commit(tmp_path, "old_sha")
        mock_git.return_value = _completed(stdout="new_sha\n")
        # Started 10 seconds ago → within the 60s window
        startup_time = time.time() - 10
        assert should_rollback(tmp_path, startup_time) is True

    @patch("colonyos.maintenance._git")
    def test_no_rollback_when_sha_matches(
        self, mock_git: patch, tmp_path: Path,
    ) -> None:
        record_last_good_commit(tmp_path, "same_sha")
        mock_git.return_value = _completed(stdout="same_sha\n")
        startup_time = time.time() - 10
        assert should_rollback(tmp_path, startup_time) is False

    @patch("colonyos.maintenance._git")
    def test_no_rollback_when_old_start(
        self, mock_git: patch, tmp_path: Path,
    ) -> None:
        record_last_good_commit(tmp_path, "old_sha")
        mock_git.return_value = _completed(stdout="new_sha\n")
        # Started 120 seconds ago → outside the 60s window
        startup_time = time.time() - 120
        assert should_rollback(tmp_path, startup_time) is False

    def test_no_rollback_when_no_last_good_commit(self, tmp_path: Path) -> None:
        startup_time = time.time() - 5
        assert should_rollback(tmp_path, startup_time) is False

    @patch("colonyos.maintenance._git")
    def test_no_rollback_on_git_failure(
        self, mock_git: patch, tmp_path: Path,
    ) -> None:
        record_last_good_commit(tmp_path, "old_sha")
        mock_git.return_value = _completed(returncode=128, stderr="fatal")
        startup_time = time.time() - 10
        assert should_rollback(tmp_path, startup_time) is False
