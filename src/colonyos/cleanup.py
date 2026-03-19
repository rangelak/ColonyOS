"""Codebase hygiene and structural analysis for ColonyOS.

Provides three capabilities:
1. Branch cleanup — prune merged ``colonyos/`` branches (local + remote).
2. Artifact cleanup — remove old ``.colonyos/runs/`` directories.
3. Structural scan — static analysis for complex/large files.

All destructive operations default to dry-run; pass ``execute=True`` to act.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class ComplexityCategory(str, Enum):
    LARGE = "large"
    VERY_LARGE = "very-large"
    MASSIVE = "massive"


@dataclass(frozen=True)
class BranchInfo:
    """Metadata for a single git branch."""
    name: str
    last_commit_date: str
    is_merged: bool
    skip_reason: str | None = None


@dataclass(frozen=True)
class BranchCleanupResult:
    """Summary of a branch cleanup operation."""
    deleted_local: list[str] = field(default_factory=list)
    deleted_remote: list[str] = field(default_factory=list)
    skipped: list[BranchInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ArtifactInfo:
    """Metadata for a single run artifact directory."""
    run_id: str
    date: str
    status: str
    size_bytes: int
    path: Path


@dataclass(frozen=True)
class ArtifactCleanupResult:
    """Summary of an artifact cleanup operation."""
    removed: list[ArtifactInfo] = field(default_factory=list)
    skipped: list[ArtifactInfo] = field(default_factory=list)
    bytes_reclaimed: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FileComplexity:
    """Static analysis result for a single file."""
    path: str
    line_count: int
    function_count: int
    category: ComplexityCategory


# ---------------------------------------------------------------------------
# Branch cleanup
# ---------------------------------------------------------------------------

def _get_default_branch(repo_root: Path) -> str:
    """Detect the default branch (main or master)."""
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True, text=True, timeout=5, cwd=repo_root,
        )
        if result.returncode == 0:
            # e.g. "refs/remotes/origin/main"
            ref = result.stdout.strip()
            return ref.rsplit("/", 1)[-1]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # Fallback: check if main exists, else master
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "main"],
            capture_output=True, text=True, timeout=5, cwd=repo_root,
        )
        if result.returncode == 0:
            return "main"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "master"


def _get_current_branch(repo_root: Path) -> str:
    """Return the name of the currently checked-out branch."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=repo_root,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _get_branch_last_commit_date(branch: str, repo_root: Path) -> str:
    """Return ISO-format date of the last commit on *branch*."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%aI", branch],
            capture_output=True, text=True, timeout=5, cwd=repo_root,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


def list_merged_branches(
    repo_root: Path,
    prefix: str = "colonyos/",
    include_all: bool = False,
) -> list[BranchInfo]:
    """Return local branches fully merged into the default branch.

    Parameters
    ----------
    repo_root:
        Repository root.
    prefix:
        Only include branches whose name starts with *prefix*.
        Ignored when *include_all* is True.
    include_all:
        If True, include all merged branches regardless of prefix.
    """
    default_branch = _get_default_branch(repo_root)
    current_branch = _get_current_branch(repo_root)

    try:
        result = subprocess.run(
            ["git", "branch", "--merged", default_branch],
            capture_output=True, text=True, timeout=10, cwd=repo_root,
        )
        if result.returncode != 0:
            logger.warning("git branch --merged failed: %s", result.stderr.strip())
            return []
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("Failed to list merged branches: %s", exc)
        return []

    branches: list[BranchInfo] = []
    for line in result.stdout.splitlines():
        name = line.strip().lstrip("* ").strip()
        if not name:
            continue
        # Never include the default branch or current branch
        if name in (default_branch, current_branch):
            continue
        # Filter by prefix unless include_all
        if not include_all and not name.startswith(prefix):
            continue

        last_date = _get_branch_last_commit_date(name, repo_root)
        branches.append(BranchInfo(
            name=name,
            last_commit_date=last_date,
            is_merged=True,
        ))

    return branches


def check_branch_safety(
    branch: str,
    repo_root: Path,
) -> str | None:
    """Check whether *branch* is safe to delete.

    Returns a skip reason string if the branch should be skipped, or
    ``None`` if it is safe to delete.
    """
    default_branch = _get_default_branch(repo_root)
    current_branch = _get_current_branch(repo_root)

    if branch == default_branch:
        return "default branch"
    if branch == current_branch:
        return "current branch"

    # Check for open PRs (non-blocking)
    try:
        from colonyos.github import check_open_pr
        pr_number, _pr_url = check_open_pr(branch, repo_root, timeout=5)
        if pr_number is not None:
            return f"has open PR #{pr_number}"
    except Exception as exc:
        logger.warning("Failed to check open PR for %s: %s", branch, exc)

    return None


def delete_branches(
    branches: list[BranchInfo],
    repo_root: Path,
    include_remote: bool = False,
    execute: bool = False,
) -> BranchCleanupResult:
    """Delete merged branches (dry-run by default).

    Returns a :class:`BranchCleanupResult` summarizing what was done.
    """
    deleted_local: list[str] = []
    deleted_remote: list[str] = []
    skipped: list[BranchInfo] = []
    errors: list[str] = []

    for branch_info in branches:
        skip_reason = check_branch_safety(branch_info.name, repo_root)
        if skip_reason:
            skipped.append(BranchInfo(
                name=branch_info.name,
                last_commit_date=branch_info.last_commit_date,
                is_merged=branch_info.is_merged,
                skip_reason=skip_reason,
            ))
            continue

        if not execute:
            deleted_local.append(branch_info.name)
            if include_remote:
                deleted_remote.append(branch_info.name)
            continue

        # Actually delete local branch
        try:
            result = subprocess.run(
                ["git", "branch", "-d", branch_info.name],
                capture_output=True, text=True, timeout=10, cwd=repo_root,
            )
            if result.returncode == 0:
                deleted_local.append(branch_info.name)
            else:
                errors.append(f"Failed to delete local branch {branch_info.name}: {result.stderr.strip()}")
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            errors.append(f"Error deleting local branch {branch_info.name}: {exc}")

        # Delete remote branch if requested
        if include_remote:
            try:
                result = subprocess.run(
                    ["git", "push", "--delete", "origin", branch_info.name],
                    capture_output=True, text=True, timeout=15, cwd=repo_root,
                )
                if result.returncode == 0:
                    deleted_remote.append(branch_info.name)
                else:
                    stderr = result.stderr.strip()
                    # Not an error if remote branch doesn't exist
                    if "remote ref does not exist" not in stderr:
                        errors.append(f"Failed to delete remote branch {branch_info.name}: {stderr}")
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                errors.append(f"Error deleting remote branch {branch_info.name}: {exc}")

    return BranchCleanupResult(
        deleted_local=deleted_local,
        deleted_remote=deleted_remote,
        skipped=skipped,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Artifact cleanup
# ---------------------------------------------------------------------------

def _dir_size(path: Path) -> int:
    """Calculate total size of a directory in bytes."""
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def list_stale_artifacts(
    runs_dir: Path,
    retention_days: int = 30,
) -> tuple[list[ArtifactInfo], list[ArtifactInfo]]:
    """Find completed run artifacts older than *retention_days*.

    Returns ``(stale, skipped)`` where *skipped* includes RUNNING runs
    and runs within the retention period.
    """
    if not runs_dir.exists():
        return [], []

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    stale: list[ArtifactInfo] = []
    skipped: list[ArtifactInfo] = []

    for entry in sorted(runs_dir.iterdir()):
        if not entry.is_file() or not entry.name.endswith(".json"):
            continue
        # Skip cleanup logs themselves
        if entry.name.startswith("cleanup_"):
            continue
        # Skip loop/queue state files
        if entry.name.startswith(("loop_state_", "queue")):
            continue

        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        run_id = data.get("run_id", entry.stem)
        status = data.get("status", "unknown")
        started_at = data.get("started_at", "")

        # Parse date
        try:
            run_date = datetime.fromisoformat(started_at)
        except (ValueError, TypeError):
            continue

        size = entry.stat().st_size

        info = ArtifactInfo(
            run_id=run_id,
            date=started_at,
            status=status,
            size_bytes=size,
            path=entry,
        )

        # Never delete RUNNING runs
        if status == "running":
            skipped.append(info)
            continue

        # Check retention
        if run_date < cutoff:
            stale.append(info)
        else:
            skipped.append(info)

    return stale, skipped


def delete_artifacts(
    artifacts: list[ArtifactInfo],
    execute: bool = False,
) -> ArtifactCleanupResult:
    """Delete stale artifact files (dry-run by default)."""
    removed: list[ArtifactInfo] = []
    errors: list[str] = []
    total_bytes = 0

    for artifact in artifacts:
        if not execute:
            removed.append(artifact)
            total_bytes += artifact.size_bytes
            continue

        try:
            artifact.path.unlink()
            removed.append(artifact)
            total_bytes += artifact.size_bytes
        except OSError as exc:
            errors.append(f"Failed to remove {artifact.path}: {exc}")

    return ArtifactCleanupResult(
        removed=removed,
        skipped=[],
        bytes_reclaimed=total_bytes,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Structural scan
# ---------------------------------------------------------------------------

# Regex patterns for function/class definitions by language family
_FUNCTION_PATTERNS: dict[str, re.Pattern[str]] = {
    ".py": re.compile(r"^\s*(?:def|class|async\s+def)\s+\w+", re.MULTILINE),
    ".js": re.compile(r"(?:^\s*(?:function|class)\s+\w+|^\s*(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?(?:\(|function))", re.MULTILINE),
    ".ts": re.compile(r"(?:^\s*(?:function|class|interface|type)\s+\w+|^\s*(?:export\s+)?(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?(?:\(|function))", re.MULTILINE),
    ".tsx": re.compile(r"(?:^\s*(?:function|class|interface|type)\s+\w+|^\s*(?:export\s+)?(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?(?:\(|function))", re.MULTILINE),
    ".jsx": re.compile(r"(?:^\s*(?:function|class)\s+\w+|^\s*(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?(?:\(|function))", re.MULTILINE),
    ".go": re.compile(r"^\s*(?:func|type)\s+\w+", re.MULTILINE),
    ".rs": re.compile(r"^\s*(?:fn|struct|enum|impl|trait)\s+\w+", re.MULTILINE),
    ".java": re.compile(r"^\s*(?:public|private|protected|static|\s)*(?:class|interface|void|int|String|boolean|long|double|float)\s+\w+", re.MULTILINE),
    ".rb": re.compile(r"^\s*(?:def|class|module)\s+\w+", re.MULTILINE),
}

# Directories to always skip during scan
_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".colonyos", ".next", "coverage", ".eggs", "*.egg-info",
})

# File extensions to scan
_SOURCE_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs",
    ".java", ".rb", ".c", ".cpp", ".h", ".hpp", ".cs",
})


def scan_file_complexity(path: Path) -> tuple[int, int]:
    """Analyze a single file and return ``(line_count, function_count)``."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, 0

    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)

    ext = path.suffix.lower()
    pattern = _FUNCTION_PATTERNS.get(ext)
    if pattern:
        function_count = len(pattern.findall(content))
    else:
        # Fallback: count lines starting with common definition keywords
        function_count = len(re.findall(
            r"^\s*(?:def|function|class|func|fn|sub)\s+\w+",
            content,
            re.MULTILINE,
        ))

    return line_count, function_count


def _categorize_complexity(
    line_count: int,
    function_count: int,
    max_lines: int,
    max_functions: int,
) -> ComplexityCategory | None:
    """Categorize file complexity based on thresholds.

    Returns ``None`` if the file is under all thresholds.
    """
    line_ratio = line_count / max_lines if max_lines > 0 else 0
    func_ratio = function_count / max_functions if max_functions > 0 else 0
    ratio = max(line_ratio, func_ratio)

    if ratio >= 3:
        return ComplexityCategory.MASSIVE
    elif ratio >= 2:
        return ComplexityCategory.VERY_LARGE
    elif ratio >= 1:
        return ComplexityCategory.LARGE
    return None


def scan_directory(
    root: Path,
    max_lines: int = 500,
    max_functions: int = 20,
    exclude_patterns: list[str] | None = None,
) -> list[FileComplexity]:
    """Walk the source tree and return files exceeding thresholds.

    Results are sorted by line count descending (most complex first).
    """
    exclude = set(exclude_patterns or [])
    flagged: list[FileComplexity] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Filter out skip directories (in-place modification of dirnames)
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and d not in exclude
        ]

        for filename in filenames:
            fpath = Path(dirpath) / filename
            if fpath.suffix.lower() not in _SOURCE_EXTENSIONS:
                continue

            line_count, function_count = scan_file_complexity(fpath)
            category = _categorize_complexity(
                line_count, function_count, max_lines, max_functions,
            )
            if category is not None:
                try:
                    rel_path = str(fpath.relative_to(root))
                except ValueError:
                    rel_path = str(fpath)
                flagged.append(FileComplexity(
                    path=rel_path,
                    line_count=line_count,
                    function_count=function_count,
                    category=category,
                ))

    # Sort by line count descending
    flagged.sort(key=lambda f: f.line_count, reverse=True)
    return flagged


# ---------------------------------------------------------------------------
# Refactor prompt synthesis
# ---------------------------------------------------------------------------

def synthesize_refactor_prompt(
    file_path: str,
    scan_results: list[FileComplexity] | None = None,
) -> str:
    """Generate a focused refactoring prompt for ``colonyos run``."""
    parts = [f"Refactor `{file_path}`:"]

    # Find the file in scan results for specific guidance
    file_info = None
    if scan_results:
        for result in scan_results:
            if result.path == file_path:
                file_info = result
                break

    if file_info:
        if file_info.line_count > 500:
            parts.append(
                f"  - The file is {file_info.line_count} lines long. "
                "Split it into focused modules with clear responsibilities."
            )
        if file_info.function_count > 20:
            parts.append(
                f"  - The file has {file_info.function_count} functions/classes. "
                "Group related functions into separate modules."
            )
        parts.append(
            f"  - Complexity category: {file_info.category.value}."
        )
    else:
        parts.append("  - Analyze the file for structural improvements.")
        parts.append("  - Split overly large files into focused modules.")

    parts.append("  - Maintain all existing functionality and public interfaces.")
    parts.append("  - Add or update tests to cover any refactored code.")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def write_cleanup_log(
    runs_dir: Path,
    operation: str,
    result: dict,
) -> Path:
    """Write an audit log for a cleanup operation.

    Returns the path to the log file.
    """
    runs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = runs_dir / f"cleanup_{timestamp}.json"

    log_data = {
        "operation": operation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "result": result,
    }

    log_path.write_text(
        json.dumps(log_data, indent=2, default=str),
        encoding="utf-8",
    )
    return log_path
