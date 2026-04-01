"""Tests for maintenance.py — self-update and branch sync (Tasks 2.0 & 3.0)."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from colonyos.maintenance import (
    BranchStatus,
    format_branch_sync_report,
    pull_and_check_update,
    read_last_good_commit,
    record_last_good_commit,
    run_self_update,
    scan_diverged_branches,
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


# ---------------------------------------------------------------------------
# scan_diverged_branches (Task 3.1)
# ---------------------------------------------------------------------------


class TestScanDivergedBranches:
    """Task 3.1 — scan_diverged_branches returns list[BranchStatus]."""

    @patch("colonyos.maintenance._fetch_open_prs_for_prefix")
    @patch("colonyos.maintenance._git")
    def test_no_branches(self, mock_git, mock_prs, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _completed(),  # fetch --prune
            _completed(stdout=""),  # branch -r --list
        ]
        result = scan_diverged_branches(tmp_path)
        assert result == []

    @patch("colonyos.maintenance._fetch_open_prs_for_prefix")
    @patch("colonyos.maintenance._git")
    def test_all_up_to_date(self, mock_git, mock_prs, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _completed(),  # fetch --prune
            _completed(stdout="origin/colonyos/feat-a\n"),  # branch -r
            _completed(stdout="0\t0\n"),  # rev-list (ahead=0, behind=0)
        ]
        mock_prs.return_value = {}
        result = scan_diverged_branches(tmp_path)
        assert result == []

    @patch("colonyos.maintenance._fetch_open_prs_for_prefix")
    @patch("colonyos.maintenance._git")
    def test_some_diverged(self, mock_git, mock_prs, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _completed(),  # fetch --prune
            _completed(stdout="origin/colonyos/feat-a\norigin/colonyos/feat-b\n"),
            _completed(stdout="3\t5\n"),  # feat-a: 3 ahead, 5 behind
            _completed(stdout="0\t0\n"),  # feat-b: up-to-date
        ]
        mock_prs.return_value = {"colonyos/feat-a": 42}
        result = scan_diverged_branches(tmp_path)
        assert len(result) == 1
        assert result[0].name == "colonyos/feat-a"
        assert result[0].ahead == 3
        assert result[0].behind == 5
        assert result[0].has_open_pr is True
        assert result[0].pr_number == 42

    @patch("colonyos.maintenance._fetch_open_prs_for_prefix")
    @patch("colonyos.maintenance._git")
    def test_branch_without_pr(self, mock_git, mock_prs, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _completed(),  # fetch --prune
            _completed(stdout="origin/colonyos/orphan\n"),
            _completed(stdout="1\t2\n"),  # 1 ahead, 2 behind
        ]
        mock_prs.return_value = {}
        result = scan_diverged_branches(tmp_path)
        assert len(result) == 1
        assert result[0].has_open_pr is False
        assert result[0].pr_number is None

    @patch("colonyos.maintenance._fetch_open_prs_for_prefix")
    @patch("colonyos.maintenance._git")
    def test_git_branch_list_failure(self, mock_git, mock_prs, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _completed(),  # fetch --prune
            _completed(returncode=1, stderr="error"),  # branch -r failed
        ]
        result = scan_diverged_branches(tmp_path)
        assert result == []

    @patch("colonyos.maintenance._fetch_open_prs_for_prefix")
    @patch("colonyos.maintenance._git")
    def test_fetch_failure_continues(self, mock_git, mock_prs, tmp_path: Path) -> None:
        """git fetch failure should not prevent scanning with stale refs."""
        mock_git.side_effect = [
            subprocess.TimeoutExpired(cmd="git fetch", timeout=30),  # fetch fails
            _completed(stdout="origin/colonyos/feat-x\n"),  # branch -r works
            _completed(stdout="0\t3\n"),  # behind only
        ]
        mock_prs.return_value = {}
        result = scan_diverged_branches(tmp_path)
        assert len(result) == 1
        assert result[0].behind == 3

    @patch("colonyos.maintenance._fetch_open_prs_for_prefix")
    @patch("colonyos.maintenance._git")
    def test_rev_list_failure_skips_branch(self, mock_git, mock_prs, tmp_path: Path) -> None:
        mock_git.side_effect = [
            _completed(),  # fetch --prune
            _completed(stdout="origin/colonyos/broken\n"),
            _completed(returncode=128, stderr="fatal"),  # rev-list fails
        ]
        mock_prs.return_value = {}
        result = scan_diverged_branches(tmp_path)
        assert result == []

    @patch("colonyos.maintenance._fetch_open_prs_for_prefix")
    @patch("colonyos.maintenance._git")
    def test_only_ahead_included(self, mock_git, mock_prs, tmp_path: Path) -> None:
        """Branches that are ahead-only (behind=0, ahead>0) are still diverged."""
        mock_git.side_effect = [
            _completed(),  # fetch --prune
            _completed(stdout="origin/colonyos/ahead-only\n"),
            _completed(stdout="5\t0\n"),  # 5 ahead, 0 behind
        ]
        mock_prs.return_value = {}
        result = scan_diverged_branches(tmp_path)
        assert len(result) == 1
        assert result[0].ahead == 5
        assert result[0].behind == 0


# ---------------------------------------------------------------------------
# format_branch_sync_report (Task 3.2)
# ---------------------------------------------------------------------------


class TestFormatBranchSyncReport:
    """Task 3.2 — format_branch_sync_report returns Slack mrkdwn summary."""

    def test_empty_list_returns_none(self) -> None:
        assert format_branch_sync_report([]) is None

    def test_single_branch(self) -> None:
        branches = [BranchStatus(name="colonyos/feat", ahead=1, behind=3, has_open_pr=True, pr_number=10)]
        report = format_branch_sync_report(branches)
        assert report is not None
        assert "*Branch Sync Report*" in report
        assert "`colonyos/feat`" in report
        assert "3 behind" in report
        assert "1 ahead" in report
        assert "PR #10" in report
        assert "1 diverged branch(es)" in report

    def test_multiple_branches_sorted_by_behind(self) -> None:
        branches = [
            BranchStatus(name="colonyos/a", ahead=0, behind=2),
            BranchStatus(name="colonyos/b", ahead=0, behind=10),
            BranchStatus(name="colonyos/c", ahead=0, behind=5),
        ]
        report = format_branch_sync_report(branches)
        assert report is not None
        lines = report.splitlines()
        # Find the bullet lines
        bullets = [l for l in lines if l.startswith("\u2022")]
        assert len(bullets) == 3
        # Most behind first
        assert "colonyos/b" in bullets[0]
        assert "colonyos/c" in bullets[1]
        assert "colonyos/a" in bullets[2]

    def test_branch_without_pr(self) -> None:
        branches = [BranchStatus(name="colonyos/orphan", ahead=2, behind=1)]
        report = format_branch_sync_report(branches)
        assert report is not None
        assert "PR #" not in report

    def test_ahead_only_branch(self) -> None:
        branches = [BranchStatus(name="colonyos/ahead", ahead=5, behind=0)]
        report = format_branch_sync_report(branches)
        assert report is not None
        assert "5 ahead" in report
        assert "behind" not in report.split("`colonyos/ahead`")[1].split("\n")[0]


# ---------------------------------------------------------------------------
# _fetch_open_prs_for_prefix
# ---------------------------------------------------------------------------


class TestFetchOpenPrsForPrefix:
    """Test the internal _fetch_open_prs_for_prefix helper."""

    @patch("colonyos.maintenance.subprocess.run")
    def test_returns_matching_prs(self, mock_run, tmp_path: Path) -> None:
        from colonyos.maintenance import _fetch_open_prs_for_prefix

        mock_run.return_value = _completed(
            stdout=json.dumps([
                {"number": 10, "headRefName": "colonyos/feat-a"},
                {"number": 20, "headRefName": "colonyos/feat-b"},
                {"number": 30, "headRefName": "other/branch"},
            ])
        )
        result = _fetch_open_prs_for_prefix(tmp_path, "colonyos/")
        assert result == {"colonyos/feat-a": 10, "colonyos/feat-b": 20}

    @patch("colonyos.maintenance.subprocess.run")
    def test_gh_failure_returns_empty(self, mock_run, tmp_path: Path) -> None:
        from colonyos.maintenance import _fetch_open_prs_for_prefix

        mock_run.return_value = _completed(returncode=1, stderr="not logged in")
        result = _fetch_open_prs_for_prefix(tmp_path, "colonyos/")
        assert result == {}

    @patch("colonyos.maintenance.subprocess.run")
    def test_timeout_returns_empty(self, mock_run, tmp_path: Path) -> None:
        from colonyos.maintenance import _fetch_open_prs_for_prefix

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=10)
        result = _fetch_open_prs_for_prefix(tmp_path, "colonyos/")
        assert result == {}

    @patch("colonyos.maintenance.subprocess.run")
    def test_invalid_json_returns_empty(self, mock_run, tmp_path: Path) -> None:
        from colonyos.maintenance import _fetch_open_prs_for_prefix

        mock_run.return_value = _completed(stdout="not json")
        result = _fetch_open_prs_for_prefix(tmp_path, "colonyos/")
        assert result == {}
