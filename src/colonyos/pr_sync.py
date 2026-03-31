"""PR sync — keep ColonyOS PRs up-to-date with main.

Detects open ColonyOS PRs that are behind ``main``, merges the latest
``main`` into those branches in an isolated worktree, and pushes the
result.  Merge conflicts are aborted cleanly and surfaced via Slack +
PR comment.

This module is called by the daemon tick loop as concern #7.  It is
safe to call repeatedly — each invocation processes at most 1 PR.
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from colonyos.config import ColonyConfig
from colonyos.github import post_pr_comment
from colonyos.outcomes import OutcomeStore

logger = logging.getLogger(__name__)

# mergeStateStatus values that indicate the branch needs syncing.
_STALE_STATES = {"BEHIND", "DIRTY"}


def sync_stale_prs(
    *,
    repo_root: Path,
    config: ColonyConfig,
    queue_state_items: Sequence[Any],
    post_slack_fn: Callable[[str], None],
    write_enabled: bool,
) -> bool | None:
    """Detect and sync a single stale ColonyOS PR.

    Returns ``True`` if a PR was synced successfully, ``False`` if a sync
    was attempted but failed, or ``None`` if no sync was attempted.

    Parameters
    ----------
    repo_root:
        Repository root directory.
    config:
        Full ColonyOS configuration.
    queue_state_items:
        Current queue items — used to skip branches with RUNNING work.
    post_slack_fn:
        Callback to post Slack messages (matches ``Daemon._post_slack_message``).
    write_enabled:
        Whether write operations (push) are allowed.
    """
    pr_sync_cfg = config.daemon.pr_sync

    # Gate: must be enabled and write-enabled
    if not pr_sync_cfg.enabled:
        logger.debug("PR sync disabled, skipping")
        return None
    if not write_enabled:
        logger.debug("Write not enabled, skipping PR sync")
        return None

    # Collect running branch names for conflict avoidance
    from colonyos.models import QueueItemStatus

    running_branches: set[str] = set()
    for item in queue_state_items:
        if getattr(item, "status", None) == QueueItemStatus.RUNNING:
            branch = getattr(item, "branch_name", None)
            if branch:
                running_branches.add(branch)

    # Get sync candidates from OutcomeStore
    store = OutcomeStore(repo_root)
    try:
        candidates = store.get_sync_candidates(pr_sync_cfg.max_sync_failures)
    finally:
        store.close()

    branch_prefix = config.branch_prefix

    for candidate in candidates:
        branch_name = candidate["branch_name"]
        pr_number = candidate["pr_number"]

        # Filter: only colonyos/ branches
        if not branch_name.startswith(branch_prefix):
            logger.debug(
                "Skipping PR #%d — branch %s does not match prefix %s",
                pr_number, branch_name, branch_prefix,
            )
            continue

        # Filter: skip branches with running queue items
        if branch_name in running_branches:
            logger.debug(
                "Skipping PR #%d — branch %s has a RUNNING queue item",
                pr_number, branch_name,
            )
            continue

        # Check merge state via GitHub API
        merge_state = _check_merge_state(repo_root, pr_number)
        if merge_state not in _STALE_STATES:
            logger.debug(
                "Skipping PR #%d — mergeStateStatus=%s (not stale)",
                pr_number, merge_state,
            )
            continue

        # Found a candidate — sync it and return (1 per invocation)
        logger.info(
            "Syncing PR #%d (branch=%s, mergeStateStatus=%s)",
            pr_number, branch_name, merge_state,
        )
        success = _sync_single_pr(
            repo_root=repo_root,
            pr_number=pr_number,
            branch_name=branch_name,
            post_slack_fn=post_slack_fn,
        )
        return success

    # No candidate found
    return None


def _check_merge_state(repo_root: Path, pr_number: int) -> str:
    """Query GitHub for the PR's ``mergeStateStatus``.

    Returns the status string (e.g. ``"BEHIND"``, ``"CLEAN"``) or
    ``"UNKNOWN"`` on any error.
    """
    try:
        result = subprocess.run(
            [
                "gh", "pr", "view", str(pr_number),
                "--json", "mergeStateStatus",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(repo_root),
        )
        if result.returncode != 0:
            logger.warning(
                "gh pr view failed for PR #%d: %s",
                pr_number, result.stderr.strip(),
            )
            return "UNKNOWN"
        data = json.loads(result.stdout)
        return data.get("mergeStateStatus", "UNKNOWN")
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        logger.warning("Failed to check merge state for PR #%d: %s", pr_number, exc)
        return "UNKNOWN"
    except FileNotFoundError:
        logger.warning("gh CLI not found — cannot check merge state")
        return "UNKNOWN"


def _sync_single_pr(
    *,
    repo_root: Path,
    pr_number: int,
    branch_name: str,
    post_slack_fn: Callable[[str], None],
) -> bool:
    """Merge ``origin/main`` into a single PR branch.

    Performs the merge in an ephemeral worktree to avoid corrupting the
    main working tree.

    Returns ``True`` on success, ``False`` on conflict or error.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    store = OutcomeStore(repo_root)

    # Sanitise branch name for use as a worktree task-id
    task_id = f"pr-sync-{pr_number}"
    worktree_path = repo_root / ".colonyos" / "worktrees" / f"task-{task_id}"

    try:
        # 1. Fetch latest main and the PR branch
        _run_git(repo_root, ["git", "fetch", "origin", "main"], "fetch origin main")
        _run_git(repo_root, ["git", "fetch", "origin", branch_name], f"fetch origin {branch_name}")

        # 2. Get pre-sync HEAD
        pre_sha = _get_rev(repo_root, f"origin/{branch_name}")

        # 3. Create ephemeral worktree on the PR branch
        _run_git(
            repo_root,
            ["git", "worktree", "add", str(worktree_path), f"origin/{branch_name}", "--detach"],
            "create worktree",
        )

        # 4. Check out the branch in the worktree (so push updates the ref)
        _run_git(worktree_path, ["git", "checkout", branch_name], "checkout branch in worktree")

        # 5. Attempt merge
        merge_result = subprocess.run(
            ["git", "merge", "origin/main", "--no-edit"],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
        )

        if merge_result.returncode != 0:
            # Merge conflict — collect conflicting files, abort, notify
            conflict_files = _get_conflict_files(worktree_path)
            _run_git(worktree_path, ["git", "merge", "--abort"], "merge --abort")

            # Update failure tracking
            current_failures = _get_current_failures(store, pr_number)
            new_failures = current_failures + 1
            store.update_sync_status(pr_number, now_iso, new_failures)

            # Notify via Slack
            conflict_list = ", ".join(conflict_files[:5]) if conflict_files else "(unknown files)"
            slack_msg = (
                f":warning: PR #{pr_number} (`{branch_name}`) has merge conflicts "
                f"with main.\nConflicting files: {conflict_list}\n"
                f"Sync failure {new_failures} — "
                f"manual resolution required."
            )
            try:
                post_slack_fn(slack_msg)
            except Exception:
                logger.warning("Failed to post Slack notification for PR #%d", pr_number, exc_info=True)

            # Post PR comment
            comment_body = (
                f"## :warning: ColonyOS Sync Conflict\n\n"
                f"Failed to merge `main` into this branch. "
                f"Manual conflict resolution is required.\n\n"
                f"**Conflicting files:**\n"
                + "\n".join(f"- `{f}`" for f in conflict_files[:10])
                + f"\n\n_Sync failure #{new_failures}_"
            )
            post_pr_comment(repo_root, pr_number, comment_body)

            logger.warning(
                "PR #%d sync failed — merge conflict (files: %s, failure #%d)",
                pr_number, conflict_list, new_failures,
            )
            return False

        # 6. Push the merged result
        _run_git(worktree_path, ["git", "push", "origin", branch_name], "push")

        # 7. Get post-sync HEAD
        post_sha = _get_rev(worktree_path, "HEAD")

        # 8. Update OutcomeStore — reset failures on success
        store.update_sync_status(pr_number, now_iso, 0)

        logger.info(
            "PR #%d synced successfully: %s -> %s (branch=%s)",
            pr_number, pre_sha[:8], post_sha[:8], branch_name,
        )
        return True

    except Exception as exc:
        logger.warning("Unexpected error syncing PR #%d: %s", pr_number, exc, exc_info=True)

        # Best-effort failure tracking
        try:
            current_failures = _get_current_failures(store, pr_number)
            store.update_sync_status(pr_number, now_iso, current_failures + 1)
        except Exception:
            logger.debug("Could not update sync failure count for PR #%d", pr_number)

        return False
    finally:
        # Always tear down the worktree
        try:
            subprocess.run(
                ["git", "worktree", "remove", str(worktree_path), "--force"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            logger.debug("Worktree cleanup failed for task %s", task_id)
        store.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_git(cwd: Path, cmd: list[str], description: str) -> subprocess.CompletedProcess:
    """Run a git command, raising on failure."""
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"git {description} failed: {result.stderr.strip()}")
    return result


def _get_rev(cwd: Path, ref: str) -> str:
    """Return the SHA for a git ref."""
    result = subprocess.run(
        ["git", "rev-parse", ref],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _get_conflict_files(worktree_path: Path) -> list[str]:
    """Return list of files with merge conflicts."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=str(worktree_path),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().splitlines()
    return []


def _get_current_failures(store: OutcomeStore, pr_number: int) -> int:
    """Read current sync_failures count for a PR."""
    try:
        rows = store.get_sync_candidates(999999)
        for row in rows:
            if row["pr_number"] == pr_number:
                return row["sync_failures"]
    except Exception:
        pass
    return 0
