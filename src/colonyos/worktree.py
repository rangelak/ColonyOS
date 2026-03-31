"""Git worktree manager for parallel implement mode.

This module provides functionality to:
1. Create ephemeral git worktrees for task isolation
2. Clean up worktrees after task completion
3. Detect worktree support (shallow clones, old Git versions)
4. Validate task IDs to prevent path traversal attacks
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Base directory for worktrees, relative to repo root
WORKTREE_BASE_DIR = ".colonyos/worktrees"

# Minimum Git version required for worktree support
MIN_GIT_VERSION = (2, 5, 0)

# Valid task ID pattern: alphanumeric, dots, dashes, underscores
# Must not contain path separators or traversal sequences
VALID_TASK_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")


class WorktreeError(Exception):
    """Raised when a git worktree operation fails."""
    pass


class WorktreeManager:
    """Manages ephemeral git worktrees for parallel task execution.

    Each task gets its own isolated worktree, which allows concurrent
    file modifications without conflicts. After task completion, worktrees
    are cleaned up.
    """

    def __init__(self, repo_root: Path) -> None:
        """Initialize the worktree manager.

        Args:
            repo_root: Path to the repository root directory.
        """
        self.repo_root = repo_root
        self._worktree_base = repo_root / WORKTREE_BASE_DIR

    def get_worktree_path(self, task_id: str) -> Path:
        """Get the path where a task's worktree would be located.

        Args:
            task_id: The task identifier (e.g., "1.0", "2.0").

        Returns:
            Path to the worktree directory.
        """
        return self._worktree_base / f"task-{task_id}"

    def create_worktree(self, task_id: str, base_branch: str) -> Path:
        """Create a new worktree for a task.

        Creates an ephemeral worktree under .colonyos/worktrees/<task_id>/
        based on the specified branch.

        Args:
            task_id: The task identifier (e.g., "1.0", "2.0").
            base_branch: The branch to base the worktree on.

        Returns:
            Path to the created worktree.

        Raises:
            ValueError: If task_id contains invalid characters.
            WorktreeError: If worktree creation fails.
        """
        self._validate_task_id(task_id)

        worktree_path = self.get_worktree_path(task_id)
        branch_name = f"task-{task_id}"

        # Ensure parent directory exists
        self._worktree_base.mkdir(parents=True, exist_ok=True)

        # Remove existing worktree if present
        if worktree_path.exists():
            self._remove_worktree(worktree_path)

        try:
            # Create a new branch for the task
            # git worktree add <path> -b <branch> <base>
            result = subprocess.run(
                [
                    "git", "worktree", "add",
                    str(worktree_path),
                    "-b", branch_name,
                    base_branch,
                ],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                # Try without -b flag if branch already exists
                result = subprocess.run(
                    [
                        "git", "worktree", "add",
                        str(worktree_path),
                        branch_name,
                    ],
                    cwd=self.repo_root,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    raise WorktreeError(
                        f"Failed to create worktree: {result.stderr}"
                    )

            logger.info("Created worktree for task %s at %s", task_id, worktree_path)
            return worktree_path

        except subprocess.SubprocessError as e:
            raise WorktreeError(f"Failed to create worktree: {e}") from e

    def create_detached_worktree(self, task_id: str, ref: str) -> Path:
        """Create a detached worktree on an existing ref.

        Unlike :meth:`create_worktree` which creates a new branch, this
        creates a ``--detach`` worktree suitable for checking out an
        existing remote branch (e.g. for PR sync).

        Args:
            task_id: The task identifier (e.g., "pr-sync-42").
            ref: The git ref to base the worktree on (e.g., "origin/feat-x").

        Returns:
            Path to the created worktree.

        Raises:
            ValueError: If task_id contains invalid characters.
            WorktreeError: If worktree creation fails.
        """
        self._validate_task_id(task_id)

        worktree_path = self.get_worktree_path(task_id)

        # Ensure parent directory exists
        self._worktree_base.mkdir(parents=True, exist_ok=True)

        # Remove existing worktree if present
        if worktree_path.exists():
            self._remove_worktree(worktree_path)

        try:
            result = subprocess.run(
                [
                    "git", "worktree", "add",
                    str(worktree_path),
                    ref,
                    "--detach",
                ],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise WorktreeError(
                    f"Failed to create detached worktree: {result.stderr}"
                )

            logger.info(
                "Created detached worktree for task %s at %s (ref=%s)",
                task_id, worktree_path, ref,
            )
            return worktree_path

        except subprocess.SubprocessError as e:
            raise WorktreeError(f"Failed to create detached worktree: {e}") from e

    def cleanup_worktree(self, task_id: str) -> None:
        """Remove a worktree for a task.

        Args:
            task_id: The task identifier.
        """
        worktree_path = self.get_worktree_path(task_id)
        if not worktree_path.exists():
            logger.debug("Worktree for task %s does not exist, skipping cleanup", task_id)
            return

        self._remove_worktree(worktree_path)
        logger.info("Cleaned up worktree for task %s", task_id)

    def cleanup_all_worktrees(self) -> None:
        """Remove all worktrees managed by ColonyOS."""
        if not self._worktree_base.exists():
            return

        # List all worktrees and remove them
        try:
            result = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("worktree "):
                        path = Path(line[9:])  # Remove "worktree " prefix
                        if str(self._worktree_base) in str(path):
                            self._remove_worktree(path)
        except subprocess.SubprocessError:
            pass

        # Also try direct directory removal as fallback
        if self._worktree_base.exists():
            for child in self._worktree_base.iterdir():
                if child.is_dir():
                    self._remove_worktree(child)

            # Remove the base directory if empty
            try:
                self._worktree_base.rmdir()
            except OSError:
                pass

        logger.info("Cleaned up all ColonyOS worktrees")

    def check_worktree_support(self) -> tuple[bool, str]:
        """Check if git worktrees are supported in this environment.

        Returns:
            A tuple of (supported: bool, reason: str).
            If supported, reason is empty string.
            If not supported, reason explains why.
        """
        # Check for shallow clone
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-shallow-repository"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip().lower() == "true":
                return False, "Repository is a shallow clone (worktrees not supported)"
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
                version_str = result.stdout.strip()
                version = self._parse_git_version(version_str)
                if version < MIN_GIT_VERSION:
                    return False, (
                        f"Git version {'.'.join(map(str, version))} is too old. "
                        f"Worktrees require Git >= {'.'.join(map(str, MIN_GIT_VERSION))}"
                    )
        except subprocess.SubprocessError:
            return False, "Could not determine Git version"

        return True, ""

    def _validate_task_id(self, task_id: str) -> None:
        """Validate that a task ID is safe for filesystem use.

        Args:
            task_id: The task identifier to validate.

        Raises:
            ValueError: If the task_id contains invalid characters.
        """
        if not task_id:
            raise ValueError("Invalid task_id: cannot be empty")

        if "/" in task_id or "\\" in task_id:
            raise ValueError(f"Invalid task_id: contains path separator: {task_id}")

        if ".." in task_id:
            raise ValueError(f"Invalid task_id: contains path traversal: {task_id}")

        if not VALID_TASK_ID_PATTERN.match(task_id):
            raise ValueError(f"Invalid task_id: {task_id}")

    def _remove_worktree(self, path: Path) -> None:
        """Remove a worktree using git worktree remove."""
        try:
            # First try git worktree remove
            result = subprocess.run(
                ["git", "worktree", "remove", "--force", str(path)],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                # Fall back to direct removal
                if path.exists():
                    shutil.rmtree(path)
                # Prune worktree records
                subprocess.run(
                    ["git", "worktree", "prune"],
                    cwd=self.repo_root,
                    capture_output=True,
                )
        except (subprocess.SubprocessError, OSError) as e:
            logger.warning("Error removing worktree %s: %s", path, e)
            # Try direct removal as last resort
            if path.exists():
                try:
                    shutil.rmtree(path)
                except OSError:
                    pass

    def _parse_git_version(self, version_str: str) -> tuple[int, ...]:
        """Parse git version string into tuple of integers.

        Args:
            version_str: Git version string like "git version 2.39.0"

        Returns:
            Tuple of version numbers (major, minor, patch).
        """
        # Extract version numbers from string like "git version 2.39.0"
        match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", version_str)
        if match:
            major = int(match.group(1))
            minor = int(match.group(2))
            patch = int(match.group(3)) if match.group(3) else 0
            return (major, minor, patch)
        return (0, 0, 0)
