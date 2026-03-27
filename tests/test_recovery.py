from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from colonyos.recovery import (
    dirty_paths_from_status,
    preserve_and_reset_worktree,
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
