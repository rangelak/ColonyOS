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


def _git(repo_root: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=check,
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
