from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class PreservationResult:
    snapshot_dir: Path
    preservation_mode: str
    stash_message: str | None = None


def recovery_dir_path(repo_root: Path) -> Path:
    """Return the directory used for recovery incident artifacts."""
    return repo_root / ".colonyos" / "recovery"


def incident_slug(prefix: str) -> str:
    """Return a filesystem-safe incident slug."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in prefix).strip("-")
    cleaned = "-".join(part for part in cleaned.split("-") if part) or "incident"
    return f"{timestamp}_{cleaned[:40]}"


_DEFAULT_GIT_TIMEOUT = 30


def _git(
    repo_root: Path, *args: str, check: bool = False, timeout: int | None = _DEFAULT_GIT_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
    )


def git_status_porcelain(repo_root: Path) -> str:
    """Return ``git status --porcelain`` output."""
    result = _git(repo_root, "status", "--porcelain")
    return result.stdout.strip()


def git_merge_in_progress(repo_root: Path) -> bool:
    """Return True when ``MERGE_HEAD`` exists."""
    result = _git(repo_root, "rev-parse", "-q", "--verify", "MERGE_HEAD")
    return result.returncode == 0 and bool(result.stdout.strip())


def dirty_paths_from_status(dirty_output: str) -> list[str]:
    """Parse repo-relative dirty paths from porcelain output."""
    paths: list[str] = []
    for raw_line in dirty_output.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        candidate = line[3:] if len(line) > 3 else line
        if " -> " in candidate:
            candidate = candidate.split(" -> ", 1)[1]
        path = candidate.strip()
        if path:
            paths.append(path)
    return paths


def write_incident_summary(
    repo_root: Path,
    label: str,
    *,
    summary: str,
    metadata: dict[str, object] | None = None,
) -> Path:
    """Persist a recovery incident summary and optional metadata."""
    incident_dir = recovery_dir_path(repo_root)
    incident_dir.mkdir(parents=True, exist_ok=True)
    summary_path = incident_dir / f"{label}.md"
    payload = {
        "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    }
    summary_path.write_text(
        "# Recovery Incident\n\n"
        f"## Summary\n\n{summary.strip() or '(empty summary)'}\n\n"
        "## Metadata\n\n"
        "```json\n"
        f"{json.dumps(payload, indent=2)}\n"
        "```\n",
        encoding="utf-8",
    )
    return summary_path


def snapshot_dirty_state(repo_root: Path, label: str, dirty_output: str | None = None) -> Path:
    """Capture the current repo state before destructive recovery."""
    snapshot_dir = recovery_dir_path(repo_root) / label
    files_dir = snapshot_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    dirty_text = dirty_output if dirty_output is not None else git_status_porcelain(repo_root)
    (snapshot_dir / "git-status.txt").write_text(dirty_text + "\n", encoding="utf-8")

    worktree_diff = _git(repo_root, "diff")
    (snapshot_dir / "git-diff.patch").write_text(worktree_diff.stdout, encoding="utf-8")

    staged_diff = _git(repo_root, "diff", "--cached")
    (snapshot_dir / "git-diff-cached.patch").write_text(staged_diff.stdout, encoding="utf-8")

    untracked = _git(repo_root, "ls-files", "--others", "--exclude-standard")
    (snapshot_dir / "untracked.txt").write_text(untracked.stdout, encoding="utf-8")

    for rel_path in dirty_paths_from_status(dirty_text):
        source = repo_root / rel_path
        if not source.exists() or not source.is_file():
            continue
        target = files_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_bytes(source.read_bytes())
        except OSError:
            continue

    return snapshot_dir


def preserve_and_reset_worktree(repo_root: Path, label: str) -> PreservationResult:
    """Preserve the current state, then leave the worktree clean for recovery."""
    dirty_output = git_status_porcelain(repo_root)
    snapshot_dir = snapshot_dirty_state(repo_root, label, dirty_output)
    stash_message = f"colonyos-nuke-{label}"

    if dirty_output:
        stash_result = _git(repo_root, "stash", "push", "--include-untracked", "-m", stash_message)
        stash_stdout = f"{stash_result.stdout}\n{stash_result.stderr}".strip()
        if stash_result.returncode == 0 and "No local changes to save" not in stash_stdout:
            return PreservationResult(
                snapshot_dir=snapshot_dir,
                preservation_mode="stash",
                stash_message=stash_message,
            )

    if git_merge_in_progress(repo_root):
        abort_result = _git(repo_root, "merge", "--abort")
        if abort_result.returncode != 0:
            raise RuntimeError(abort_result.stderr.strip() or "git merge --abort failed")
    else:
        reset_result = _git(repo_root, "reset", "--hard", "HEAD")
        if reset_result.returncode != 0:
            raise RuntimeError(reset_result.stderr.strip() or "git reset --hard HEAD failed")

    clean_result = _git(repo_root, "clean", "-fd", "-e", ".colonyos/recovery/")
    if clean_result.returncode != 0:
        raise RuntimeError(clean_result.stderr.strip() or "git clean -fd failed")

    return PreservationResult(
        snapshot_dir=snapshot_dir,
        preservation_mode="snapshot",
        stash_message=None,
    )


def pull_branch(
    repo_root: Path, timeout: int = _DEFAULT_GIT_TIMEOUT,
) -> tuple[bool, str | None]:
    """Pull the latest from the remote for the current branch using ``--ff-only``.

    Returns ``(True, None)`` on success.  If there is no remote tracking
    branch the pull is silently skipped and ``(False, None)`` is returned.
    On failure ``(False, error_message)`` is returned.
    """
    # Check for a remote tracking branch first.
    upstream_result = _git(
        repo_root, "rev-parse", "--abbrev-ref", "@{upstream}", timeout=10,
    )
    if upstream_result.returncode != 0:
        # No upstream configured — nothing to pull.
        return False, None

    branch_result = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD", timeout=10)
    branch_name = branch_result.stdout.strip() or "unknown"

    try:
        pull_result = _git(repo_root, "pull", "--ff-only", timeout=timeout)
    except subprocess.TimeoutExpired:
        msg = f"git pull --ff-only timed out after {timeout}s on {branch_name}"
        _LOGGER.warning(msg)
        return False, msg

    if pull_result.returncode != 0:
        msg = pull_result.stderr.strip() or f"git pull --ff-only failed on {branch_name}"
        _LOGGER.warning("Pull failed on %s: %s", branch_name, msg)
        return False, msg

    _LOGGER.info("Pulled latest for %s", branch_name)
    return True, None


def checkout_branch(repo_root: Path, branch_name: str) -> None:
    """Check out an existing branch."""
    result = _git(repo_root, "checkout", branch_name)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git checkout {branch_name} failed")


def create_branch(repo_root: Path, branch_name: str) -> None:
    """Create and check out a new branch from the current HEAD."""
    result = _git(repo_root, "checkout", "-b", branch_name)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git checkout -b {branch_name} failed")


_PROTECTED_BRANCHES = frozenset({"main", "master"})

_LOGGER = __import__("logging").getLogger(__name__)

_SAFETY_STASH_PREFIXES = ("colonyos-safety", "colonyos-branch-restore")
_MAX_SAFETY_STASHES = 5


def _prune_old_safety_stashes(repo_root: Path) -> None:
    """Drop old ColonyOS safety stashes beyond ``_MAX_SAFETY_STASHES``.

    Stash indices are 0-based with 0 being the newest.  We keep the
    ``_MAX_SAFETY_STASHES`` most recent safety stashes and drop the rest,
    iterating from highest index to lowest so that drops don't shift the
    indices of entries we still need to process.

    Best-effort: failures are silently ignored.
    """
    try:
        result = _git(repo_root, "stash", "list")
        if result.returncode != 0 or not result.stdout.strip():
            return

        safety_indices: list[int] = []
        for line in result.stdout.strip().splitlines():
            if any(prefix in line for prefix in _SAFETY_STASH_PREFIXES):
                try:
                    idx = int(line.split("@{", 1)[1].split("}", 1)[0])
                    safety_indices.append(idx)
                except (IndexError, ValueError):
                    continue

        if len(safety_indices) <= _MAX_SAFETY_STASHES:
            return

        safety_indices.sort()
        to_drop = safety_indices[_MAX_SAFETY_STASHES:]
        for idx in sorted(to_drop, reverse=True):
            _git(repo_root, "stash", "drop", f"stash@{{{idx}}}")
        _LOGGER.debug(
            "Pruned %d old safety stash(es)", len(to_drop),
        )
    except Exception:
        pass


def safety_commit_partial_work(
    repo_root: Path,
    *,
    context_lines: list[str] | None = None,
) -> str | None:
    """Commit or stash dirty working-tree state after a failed pipeline run.

    On feature branches the changes are committed (preserving partial work
    on the branch for later inspection or ``--resume``).  On protected
    branches (main/master) the changes are stashed instead.

    Uses ``--no-verify`` and a generous timeout to avoid the exact failure
    mode that caused the original issue (pre-commit hooks timing out).

    Returns a short description of what was done, or ``None`` if the tree
    was already clean.  Never raises — all errors are logged and swallowed
    so this cannot mask the original pipeline failure.
    """
    try:
        status = _git(repo_root, "status", "--porcelain")
        dirty = status.stdout.strip()
        if not dirty:
            return None

        branch_result = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
        current_branch = branch_result.stdout.strip() or "UNKNOWN"

        # Detached HEAD or protected branches: stash instead of committing.
        # On detached HEAD, a commit would be unreachable (effectively lost).
        should_stash = (
            current_branch in _PROTECTED_BRANCHES
            or current_branch in ("HEAD", "UNKNOWN")
        )

        if should_stash:
            stash_msg = f"colonyos-safety-stash-{current_branch}"
            _git(repo_root, "stash", "push", "--include-untracked", "-m", stash_msg, timeout=60)
            desc = f"Stashed dirty state on {current_branch} ({stash_msg})"
            _LOGGER.info(desc)
            return desc

        lines = ["WIP: preserving partial work after pipeline failure", ""]
        if context_lines:
            lines.extend(context_lines)
            lines.append("")
        lines.append("Automatic safety commit by ColonyOS.")
        lines.append("Preserves partial work and keeps the tree clean")
        lines.append("for subsequent pipeline runs.")
        msg = "\n".join(lines)

        _git(repo_root, "add", "-A", timeout=60)
        commit = _git(repo_root, "commit", "--no-verify", "-m", msg, timeout=120)

        if commit.returncode == 0:
            desc = f"Safety-committed partial work on {current_branch}"
            _LOGGER.info(desc)
            return desc

        # Commit failed (e.g. empty after add, or hook error despite
        # --no-verify).  Reset the index to undo the add, then stash.
        _git(repo_root, "reset", "HEAD", timeout=30)
        stash_msg = f"colonyos-safety-{current_branch}"
        _git(repo_root, "stash", "push", "--include-untracked", "-m", stash_msg, timeout=60)
        desc = f"Commit failed, stashed on {current_branch} ({stash_msg})"
        _LOGGER.warning(desc)
        return desc
    except Exception:
        _LOGGER.warning("safety_commit_partial_work failed", exc_info=True)
        return None
    finally:
        _prune_old_safety_stashes(repo_root)


def restore_to_branch(
    repo_root: Path, target_branch: str, *, pull: bool = True,
) -> str | None:
    """Ensure the repo is on *target_branch*, cleaning up if necessary.

    Intended for daemon use: after a pipeline run (success or failure) the
    daemon should be back on the default branch ready for the next item.

    When *pull* is ``True`` (the default) the branch is pulled after checkout
    so that subsequent work starts from the latest remote state.  Pull
    failures are logged as warnings but never cause the function to fail.

    Returns a description of what was done, or ``None`` if already there.
    Never raises.
    """
    try:
        branch_result = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
        current = branch_result.stdout.strip()
        if current == target_branch:
            return None

        status = _git(repo_root, "status", "--porcelain")
        if status.stdout.strip():
            safe_label = current if current not in ("HEAD", "") else "detached"
            stash_msg = f"colonyos-branch-restore-{safe_label}"
            _git(repo_root, "stash", "push", "--include-untracked", "-m", stash_msg, timeout=60)
            _LOGGER.info("Stashed leftover dirty state before restoring to %s", target_branch)

        checkout = _git(repo_root, "checkout", target_branch)
        if checkout.returncode != 0:
            _LOGGER.warning(
                "Failed to checkout %s: %s", target_branch, checkout.stderr.strip()
            )
            return None

        desc = f"Restored to {target_branch} (was on {current})"

        if pull:
            try:
                pulled, pull_err = pull_branch(repo_root)
                if pulled:
                    desc += ", pulled latest"
                elif pull_err:
                    _LOGGER.warning("Pull after restore failed: %s", pull_err)
                    desc += f", pull failed: {pull_err}"
            except Exception:
                _LOGGER.warning("Pull after restore raised unexpectedly", exc_info=True)

        _LOGGER.info(desc)
        return desc
    except Exception:
        _LOGGER.warning("restore_to_branch failed", exc_info=True)
        return None
    finally:
        _prune_old_safety_stashes(repo_root)
