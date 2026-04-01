from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from colonyos.recovery import (
    dirty_paths_from_status,
    preserve_and_reset_worktree,
    pull_branch,
    snapshot_dirty_state,
)


def test_dirty_paths_from_status_parses_conflicts() -> None:
    dirty = "UU src/app.py\nAA tests/test_app.py\n?? notes.md\n"
    assert dirty_paths_from_status(dirty) == [
        "src/app.py",
        "tests/test_app.py",
        "notes.md",
    ]


@patch("colonyos.recovery._git")
def test_snapshot_dirty_state_captures_status_and_file_copy(
    mock_git,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    source = repo_root / "src" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('hi')\n", encoding="utf-8")

    mock_git.side_effect = [
        subprocess.CompletedProcess(args=[], returncode=0, stdout="diff\n", stderr=""),
        subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    ]

    snapshot_dir = snapshot_dirty_state(repo_root, "incident", " M src/app.py\n")

    assert (snapshot_dir / "git-status.txt").exists()
    assert (snapshot_dir / "git-diff.patch").read_text(encoding="utf-8") == "diff\n"
    copied = snapshot_dir / "files" / "src" / "app.py"
    assert copied.read_text(encoding="utf-8") == "print('hi')\n"


@patch("colonyos.recovery._git")
def test_preserve_and_reset_worktree_falls_back_to_snapshot_mode_on_stash_failure(
    mock_git,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path

    mock_git.side_effect = [
        subprocess.CompletedProcess(args=[], returncode=0, stdout="UU src/app.py\n", stderr=""),  # status
        subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),  # diff
        subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),  # diff --cached
        subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),  # ls-files
        subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="stash failed"),  # stash
        subprocess.CompletedProcess(args=[], returncode=0, stdout="MERGE_HEAD\n", stderr=""),  # merge in progress
        subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),  # merge --abort
        subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),  # clean -fd
    ]

    result = preserve_and_reset_worktree(repo_root, "incident")

    assert result.preservation_mode == "snapshot"
    assert result.snapshot_dir.exists()
    clean_call = mock_git.call_args_list[-1]
    assert clean_call.args[1:] == ("clean", "-fd", "-e", ".colonyos/recovery/")


# ---------------------------------------------------------------------------
# pull_branch() tests
# ---------------------------------------------------------------------------


@patch("colonyos.recovery._git")
def test_pull_branch_success(mock_git: object, tmp_path: Path) -> None:
    """Branch has upstream, pull --ff-only succeeds → (True, None)."""
    mock_git.side_effect = [  # type: ignore[attr-defined]
        # rev-parse --abbrev-ref @{upstream}
        subprocess.CompletedProcess(args=[], returncode=0, stdout="origin/main\n", stderr=""),
        # rev-parse --abbrev-ref HEAD (branch name for logging)
        subprocess.CompletedProcess(args=[], returncode=0, stdout="main\n", stderr=""),
        # pull --ff-only
        subprocess.CompletedProcess(args=[], returncode=0, stdout="Already up to date.\n", stderr=""),
    ]

    ok, err = pull_branch(tmp_path)

    assert ok is True
    assert err is None
    # Verify _git was called with the right args
    calls = mock_git.call_args_list  # type: ignore[attr-defined]
    assert calls[0].args == (tmp_path, "rev-parse", "--abbrev-ref", "@{upstream}")
    assert calls[2].args == (tmp_path, "pull", "--ff-only")


@patch("colonyos.recovery._git")
def test_pull_branch_no_upstream_skips_silently(mock_git: object, tmp_path: Path) -> None:
    """No remote tracking branch → skip silently, return (False, None)."""
    mock_git.side_effect = [  # type: ignore[attr-defined]
        # rev-parse --abbrev-ref @{upstream} fails (no upstream)
        subprocess.CompletedProcess(
            args=[], returncode=128,
            stdout="", stderr="fatal: no upstream configured for branch 'topic'\n",
        ),
    ]

    ok, err = pull_branch(tmp_path)

    assert ok is False
    assert err is None
    # Should NOT have called pull
    assert len(mock_git.call_args_list) == 1  # type: ignore[attr-defined]


@patch("colonyos.recovery._git")
def test_pull_branch_pull_failure(mock_git: object, tmp_path: Path) -> None:
    """Pull exits non-zero → (False, error_message)."""
    mock_git.side_effect = [  # type: ignore[attr-defined]
        subprocess.CompletedProcess(args=[], returncode=0, stdout="origin/main\n", stderr=""),
        subprocess.CompletedProcess(args=[], returncode=0, stdout="main\n", stderr=""),
        subprocess.CompletedProcess(
            args=[], returncode=1, stdout="",
            stderr="fatal: Not possible to fast-forward, aborting.\n",
        ),
    ]

    ok, err = pull_branch(tmp_path)

    assert ok is False
    assert err is not None
    assert "fast-forward" in err.lower()


@patch("colonyos.recovery._git")
def test_pull_branch_timeout(mock_git: object, tmp_path: Path) -> None:
    """Timeout during pull → (False, error_message mentioning timeout)."""
    mock_git.side_effect = [  # type: ignore[attr-defined]
        subprocess.CompletedProcess(args=[], returncode=0, stdout="origin/main\n", stderr=""),
        subprocess.CompletedProcess(args=[], returncode=0, stdout="main\n", stderr=""),
        subprocess.TimeoutExpired(cmd=["git", "pull", "--ff-only"], timeout=30),
    ]

    ok, err = pull_branch(tmp_path)

    assert ok is False
    assert err is not None
    assert "timed out" in err.lower()


@patch("colonyos.recovery._git")
def test_pull_branch_custom_timeout(mock_git: object, tmp_path: Path) -> None:
    """Custom timeout is passed through to _git()."""
    mock_git.side_effect = [  # type: ignore[attr-defined]
        subprocess.CompletedProcess(args=[], returncode=0, stdout="origin/main\n", stderr=""),
        subprocess.CompletedProcess(args=[], returncode=0, stdout="main\n", stderr=""),
        subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    ]

    pull_branch(tmp_path, timeout=10)

    calls = mock_git.call_args_list  # type: ignore[attr-defined]
    # The pull call (3rd _git call) should have timeout=10
    assert calls[2].kwargs.get("timeout") == 10
