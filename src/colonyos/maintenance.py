"""Daemon inter-queue maintenance — self-update detection and installation.

This module provides helpers for the daemon maintenance cycle that runs
between queue items.  Task 2.0 covers self-update detection, installation,
rollback bookkeeping, and the ``should_rollback`` startup check.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_GIT_TIMEOUT = 30
_SELF_UPDATE_INSTALL_TIMEOUT = 120
_ROLLBACK_WINDOW_SECONDS = 60


# ---------------------------------------------------------------------------
# Internal git helper (mirrors recovery._git pattern)
# ---------------------------------------------------------------------------

def _git(
    repo_root: Path,
    *args: str,
    check: bool = False,
    timeout: int | None = _DEFAULT_GIT_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Self-update detection (FR-1)
# ---------------------------------------------------------------------------

def pull_and_check_update(
    repo_root: Path,
) -> tuple[bool, str | None, str | None]:
    """Pull latest from remote and detect whether HEAD changed.

    Returns ``(changed, old_sha, new_sha)``.

    * ``changed`` is *True* only when a fast-forward pull moved HEAD.
    * On any failure the function returns ``(False, ...)`` without raising.
    """
    # 1. Record pre-pull SHA
    try:
        pre = _git(repo_root, "rev-parse", "HEAD")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.warning("Failed to read HEAD SHA before pull", exc_info=True)
        return False, None, None

    if pre.returncode != 0:
        logger.warning("git rev-parse HEAD failed: %s", pre.stderr.strip())
        return False, None, None

    old_sha = pre.stdout.strip()

    # 2. Pull (fast-forward only)
    try:
        pull = _git(repo_root, "pull", "--ff-only", timeout=_DEFAULT_GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.warning("git pull --ff-only timed out")
        return False, old_sha, None

    if pull.returncode != 0:
        logger.info(
            "git pull --ff-only exited %d: %s",
            pull.returncode,
            pull.stderr.strip(),
        )
        return False, old_sha, None

    # 3. Record post-pull SHA
    try:
        post = _git(repo_root, "rev-parse", "HEAD")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.warning("Failed to read HEAD SHA after pull", exc_info=True)
        return False, old_sha, None

    new_sha = post.stdout.strip() if post.returncode == 0 else None
    if new_sha is None:
        return False, old_sha, None

    changed = old_sha != new_sha
    if changed:
        logger.info("Self-update detected: %s → %s", old_sha[:10], new_sha[:10])
    return changed, old_sha, new_sha


# ---------------------------------------------------------------------------
# Self-update installation (FR-1)
# ---------------------------------------------------------------------------

def run_self_update(repo_root: Path, command: str) -> bool:
    """Run the install command (e.g. ``uv pip install .``) and return success.

    Uses ``shell=True`` so the command string is interpreted by the shell,
    matching the configurable ``self_update_command`` field.
    """
    logger.info("Running self-update command: %s", command)
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=_SELF_UPDATE_INSTALL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.error("Self-update command timed out after %ds", _SELF_UPDATE_INSTALL_TIMEOUT)
        return False
    except FileNotFoundError:
        logger.error("Self-update command not found: %s", command)
        return False

    if result.returncode != 0:
        logger.error(
            "Self-update command failed (exit %d): %s",
            result.returncode,
            result.stderr.strip(),
        )
        return False

    logger.info("Self-update command succeeded")
    return True


# ---------------------------------------------------------------------------
# Last-good-commit bookkeeping (FR-2)
# ---------------------------------------------------------------------------

_LAST_GOOD_COMMIT_PATH = ".colonyos/last_good_commit"


def record_last_good_commit(repo_root: Path, sha: str) -> None:
    """Persist *sha* as the last known-good commit."""
    target = repo_root / _LAST_GOOD_COMMIT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(sha.strip() + "\n", encoding="utf-8")


def read_last_good_commit(repo_root: Path) -> str | None:
    """Read the last known-good commit SHA, or *None* if absent/empty."""
    target = repo_root / _LAST_GOOD_COMMIT_PATH
    if not target.is_file():
        return None
    content = target.read_text(encoding="utf-8").strip()
    return content or None


# ---------------------------------------------------------------------------
# Startup rollback check (FR-2)
# ---------------------------------------------------------------------------

def should_rollback(repo_root: Path, startup_time: float) -> bool:
    """Return *True* if the daemon should roll back to the last-good commit.

    Conditions (all must be true):
    1. A ``last_good_commit`` file exists with a SHA.
    2. The current ``HEAD`` differs from that SHA.
    3. The process started less than ``_ROLLBACK_WINDOW_SECONDS`` ago.
    """
    last_good = read_last_good_commit(repo_root)
    if last_good is None:
        return False

    elapsed = time.time() - startup_time
    if elapsed >= _ROLLBACK_WINDOW_SECONDS:
        return False

    try:
        result = _git(repo_root, "rev-parse", "HEAD")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.warning("Cannot determine HEAD for rollback check", exc_info=True)
        return False

    if result.returncode != 0:
        logger.warning("git rev-parse HEAD failed during rollback check")
        return False

    current_sha = result.stdout.strip()
    if current_sha == last_good:
        return False

    logger.warning(
        "Rollback candidate: HEAD=%s differs from last_good_commit=%s (uptime=%.1fs)",
        current_sha[:10],
        last_good[:10],
        elapsed,
    )
    return True
