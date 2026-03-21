"""Tests for parallel mode preflight checks (Task 11.0)."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colonyos.parallel_preflight import (
    ParallelPreflightResult,
    check_parallel_preflight,
    check_disk_space,
    check_git_worktree_support,
    MIN_FREE_SPACE_MB,
)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository for testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    (repo / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    return repo


class TestParallelPreflightResult:
    def test_can_proceed_all_clear(self) -> None:
        result = ParallelPreflightResult(
            worktree_supported=True,
            disk_space_ok=True,
        )
        assert result.can_proceed is True
        assert result.blocking_errors == []

    def test_cannot_proceed_worktree_unsupported(self) -> None:
        result = ParallelPreflightResult(
            worktree_supported=False,
            worktree_error="Shallow clone detected",
            disk_space_ok=True,
        )
        assert result.can_proceed is False
        assert "Shallow clone" in result.blocking_errors[0]

    def test_cannot_proceed_disk_space(self) -> None:
        result = ParallelPreflightResult(
            worktree_supported=True,
            disk_space_ok=False,
            disk_space_error="Insufficient space",
        )
        assert result.can_proceed is False
        assert "Insufficient" in result.blocking_errors[0]

    def test_multiple_errors(self) -> None:
        result = ParallelPreflightResult(
            worktree_supported=False,
            worktree_error="Error 1",
            disk_space_ok=False,
            disk_space_error="Error 2",
        )
        assert result.can_proceed is False
        assert len(result.blocking_errors) == 2


class TestCheckGitWorktreeSupport:
    def test_normal_repo_supported(self, tmp_repo: Path) -> None:
        supported, error = check_git_worktree_support(tmp_repo)
        assert supported is True
        assert error == ""

    def test_shallow_clone_not_supported(self, tmp_repo: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="true\n",
                returncode=0,
            )
            supported, error = check_git_worktree_support(tmp_repo)
            assert supported is False
            assert "shallow" in error.lower()

    def test_old_git_version_not_supported(self, tmp_repo: Path) -> None:
        with patch("subprocess.run") as mock_run:
            def side_effect(*args, **kwargs):
                cmd = args[0]
                if "is-shallow-repository" in cmd:
                    return MagicMock(stdout="false\n", returncode=0)
                elif "--version" in cmd:
                    return MagicMock(stdout="git version 2.4.0\n", returncode=0)
                return MagicMock(returncode=0)

            mock_run.side_effect = side_effect
            supported, error = check_git_worktree_support(tmp_repo)
            assert supported is False
            assert "2.5" in error or "version" in error.lower()


class TestCheckDiskSpace:
    def test_sufficient_space(self, tmp_path: Path) -> None:
        ok, error = check_disk_space(tmp_path, num_worktrees=3)
        # Most systems have >500MB free, this should pass
        assert ok is True
        assert error == ""

    def test_insufficient_space_mocked(self, tmp_path: Path) -> None:
        with patch("shutil.disk_usage") as mock_disk:
            # Mock only 100MB free
            mock_disk.return_value = MagicMock(free=100 * 1024 * 1024)
            ok, error = check_disk_space(tmp_path, num_worktrees=10)
            assert ok is False
            assert "space" in error.lower()


class TestCheckParallelPreflight:
    def test_all_checks_pass(self, tmp_repo: Path) -> None:
        result = check_parallel_preflight(tmp_repo, num_tasks=3)
        assert result.can_proceed is True
        assert result.worktree_supported is True
        assert result.disk_space_ok is True

    def test_sequential_fallback_on_failure(self, tmp_repo: Path) -> None:
        with patch("subprocess.run") as mock_run:
            # Simulate shallow clone
            mock_run.return_value = MagicMock(
                stdout="true\n",
                returncode=0,
            )
            result = check_parallel_preflight(tmp_repo, num_tasks=3)
            assert result.can_proceed is False
            assert result.worktree_supported is False


class TestMinFreeSpaceConstant:
    def test_constant_value(self) -> None:
        # 500MB per worktree as per PRD
        assert MIN_FREE_SPACE_MB == 500
