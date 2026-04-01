"""Daemon inter-queue maintenance — self-update, branch sync, and CI fix.

This module provides helpers for the daemon maintenance cycle that runs
between queue items.  Task 2.0 covers self-update detection, installation,
rollback bookkeeping, and the ``should_rollback`` startup check.
Task 3.0 adds branch sync scanning to identify diverged ``colonyos/``
branches and report them via Slack.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
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


# ---------------------------------------------------------------------------
# Branch sync scan (FR-3)
# ---------------------------------------------------------------------------

_GH_TIMEOUT = 10


@dataclass(frozen=True)
class BranchStatus:
    """Divergence status for a single remote branch."""

    name: str
    ahead: int = 0
    behind: int = 0
    has_open_pr: bool = False
    pr_number: int | None = None


def scan_diverged_branches(
    repo_root: Path,
    prefix: str = "colonyos/",
) -> list[BranchStatus]:
    """Enumerate remote branches with *prefix* and compute divergence from main.

    For each branch that is behind ``origin/main`` by at least one commit,
    return a :class:`BranchStatus` with ahead/behind counts and open-PR info.

    Branches that are fully up-to-date (behind == 0) are omitted from the
    result.  All errors are caught and logged — the function never raises.
    """
    # 1. Fetch to ensure refs are current (best-effort)
    try:
        _git(repo_root, "fetch", "--prune", timeout=_DEFAULT_GIT_TIMEOUT)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.warning("git fetch --prune failed; using stale refs", exc_info=True)

    # 2. List remote branches matching prefix
    try:
        result = _git(
            repo_root,
            "branch", "-r", "--list", f"origin/{prefix}*",
            "--format", "%(refname:short)",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.warning("Failed to list remote branches", exc_info=True)
        return []

    if result.returncode != 0:
        logger.warning("git branch -r failed: %s", result.stderr.strip())
        return []

    branch_refs = [
        line.strip() for line in result.stdout.splitlines() if line.strip()
    ]
    if not branch_refs:
        return []

    # 3. Batch-fetch open PRs for prefix branches
    open_prs = _fetch_open_prs_for_prefix(repo_root, prefix)

    # 4. Compute ahead/behind for each branch
    branches: list[BranchStatus] = []
    for ref in branch_refs:
        # ref looks like "origin/colonyos/foo" — strip the "origin/" to get
        # the logical branch name
        branch_name = ref.removeprefix("origin/")
        ahead, behind = _ahead_behind(repo_root, ref)
        if behind == 0 and ahead == 0:
            continue

        pr_number = open_prs.get(branch_name)
        branches.append(BranchStatus(
            name=branch_name,
            ahead=ahead,
            behind=behind,
            has_open_pr=pr_number is not None,
            pr_number=pr_number,
        ))

    return branches


def _ahead_behind(repo_root: Path, remote_ref: str) -> tuple[int, int]:
    """Return ``(ahead, behind)`` counts of *remote_ref* relative to ``origin/main``."""
    try:
        result = _git(
            repo_root,
            "rev-list", "--count", "--left-right",
            f"{remote_ref}...origin/main",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.warning("Failed to compute ahead/behind for %s", remote_ref, exc_info=True)
        return 0, 0

    if result.returncode != 0:
        logger.warning(
            "git rev-list --left-right failed for %s: %s",
            remote_ref,
            result.stderr.strip(),
        )
        return 0, 0

    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return 0, 0

    try:
        ahead = int(parts[0])
        behind = int(parts[1])
    except ValueError:
        return 0, 0

    return ahead, behind


def _fetch_open_prs_for_prefix(
    repo_root: Path,
    prefix: str,
) -> dict[str, int]:
    """Return a mapping of ``{branch_name: pr_number}`` for open PRs.

    Uses a single ``gh pr list`` call to fetch all open PRs, then filters
    to branches that start with *prefix*.
    """
    try:
        result = subprocess.run(
            [
                "gh", "pr", "list",
                "--state", "open",
                "--json", "number,headRefName",
                "--limit", "100",
            ],
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT,
            cwd=repo_root,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("Failed to fetch open PRs: %s", exc)
        return {}

    if result.returncode != 0:
        logger.warning("gh pr list failed: %s", result.stderr.strip())
        return {}

    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("Failed to parse gh pr list output")
        return {}

    if not isinstance(items, list):
        return {}

    mapping: dict[str, int] = {}
    for item in items:
        branch = item.get("headRefName", "")
        number = item.get("number")
        if branch.startswith(prefix) and isinstance(number, int):
            mapping[branch] = number

    return mapping


def format_branch_sync_report(branches: list[BranchStatus]) -> str | None:
    """Format a Slack mrkdwn summary of diverged branches.

    Returns ``None`` if *branches* is empty.
    """
    if not branches:
        return None

    lines = ["*Branch Sync Report*", ""]
    for b in sorted(branches, key=lambda x: x.behind, reverse=True):
        pr_tag = f" (PR #{b.pr_number})" if b.pr_number else ""
        behind_tag = f"{b.behind} behind" if b.behind else ""
        ahead_tag = f"{b.ahead} ahead" if b.ahead else ""
        counts = ", ".join(filter(None, [behind_tag, ahead_tag]))
        lines.append(f"\u2022 `{b.name}` — {counts}{pr_tag}")

    lines.append("")
    lines.append(f"_{len(branches)} diverged branch(es) found._")
    return "\n".join(lines)
