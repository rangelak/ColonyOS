"""Preflight checks for parallel implement mode.

This module provides functionality to:
1. Check git worktree support (not shallow clone, git >= 2.5)
2. Check disk space availability for worktrees
3. Aggregate check results and determine if parallel mode can proceed
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Minimum free space per worktree (500MB as per PRD)
MIN_FREE_SPACE_MB = 500

# Minimum Git version required for worktree support
MIN_GIT_VERSION = (2, 5, 0)


@dataclass
class ParallelPreflightResult:
    """Result of parallel mode preflight checks."""

    worktree_supported: bool = True
    worktree_error: str = ""
    disk_space_ok: bool = True
    disk_space_error: str = ""

    @property
    def can_proceed(self) -> bool:
        """Return True if all checks pass and parallel mode can proceed."""
        return self.worktree_supported and self.disk_space_ok

    @property
    def blocking_errors(self) -> list[str]:
        """Return list of blocking error messages."""
        errors = []
        if not self.worktree_supported and self.worktree_error:
            errors.append(self.worktree_error)
        if not self.disk_space_ok and self.disk_space_error:
            errors.append(self.disk_space_error)
        return errors


def check_git_worktree_support(repo_root: Path) -> tuple[bool, str]:
    """Check if git worktrees are supported in this repository.

    Args:
        repo_root: Path to the repository root.

    Returns:
        A tuple of (supported: bool, error: str).
        If supported, error is empty string.
    """
    # Check for shallow clone
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip().lower() == "true":
            return False, (
                "Repository is a shallow clone. Git worktrees are not supported. "
                "Run 'git fetch --unshallow' to convert to a full clone."
            )
    except subprocess.SubprocessError:
        pass

    # Check Git version
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            version = _parse_git_version(result.stdout.strip())
            if version < MIN_GIT_VERSION:
                return False, (
                    f"Git version {'.'.join(map(str, version))} is too old. "
                    f"Git worktrees require version >= {'.'.join(map(str, MIN_GIT_VERSION))}. "
                    "Please upgrade Git."
                )
    except subprocess.SubprocessError:
        return False, "Could not determine Git version."

    return True, ""


def check_disk_space(path: Path, num_worktrees: int) -> tuple[bool, str]:
    """Check if there is sufficient disk space for worktrees.

    Args:
        path: Path to check disk space for.
        num_worktrees: Number of worktrees to be created.

    Returns:
        A tuple of (ok: bool, error: str).
        If ok, error is empty string.
    """
    required_mb = num_worktrees * MIN_FREE_SPACE_MB

    try:
        usage = shutil.disk_usage(path)
        free_mb = usage.free // (1024 * 1024)

        if free_mb < required_mb:
            return False, (
                f"Insufficient disk space. Need ~{required_mb}MB for {num_worktrees} "
                f"worktrees, but only {free_mb}MB available."
            )

        return True, ""
    except OSError as e:
        return False, f"Could not check disk space: {e}"


def check_parallel_preflight(
    repo_root: Path,
    num_tasks: int,
) -> ParallelPreflightResult:
    """Run all preflight checks for parallel implement mode.

    Args:
        repo_root: Path to the repository root.
        num_tasks: Number of tasks that will run in parallel.

    Returns:
        ParallelPreflightResult with all check results.
    """
    result = ParallelPreflightResult()

    # Check worktree support
    worktree_ok, worktree_error = check_git_worktree_support(repo_root)
    result.worktree_supported = worktree_ok
    result.worktree_error = worktree_error

    # Check disk space
    disk_ok, disk_error = check_disk_space(repo_root, num_tasks)
    result.disk_space_ok = disk_ok
    result.disk_space_error = disk_error

    if not result.can_proceed:
        logger.warning(
            "Parallel preflight failed: %s",
            "; ".join(result.blocking_errors),
        )

    return result


def _parse_git_version(version_str: str) -> tuple[int, ...]:
    """Parse git version string into tuple of integers.

    Args:
        version_str: Git version string like "git version 2.39.0"

    Returns:
        Tuple of version numbers (major, minor, patch).
    """
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", version_str)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2))
        patch = int(match.group(3)) if match.group(3) else 0
        return (major, minor, patch)
    return (0, 0, 0)
