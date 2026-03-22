"""Tests for git worktree manager (Task 3.0)."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colonyos.worktree import (
    WorktreeManager,
    WorktreeError,
    WORKTREE_BASE_DIR,
)

pytestmark = pytest.mark.usefixtures("mock_git_subprocess")


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Temporary repo root (no real git; subprocess git calls are mocked)."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    return repo


class TestWorktreeManagerCreation:
    """Tests for worktree creation."""

    def test_create_worktree_success(self, tmp_repo: Path) -> None:
        manager = WorktreeManager(repo_root=tmp_repo)
        worktree_path = manager.create_worktree(task_id="1.0", base_branch="main")

        assert worktree_path.exists()
        assert worktree_path.is_dir()
        # Check it's under .colonyos/worktrees/
        assert WORKTREE_BASE_DIR in str(worktree_path)
        # Check git worktree is functional
        assert (worktree_path / ".git").exists() or (worktree_path / "README.md").exists()

    def test_create_worktree_creates_task_branch(self, tmp_repo: Path) -> None:
        manager = WorktreeManager(repo_root=tmp_repo)
        manager.create_worktree(task_id="1.0", base_branch="main")

        # Verify the task branch was created
        result = subprocess.run(
            ["git", "branch", "--list"],
            cwd=tmp_repo,
            capture_output=True,
            text=True,
        )
        # The worktree should have created a new branch for the task
        assert "task-1.0" in result.stdout or "1.0" in result.stdout

    def test_create_multiple_worktrees(self, tmp_repo: Path) -> None:
        manager = WorktreeManager(repo_root=tmp_repo)
        wt1 = manager.create_worktree(task_id="1.0", base_branch="main")
        wt2 = manager.create_worktree(task_id="2.0", base_branch="main")

        assert wt1 != wt2
        assert wt1.exists()
        assert wt2.exists()


class TestWorktreeManagerCleanup:
    """Tests for worktree cleanup."""

    def test_cleanup_worktree_removes_directory(self, tmp_repo: Path) -> None:
        manager = WorktreeManager(repo_root=tmp_repo)
        worktree_path = manager.create_worktree(task_id="1.0", base_branch="main")
        assert worktree_path.exists()

        manager.cleanup_worktree(task_id="1.0")
        assert not worktree_path.exists()

    def test_cleanup_nonexistent_worktree_no_error(self, tmp_repo: Path) -> None:
        manager = WorktreeManager(repo_root=tmp_repo)
        # Should not raise
        manager.cleanup_worktree(task_id="nonexistent")

    def test_cleanup_all_worktrees(self, tmp_repo: Path) -> None:
        manager = WorktreeManager(repo_root=tmp_repo)
        wt1 = manager.create_worktree(task_id="1.0", base_branch="main")
        wt2 = manager.create_worktree(task_id="2.0", base_branch="main")
        assert wt1.exists()
        assert wt2.exists()

        manager.cleanup_all_worktrees()
        assert not wt1.exists()
        assert not wt2.exists()


class TestWorktreeManagerSupport:
    """Tests for worktree support detection."""

    def test_check_worktree_support_normal_repo(self, tmp_repo: Path) -> None:
        manager = WorktreeManager(repo_root=tmp_repo)
        supported, reason = manager.check_worktree_support()
        assert supported is True
        assert reason == ""

    def test_check_worktree_support_shallow_clone(self, tmp_repo: Path) -> None:
        manager = WorktreeManager(repo_root=tmp_repo)
        # Mock the subprocess call to simulate shallow clone
        with patch.object(subprocess, "run") as mock_run:
            # First call for git rev-parse --is-shallow-repository
            mock_run.return_value = MagicMock(
                stdout="true\n",
                returncode=0,
            )
            supported, reason = manager.check_worktree_support()
            assert supported is False
            assert "shallow" in reason.lower()

    def test_check_worktree_support_old_git_version(self, tmp_repo: Path) -> None:
        manager = WorktreeManager(repo_root=tmp_repo)
        with patch.object(subprocess, "run") as mock_run:
            def side_effect(*args, **kwargs):
                cmd = args[0]
                if "is-shallow-repository" in cmd:
                    return MagicMock(stdout="false\n", returncode=0)
                elif "--version" in cmd:
                    return MagicMock(stdout="git version 2.4.0\n", returncode=0)
                return MagicMock(returncode=0)

            mock_run.side_effect = side_effect
            supported, reason = manager.check_worktree_support()
            assert supported is False
            assert "2.5" in reason or "version" in reason.lower()


class TestWorktreePathValidation:
    """Tests for path traversal prevention."""

    def test_invalid_task_id_with_path_traversal(self, tmp_repo: Path) -> None:
        manager = WorktreeManager(repo_root=tmp_repo)
        with pytest.raises(ValueError, match="Invalid task_id"):
            manager.create_worktree(task_id="../../../etc/passwd", base_branch="main")

    def test_invalid_task_id_with_slash(self, tmp_repo: Path) -> None:
        manager = WorktreeManager(repo_root=tmp_repo)
        with pytest.raises(ValueError, match="Invalid task_id"):
            manager.create_worktree(task_id="foo/bar", base_branch="main")

    def test_valid_task_id_formats(self, tmp_repo: Path) -> None:
        manager = WorktreeManager(repo_root=tmp_repo)
        # These should all be valid
        manager.create_worktree(task_id="1.0", base_branch="main")
        manager.create_worktree(task_id="10.5", base_branch="main")
        manager.create_worktree(task_id="task-1", base_branch="main")


class TestWorktreeError:
    """Tests for WorktreeError exception."""

    def test_error_message(self) -> None:
        err = WorktreeError("Failed to create worktree")
        assert "Failed to create worktree" in str(err)


class TestWorktreeManagerWorktreePath:
    """Tests for getting worktree path."""

    def test_get_worktree_path(self, tmp_repo: Path) -> None:
        manager = WorktreeManager(repo_root=tmp_repo)
        path = manager.get_worktree_path(task_id="1.0")
        expected = tmp_repo / WORKTREE_BASE_DIR / "task-1.0"
        assert path == expected

    def test_worktree_base_dir_constant(self) -> None:
        assert WORKTREE_BASE_DIR == ".colonyos/worktrees"
