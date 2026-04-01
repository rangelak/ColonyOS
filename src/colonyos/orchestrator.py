from __future__ import annotations

import inspect
import json
import logging
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Protocol

import click
from claude_agent_sdk import AgentDefinition

from colonyos.agent import run_phase_sync, run_phases_parallel_sync
from colonyos.config import ColonyConfig, runs_dir_path
from colonyos.dag import TaskDAG, parse_task_file
from colonyos.models import TaskStatus
from colonyos.parallel_orchestrator import (
    ParallelOrchestrator,
    should_use_parallel,
    ManualInterventionRequired,
)
from colonyos.learnings import (
    LearningEntry,
    append_learnings,
    learnings_path,
    load_learnings_for_injection,
    parse_learnings,
)
from colonyos.models import BranchRestoreError, Persona, Phase, PhaseResult, PreflightError, PreflightResult, ResumeState, RetryInfo, RunLog, RunStatus
from colonyos.naming import (
    decision_artifact_path,
    generate_timestamp,
    persona_review_artifact_path,
    planning_names,
    proposal_names,
    slugify,
    standalone_decision_artifact_path,
    summary_artifact_path,
)
from colonyos.github import check_open_pr
from colonyos.repo_map import generate_repo_map
from colonyos.memory import MemoryCategory, MemoryStore, load_memory_for_injection
from colonyos.outcomes import OutcomeStore, format_outcome_summary
from colonyos.recovery import (
    PreservationResult,
    checkout_branch,
    create_branch,
    incident_slug,
    preserve_and_reset_worktree,
    pull_branch,
    recovery_dir_path,
    write_incident_summary,
)
from colonyos.sanitize import sanitize_for_slack, sanitize_untrusted_content
from colonyos.slack import is_valid_git_ref
from colonyos.ui import (
    NullUI,
    ParallelProgressLine,
    PhaseUI,
    StreamBadge,
    make_reviewer_badge,
    make_task_prefix,
    print_reviewer_legend,
)

logger = logging.getLogger(__name__)


class UIFactory(Protocol):
    """Callable that produces phase-UI instances.

    Extended factories accept ``prefix``, ``task_id``, and ``badge``
    keyword arguments.  Legacy factories that only accept a positional
    ``prefix`` string are handled via ``_invoke_ui_factory``.
    """

    def __call__(
        self,
        *,
        prefix: str = "",
        task_id: str | None = None,
        badge: StreamBadge | None = None,
    ) -> object: ...


def _touch_heartbeat(repo_root: Path) -> None:
    """Touch the heartbeat file to signal the orchestrator is alive."""
    heartbeat_path = runs_dir_path(repo_root) / "heartbeat"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.touch()


def _log(msg: str) -> None:
    print(f"[colonyos] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Memory helpers
# ---------------------------------------------------------------------------


def _get_memory_store(
    repo_root: Path, config: ColonyConfig
) -> MemoryStore | None:
    """Return a MemoryStore if memory is enabled, else None."""
    if not config.memory.enabled:
        return None
    try:
        return MemoryStore(
            repo_root, max_entries=config.memory.max_entries
        )
    except Exception:
        _log("Warning: failed to open memory store, continuing without memory")
        return None


def _capture_phase_memory(
    store: MemoryStore | None,
    phase_result: PhaseResult,
    run_id: str,
    config: ColonyConfig,
) -> None:
    """Extract key observations from a phase result and persist them.

    Writes happen only inside the orchestrator process — never from agent
    sessions — to prevent prompt-injection from poisoning the memory store.
    """
    if store is None:
        return

    phase_name = phase_result.phase.value

    # Capture failure context
    if not phase_result.success:
        if not config.memory.capture_failures:
            return
        error_text = phase_result.error or "Phase failed (no error message)"
        try:
            store.add_memory(
                category=MemoryCategory.FAILURE,
                phase=phase_name,
                run_id=run_id,
                text=f"Phase {phase_name} failed: {error_text}",
                tags=["failure", phase_name],
            )
        except Exception:
            _log(f"Warning: failed to capture failure memory for {phase_name}")
        return

    # Map phase to appropriate category
    phase_category_map: dict[str, MemoryCategory] = {
        "implement": MemoryCategory.CODEBASE,
        "fix": MemoryCategory.CODEBASE,
        "plan": MemoryCategory.CODEBASE,
        "review": MemoryCategory.REVIEW_PATTERN,
        "decision": MemoryCategory.REVIEW_PATTERN,
        "standalone_review": MemoryCategory.REVIEW_PATTERN,
        "standalone_fix": MemoryCategory.CODEBASE,
        "standalone_decision": MemoryCategory.REVIEW_PATTERN,
        "thread_fix": MemoryCategory.CODEBASE,
    }

    category = phase_category_map.get(phase_name)
    if category is None:
        return

    # Extract result text from artifacts if available
    result_text = phase_result.artifacts.get("result", "")
    if not result_text:
        return

    # Truncate to a reasonable summary length
    summary = result_text[:2000] if len(result_text) > 2000 else result_text
    try:
        store.add_memory(
            category=category,
            phase=phase_name,
            run_id=run_id,
            text=summary,
            tags=[phase_name],
        )
    except Exception:
        _log(f"Warning: failed to capture memory for {phase_name}")


def _inject_memory_block(
    system: str,
    store: MemoryStore | None,
    phase: str,
    prompt_text: str,
    config: ColonyConfig,
) -> str:
    """Append a memory context block to the system prompt if applicable."""
    if store is None:
        return system
    memory_block = load_memory_for_injection(
        store, phase, prompt_text, max_tokens=config.memory.max_inject_tokens
    )
    if memory_block:
        line_count = memory_block.count("\n")
        _log(f"Injected {line_count} memories ({len(memory_block)} chars) for phase {phase}")
        system += f"\n\n{memory_block}"
    return system


def _inject_repo_map(system: str, repo_map_text: str) -> str:
    """Append a repository structure block to the system prompt.

    Follows the same pattern as :func:`_inject_memory_block` — appends
    after the existing system prompt with a ``## Repository Structure``
    header (FR-18).  Returns *system* unchanged when *repo_map_text* is
    empty or whitespace-only.
    """
    if not repo_map_text or not repo_map_text.strip():
        return system
    _log(f"Injected repo map ({len(repo_map_text)} chars)")
    return system + f"\n\n## Repository Structure\n\n{repo_map_text}"


def _get_current_branch(repo_root: Path) -> str:
    """Get the current git branch name. Raises PreflightError on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        branch = result.stdout.strip()
        if not branch:
            raise PreflightError(
                "Could not determine current branch. Are you in a git repository?"
            )
        return branch
    except OSError as exc:
        raise PreflightError(
            f"Failed to run git: {exc}. Is git installed and is this a git repository?"
        )


def _ensure_branch_exists(repo_root: Path, branch_name: str) -> None:
    """Create the branch from HEAD if it doesn't already exist."""
    check = subprocess.run(
        ["git", "rev-parse", "--verify", branch_name],
        capture_output=True, text=True, cwd=repo_root,
    )
    if check.returncode == 0:
        return

    result = subprocess.run(
        ["git", "checkout", "-b", branch_name],
        capture_output=True, text=True, cwd=repo_root,
    )
    if result.returncode != 0:
        raise PreflightError(
            f"Failed to create feature branch '{branch_name}': {result.stderr.strip()}"
        )
    _log(f"Created feature branch '{branch_name}' for parallel implement")


COLONYOS_OUTPUT_PREFIXES = (
    "cOS_prds/",
    "cOS_tasks/",
    "cOS_reviews/",
    "cOS_proposals/",
    ".colonyos/",
    "generated/",
)


def _check_working_tree_clean(
    repo_root: Path, *, ignore_colonyos_dirs: bool = True,
) -> tuple[bool, str]:
    """Check if the working tree is clean. Returns (is_clean, dirty_output).

    When *ignore_colonyos_dirs* is True (the default), files inside known
    ColonyOS output directories are excluded so the pipeline's own artifacts
    don't block subsequent phases.

    Raises :class:`PreflightError` if git status cannot be determined (fail-closed).
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=30,
        )
        if result.returncode != 0:
            raise PreflightError(
                f"git status exited with code {result.returncode}: "
                f"{result.stderr.strip() or '(no stderr)'}. "
                "Cannot determine working tree state."
            )
        lines = result.stdout.strip().splitlines()
        if ignore_colonyos_dirs:
            lines = [
                ln for ln in lines
                if not any(ln[3:].startswith(p) for p in COLONYOS_OUTPUT_PREFIXES)
            ]
        dirty_output = "\n".join(lines)
        return (not dirty_output, dirty_output)
    except subprocess.TimeoutExpired:
        raise PreflightError(
            "git status timed out after 30s. Cannot determine working tree state."
        )
    except OSError as exc:
        raise PreflightError(
            f"Failed to run git status: {exc}. Cannot determine working tree state."
        )


def _get_head_sha(repo_root: Path) -> str:
    """Get the current HEAD SHA. Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except OSError:
        return ""


def _preflight_check(
    repo_root: Path,
    branch_name: str,
    config: ColonyConfig,
    *,
    offline: bool = False,
    force: bool = False,
) -> PreflightResult:
    """Run pre-flight git state assessment before any agent phases.

    Checks for uncommitted changes, existing branches, open PRs, and
    stale main. Raises :class:`PreflightError` on fatal issues
    unless ``force=True``.
    """
    warnings: list[str] = []

    # Determine current branch (fail-closed)
    current_branch = _get_current_branch(repo_root)

    # Check for uncommitted changes (fail-closed)
    is_clean, dirty_output = _check_working_tree_clean(repo_root)

    if not is_clean and not force:
        dirty_files = dirty_output.splitlines()[:10]
        file_list = "\n  ".join(dirty_files)
        if len(dirty_output.splitlines()) > 10:
            file_list += f"\n  ... and {len(dirty_output.splitlines()) - 10} more"
        raise PreflightError(
            f"Uncommitted changes detected:\n  {file_list}\n\n"
            "Please commit or stash your changes before running colonyos.",
            code="dirty_worktree",
            details={
                "current_branch": current_branch,
                "dirty_files": dirty_files,
                "dirty_output": dirty_output,
            },
        )

    # Check if branch already exists locally
    branch_exists, _ = validate_branch_exists(branch_name, repo_root)

    # If branch exists, check for open PRs
    open_pr_number: int | None = None
    open_pr_url: str | None = None
    if branch_exists and not offline:
        open_pr_number, open_pr_url = check_open_pr(branch_name, repo_root)

    if branch_exists and not force:
        if open_pr_number is not None:
            raise PreflightError(
                f"Branch '{branch_name}' already exists with open PR #{open_pr_number}: "
                f"{open_pr_url}\n\n"
                f"Use --resume to continue existing work, or --force to bypass this check.",
                code="branch_exists",
                details={"branch_name": branch_name, "open_pr_number": open_pr_number, "open_pr_url": open_pr_url},
            )
        raise PreflightError(
            f"Branch '{branch_name}' already exists locally.\n\n"
            "Use --resume to continue existing work, or --force to bypass this check.",
            code="branch_exists",
            details={"branch_name": branch_name},
        )

    # Pull latest for the current branch instead of just fetching and warning.
    main_behind_count: int | None = None
    if not offline:
        pull_ok, pull_err = pull_branch(repo_root)
        if not pull_ok and pull_err is not None:
            warnings.append(f"Failed to pull latest: {pull_err}")
        if pull_ok:
            # Pull succeeded — local branch is up-to-date, no behind count.
            main_behind_count = 0

    action = "proceed"
    if force and (not is_clean or branch_exists):
        action = "forced"

    head_sha = _get_head_sha(repo_root)

    return PreflightResult(
        current_branch=current_branch,
        is_clean=is_clean,
        branch_exists=branch_exists,
        open_pr_number=open_pr_number,
        open_pr_url=open_pr_url,
        main_behind_count=main_behind_count,
        action_taken=action,
        warnings=warnings,
        head_sha=head_sha,
    )


def _resume_preflight(
    repo_root: Path,
    branch_name: str,
    *,
    expected_head_sha: str | None = None,
) -> PreflightResult:
    """Lightweight pre-flight check for resume mode.

    Only validates that the working tree is clean.
    Raises :class:`PreflightError` if uncommitted changes are found
    or if the HEAD SHA has diverged from the expected value.
    """
    current_branch = _get_current_branch(repo_root)
    is_clean, dirty_output = _check_working_tree_clean(repo_root)

    if not is_clean:
        dirty_files = dirty_output.splitlines()[:10]
        file_list = "\n  ".join(dirty_files)
        raise PreflightError(
            f"Uncommitted changes detected:\n  {file_list}\n\n"
            "Please commit or stash your changes before resuming.",
            code="dirty_worktree",
            details={
                "current_branch": current_branch,
                "dirty_files": dirty_files,
                "dirty_output": dirty_output,
            },
        )

    head_sha = _get_head_sha(repo_root)

    if expected_head_sha and head_sha and head_sha != expected_head_sha:
        raise PreflightError(
            f"HEAD SHA has diverged since last run.\n"
            f"  Expected: {expected_head_sha}\n"
            f"  Current:  {head_sha}\n\n"
            "The branch has changed since the last run. Use --force to bypass."
        )

    return PreflightResult(
        current_branch=current_branch,
        is_clean=True,
        branch_exists=True,
        action_taken="proceed",
        head_sha=head_sha,
    )


def _build_run_id(prompt: str) -> str:
    digest = sha1(prompt.strip().encode()).hexdigest()[:10]
    return f"run-{generate_timestamp()}-{digest}"


def _load_instruction(name: str) -> str:
    instructions_dir = Path(__file__).parent / "instructions"
    path = instructions_dir / name
    if not path.exists():
        raise FileNotFoundError(f"Instruction template not found: {path}")
    return path.read_text(encoding="utf-8")


def _format_base(config: ColonyConfig) -> str:
    """Format the base instruction template with all config directories."""
    base = _load_instruction("base.md")
    result = base.format(
        prds_dir=config.prds_dir,
        tasks_dir=config.tasks_dir,
        reviews_dir=config.reviews_dir,
        branch_prefix=config.branch_prefix,
    )
    if config.user_directions:
        result += (
            "\n\n## User Directions (HIGHEST PRIORITY)\n\n"
            "The following directions come directly from the project owner. "
            "Treat these as top-priority constraints that override default behavior.\n\n"
            f"{config.user_directions}"
        )
    return result


def _persona_slug(role: str) -> str:
    """Turn a persona role into a safe subagent key, e.g. 'Steve Jobs' → 'steve-jobs'."""
    return slugify(role)


def _build_persona_agents(personas: list[Persona]) -> dict[str, AgentDefinition]:
    """Build an AgentDefinition per persona so the plan agent can call them in parallel."""
    agents: dict[str, AgentDefinition] = {}
    for p in personas:
        key = _persona_slug(p.role)
        agents[key] = AgentDefinition(
            description=f"{p.role} — {p.expertise}",
            prompt=(
                f"You are {p.role}.\n"
                f"Expertise: {p.expertise}\n"
                f"Perspective: {p.perspective}\n\n"
                "You will be given clarifying questions about a feature request. "
                "Answer every question from your unique perspective. Be opinionated, "
                "specific, and grounded in the codebase you can see. Keep each answer "
                "to 2-4 sentences."
            ),
            tools=["Read", "Glob", "Grep"],
        )
    return agents


def _format_personas_block(personas: list[Persona]) -> str:
    """Build a persona listing for the plan system prompt.

    When subagents are available, this tells the planner which agents to call.
    Falls back to inline role-play when no personas are defined.
    """
    if not personas:
        return (
            "No project personas are defined. Answer clarifying questions from "
            "the perspectives of: a senior engineer, a product lead, and a "
            "potential end-user of this feature."
        )

    lines = [
        "The following expert personas are available as subagents. "
        "After generating your clarifying questions, delegate ALL questions to "
        "EVERY persona subagent IN PARALLEL (call all Agent tools at once). "
        "Each persona has read-only access to the codebase and will answer "
        "from their unique perspective.\n"
    ]
    for p in personas:
        key = _persona_slug(p.role)
        lines.append(f"- **`{key}`**: {p.role} — {p.expertise}")
    lines.append("")
    lines.append(
        "After collecting all persona responses, synthesize their answers "
        "into the PRD. Highlight areas of agreement and tension between personas."
    )
    return "\n".join(lines)


def _build_plan_prompt(
    prompt: str,
    config: ColonyConfig,
    prd_filename: str,
    task_filename: str,
    *,
    source_issue: int | None = None,
    source_issue_url: str | None = None,
) -> tuple[str, str]:
    """Build the system prompt and user prompt for the plan phase."""
    plan_template = _load_instruction("plan.md")

    system = _format_base(config) + "\n\n" + plan_template.format(
        personas_block=_format_personas_block(config.personas),
        prds_dir=config.prds_dir,
        tasks_dir=config.tasks_dir,
        prd_filename=prd_filename,
        task_filename=task_filename,
    )

    if source_issue is not None:
        issue_url = source_issue_url or ""
        system += (
            f"\n\nThis feature request originates from GitHub issue "
            f"#{source_issue} ({issue_url}). The generated PRD must include "
            f"a '## Source Issue' section linking back to the issue."
        )

    user = f"Feature request:\n\n{prompt}"
    return system, user


def _build_implement_prompt(
    config: ColonyConfig,
    prd_path: str,
    task_path: str,
    branch_name: str,
    repo_root: Path | None = None,
) -> tuple[str, str]:
    impl_template = _load_instruction("implement.md")

    system = _format_base(config) + "\n\n" + impl_template.format(
        prd_path=prd_path,
        task_path=task_path,
        branch_name=branch_name,
    )

    if repo_root is not None:
        learnings = load_learnings_for_injection(repo_root)
        if learnings:
            system += f"\n\n## Learnings from Past Runs\n\n{learnings}"

    user = (
        f"Implement the feature described in the PRD at `{prd_path}`. "
        f"Follow the task list at `{task_path}`. "
        f"Work on branch `{branch_name}`."
    )
    return system, user


def _build_single_task_implement_prompt(
    config: ColonyConfig,
    task_id: str,
    task_description: str,
    prd_path: str,
    task_path: str,
    branch_name: str,
    completed_tasks: list[str],
    repo_root: Path | None = None,
) -> tuple[str, str]:
    """Build system and user prompts scoped to a single task in sequential mode.

    Unlike the parallel prompt, this runs in the main worktree (not a
    separate git worktree) and includes context about previously completed
    tasks so the agent can build on prior work.
    """
    impl_template = _load_instruction("implement.md")

    system = _format_base(config) + "\n\n" + impl_template.format(
        prd_path=prd_path,
        task_path=task_path,
        branch_name=branch_name,
    )

    # Add context about completed tasks so the agent knows what's already done.
    # Cap at 10 most recent to avoid consuming excessive context window.
    if completed_tasks:
        max_completed_shown = 10
        if len(completed_tasks) > max_completed_shown:
            trimmed = completed_tasks[-max_completed_shown:]
            omitted = len(completed_tasks) - max_completed_shown
            completed_block = (
                f"  - ... ({omitted} earlier task(s) omitted)\n"
                + "\n".join(f"  - {t}" for t in trimmed)
            )
        else:
            completed_block = "\n".join(f"  - {t}" for t in completed_tasks)
        system += (
            "\n\n## Previously Completed Tasks\n\n"
            "The following tasks have already been implemented and committed. "
            "Do NOT re-implement them. Build on the existing code.\n\n"
            f"{completed_block}"
        )

    if repo_root is not None:
        learnings = load_learnings_for_injection(repo_root)
        if learnings:
            system += f"\n\n## Learnings from Past Runs\n\n{learnings}"

    user = (
        f"Implement ONLY task {task_id}: {task_description}\n\n"
        f"Read the PRD at `{prd_path}` for overall context.\n"
        f"Read the task list at `{task_path}` for details on this specific task.\n"
        f"Work on branch `{branch_name}`.\n\n"
        f"Focus exclusively on task {task_id}. Do not implement other tasks."
    )
    return system, user


def reviewer_personas(config: ColonyConfig) -> list[Persona]:
    """Return only personas that have reviewer=True."""
    return [p for p in config.personas if p.reviewer]


def _build_parallel_implement_prompt(
    config: ColonyConfig,
    task_id: str,
    task_description: str,
    worktree_path: Path,
    prd_path: str,
    task_file_path: str,
    base_branch: str,
) -> tuple[str, str]:
    """Build the system and user prompts for a parallel implement task."""
    impl_template = _load_instruction("implement_parallel.md")

    system = _format_base(config) + "\n\n" + impl_template.format(
        task_id=task_id,
        task_description=task_description,
        worktree_path=str(worktree_path),
        prd_path=prd_path,
        task_file=task_file_path,
        base_branch=base_branch,
    )

    user = (
        f"Implement task {task_id}: {task_description}\n\n"
        f"Work in worktree at: {worktree_path}\n"
        f"Read the PRD at `{prd_path}` for context.\n"
        f"Read the task list at `{task_file_path}` for your specific task."
    )
    return system, user


def _build_conflict_resolve_prompt(
    config: ColonyConfig,
    conflict_files: list[str],
    task_id: str,
    target_branch: str,
    working_dir: Path,
) -> tuple[str, str]:
    """Build the system and user prompts for conflict resolution."""
    template = _load_instruction("conflict_resolve.md")

    system = _format_base(config) + "\n\n" + template.format(
        target_branch=target_branch,
        conflicting_branches=f"task-{task_id}",
        conflict_files=", ".join(conflict_files),
        working_dir=str(working_dir),
    )

    user = (
        f"Resolve merge conflicts from task {task_id}.\n\n"
        f"Conflicting files: {', '.join(conflict_files)}\n\n"
        f"Analyze both sides of each conflict and merge them correctly."
    )
    return system, user


def _run_sequential_implement(
    *,
    log: RunLog,
    repo_root: Path,
    config: ColonyConfig,
    branch_name: str,
    prd_rel: str,
    task_rel: str,
    _make_ui,
    memory_store: MemoryStore | None = None,
    user_injection_provider: Callable[[], list[str]] | None = None,
    repo_map_text: str = "",
) -> PhaseResult | None:
    """Run sequential implementation: one task at a time in topological order.

    Parses the task file into a DAG, iterates in dependency order, and runs
    a focused agent session per task.  Each successful task is committed
    individually.  If a task fails, all transitive dependents are marked
    BLOCKED and skipped.

    Returns a merged PhaseResult or None if the task file cannot be parsed.
    """
    task_file_path = repo_root / task_rel
    if not task_file_path.exists():
        _log(f"Task file not found: {task_rel}")
        return None

    content = task_file_path.read_text(encoding="utf-8")
    deps = parse_task_file(content)
    if not deps:
        _log("No tasks found in task file, falling back to single-prompt mode")
        return None

    dag = TaskDAG(dependencies=deps)
    cycle = dag.detect_cycle()
    if cycle is not None:
        _log(f"Circular dependency detected: {' -> '.join(cycle)}")
        return None

    task_order = dag.topological_sort()
    task_count = len(task_order)
    per_task_budget = config.budget.per_phase / max(task_count, 1)

    _log(
        f"Sequential implement: {task_count} tasks, "
        f"${per_task_budget:.2f}/task budget"
    )

    # Extract task descriptions from the file content
    task_descriptions: dict[str, str] = {}
    for line in content.splitlines():
        m = re.match(r"^-\s*\[[x ]\]\s*(\d+\.\d+)\s+(.*)", line, re.IGNORECASE)
        if m:
            task_descriptions[m.group(1)] = m.group(2).strip()

    completed: set[str] = set()
    failed: set[str] = set()
    blocked: set[str] = set()
    task_results: dict[str, dict] = {}
    total_cost = 0.0
    total_duration_ms = 0
    overall_success = True

    for task_id in task_order:
        task_desc = task_descriptions.get(task_id, f"Task {task_id}")

        # Check if any dependency (direct or transitive) has failed or is blocked
        task_deps = dag.dependencies.get(task_id, [])
        blocked_by: list[str] = []
        for dep in task_deps:
            if dep in failed or dep in blocked:
                blocked_by.append(dep)

        if blocked_by:
            blocked.add(task_id)
            task_results[task_id] = {
                "status": "BLOCKED",
                "blocked_by": blocked_by,
                "description": task_desc,
            }
            _log(
                f"Task {task_id} BLOCKED (depends on failed/blocked: "
                f"{', '.join(blocked_by)})"
            )
            overall_success = False
            continue

        _log(f"Running task {task_id}: {task_desc}")
        t0 = time.monotonic()

        system, user = _build_single_task_implement_prompt(
            config,
            task_id=task_id,
            task_description=task_desc,
            prd_path=prd_rel,
            task_path=task_rel,
            branch_name=branch_name,
            completed_tasks=[
                f"{tid}: {task_descriptions.get(tid, tid)}" for tid in task_order if tid in completed
            ],
            repo_root=repo_root,
        )

        # Inject repo map, semantic memory, and external context (Slack/GitHub)
        system = _inject_repo_map(system, repo_map_text)
        system = _inject_memory_block(system, memory_store, "implement", user, config)
        user += _drain_injected_context(user_injection_provider)

        ui = _make_ui()
        if ui is not None:
            safe_desc = sanitize_for_slack(sanitize_untrusted_content(task_desc))
            short_desc = safe_desc[:_SLACK_TASK_DESC_MAX]
            if len(safe_desc) > _SLACK_TASK_DESC_MAX:
                short_desc = safe_desc[:_SLACK_TASK_DESC_MAX - 3] + "..."
            ui.phase_header(
                f"Implement [{task_id}] {short_desc}",
                per_task_budget,
                config.get_model(Phase.IMPLEMENT),
                branch_name,
            )

        try:
            result = run_phase_sync(
                Phase.IMPLEMENT,
                user,
                cwd=repo_root,
                system_prompt=system,
                model=config.get_model(Phase.IMPLEMENT),
                budget_usd=per_task_budget,
                ui=ui,
                retry_config=config.retry,
                timeout_seconds=config.budget.phase_timeout_seconds,
            )
        except Exception as exc:
            _log(f"Task {task_id} raised exception: {exc}")
            failed.add(task_id)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            task_results[task_id] = {
                "status": "FAILED",
                "error": str(exc),
                "description": task_desc,
                "duration_ms": elapsed_ms,
            }
            overall_success = False
            continue

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        task_cost = result.cost_usd or 0.0
        total_cost += task_cost
        total_duration_ms += elapsed_ms

        if result.success:
            # Selective staging: get changed files, filter out secrets
            diff_result = subprocess.run(
                ["git", "diff", "--name-only"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=30,
            )
            untracked_result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if diff_result.returncode != 0:
                _log(f"Task {task_id}: git diff failed (rc={diff_result.returncode}): {diff_result.stderr.strip()}")
            if untracked_result.returncode != 0:
                _log(f"Task {task_id}: git ls-files failed (rc={untracked_result.returncode}): {untracked_result.stderr.strip()}")
            changed_files = [
                f.strip()
                for f in (
                    (diff_result.stdout.splitlines() if diff_result.returncode == 0 else [])
                    + (untracked_result.stdout.splitlines() if untracked_result.returncode == 0 else [])
                )
                if f.strip()
            ]
            # Filter out sensitive files
            safe_files = [f for f in changed_files if not _is_secret_like_path(f)]
            secret_files = [f for f in changed_files if _is_secret_like_path(f)]
            if secret_files:
                _log(
                    f"Task {task_id}: skipping {len(secret_files)} "
                    f"sensitive file(s) from staging: {secret_files}"
                )

            # Audit trail: log what files this task modified
            if safe_files:
                _log(f"Task {task_id} modified {len(safe_files)} file(s): {safe_files}")

            if safe_files:
                subprocess.run(
                    ["git", "add", "--"] + safe_files,
                    cwd=repo_root,
                    capture_output=True,
                    timeout=30,
                )
            safe_desc = sanitize_untrusted_content(task_desc)
            commit_result = subprocess.run(
                ["git", "commit", "-m", f"Implement task {task_id}: {safe_desc}"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if commit_result.returncode == 0:
                _log(f"Task {task_id} completed and committed")
            else:
                # Nothing to commit is fine (agent may have already committed)
                _log(f"Task {task_id} completed (no new changes to commit)")

            completed.add(task_id)
            task_results[task_id] = {
                "status": "COMPLETED",
                "cost_usd": task_cost,
                "duration_ms": elapsed_ms,
                "description": task_desc,
            }
        else:
            failed.add(task_id)
            task_results[task_id] = {
                "status": "FAILED",
                "error": result.error or "unknown",
                "cost_usd": task_cost,
                "duration_ms": elapsed_ms,
                "description": task_desc,
            }
            overall_success = False
            _log(f"Task {task_id} failed: {result.error}")

    # Build merged PhaseResult
    artifacts = {
        "mode": "sequential",
        "total_tasks": str(task_count),
        "completed": str(len(completed)),
        "failed": str(len(failed)),
        "blocked": str(len(blocked)),
        "task_results": task_results,
    }

    return PhaseResult(
        phase=Phase.IMPLEMENT,
        success=overall_success,
        cost_usd=total_cost,
        duration_ms=total_duration_ms,
        artifacts=artifacts,
        error=None if overall_success else (
            f"{len(failed)} task(s) failed, {len(blocked)} task(s) blocked"
        ),
    )


def _run_parallel_implement(
    *,
    log: RunLog,
    repo_root: Path,
    config: ColonyConfig,
    branch_name: str,
    prd_rel: str,
    task_rel: str,
    _make_ui,
) -> PhaseResult | None:
    """Run parallel implementation using the ParallelOrchestrator.

    This function implements Task 6.4 and 6.6 from the PRD.

    Args:
        log: The run log to append results to.
        repo_root: Path to the repository root.
        config: ColonyOS configuration.
        branch_name: The feature branch name.
        prd_rel: Path to the PRD file.
        task_rel: Path to the task file.
        _make_ui: Factory for creating UI objects.

    Returns:
        The overall PhaseResult for the parallel implement phase,
        or None if parallel mode is not available (falls back to sequential).
    """
    import asyncio

    # Read task file content
    task_file_path = repo_root / task_rel
    if not task_file_path.exists():
        _log(f"Task file not found: {task_rel}")
        return None

    task_content = task_file_path.read_text(encoding="utf-8")

    # Parse tasks to count them
    dependencies = parse_task_file(task_content)
    task_count = len(dependencies)

    if not should_use_parallel(config, task_count):
        _log(f"Parallel mode not applicable (task_count={task_count})")
        return None

    _log(f"Parallel implement mode: {task_count} tasks detected")

    # Create the parallel orchestrator
    def make_agent_runner(prd_path: str, task_file: str, base_branch: str):
        """Create an agent runner closure that captures context."""
        def agent_runner(
            task_id: str,
            worktree_path: Path,
            task_description: str,
            budget_usd: float,
        ) -> PhaseResult:
            # Build prompts for this task
            system, user = _build_parallel_implement_prompt(
                config,
                task_id,
                task_description,
                worktree_path,
                prd_path,
                task_file,
                base_branch,
            )

            # Create a task-specific UI with prefix
            task_ui = _make_ui(task_id=task_id)

            # Run the agent
            result = run_phase_sync(
                Phase.IMPLEMENT,
                user,
                cwd=worktree_path,  # Run in the worktree
                system_prompt=system,
                model=config.get_model(Phase.IMPLEMENT),
                budget_usd=budget_usd,
                ui=task_ui,
                retry_config=config.retry,
                timeout_seconds=config.budget.phase_timeout_seconds,
            )

            # Add task_id to artifacts for tracking (FR-10)
            result.artifacts["task_id"] = task_id

            return result

        return agent_runner

    def make_conflict_resolver(prd_path: str, task_file: str, base_branch: str):
        """Create a conflict resolver closure that captures context."""
        def conflict_resolver(
            conflict_files: list[str],
            task_id: str,
            working_dir: Path,
            prd_path: str,
            task_file_path: str,
            budget_usd: float,
        ) -> PhaseResult:
            system, user = _build_conflict_resolve_prompt(
                config,
                conflict_files,
                task_id,
                base_branch,
                working_dir,
            )

            conflict_ui = _make_ui(
                badge=StreamBadge(text=f"[CONFLICT {task_id}]", style="dim"),
            )

            result = run_phase_sync(
                Phase.CONFLICT_RESOLVE,
                user,
                cwd=working_dir,
                system_prompt=system,
                model=config.get_model(Phase.IMPLEMENT),  # Use implement model
                budget_usd=budget_usd,
                ui=conflict_ui,
                retry_config=config.retry,
                timeout_seconds=config.budget.phase_timeout_seconds,
            )

            return result

        return conflict_resolver

    try:
        orchestrator = ParallelOrchestrator(
            repo_root=repo_root,
            config=config,
            task_file_content=task_content,
            base_branch=branch_name,
            prd_path=prd_rel,
            task_file_path=task_rel,
            phase_budget_usd=config.budget.per_phase,
            conflict_resolver=make_conflict_resolver(prd_rel, task_rel, branch_name),
        )

        orchestrator.parse_tasks()

        # Check preflight
        if not orchestrator.preflight():
            _log("Parallel preflight failed, falling back to sequential")
            return None

        # Ensure the feature branch exists before creating worktrees.
        # In sequential mode the LLM agent creates it, but parallel mode
        # needs a valid git ref to base the task worktrees on.
        _ensure_branch_exists(repo_root, branch_name)

        # Create worktrees
        _log(f"Creating {len(orchestrator.state.tasks)} worktrees...")
        orchestrator.create_worktrees()

        # Run all tasks in parallel
        agent_runner = make_agent_runner(prd_rel, task_rel, branch_name)

        _log("Starting parallel task execution...")
        state = asyncio.run(orchestrator.run_all(agent_runner))

        # Merge results back
        _log("Merging task branches...")
        try:
            conflicts = asyncio.run(orchestrator.merge_worktrees())
            if conflicts:
                _log(f"Warning: Unresolved conflicts in: {conflicts}")
        except ManualInterventionRequired as e:
            _log(f"Manual intervention required: {e}")
            # Still continue - partial work is preserved

        # Clean up worktrees
        orchestrator.cleanup_worktrees()

        # Add all task results to log
        for task_id, task in state.tasks.items():
            if task.phase_result is not None:
                log.phases.append(task.phase_result)

        _save_run_log(repo_root, log)

        # Update log with parallel metadata (FR-11)
        summary = orchestrator.get_summary()
        log.parallel_tasks = summary["total_tasks"]
        log.wall_time_ms = summary["wall_time_ms"]
        log.agent_time_ms = summary["agent_time_ms"]

        # Create aggregate result
        any_failed = len(state.failed) > 0
        aggregate_result = PhaseResult(
            phase=Phase.IMPLEMENT,
            success=not any_failed,
            cost_usd=summary["total_actual_cost_usd"],
            duration_ms=summary["wall_time_ms"],
            artifacts={
                "parallel_tasks": str(summary["total_tasks"]),
                "total_tasks": str(summary["total_tasks"]),
                "completed": str(summary["completed"]),
                "failed": str(summary["failed"]),
                "blocked": str(summary["blocked"]),
                "parallelism_ratio": f"{summary['parallelism_ratio']:.2f}x",
                "task_results": {
                    task_id: {
                        "status": task.status.value.upper(),
                        "description": task.description,
                        "cost_usd": task.actual_cost_usd,
                        "duration_ms": task.duration_ms,
                        "error": task.error or "",
                    }
                    for task_id, task in state.tasks.items()
                },
            },
            error=f"{len(state.failed)} task(s) failed" if any_failed else None,
        )

        return aggregate_result

    except Exception as e:
        _log(f"Parallel implement failed with exception: {e}")
        return PhaseResult(
            phase=Phase.IMPLEMENT,
            success=False,
            error=str(e),
        )


def _build_persona_review_prompt(
    persona: Persona,
    config: ColonyConfig,
    prd_path: str,
    branch_name: str,
) -> tuple[str, str]:
    """Build a review prompt for a single persona with identity baked in."""
    review_template = _load_instruction("review.md")

    system = _format_base(config) + "\n\n" + review_template.format(
        reviewer_role=persona.role,
        reviewer_expertise=persona.expertise,
        reviewer_perspective=persona.perspective,
        prd_path=prd_path,
        branch_name=branch_name,
    )

    user = (
        f"Review the implementation on branch `{branch_name}` against the PRD at "
        f"`{prd_path}`. Assess the entire implementation holistically from your "
        f"perspective as {persona.role}."
    )
    return system, user


_REVIEW_VERDICT_RE = re.compile(
    r"VERDICT:\s*(approve|request-changes)", re.IGNORECASE
)


def extract_review_verdict(result_text: str) -> str:
    """Extract VERDICT: approve or VERDICT: request-changes from review output."""
    match = _REVIEW_VERDICT_RE.search(result_text)
    return match.group(1).lower() if match else "request-changes"


def _collect_review_findings(
    results: list[PhaseResult],
    reviewers: list[Persona],
) -> list[tuple[str, str]]:
    """Parse review results and return (role, full_text) for those requesting changes."""
    findings: list[tuple[str, str]] = []
    for persona, result in zip(reviewers, results):
        text = result.artifacts.get("result", "")
        verdict = extract_review_verdict(text)
        if verdict == "request-changes":
            findings.append((persona.role, text))
    return findings


def _task_sort_key(task_id: str) -> tuple[int, ...]:
    """Sort task IDs numerically where possible."""
    parts: list[int] = []
    for chunk in task_id.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            return (10**9,)
    return tuple(parts)


def _load_task_outline(repo_root: Path, task_rel: str) -> list[tuple[str, str]]:
    """Extract ordered task IDs and descriptions from a task markdown file."""
    task_path = repo_root / task_rel
    if not task_path.exists():
        return []
    outline: list[tuple[str, str]] = []
    content = task_path.read_text(encoding="utf-8")
    for line in content.splitlines():
        match = re.match(r"^-\s*\[[x ]\]\s*(\d+\.\d+)\s+(.*)", line, re.IGNORECASE)
        if match:
            outline.append((match.group(1), match.group(2).strip()))
    return outline


# ---------------------------------------------------------------------------
# Slack formatting constants
# ---------------------------------------------------------------------------
# Maximum character length for Slack thread notes.  Keeps messages well under
# Slack's 40,000-char limit while remaining scannable.
_SLACK_MAX_CHARS = 3000
# Maximum visible tasks / task descriptions shown before ``+N more`` overflow.
_SLACK_MAX_SHOWN_TASKS = 6
# Maximum length for a single task description line (truncated with ``...``).
_SLACK_TASK_DESC_MAX = 72
# Maximum length for a single review finding summary line.
_SLACK_FINDING_MAX = 80


def _truncate_slack_message(text: str, max_chars: int = _SLACK_MAX_CHARS) -> str:
    """Truncate a Slack message to *max_chars* at a newline boundary.

    If *text* exceeds *max_chars*, it is cut at the last newline before the
    limit and a ``_(truncated)_`` indicator is appended.  This keeps messages
    well under Slack's 40,000-char limit while remaining scannable.
    """
    if len(text) <= max_chars:
        return text
    # Find last newline before the limit (leave room for the indicator)
    indicator = "\n_(truncated)_"
    cut = text.rfind("\n", 0, max_chars - len(indicator))
    if cut <= 0:
        # No newline found — hard cut
        cut = max_chars - len(indicator)
    return text[:cut] + indicator


def _format_task_outline_note(tasks: list[tuple[str, str]]) -> str:
    """Summarize the planned task list for the implement phase.

    Returns a Slack mrkdwn formatted bullet list with a bold header line,
    one ``•`` bullet per task (up to 6), and a ``+N more`` overflow line.
    """
    if not tasks:
        return ""
    lines: list[str] = [f"*Implement tasks ({len(tasks)}):*"]
    for task_id, description in tasks[:_SLACK_MAX_SHOWN_TASKS]:
        safe_desc = sanitize_for_slack(sanitize_untrusted_content(description))
        short = safe_desc if len(safe_desc) <= _SLACK_TASK_DESC_MAX else f"{safe_desc[:_SLACK_TASK_DESC_MAX - 3]}..."
        lines.append(f"\u2022 `{task_id}` {short}")
    if len(tasks) > _SLACK_MAX_SHOWN_TASKS:
        lines.append(f"+{len(tasks) - _SLACK_MAX_SHOWN_TASKS} more")
    return _truncate_slack_message("\n".join(lines))


def _normalize_task_status(raw: object) -> str:
    return str(raw or "").strip().upper().replace("_", "-")


def _parse_task_results_artifact(raw: object) -> dict[str, dict[str, object]]:
    """Decode the serialized task-results artifact when present."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        normalized: dict[str, dict[str, object]] = {}
        for task_id, info in raw.items():
            if isinstance(task_id, str) and isinstance(info, dict):
                normalized[task_id] = dict(info)
        return normalized
    if not isinstance(raw, (str, bytes, bytearray)):
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    normalized = dict[str, dict[str, object]]()
    for task_id, info in parsed.items():
        if isinstance(task_id, str) and isinstance(info, dict):
            normalized[task_id] = dict(info)
    return normalized


def _format_task_ids(task_ids: list[str]) -> str:
    ordered = sorted(task_ids, key=_task_sort_key)
    return ", ".join(f"`{task_id}`" for task_id in ordered)


def _format_task_list_with_descriptions(
    task_ids: list[str],
    task_results: dict[str, dict[str, object]],
    *,
    max_shown: int = _SLACK_MAX_SHOWN_TASKS,
) -> str:
    """Format task IDs with descriptions as bullet points.

    Each line is ``• `{id}` {description}`` with optional cost/duration suffix.
    Shows up to *max_shown* tasks with ``+N more`` overflow.
    """
    ordered = sorted(task_ids, key=_task_sort_key)
    lines: list[str] = []
    for task_id in ordered[:max_shown]:
        info = task_results.get(task_id, {})
        desc = str(info.get("description", ""))
        desc = sanitize_for_slack(sanitize_untrusted_content(desc))
        if len(desc) > _SLACK_TASK_DESC_MAX:
            desc = desc[:_SLACK_TASK_DESC_MAX - 3] + "..."
        suffix = ""
        cost = info.get("cost_usd")
        dur = info.get("duration_ms")
        if cost is not None and dur is not None:
            try:
                secs = int(dur) // 1000
                suffix = f" — ${float(cost):.2f}, {secs}s"
            except (ValueError, TypeError):
                logger.debug("Skipping malformed cost/duration for task %s: cost=%r, dur=%r", task_id, cost, dur)
        line = f"• `{task_id}` {desc}{suffix}" if desc else f"• `{task_id}`{suffix}"
        lines.append(line)
    if len(ordered) > max_shown:
        lines.append(f"+{len(ordered) - max_shown} more")
    return "\n".join(lines)


def _format_implement_result_note(result: PhaseResult) -> str:
    """Summarize completed/failed/blocked tasks for a finished implement phase.

    When structured ``task_results`` are available, renders a categorized bullet
    list with descriptions and optional cost/duration per task.  Falls back to
    plain counts when the artifact is missing or unparseable.
    """
    task_results = _parse_task_results_artifact(result.artifacts.get("task_results"))
    if task_results:
        completed = [
            task_id for task_id, info in task_results.items()
            if _normalize_task_status(info.get("status")) == "COMPLETED"
        ]
        failed = [
            task_id for task_id, info in task_results.items()
            if _normalize_task_status(info.get("status")) == "FAILED"
        ]
        blocked = [
            task_id for task_id, info in task_results.items()
            if _normalize_task_status(info.get("status")) == "BLOCKED"
        ]
    else:
        completed_count = int(result.artifacts.get("completed", "0") or "0")
        failed_count = int(result.artifacts.get("failed", "0") or "0")
        blocked_count = int(result.artifacts.get("blocked", "0") or "0")
        return (
            f"Task results: {completed_count} completed, "
            f"{failed_count} failed, {blocked_count} blocked."
        )

    parts: list[str] = [
        f"*Task results:* {len(completed)} completed, {len(failed)} failed, {len(blocked)} blocked."
    ]
    if completed:
        parts.append(":white_check_mark: *Completed:*")
        parts.append(_format_task_list_with_descriptions(completed, task_results))
    if failed:
        parts.append(":x: *Failed:*")
        parts.append(_format_task_list_with_descriptions(failed, task_results))
    if blocked:
        parts.append(":no_entry_sign: *Blocked:*")
        parts.append(_format_task_list_with_descriptions(blocked, task_results))
    return _truncate_slack_message("\n".join(parts))


def _invoke_ui_factory(
    ui_factory: UIFactory | Callable[..., object],
    *,
    prefix: str = "",
    task_id: str | None = None,
    badge: StreamBadge | None = None,
) -> object:
    """Call UI factories while preserving legacy prefix-only compatibility."""
    try:
        signature = inspect.signature(ui_factory)
    except (TypeError, ValueError):
        signature = None

    if signature is not None:
        parameters = signature.parameters.values()
        supports_extended_args = any(
            param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters
        ) or any(name in signature.parameters for name in ("task_id", "badge"))
        if not supports_extended_args:
            fallback_prefix = prefix
            if badge is not None:
                fallback_prefix = f"{badge.markup} "
            elif task_id is not None:
                fallback_prefix = make_task_prefix(task_id)
            return ui_factory(fallback_prefix)  # type: ignore[operator]

    return ui_factory(prefix=prefix, task_id=task_id, badge=badge)  # type: ignore[operator]


def _reviewer_reference(index: int, role: str) -> str:
    return f"R{index + 1} {role}"


def _extract_review_findings_summary(
    text: str,
    max_findings: int = 2,
    max_chars: int = _SLACK_FINDING_MAX,
) -> list[str]:
    """Extract a condensed list of findings from review result text.

    Strategy:
    1. Look for a ``FINDINGS:`` section and collect ``- `` prefixed lines.
    2. If no FINDINGS section, try ``SYNTHESIS:`` and use its first sentence.
    3. Fall back to the first non-empty, non-verdict line of text.

    Each returned string is truncated to *max_chars*.
    """
    if not text or not text.strip():
        return []

    lines = text.splitlines()

    # --- attempt 1: explicit FINDINGS section ---
    findings_lines: list[str] = []
    in_findings = False
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("FINDINGS:"):
            in_findings = True
            continue
        if in_findings:
            if stripped.startswith("- "):
                findings_lines.append(stripped[2:].strip())
            elif not stripped and len(findings_lines) < max_findings:
                # Tolerate a single blank line between findings, but only
                # while we haven't yet collected enough.
                continue
            else:
                # Hit a non-finding line or blank after enough findings — stop
                break
    if findings_lines:
        truncated = []
        for f in findings_lines[:max_findings]:
            f = sanitize_for_slack(sanitize_untrusted_content(f))
            if len(f) > max_chars:
                truncated.append(f[: max_chars - 3] + "...")
            else:
                truncated.append(f)
        return truncated

    # --- attempt 2: SYNTHESIS section ---
    in_synthesis = False
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("SYNTHESIS:"):
            in_synthesis = True
            continue
        if in_synthesis and stripped:
            # Take the first sentence / first non-empty line
            sentence = stripped.split(". ")[0]
            if not sentence.endswith("."):
                sentence += "."
            sentence = sanitize_for_slack(sanitize_untrusted_content(sentence))
            if len(sentence) > max_chars:
                sentence = sentence[: max_chars - 3] + "..."
            return [sentence]

    # --- attempt 3: first non-empty, non-verdict line ---
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.upper().startswith("VERDICT:"):
            stripped = sanitize_for_slack(sanitize_untrusted_content(stripped))
            if len(stripped) > max_chars:
                stripped = stripped[: max_chars - 3] + "..."
            return [stripped]

    return []


def _format_review_round_note(
    results: list[PhaseResult],
    reviewers: list[Persona],
    round_num: int,
    total_rounds: int,
) -> str:
    """Summarize one full review round for Slack and terminal milestone updates.

    Groups reviewers into approved / requested-changes / failed categories
    with emoji markers for visual hierarchy.  For reviewers who requested
    changes, includes condensed finding summaries extracted from the review
    result text via :func:`_extract_review_findings_summary`.
    """
    approved: list[str] = []
    requested_changes: list[tuple[str, str]] = []  # (reviewer_ref, result_text)
    failed: list[str] = []

    for index, (persona, result) in enumerate(zip(reviewers, results)):
        reviewer_ref = _reviewer_reference(index, persona.role)
        if not result.success:
            failed.append(reviewer_ref)
            continue
        result_text = result.artifacts.get("result", "")
        verdict = extract_review_verdict(result_text)
        if verdict == "request-changes":
            requested_changes.append((reviewer_ref, result_text))
        else:
            approved.append(reviewer_ref)

    summary = (
        f"Review round {round_num}/{total_rounds}: "
        f"{len(approved)} approved, {len(requested_changes)} requested changes, "
        f"{len(failed)} failed."
    )
    details: list[str] = [summary]

    if approved:
        details.append("")
        details.append(":white_check_mark: *Approved:* " + ", ".join(approved))

    if requested_changes:
        details.append("")
        details.append(":warning: *Requested changes:*")
        for reviewer_ref, result_text in requested_changes:
            findings = _extract_review_findings_summary(result_text)
            if findings:
                details.append(f"• *{reviewer_ref}:* " + "; ".join(findings))
            else:
                details.append(f"• *{reviewer_ref}*")

    if failed:
        details.append("")
        details.append("Failed reviewers: " + ", ".join(failed))

    if not requested_changes and not failed:
        details.append("All reviewers approved; moving to the decision gate.")

    return _truncate_slack_message("\n".join(details))


def _format_fix_iteration_extra(
    reviewers: list[Persona],
    findings: list[tuple[str, str]],
) -> str:
    """Return a short fix-phase header summary for the reviewer findings."""
    if not findings:
        return ""
    reviewer_indices = {persona.role: index for index, persona in enumerate(reviewers)}
    refs: list[str] = []
    for role, _ in findings:
        idx = reviewer_indices.get(role)
        refs.append(_reviewer_reference(idx, role) if idx is not None else role)
    rendered = ", ".join(refs[:3])
    if len(refs) > 3:
        rendered += f", +{len(refs) - 3} more"
    return f"Addressing feedback from {rendered}"


def _build_decision_prompt(
    config: ColonyConfig,
    prd_path: str,
    branch_name: str,
) -> tuple[str, str]:
    """Build the system prompt and user prompt for the decision gate."""
    decision_template = _load_instruction("decision.md")

    system = _format_base(config) + "\n\n" + decision_template.format(
        prd_path=prd_path,
        branch_name=branch_name,
        reviews_dir=config.reviews_dir,
    )

    user = (
        f"Review all artifacts for the implementation on branch `{branch_name}` "
        f"and make a GO / NO-GO decision. "
        f"The PRD is at `{prd_path}`. Review artifacts are in `{config.reviews_dir}/`."
    )
    return system, user


def _extract_verdict(result_text: str) -> str:
    """Extract VERDICT: GO or VERDICT: NO-GO from decision output."""
    match = re.search(r"VERDICT:\s*(GO|NO-GO)", result_text, re.IGNORECASE)
    return match.group(1).upper() if match else "UNKNOWN"


def _build_fix_prompt(
    config: ColonyConfig,
    prd_path: str,
    task_path: str,
    branch_name: str,
    findings_text: str,
    fix_iteration: int,
    repo_root: Path | None = None,
) -> tuple[str, str]:
    """Build the system prompt and user prompt for the fix phase."""
    fix_template = _load_instruction("fix.md")

    system = _format_base(config) + "\n\n" + fix_template.format(
        prd_path=prd_path,
        task_path=task_path,
        branch_name=branch_name,
        reviews_dir=config.reviews_dir,
        findings_text=findings_text,
        fix_iteration=fix_iteration,
        max_fix_iterations=config.max_fix_iterations,
    )

    if repo_root is not None:
        learnings = load_learnings_for_injection(repo_root)
        if learnings:
            system += f"\n\n## Learnings from Past Runs\n\n{learnings}"

    user = (
        f"Fix the issues identified by reviewers for branch `{branch_name}`. "
        f"This is fix iteration {fix_iteration} of {config.max_fix_iterations}. "
        f"The PRD is at `{prd_path}` and the task file is at `{task_path}`."
    )
    return system, user


def _build_ci_fix_prompt(
    config: ColonyConfig,
    branch_name: str,
    ci_failure_context: str,
    fix_attempt: int,
    max_retries: int,
) -> tuple[str, str]:
    """Build the system prompt and user prompt for the CI fix phase."""
    ci_fix_template = _load_instruction("ci_fix.md")

    system = _format_base(config) + "\n\n" + ci_fix_template.format(
        branch_name=branch_name,
        ci_failure_context=ci_failure_context,
        fix_attempt=fix_attempt,
        max_retries=max_retries,
    )

    user = (
        f"Fix the CI failures on branch `{branch_name}`. "
        f"This is attempt {fix_attempt} of {max_retries}."
    )
    return system, user


def _build_preflight_recovery_prompt(
    config: ColonyConfig,
    branch_name: str,
    blocked_prompt: str,
    dirty_output: str,
) -> tuple[str, str]:
    """Build the system prompt and user prompt for dirty-worktree recovery."""
    recovery_template = _load_instruction("preflight_recovery.md")

    system = _format_base(config) + "\n\n" + recovery_template.format(
        branch_name=branch_name,
        dirty_output=dirty_output.strip() or "(git status returned no details)",
    )

    user = (
        f"A TUI pipeline run was blocked before start because the working tree was dirty.\n\n"
        f"Saved user prompt:\n{blocked_prompt}\n"
    )
    return system, user


_SECRET_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
_SECRET_FILE_SUFFIXES = {
    ".pem",
    ".p12",
    ".pfx",
    ".key",
    ".crt",
    ".cer",
    ".der",
}


def _dirty_paths_from_output(dirty_output: str) -> list[str]:
    """Parse repo-relative paths from ``git status --porcelain`` output."""
    paths: list[str] = []
    for raw_line in dirty_output.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        match = re.match(r"^[ MADRCU?!]{1,2}\s+(.*)$", line)
        candidate = match.group(1) if match else line
        if " -> " in candidate:
            candidate = candidate.split(" -> ", 1)[1]
        path = candidate.strip()
        if path:
            paths.append(path)
    return paths


def _is_secret_like_path(path: str) -> bool:
    """Return True for obviously sensitive files that must never be auto-committed."""
    pure_path = Path(path)
    lower_name = pure_path.name.lower()
    lower_parts = {part.lower() for part in pure_path.parts}
    if lower_name in _SECRET_FILE_NAMES:
        return True
    if lower_name.startswith(".env"):
        return True
    if pure_path.suffix.lower() in _SECRET_FILE_SUFFIXES:
        return True
    if ".ssh" in lower_parts:
        return True
    return False


def _recovery_scope_extras(
    blocked_paths: set[str],
    changed_paths: set[str],
) -> list[str]:
    """Return changed paths that exceed the allowed recovery scope."""
    extras = sorted(
        path for path in changed_paths
        if path not in blocked_paths and not path.startswith("tests/")
    )
    return extras


def _changed_paths_between(repo_root: Path, before_head: str, after_head: str) -> set[str]:
    """Return files changed between two revisions."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{before_head}..{after_head}"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PreflightError(
            f"Failed to inspect recovery commit scope: {exc}",
        ) from exc
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def run_preflight_recovery(
    repo_root: Path,
    config: ColonyConfig,
    *,
    blocked_prompt: str,
    dirty_output: str,
    branch_name: str | None = None,
    ui: PhaseUI | NullUI | None = None,
) -> PhaseResult:
    """Run a dedicated agent that commits dirty worktree changes before retrying."""
    active_branch = branch_name or _get_current_branch(repo_root)
    blocked_paths = _dirty_paths_from_output(dirty_output)
    secret_paths = [path for path in blocked_paths if _is_secret_like_path(path)]
    if secret_paths:
        summary = "\n".join(secret_paths[:10])
        return PhaseResult(
            phase=Phase.PREFLIGHT_RECOVERY,
            success=False,
            model=config.get_model(Phase.PREFLIGHT_RECOVERY),
            error=(
                "Preflight recovery refused to auto-commit sensitive-looking files:\n"
                f"{summary}\n\nCommit or stash these changes manually."
            ),
        )

    system_prompt, user_prompt = _build_preflight_recovery_prompt(
        config,
        active_branch,
        blocked_prompt,
        dirty_output,
    )
    model = config.get_model(Phase.PREFLIGHT_RECOVERY)

    if ui is not None:
        ui.phase_header(
            "Preflight Recovery",
            config.budget.per_phase,
            model,
            active_branch,
        )

    before_head = _get_head_sha(repo_root)
    phase_result = run_phase_sync(
        Phase.PREFLIGHT_RECOVERY,
        user_prompt,
        cwd=repo_root,
        system_prompt=system_prompt,
        model=model,
        budget_usd=config.budget.per_phase,
        allowed_tools=["Read", "Glob", "Grep", "Bash", "Write", "Edit"],
        ui=ui,
        retry_config=config.retry,
        timeout_seconds=config.budget.phase_timeout_seconds,
    )

    if not phase_result.success:
        return phase_result

    is_clean, remaining_dirty = _check_working_tree_clean(repo_root)
    if not is_clean:
        dirty_files = remaining_dirty.splitlines()[:10]
        summary = "\n".join(dirty_files)
        return PhaseResult(
            phase=Phase.PREFLIGHT_RECOVERY,
            success=False,
            model=model,
            error=(
                "Preflight recovery left uncommitted changes in the working tree:\n"
                f"{summary}"
            ),
        )

    after_head = _get_head_sha(repo_root)
    if before_head and after_head == before_head:
        return PhaseResult(
            phase=Phase.PREFLIGHT_RECOVERY,
            success=False,
            model=model,
            error="Preflight recovery did not create a commit.",
        )

    if before_head and after_head:
        changed_paths = _changed_paths_between(repo_root, before_head, after_head)
        missing_paths = sorted(path for path in blocked_paths if path not in changed_paths)
        if missing_paths:
            summary = "\n".join(missing_paths[:10])
            return PhaseResult(
                phase=Phase.PREFLIGHT_RECOVERY,
                success=False,
                model=model,
                error=(
                    "Preflight recovery created a commit, but it did not cover all blocked files:\n"
                    f"{summary}"
                ),
            )

        extras = _recovery_scope_extras(set(blocked_paths), changed_paths)
        if extras:
            summary = "\n".join(extras[:10])
            return PhaseResult(
                phase=Phase.PREFLIGHT_RECOVERY,
                success=False,
                model=model,
                error=(
                    "Preflight recovery expanded scope beyond the blocked files and direct test updates:\n"
                    f"{summary}"
                ),
            )

    return phase_result


def _build_auto_recovery_prompt(
    config: ColonyConfig,
    *,
    phase: Phase,
    branch_name: str,
    prd_rel: str,
    task_rel: str,
    original_prompt: str,
    failure_reason: str,
) -> tuple[str, str]:
    """Build the prompt for an automatic phase-recovery agent."""
    recovery_template = _load_instruction("auto_recovery.md")
    system = _format_base(config) + "\n\n" + recovery_template.format(
        failed_phase=phase.value,
        branch_name=branch_name,
        prd_rel=prd_rel,
        task_rel=task_rel,
    )
    user = (
        f"Original user prompt:\n{original_prompt}\n\n"
        f"Failure reason:\n{failure_reason.strip() or '(missing error message)'}\n"
    )
    return system, user


def run_auto_recovery(
    repo_root: Path,
    config: ColonyConfig,
    *,
    phase: Phase,
    branch_name: str,
    prd_rel: str,
    task_rel: str,
    original_prompt: str,
    failure_reason: str,
    ui: PhaseUI | NullUI | None = None,
) -> PhaseResult:
    """Run a narrow repair agent after a failed pipeline phase."""
    system_prompt, user_prompt = _build_auto_recovery_prompt(
        config,
        phase=phase,
        branch_name=branch_name,
        prd_rel=prd_rel,
        task_rel=task_rel,
        original_prompt=original_prompt,
        failure_reason=failure_reason,
    )
    model = config.get_model(Phase.AUTO_RECOVERY)
    if ui is not None:
        ui.phase_header("Auto Recovery", config.budget.per_phase, model, phase.value)
    return run_phase_sync(
        Phase.AUTO_RECOVERY,
        user_prompt,
        cwd=repo_root,
        system_prompt=system_prompt,
        model=model,
        budget_usd=config.budget.per_phase,
        allowed_tools=["Read", "Glob", "Grep", "Bash", "Write", "Edit"],
        ui=ui,
        retry_config=config.retry,
        timeout_seconds=config.budget.phase_timeout_seconds,
    )


def _build_nuke_recovery_prompt(
    config: ColonyConfig,
    *,
    phase: Phase,
    branch_name: str,
    original_prompt: str,
    failure_reason: str,
) -> tuple[str, str]:
    """Build the prompt for the final read-only incident summarizer."""
    nuke_template = _load_instruction("nuke_recovery.md")
    system = _format_base(config) + "\n\n" + nuke_template.format(
        failed_phase=phase.value,
        branch_name=branch_name,
    )
    user = (
        f"Original user prompt:\n{original_prompt}\n\n"
        f"Failure reason:\n{failure_reason.strip() or '(missing error message)'}\n"
    )
    return system, user


def run_nuke_summary(
    repo_root: Path,
    config: ColonyConfig,
    *,
    phase: Phase,
    branch_name: str,
    original_prompt: str,
    failure_reason: str,
    ui: PhaseUI | NullUI | None = None,
) -> PhaseResult:
    """Run a read-only agent that compresses incident context for nuke recovery."""
    system_prompt, user_prompt = _build_nuke_recovery_prompt(
        config,
        phase=phase,
        branch_name=branch_name,
        original_prompt=original_prompt,
        failure_reason=failure_reason,
    )
    model = config.get_model(Phase.NUKE)
    if ui is not None:
        ui.phase_header("Nuke Summary", config.budget.per_phase, model, phase.value)
    return run_phase_sync(
        Phase.NUKE,
        user_prompt,
        cwd=repo_root,
        system_prompt=system_prompt,
        model=model,
        budget_usd=config.budget.per_phase,
        allowed_tools=["Read", "Glob", "Grep"],
        ui=ui,
        retry_config=config.retry,
        timeout_seconds=config.budget.phase_timeout_seconds,
    )


# ---------------------------------------------------------------------------
# Deliver, CEO, and other prompt builders
# ---------------------------------------------------------------------------


def _build_deliver_prompt(
    config: ColonyConfig,
    prd_path: str,
    branch_name: str,
    *,
    source_issue: int | None = None,
    base_branch: str | None = None,
    skip_pr_creation: bool = False,
) -> tuple[str, str]:
    deliver_template = _load_instruction("deliver.md")

    system = _format_base(config) + "\n\n" + deliver_template.format(
        prd_path=prd_path,
        branch_name=branch_name,
    )

    if source_issue is not None:
        system += (
            f"\n\nThis implementation addresses GitHub issue #{source_issue}. "
            f"The PR body MUST include 'Closes #{source_issue}' to auto-close "
            f"the issue on merge. Reference the issue in the summary section."
        )

    if base_branch:
        system += (
            f"\n\nIMPORTANT: This PR must target the branch `{base_branch}` "
            f"instead of `main`. Use `--base {base_branch}` when creating the PR."
        )

    if skip_pr_creation:
        system += (
            "\n\nIMPORTANT: A PR already exists for this branch. "
            "Do NOT create a new PR. Only push the new commits to the "
            "existing branch. The existing PR will be automatically updated."
        )

    user = (
        f"Push branch `{branch_name}` and open a pull request for the "
        f"feature described in `{prd_path}`."
    )
    if skip_pr_creation:
        user = (
            f"Push the latest commits on branch `{branch_name}` to the remote. "
            f"Do NOT create a new PR — one already exists."
        )
    elif base_branch:
        user += f" Target branch: `{base_branch}` (not main)."
    return system, user


def _build_learn_prompt(
    config: ColonyConfig,
    repo_root: Path,
) -> tuple[str, str]:
    """Build the system and user prompts for the learn (extraction) phase."""
    learn_template = _load_instruction("learn.md")
    lpath = learnings_path(repo_root)

    system = learn_template.format(
        reviews_dir=config.reviews_dir,
        learnings_path=str(lpath.relative_to(repo_root)) if lpath.exists() else ".colonyos/learnings.md",
    )

    user = (
        f"Read all review artifacts in `{config.reviews_dir}/` and extract "
        f"3-5 actionable learning patterns. Check `{lpath.relative_to(repo_root) if lpath.exists() else '.colonyos/learnings.md'}` "
        f"for existing entries to avoid duplicates."
    )
    return system, user


def _write_fast_path_artifacts(
    repo_root: Path,
    config: ColonyConfig,
    prd_rel: str,
    task_rel: str,
    prompt: str,
) -> None:
    """Create lightweight PRD/task files for skip-planning runs."""
    safe_prompt = sanitize_untrusted_content(prompt).strip()
    prd_path = repo_root / prd_rel
    task_path = repo_root / task_rel
    prd_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.parent.mkdir(parents=True, exist_ok=True)

    prd_path.write_text(
        "\n".join([
            "# PRD: Fast-Path Small Fix",
            "",
            "## Request",
            "",
            safe_prompt,
            "",
            "## Notes",
            "",
            "This PRD was generated automatically because the router classified",
            "the request as a small fix that can skip the planning phase.",
            "",
        ]),
        encoding="utf-8",
    )
    task_path.write_text(
        "\n".join([
            "# Tasks: Fast-Path Small Fix",
            "",
            "## Tasks",
            "",
            "- [ ] 1.0 Implement the requested fix",
            "  - [ ] 1.1 Update or add the relevant tests",
            "  - [ ] 1.2 Verify the change before review",
            "",
        ]),
        encoding="utf-8",
    )


def _drain_injected_context(
    user_injection_provider: Callable[[], list[str]] | None,
) -> str:
    """Drain queued mid-run user notes and format them for the current phase.

    **Destructive**: Each call consumes the queued messages. Subsequent calls
    will only see messages injected *after* the previous drain.  This is
    intentional — context is timely and should apply to the phase that is
    active when the user submits it, not to all future phases.
    """
    if user_injection_provider is None:
        return ""
    messages = [sanitize_untrusted_content(msg).strip() for msg in user_injection_provider()]
    messages = [msg for msg in messages if msg]
    if not messages:
        return ""
    bullet_lines = "\n".join(f"- {msg}" for msg in messages)
    return (
        "\n\n## Additional User Context\n\n"
        "The user added these notes while the run was active. "
        "Treat them as clarifications for the remaining work.\n"
        f"{bullet_lines}"
    )


_LEARNING_ENTRY_RE = re.compile(r"^- \*\*\[([a-z-]+)\]\*\*\s+(.+)$", re.MULTILINE)

VALID_CATEGORIES = {"code-quality", "testing", "architecture", "security", "style"}


def _parse_learn_output(text: str) -> list[LearningEntry]:
    """Parse the structured output from the learn phase agent."""
    entries = []
    for match in _LEARNING_ENTRY_RE.finditer(text):
        category = match.group(1)
        entry_text = match.group(2).strip()[:150]
        if category in VALID_CATEGORIES:
            entries.append(LearningEntry(category=category, text=entry_text))
    return entries


DEFAULT_CEO_PERSONA = Persona(
    role="Product CEO",
    expertise="Product strategy, prioritization, user impact analysis",
    perspective="What is the single most impactful feature to build next that advances the project's goals?",
)


def _build_ceo_prompt(
    config: ColonyConfig,
    proposal_filename: str,
    repo_root: Path,
    *,
    persona: "Persona | None" = None,
) -> tuple[str, str]:
    """Build the system prompt and user prompt for the CEO phase."""
    from colonyos.directions import load_directions

    ceo_template = _load_instruction("ceo.md")
    persona = persona or config.ceo_persona or DEFAULT_CEO_PERSONA

    directions = load_directions(repo_root)
    if directions.strip():
        directions_block = (
            "**Landscape & inspiration document is loaded.** "
            "Scan it for projects worth studying and patterns to draw from:\n\n"
            f"{directions}"
        )
    else:
        directions_block = (
            "_No directions configured. "
            "Run `colonyos directions --regenerate` to generate a landscape doc._"
        )

    system = ceo_template.format(
        ceo_role=persona.role,
        ceo_expertise=persona.expertise,
        ceo_perspective=persona.perspective,
        project_name=config.project.name if config.project else "Unknown",
        project_description=config.project.description if config.project else "",
        project_stack=config.project.stack if config.project else "",
        vision=config.vision or "No vision statement configured.",
        prds_dir=config.prds_dir,
        tasks_dir=config.tasks_dir,
        directions_block=directions_block,
    )

    changelog = ""
    changelog_path = repo_root / "CHANGELOG.md"
    if changelog_path.exists():
        changelog = changelog_path.read_text(encoding="utf-8")

    # Fetch open issues for CEO context (non-blocking)
    issues_section = ""
    try:
        from colonyos.github import fetch_open_issues

        open_issues = fetch_open_issues(repo_root)
        if open_issues:
            lines = ["## Open Issues\n"]
            lines.append(
                "Consider these open issues as candidates. You may select one "
                "as the basis for your proposal (cite it with `Issue: #N`), "
                "or propose a novel feature if no open issue is high-impact enough.\n"
            )
            for iss in open_issues:
                safe_title = sanitize_untrusted_content(iss.title)
                safe_labels = [sanitize_untrusted_content(l) for l in iss.labels]
                label_str = (
                    " [" + ", ".join(safe_labels) + "]" if safe_labels else ""
                )
                lines.append(f"- #{iss.number}: {safe_title}{label_str}")
            issues_section = "\n".join(lines) + "\n\n"
    except Exception:
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "Failed to fetch open issues for CEO context, proceeding without."
        )

    # Fetch open PRs so the CEO avoids duplicating in-flight work (non-blocking)
    prs_section = ""
    try:
        from colonyos.github import fetch_open_prs

        open_prs = fetch_open_prs(repo_root)
        if open_prs:
            lines = ["## Open Pull Requests (Work In Progress)\n"]
            lines.append(
                "These PRs represent features **currently being developed or awaiting review**. "
                "Your proposal MUST NOT overlap with or duplicate any of these. "
                "Treat them as work that is already underway.\n"
            )
            for pr in open_prs:
                safe_title = sanitize_untrusted_content(pr.title)
                safe_branch = sanitize_untrusted_content(pr.branch)
                safe_labels = [sanitize_untrusted_content(l) for l in pr.labels]
                label_str = (
                    " [" + ", ".join(safe_labels) + "]" if safe_labels else ""
                )
                lines.append(
                    f"- PR #{pr.number}: {safe_title} (branch: `{safe_branch}`){label_str}"
                )
            prs_section = "\n".join(lines) + "\n\n"
    except Exception:
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "Failed to fetch open PRs for CEO context, proceeding without."
        )

    # Inject PR outcome history so the CEO can calibrate based on merge rate (non-blocking)
    outcomes_section = ""
    try:
        outcome_summary = format_outcome_summary(repo_root)
        if outcome_summary:
            outcomes_section = (
                "## PR Outcome History\n\n"
                f"{outcome_summary}\n\n"
            )
    except Exception:
        logger.warning(
            "Failed to compute PR outcome summary for CEO context, proceeding without."
        )

    user = (
        "## Development History\n\n"
        "Below is the complete changelog of features already built. "
        "Your proposal MUST NOT duplicate any of these. "
        "Your proposal MUST build upon or complement existing work.\n\n"
        f"{changelog}\n\n---\n\n"
        f"{prs_section}"
        f"{outcomes_section}"
        f"{issues_section}"
        "Analyze this project and propose the single most impactful feature to build next. "
        "Output your proposal in the format described in the instructions."
    )
    return system, user


def run_ceo(
    repo_root: Path,
    config: ColonyConfig,
    *,
    ui: PhaseUI | NullUI | None = None,
    ceo_persona: "Persona | None" = None,
) -> tuple[str, PhaseResult]:
    """Run the CEO phase: analyze the project and propose the next feature.

    Args:
        repo_root: Path to the repository root.
        config: Colony configuration.
        ui: Optional UI adapter for progress reporting.
        ceo_persona: Optional persona override for CEO profile rotation.

    Returns a tuple of (proposed_prompt, phase_result).
    """
    names = proposal_names("ceo_proposal")
    proposal_filename = names.proposal_filename

    system, user = _build_ceo_prompt(config, proposal_filename, repo_root, persona=ceo_persona)

    # Inject repo map into CEO phase (FR-15: all phases).
    if config.repo_map.enabled:
        try:
            ceo_repo_map_text = generate_repo_map(repo_root, config.repo_map)
            system = _inject_repo_map(system, ceo_repo_map_text)
        except Exception as exc:
            _log(f"Warning: repo map generation failed for CEO phase: {exc}")

    if ui is not None:
        ui.phase_header("CEO", config.budget.per_phase, config.get_model(Phase.CEO))
    else:
        _log("=== CEO Phase ===")
    result = run_phase_sync(
        Phase.CEO,
        user,
        cwd=repo_root,
        system_prompt=system,
        model=config.get_model(Phase.CEO),
        budget_usd=config.budget.per_phase,
        allowed_tools=["Read", "Glob", "Grep"],
        ui=ui,
        retry_config=config.retry,
        timeout_seconds=config.budget.phase_timeout_seconds,
    )

    proposal_text = result.artifacts.get("result", "")

    if result.success and proposal_text:
        proposals_dir = repo_root / config.proposals_dir
        proposals_dir.mkdir(parents=True, exist_ok=True)
        proposal_path = proposals_dir / proposal_filename
        proposal_path.write_text(proposal_text, encoding="utf-8")

    prompt = _extract_feature_prompt(proposal_text) if result.success else ""

    return prompt, result


def update_directions_after_ceo(
    repo_root: Path,
    config: ColonyConfig,
    proposal_text: str,
    iteration: int,
    *,
    ui: "PhaseUI | NullUI | None" = None,
) -> float:
    """Refresh the landscape/inspiration directions document after a CEO proposal.

    Uses a lightweight agent call to evolve the strategic directions based on
    the latest CEO proposal. Fails silently on error so it never blocks the
    main pipeline.

    Returns the USD cost incurred by the update (0.0 on skip or failure).
    """
    from colonyos.directions import (
        build_directions_update_prompt,
        load_directions,
        save_directions,
    )

    current = load_directions(repo_root)
    if not current.strip():
        return 0.0

    system, user = build_directions_update_prompt(
        config, current, proposal_text, iteration, repo_root,
    )

    try:
        result = run_phase_sync(
            Phase.CEO,
            user,
            cwd=repo_root,
            system_prompt=system,
            model=config.get_model(Phase.CEO),
            budget_usd=min(config.budget.per_phase, 1.0),
            allowed_tools=[],
            ui=ui,
            retry_config=config.retry,
            timeout_seconds=config.budget.phase_timeout_seconds,
        )
        cost = result.cost_usd or 0.0
        updated = result.artifacts.get("result", "")
        if result.success and updated.strip() and "# Strategic Directions" in updated:
            save_directions(repo_root, updated)
            _log(f"Directions refreshed (iteration {iteration})")
        else:
            _log("Directions update skipped: agent output didn't match expected format")
        return cost
    except Exception:
        _log(f"Failed to update directions after iteration {iteration}, continuing.")
        return 0.0


_FEATURE_REQUEST_RE = re.compile(
    r"^#{2,3}\s+feature\s+request\s*$", re.IGNORECASE | re.MULTILINE
)
_NEXT_SECTION_RE = re.compile(r"^#{2,3}\s+", re.MULTILINE)
_CODE_FENCE_RE = re.compile(r"^```.*$", re.MULTILINE)


def _extract_feature_prompt(proposal_text: str) -> str:
    """Extract the feature request section from a CEO proposal."""
    match = _FEATURE_REQUEST_RE.search(proposal_text)
    if match:
        body = proposal_text[match.end():].strip()
        next_match = _NEXT_SECTION_RE.search(body)
        if next_match:
            body = body[:next_match.start()].strip()
        body = _CODE_FENCE_RE.sub("", body).strip()
        if body:
            return body

    return proposal_text.strip() or "No proposal generated."


def _build_sweep_prompt(
    config: ColonyConfig,
    *,
    target_path: str | None = None,
    max_tasks: int | None = None,
    scan_context: str = "",
) -> tuple[str, str]:
    """Build the system prompt and user prompt for the sweep analysis phase."""
    sweep_template = _load_instruction("sweep.md")

    effective_max_tasks = max_tasks if max_tasks is not None else config.sweep.max_tasks
    categories_list = config.sweep.default_categories
    categories_block = "\n".join(f"- {cat.replace('_', ' ').title()}" for cat in categories_list)

    if target_path:
        target_scope = f"Analyze only the following path: `{target_path}`"
    else:
        target_scope = "Analyze the **entire codebase**. Start with the most critical modules and work outward."

    if scan_context:
        scan_block = f"The following structural scan results are available as a starting point:\n\n{scan_context}"
    else:
        scan_block = "_No pre-computed scan data available. Perform your own analysis from scratch._"

    system = sweep_template.format(
        categories=categories_block,
        target_scope=target_scope,
        max_tasks=effective_max_tasks,
        max_files_per_task=config.sweep.max_files_per_task,
        scan_context=scan_block,
    )

    user = (
        "Analyze this codebase for code quality issues. "
        "Produce a prioritized task file following the output format in your instructions. "
        f"Limit your output to the top {effective_max_tasks} findings ranked by impact * risk."
    )
    return system, user


def parse_sweep_findings(raw_output: str) -> list[dict]:
    """Parse structured findings from sweep agent markdown output.

    Each finding is extracted from parent task lines matching the pattern:
    - [ ] N.0 [Category] Title — impact:N risk:N

    Returns a sorted list of dicts with keys:
    number, category, title, impact, risk, score, raw_line
    """
    findings: list[dict] = []
    pattern = re.compile(
        r"^- \[ \]\s+(\d+\.\d+)\s+\[([^\]]+)\]\s+(.+?)\s*—\s*impact:(\d+)\s+risk:(\d+)",
        re.MULTILINE,
    )
    for m in pattern.finditer(raw_output):
        impact = int(m.group(4))
        risk = int(m.group(5))
        findings.append({
            "number": m.group(1),
            "category": m.group(2),
            "title": m.group(3).strip(),
            "impact": impact,
            "risk": risk,
            "score": impact * risk,
            "raw_line": m.group(0),
        })
    findings.sort(key=lambda f: f["score"], reverse=True)
    return findings


def run_sweep(
    repo_root: Path,
    config: ColonyConfig,
    *,
    target_path: str | None = None,
    max_tasks: int | None = None,
    execute: bool = False,
    plan_only: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    force: bool = False,
    ui: PhaseUI | NullUI | None = None,
) -> tuple[str, PhaseResult]:
    """Run the sweep analysis phase: analyze codebase for quality issues.

    Returns a tuple of (findings_text, phase_result).
    If execute=True, also delegates to run() with skip_planning=True.
    """
    effective_max_tasks = max_tasks if max_tasks is not None else config.sweep.max_tasks

    # Optionally bootstrap with structural scan context
    scan_context = ""
    try:
        from colonyos.cleanup import scan_directory
        scan_results = scan_directory(
            repo_root,
            config.cleanup.scan_max_lines,
            config.cleanup.scan_max_functions,
        )
        if scan_results:
            scan_context = "\n".join(
                f"- `{r.path}`: {r.line_count} lines, {r.function_count} functions ({r.category.value})"
                for r in scan_results
            )
    except Exception:
        logger.warning("scan_directory() bootstrap failed during sweep; continuing without scan context", exc_info=True)

    system, user_prompt = _build_sweep_prompt(
        config,
        target_path=target_path,
        max_tasks=effective_max_tasks,
        scan_context=scan_context,
    )

    if ui is not None:
        ui.phase_header("Sweep Analysis", config.budget.per_phase, config.get_model(Phase.SWEEP))
    else:
        _log("=== Sweep Analysis Phase ===")

    result = run_phase_sync(
        Phase.SWEEP,
        user_prompt,
        cwd=repo_root,
        system_prompt=system,
        model=config.get_model(Phase.SWEEP),
        budget_usd=config.budget.per_phase,
        allowed_tools=["Read", "Glob", "Grep"],
        ui=ui,
        retry_config=config.retry,
        timeout_seconds=config.budget.phase_timeout_seconds,
    )

    findings_text = result.artifacts.get("result", "")

    if not result.success:
        _log(f"Sweep analysis failed: {result.error}")
        return findings_text, result

    # Write the task file if we have findings
    if findings_text.strip():
        from colonyos.naming import generate_timestamp
        timestamp = generate_timestamp()
        task_filename = f"{timestamp}_tasks_sweep.md"
        tasks_dir = repo_root / config.tasks_dir
        tasks_dir.mkdir(parents=True, exist_ok=True)
        task_path = tasks_dir / task_filename
        task_path.write_text(findings_text, encoding="utf-8")
        _log(f"Sweep task file written to: {task_path}")
        result.artifacts["task_file"] = str(task_path)

    # Dry-run mode: just return findings
    if not execute:
        return findings_text, result

    # Plan-only mode: write task file but don't execute
    if plan_only:
        _log("Plan-only mode: task file written, stopping before implementation.")
        return findings_text, result

    # Execute mode: delegate to the main orchestrator
    scope_desc = target_path or "codebase"
    sweep_prompt = (
        f"Implement the following code quality improvements identified by a sweep analysis "
        f"of {scope_desc}. The task file has already been generated — follow it exactly.\n\n"
        f"{findings_text}"
    )

    _log("Delegating sweep findings to implementation pipeline...")
    exec_result = run(
        sweep_prompt,
        repo_root=repo_root,
        config=config,
        skip_planning=True,
        verbose=verbose,
        quiet=quiet,
        force=force,
    )

    # If execution failed, propagate the failure so callers know
    if exec_result is not None and exec_result.status == RunStatus.FAILED:
        result.success = False
        result.error = "Sweep execution failed during implementation"

    return findings_text, result


def _parse_parent_tasks(task_content: str) -> list[str]:
    """Extract parent task lines from a task file.

    Parent tasks match the pattern: `- [ ] N.0 Title` or `- [x] N.0 Title`.
    Returns the full task line text for each parent task.
    """
    pattern = re.compile(r"^- \[[ x]\] \d+\.0 .+", re.MULTILINE)
    return pattern.findall(task_content)


def _save_review_artifact(
    repo_root: Path,
    reviews_dir: str,
    filename: str,
    content: str,
    *,
    subdirectory: str | None = None,
) -> Path:
    """Save a review markdown file to the reviews directory.

    When *subdirectory* is provided, the file is written to
    ``repo_root / reviews_dir / subdirectory / filename``.  The resolved
    path is validated to stay within ``repo_root / reviews_dir``.
    """
    reviews_root = repo_root / reviews_dir
    if subdirectory:
        target_dir = reviews_root / subdirectory
    else:
        target_dir = reviews_root
    # Path-traversal guard
    if not target_dir.resolve().is_relative_to(reviews_root.resolve()):
        raise ValueError(
            f"Subdirectory {subdirectory!r} escapes the reviews directory"
        )
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename
    # Defense-in-depth: validate the final path (including filename) stays
    # within the reviews root to guard against malicious filenames.
    if not path.resolve().is_relative_to(reviews_root.resolve()):
        raise ValueError(
            f"Filename {filename!r} escapes the reviews directory"
        )
    path.write_text(content, encoding="utf-8")
    return path


def _save_run_log(repo_root: Path, log: RunLog, *, resumed: bool = False) -> Path:
    # Update head_sha to current HEAD so resume checks against post-phase state
    if log.preflight is not None:
        current_sha = _get_head_sha(repo_root)
        if current_sha:
            log.preflight.head_sha = current_sha

    runs = runs_dir_path(repo_root)
    runs.mkdir(parents=True, exist_ok=True)
    log_path = runs / f"{log.run_id}.json"
    # Derive last_successful_phase from the log's phases list
    last_successful_phase: str | None = None
    for p in log.phases:
        if p.success:
            last_successful_phase = p.phase.value

    # Load existing resume_events if re-saving the same file
    resume_events: list[str] = []
    if log_path.exists():
        try:
            existing_data = json.loads(log_path.read_text(encoding="utf-8"))
            resume_events = existing_data.get("resume_events", [])
        except (json.JSONDecodeError, KeyError):
            pass

    if resumed:
        from datetime import datetime, timezone
        resume_events.append(datetime.now(timezone.utc).isoformat())

    log_path.write_text(
        json.dumps(
            {
                "run_id": log.run_id,
                "prompt": log.prompt,
                "status": log.status.value,
                "total_cost_usd": log.total_cost_usd,
                "started_at": log.started_at,
                "finished_at": log.finished_at,
                "branch_name": log.branch_name,
                "prd_rel": log.prd_rel,
                "task_rel": log.task_rel,
                "source_issue": log.source_issue,
                "source_issue_url": log.source_issue_url,
                "source_type": log.source_type,
                "review_comment_id": log.review_comment_id,
                "pr_url": log.pr_url,
                "post_fix_head_sha": log.post_fix_head_sha,
                "parallel_tasks": log.parallel_tasks,
                "wall_time_ms": log.wall_time_ms,
                "agent_time_ms": log.agent_time_ms,
                "preflight": log.preflight.to_dict() if log.preflight else None,
                "last_successful_phase": last_successful_phase,
                "resume_events": resume_events,
                "recovery_events": list(log.recovery_events),
                "phases": [
                    {
                        "phase": p.phase.value,
                        "success": p.success,
                        "cost_usd": p.cost_usd,
                        "duration_ms": p.duration_ms,
                        "session_id": p.session_id,
                        "model": p.model,
                        "error": p.error,
                        "artifacts": p.artifacts,  # FR-10: Include artifacts for task_id tracking
                        "retry_info": {  # FR-9: Retry metadata
                            "attempts": p.retry_info.attempts,
                            "transient_errors": p.retry_info.transient_errors,
                            "fallback_model_used": p.retry_info.fallback_model_used,
                            "total_retry_delay_seconds": p.retry_info.total_retry_delay_seconds,
                        } if p.retry_info is not None else None,
                    }
                    for p in log.phases
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return log_path


def _fail_run_log(
    repo_root: Path,
    log: RunLog,
    reason: str,
) -> RunLog:
    """Mark a RunLog as FAILED, persist it, and return it.

    Extracts the 3-line boilerplate that was previously duplicated ~14 times
    across ``run_thread_fix()`` and ``run()``.
    """
    _log(reason)
    log.status = RunStatus.FAILED
    log.mark_finished()
    _save_run_log(repo_root, log)
    return log


def _record_recovery_event(log: RunLog, *, kind: str, details: dict[str, object]) -> None:
    """Append a recovery event to the run log metadata."""
    log.recovery_events.append({
        "kind": kind,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **details,
    })


def _validate_run_id(run_id: str) -> None:
    """Validate that run_id contains no path traversal characters."""
    if not run_id:
        raise click.ClickException("Run ID must not be empty.")
    if "/" in run_id or "\\" in run_id or ".." in run_id:
        raise click.ClickException(
            f"Invalid run ID: {run_id!r}. "
            "Run IDs must not contain path separators or '..' sequences."
        )


def _validate_rel_path(repo_root: Path, rel_path: str, label: str) -> None:
    """Validate that a relative path does not escape the repo root."""
    resolved = (repo_root / rel_path).resolve()
    repo_resolved = repo_root.resolve()
    if not str(resolved).startswith(str(repo_resolved) + "/") and resolved != repo_resolved:
        raise click.ClickException(
            f"{label} path escapes repository root: {rel_path!r}"
        )


def _load_run_log(repo_root: Path, run_id: str) -> RunLog:
    """Load a RunLog from its JSON file in .colonyos/runs/."""
    _validate_run_id(run_id)
    log_path = runs_dir_path(repo_root) / f"{run_id}.json"
    # Verify resolved path is under the runs directory
    runs_dir = runs_dir_path(repo_root).resolve()
    if not str(log_path.resolve()).startswith(str(runs_dir) + "/"):
        raise click.ClickException(f"Invalid run ID: {run_id!r}")
    if not log_path.exists():
        raise click.ClickException(f"Run log not found: {log_path}")
    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Corrupted run log: {log_path}: {exc}")

    try:
        phases = []
        for p in data.get("phases", []):
            phases.append(PhaseResult(
                phase=Phase(p["phase"]),
                success=p["success"],
                cost_usd=p.get("cost_usd"),
                duration_ms=p.get("duration_ms", 0),
                session_id=p.get("session_id", ""),
                model=p.get("model"),
                error=p.get("error"),
                artifacts=p.get("artifacts", {}),  # FR-10: Include artifacts for task_id tracking
                retry_info=RetryInfo(  # FR-9: Retry metadata — explicit field extraction for resilience
                    attempts=p["retry_info"].get("attempts", 1),
                    transient_errors=p["retry_info"].get("transient_errors", 0),
                    fallback_model_used=p["retry_info"].get("fallback_model_used"),
                    total_retry_delay_seconds=p["retry_info"].get("total_retry_delay_seconds", 0.0),
                ) if p.get("retry_info") else None,
            ))

        log = RunLog(
            run_id=data["run_id"],
            prompt=data["prompt"],
            status=RunStatus(data["status"]),
            phases=phases,
            total_cost_usd=data.get("total_cost_usd", 0.0),
            started_at=data.get("started_at", ""),
            finished_at=data.get("finished_at"),
            branch_name=data.get("branch_name"),
            prd_rel=data.get("prd_rel"),
            task_rel=data.get("task_rel"),
            source_issue=data.get("source_issue"),
            source_issue_url=data.get("source_issue_url"),
            preflight=PreflightResult.from_dict(data["preflight"]) if data.get("preflight") else None,
            source_type=data.get("source_type"),
            review_comment_id=data.get("review_comment_id"),
            pr_url=data.get("pr_url"),
            post_fix_head_sha=data.get("post_fix_head_sha"),
            parallel_tasks=data.get("parallel_tasks"),
            wall_time_ms=data.get("wall_time_ms"),
            agent_time_ms=data.get("agent_time_ms"),
            recovery_events=list(data.get("recovery_events", [])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise click.ClickException(
            f"Invalid run log schema in {log_path}: {exc}"
        )

    # Validate relative paths don't escape repo root
    if log.prd_rel:
        _validate_rel_path(repo_root, log.prd_rel, "prd_rel")
    if log.task_rel:
        _validate_rel_path(repo_root, log.task_rel, "task_rel")

    return log


def _validate_resume_preconditions(repo_root: Path, log: RunLog) -> None:
    """Validate that a run log is eligible for resumption."""
    if log.status != RunStatus.FAILED:
        raise click.ClickException(
            f"Cannot resume run with status '{log.status.value}'. "
            f"Only failed runs can be resumed."
        )

    if not log.branch_name:
        raise click.ClickException(
            "Run log missing branch_name. This run is not resumable."
        )

    # Check branch exists locally (-- terminates option parsing for safety)
    result = subprocess.run(
        ["git", "branch", "--list", "--", log.branch_name],
        capture_output=True, text=True, cwd=repo_root,
    )
    if not result.stdout.strip():
        raise click.ClickException(
            f"Branch '{log.branch_name}' not found locally. "
            f"Cannot resume without the branch."
        )

    if not log.prd_rel:
        raise click.ClickException(
            "Run log missing prd_rel. This run is not resumable."
        )
    if not (repo_root / log.prd_rel).exists():
        raise click.ClickException(
            f"PRD file not found: {log.prd_rel}"
        )

    if not log.task_rel:
        raise click.ClickException(
            "Run log missing task_rel. This run is not resumable."
        )
    if not (repo_root / log.task_rel).exists():
        raise click.ClickException(
            f"Task file not found: {log.task_rel}"
        )


def _compute_next_phase(last_successful_phase: str | None) -> str | None:
    """Map last_successful_phase to the next phase to resume from.

    Returns the next phase name, or None if nothing to resume.
    """
    if last_successful_phase is None:
        return None

    mapping = {
        "plan": "implement",
        "implement": "review",
        "review": "review",
        "fix": "review",
        "decision": "deliver",
    }
    return mapping.get(last_successful_phase)


# Phases that should be skipped based on last_successful_phase
_SKIP_MAP: dict[str, set[str]] = {
    "plan": {"plan"},
    "implement": {"plan", "implement"},
    "review": {"plan", "implement"},
    "fix": {"plan", "implement"},
    "decision": {"plan", "implement", "review"},
}


def prepare_resume(repo_root: Path, run_id: str) -> ResumeState:
    """Load and validate a failed run for resumption.

    This is the public API for resume preparation, used by the CLI.
    Returns a ResumeState with all data needed to resume the run.

    For parallel implement runs (FR-8), this also identifies:
    - completed_task_ids: Tasks that succeeded (don't re-run)
    - failed_task_ids: Tasks that failed (need retry)
    - blocked_task_ids: Tasks blocked by failed dependencies (need retry after deps)
    """
    log = _load_run_log(repo_root, run_id)
    _validate_resume_preconditions(repo_root, log)

    last_successful_phase = None
    for p in log.phases:
        if p.success:
            last_successful_phase = p.phase.value

    if last_successful_phase is None:
        raise click.ClickException(
            "No successful phases found in run log. Nothing to resume from."
        )

    # Extract parallel task status from phase artifacts (FR-8)
    completed_task_ids: list[str] = []
    failed_task_ids: list[str] = []
    blocked_task_ids: list[str] = []

    for p in log.phases:
        if p.phase == Phase.IMPLEMENT and "task_id" in p.artifacts:
            task_id = p.artifacts["task_id"]
            if p.success:
                completed_task_ids.append(task_id)
            else:
                # Check if blocked (error message indicates this)
                error = p.error or ""
                if "Blocked" in error or "blocked" in error.lower():
                    blocked_task_ids.append(task_id)
                else:
                    failed_task_ids.append(task_id)

    return ResumeState(
        log=log,
        branch_name=log.branch_name,  # type: ignore[arg-type]
        prd_rel=log.prd_rel,  # type: ignore[arg-type]
        task_rel=log.task_rel,  # type: ignore[arg-type]
        last_successful_phase=last_successful_phase,
        completed_task_ids=completed_task_ids,
        failed_task_ids=failed_task_ids,
        blocked_task_ids=blocked_task_ids,
    )


# ---------------------------------------------------------------------------
# Standalone review utilities
# ---------------------------------------------------------------------------


def validate_branch_exists(branch: str, repo_root: Path) -> tuple[bool, str]:
    """Verify a branch exists locally.

    Returns (True, "") if found, or (False, error_message) if not.
    Rejects remote-style refs like ``origin/foo``.
    """
    if "/" in branch and branch.split("/", 1)[0] in (
        "origin", "upstream", "remote", "remotes",
    ):
        return (
            False,
            f"Remote-style ref '{branch}' is not supported. "
            f"Check out the branch first: git checkout {branch.split('/', 1)[1]}",
        )

    result = subprocess.run(
        ["git", "branch", "--list", "--", branch],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.stdout.strip():
        return True, ""
    return (
        False,
        f"Branch '{branch}' not found locally. "
        f"Try: git fetch && git checkout {branch}",
    )


def _get_branch_diff(
    base: str,
    branch: str,
    repo_root: Path,
    *,
    max_chars: int = 10_000,
) -> str:
    """Extract ``git diff base...branch`` output, truncating if needed."""
    try:
        result = subprocess.run(
            ["git", "diff", f"{base}...{branch}"],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        diff = result.stdout or ""
    except OSError as exc:
        _log(f"Warning: failed to extract diff: {exc}")
        return ""

    if not diff:
        return ""

    if len(diff) > max_chars:
        diff = diff[:max_chars] + f"\n\n... [diff truncated — {len(diff)} total characters]"

    return diff


def _build_standalone_review_prompt(
    persona: Persona,
    config: ColonyConfig,
    branch_name: str,
    base_branch: str,
    diff_summary: str,
) -> tuple[str, str]:
    """Build a review prompt for a single persona in standalone mode (no PRD)."""
    review_template = _load_instruction("review_standalone.md")

    system = _format_base(config) + "\n\n" + review_template.format(
        reviewer_role=persona.role,
        reviewer_expertise=persona.expertise,
        reviewer_perspective=persona.perspective,
        branch_name=branch_name,
        base_branch=base_branch,
        diff_summary=diff_summary or "(empty diff)",
    )

    user = (
        f"Review the changes on branch `{branch_name}` compared to `{base_branch}`. "
        f"Assess the implementation holistically from your perspective as {persona.role}."
    )
    return system, user


def _build_standalone_fix_prompt(
    config: ColonyConfig,
    branch_name: str,
    findings_text: str,
    fix_iteration: int,
) -> tuple[str, str]:
    """Build the fix prompt for standalone mode (no PRD/task file)."""
    fix_template = _load_instruction("fix_standalone.md")

    system = _format_base(config) + "\n\n" + fix_template.format(
        branch_name=branch_name,
        reviews_dir=config.reviews_dir,
        findings_text=findings_text,
        fix_iteration=fix_iteration,
        max_fix_iterations=config.max_fix_iterations,
    )

    user = (
        f"Fix the issues identified by reviewers for branch `{branch_name}`. "
        f"This is fix iteration {fix_iteration} of {config.max_fix_iterations}."
    )
    return system, user


def _build_standalone_decision_prompt(
    config: ColonyConfig,
    branch_name: str,
    base_branch: str,
) -> tuple[str, str]:
    """Build the decision prompt for standalone mode (no PRD)."""
    decision_template = _load_instruction("decision_standalone.md")

    system = _format_base(config) + "\n\n" + decision_template.format(
        branch_name=branch_name,
        base_branch=base_branch,
        reviews_dir=config.reviews_dir,
    )

    user = (
        f"Review all artifacts for the implementation on branch `{branch_name}` "
        f"and make a GO / NO-GO decision. "
        f"Review artifacts are in `{config.reviews_dir}/`."
    )
    return system, user


def _branch_slug(branch: str) -> str:
    """Convert a branch name to a filename-safe slug."""
    return slugify(branch)


def run_standalone_review(
    branch: str,
    base: str,
    repo_root: Path,
    config: ColonyConfig,
    *,
    verbose: bool = False,
    quiet: bool = False,
    no_fix: bool = False,
    decide: bool = False,
) -> tuple[bool, list[PhaseResult], float, str | None]:
    """Run standalone multi-persona review on an arbitrary branch.

    Returns (all_approved, phase_results, total_cost_usd, decision_verdict).
    The decision_verdict is None when ``--decide`` is not used.
    """

    def _make_ui(
        prefix: str = "",
        *,
        task_id: str | None = None,
        badge: StreamBadge | None = None,
    ) -> PhaseUI | NullUI | None:
        if quiet:
            return None
        return PhaseUI(verbose=verbose, prefix=prefix, task_id=task_id, badge=badge)

    reviewers = reviewer_personas(config)
    if not reviewers:
        _log("No reviewer personas configured.")
        return True, [], 0.0, None

    diff_text = _get_branch_diff(base, branch, repo_root)
    branch_s = _branch_slug(branch)
    review_tools = ["Read", "Glob", "Grep", "Bash"]
    phase_results: list[PhaseResult] = []
    total_cost = 0.0
    all_approved = False
    last_findings: list[tuple[str, str]] = []

    for iteration in range(config.max_fix_iterations + 1):
        # Budget guard
        remaining = config.budget.per_run - total_cost
        if remaining < config.budget.per_phase:
            _log(
                f"Standalone review: budget exhausted "
                f"({remaining:.2f} remaining). Stopping."
            )
            break

        round_num = iteration + 1
        _log(f"  Review round {round_num}/{config.max_fix_iterations + 1}")
        if not quiet:
            print_reviewer_legend([(i, p.role) for i, p in enumerate(reviewers)])

        # Build parallel review calls
        review_calls = []
        for i, persona in enumerate(reviewers):
            sys_prompt, usr_prompt = _build_standalone_review_prompt(
                persona, config, branch, base, diff_text,
            )
            persona_ui = _make_ui(badge=make_reviewer_badge(i))
            review_calls.append(dict(
                phase=Phase.REVIEW,
                prompt=usr_prompt,
                cwd=repo_root,
                system_prompt=sys_prompt,
                model=config.get_model(Phase.REVIEW),
                budget_usd=config.budget.per_phase,
                allowed_tools=review_tools,
                ui=persona_ui,
                retry_config=config.retry,
            ))

        # Create progress tracker for real-time status updates
        progress_tracker: ParallelProgressLine | None = None
        if not quiet:
            is_tty = sys.stderr.isatty()
            reviewer_list = [(i, p.role) for i, p in enumerate(reviewers)]
            progress_tracker = ParallelProgressLine(reviewer_list, is_tty=is_tty)

        results = run_phases_parallel_sync(
            review_calls,
            on_complete=progress_tracker.on_reviewer_complete if progress_tracker else None,
        )

        # Print summary after all reviewers complete
        if progress_tracker is not None:
            progress_tracker.print_summary(round_num=round_num)

        # Save each persona's review artifact
        for persona, result in zip(reviewers, results):
            p_slug = _persona_slug(persona.role)
            text = result.artifacts.get("result", "")
            artifact = persona_review_artifact_path(
                branch_s, p_slug, round_num,
            )
            _save_review_artifact(
                repo_root,
                config.reviews_dir,
                artifact.filename,
                f"# Review by {persona.role} (Round {round_num})\n\n{text}",
                subdirectory=artifact.subdirectory,
            )
            phase_results.append(result)
            total_cost += result.cost_usd or 0

        last_findings = _collect_review_findings(results, reviewers)

        if not last_findings:
            _log("  All reviewers approve")
            all_approved = True
            break

        _log(
            f"  {len(last_findings)} reviewer(s) requested changes: "
            + ", ".join(role for role, _ in last_findings)
        )

        if no_fix:
            break

        if iteration < config.max_fix_iterations:
            # Budget guard before fix
            remaining = config.budget.per_run - total_cost
            if remaining < config.budget.per_phase:
                _log("  Budget exhausted before fix. Stopping.")
                break

            findings_text = "\n\n---\n\n".join(
                f"### {role}\n\n{text}" for role, text in last_findings
            )
            fix_system, fix_user = _build_standalone_fix_prompt(
                config, branch, findings_text, iteration + 1,
            )
            fix_ui = _make_ui()
            if fix_ui is not None:
                fix_ui.phase_header(
                    f"Fix (iteration {iteration + 1})",
                    config.budget.per_phase,
                    config.get_model(Phase.FIX),
                )
            else:
                _log(f"  Running fix agent (iteration {iteration + 1})...")

            fix_result = run_phase_sync(
                Phase.FIX,
                fix_user,
                cwd=repo_root,
                system_prompt=fix_system,
                model=config.get_model(Phase.FIX),
                budget_usd=config.budget.per_phase,
                ui=fix_ui,
                retry_config=config.retry,
                timeout_seconds=config.budget.phase_timeout_seconds,
            )
            phase_results.append(fix_result)
            total_cost += fix_result.cost_usd or 0

            if not fix_result.success:
                _log(f"  Fix phase failed: {fix_result.error}")
                break

            # Re-fetch diff after fix
            diff_text = _get_branch_diff(base, branch, repo_root)

    # --- Optional decision gate ---
    decision_verdict = None
    if decide:
        remaining = config.budget.per_run - total_cost
        if remaining >= config.budget.per_phase:
            decision_ui = _make_ui()
            if decision_ui is not None:
                decision_ui.phase_header(
                    "Decision Gate", config.budget.per_phase, config.get_model(Phase.DECISION),
                )
            else:
                _log("=== Decision Gate ===")

            d_system, d_user = _build_standalone_decision_prompt(
                config, branch, base,
            )
            decision_result = run_phase_sync(
                Phase.DECISION,
                d_user,
                cwd=repo_root,
                system_prompt=d_system,
                model=config.get_model(Phase.DECISION),
                budget_usd=config.budget.per_phase,
                allowed_tools=["Read", "Glob", "Grep", "Bash"],
                ui=decision_ui,
                retry_config=config.retry,
                timeout_seconds=config.budget.phase_timeout_seconds,
            )
            phase_results.append(decision_result)
            total_cost += decision_result.cost_usd or 0

            verdict_text = decision_result.artifacts.get("result", "")
            decision_verdict = _extract_verdict(verdict_text)
            _log(f"  Decision: {decision_verdict}")

            decision_art = standalone_decision_artifact_path(branch_s)
            _save_review_artifact(
                repo_root,
                config.reviews_dir,
                decision_art.filename,
                f"# Decision Gate\n\nVerdict: **{decision_verdict}**\n\n{verdict_text}",
                subdirectory=decision_art.subdirectory,
            )

            if decision_verdict == "GO":
                all_approved = True
            elif decision_verdict == "NO-GO":
                all_approved = False

    # --- Save summary artifact ---
    summary_lines = [f"# Standalone Review Summary: `{branch}` vs `{base}`\n"]
    review_results = [r for r in phase_results if r.phase == Phase.REVIEW]
    num_reviewers = len(reviewers)
    for idx, result in enumerate(review_results):
        persona = reviewers[idx % num_reviewers]
        text = result.artifacts.get("result", "")
        verdict = extract_review_verdict(text)
        summary_lines.append(f"- **{persona.role}**: {verdict}")
    summary_lines.append(f"\n**Total cost**: ${total_cost:.4f}")
    if decision_verdict:
        summary_lines.append(f"\n**Decision**: {decision_verdict}")

    summary_art = summary_artifact_path(branch_s)
    _save_review_artifact(
        repo_root,
        config.reviews_dir,
        summary_art.filename,
        "\n".join(summary_lines),
        subdirectory=summary_art.subdirectory,
    )

    return all_approved, phase_results, total_cost, decision_verdict


def _run_learn_phase(
    config: ColonyConfig,
    repo_root: Path,
    log: RunLog,
    prompt: str,
    _make_ui,
    memory_store: MemoryStore | None = None,
) -> None:
    """Execute the learn phase: extract patterns from reviews into the ledger.

    Also writes extracted learnings to the memory store (FR-2) so that
    future runs benefit from past observations.

    This is advisory and must never block the pipeline. All exceptions are
    caught and logged as warnings.
    """
    if not config.learnings.enabled:
        return

    try:
        learn_ui = _make_ui()
        if learn_ui is not None:
            learn_budget = min(0.50, config.budget.per_phase / 2)
            learn_ui.phase_header("Learn", learn_budget, config.get_model(Phase.LEARN))
        else:
            _log("=== Learn Phase ===")

        system, user = _build_learn_prompt(config, repo_root)
        learn_budget = min(0.50, config.budget.per_phase / 2)
        learn_result = run_phase_sync(
            Phase.LEARN,
            user,
            cwd=repo_root,
            system_prompt=system,
            model=config.get_model(Phase.LEARN),
            budget_usd=learn_budget,
            allowed_tools=["Read", "Glob", "Grep"],
            ui=learn_ui,
            retry_config=config.retry,
            timeout_seconds=config.budget.phase_timeout_seconds,
        )
        log.phases.append(learn_result)
        _save_run_log(repo_root, log)

        if learn_result.success:
            result_text = learn_result.artifacts.get("result", "")
            entries = _parse_learn_output(result_text)
            if entries:
                from datetime import date as date_cls

                feature_summary = slugify(prompt)[:60]
                append_learnings(
                    repo_root,
                    log.run_id,
                    date_cls.today().isoformat(),
                    feature_summary,
                    entries,
                    max_entries=config.learnings.max_entries,
                )
                _log(f"  Extracted {len(entries)} learnings")

                # FR-2: Write learnings to memory store alongside the ledger
                if memory_store is not None:
                    for entry in entries:
                        try:
                            memory_store.add_memory(
                                category=MemoryCategory.REVIEW_PATTERN,
                                phase="learn",
                                run_id=log.run_id,
                                text=f"[{entry.category}] {entry.text}",
                                tags=["learn", entry.category],
                            )
                        except Exception:
                            _log("Warning: failed to capture learn-phase memory")
                    _log(f"  Captured {len(entries)} learn-phase memories")
            else:
                _log("  No new learnings extracted")
        else:
            _log(f"  Learn phase did not succeed: {learn_result.error}")

    except Exception as exc:
        _log(f"  Learn phase failed (non-blocking): {exc}")
        log.phases.append(
            PhaseResult(
                phase=Phase.LEARN,
                success=False,
                error=str(exc),
            )
        )
        _save_run_log(repo_root, log)


def _extract_pr_number_from_log(log: RunLog) -> int | None:
    """Extract PR number from the deliver phase artifacts in a run log."""
    for phase in log.phases:
        if phase.phase == Phase.DELIVER:
            pr_url = phase.artifacts.get("pr_url", "")
            if pr_url:
                match = re.search(r"/pull/(\d+)", pr_url)
                if match:
                    return int(match.group(1))
    return None


def _register_pr_outcome(
    repo_root: Path,
    run_id: str,
    pr_url: str,
    branch_name: str,
) -> None:
    """Register a newly created PR for outcome tracking.

    Wraps :meth:`OutcomeStore.track_pr` in a try/except so tracking failures
    never block the main pipeline.  Silently returns when *pr_url* is empty
    or the PR number cannot be extracted from the URL.
    """
    if not pr_url:
        return

    match = re.search(r"/pull/(\d+)", pr_url)
    if not match:
        return

    pr_number = int(match.group(1))

    try:
        with OutcomeStore(repo_root) as store:
            store.track_pr(run_id, pr_number, pr_url, branch_name)
        logger.info("Registered PR #%d for outcome tracking", pr_number)
    except Exception:
        logger.warning(
            "Failed to register PR #%d for outcome tracking",
            pr_number,
            exc_info=True,
        )


def _run_ci_fix_loop(
    config: ColonyConfig,
    repo_root: Path,
    log: RunLog,
    branch_name: str,
) -> None:
    """Post-deliver CI fix loop: wait for CI, fix failures, retry.

    Gated by ``config.ci_fix.enabled``.  Runs up to ``config.ci_fix.max_retries``
    fix-push-wait cycles.  Each CI fix attempt is recorded as a
    ``PhaseResult`` with ``Phase.CI_FIX``.

    Respects ``config.budget.per_run`` — refuses to start a new fix attempt
    if the cumulative run cost leaves insufficient budget for a phase.
    """
    from colonyos.ci import (
        all_checks_pass,
        collect_ci_failure_context,
        format_ci_failures_as_prompt,
        poll_pr_checks,
    )

    pr_number = _extract_pr_number_from_log(log)
    if pr_number is None:
        _log("CI fix: could not determine PR number from deliver phase, skipping.")
        return

    _log(f"CI fix: waiting for initial CI checks on PR #{pr_number}...")
    try:
        checks = poll_pr_checks(
            pr_number, repo_root,
            timeout=config.ci_fix.wait_timeout,
        )
    except Exception as exc:
        _log(f"CI fix: failed to poll checks: {exc}")
        return

    if all_checks_pass(checks):
        _log("CI fix: all checks pass, no fix needed.")
        return

    for attempt in range(1, config.ci_fix.max_retries + 1):
        _log(f"CI fix: attempt {attempt}/{config.ci_fix.max_retries}")

        # Budget guard: check cumulative run cost before each attempt
        cost_so_far = sum(p.cost_usd for p in log.phases if p.cost_usd is not None)
        remaining = config.budget.per_run - cost_so_far
        if remaining < config.budget.per_phase:
            _log(
                f"CI fix: budget exhausted "
                f"(${cost_so_far:.4f} spent of ${config.budget.per_run:.2f} per-run). "
                "Stopping CI fix loop."
            )
            break

        # Collect logs from failed checks (shared helper)
        failures_for_prompt = collect_ci_failure_context(
            checks, repo_root, config.ci_fix.log_char_cap,
        )
        ci_failure_context = format_ci_failures_as_prompt(failures_for_prompt)
        system, user = _build_ci_fix_prompt(
            config, branch_name, ci_failure_context,
            attempt, config.ci_fix.max_retries,
        )

        phase_result = run_phase_sync(
            Phase.CI_FIX,
            user,
            cwd=repo_root,
            system_prompt=system,
            model=config.get_model(Phase.CI_FIX),
            budget_usd=min(config.budget.per_phase, remaining),
            ui=None,
            retry_config=config.retry,
            timeout_seconds=config.budget.phase_timeout_seconds,
        )
        log.phases.append(phase_result)

        if not phase_result.success:
            _log(f"CI fix agent failed: {phase_result.error}")
            continue

        # Push the fix — abort loop on failure to avoid wasting retries
        push_result = subprocess.run(
            ["git", "push"],
            capture_output=True, text=True, timeout=60, cwd=repo_root,
        )
        if push_result.returncode != 0:
            _log(f"CI fix: git push failed: {push_result.stderr.strip()}")
            break

        # Wait for CI
        try:
            checks = poll_pr_checks(
                pr_number, repo_root,
                timeout=config.ci_fix.wait_timeout,
            )
        except Exception as exc:
            _log(f"CI fix: failed to poll checks after fix: {exc}")
            break

        if all_checks_pass(checks):
            _log("CI fix: all checks now pass!")
            return

        _log("CI fix: checks still failing after fix attempt.")

    _log("CI fix: retries exhausted, CI still failing.")


def _build_thread_fix_prompt(
    config: ColonyConfig,
    branch_name: str,
    prd_rel: str,
    task_rel: str,
    fix_request: str,
    original_prompt: str,
    repo_root: Path | None = None,
    pr_review_context: dict[str, str | int] | None = None,
) -> tuple[str, str]:
    """Build the system/user prompts for a thread-fix pipeline run.

    Defense-in-depth: both ``fix_request`` and ``original_prompt`` are
    sanitized here at point of use, regardless of whether callers have
    already sanitized them.  This prevents injection if a future caller
    passes unsanitized content.

    When ``pr_review_context`` is provided, uses the PR-review-specific
    instruction template (thread_fix_pr_review.md) with rich context about
    the reviewer, file, and line number.
    """
    # Sanitize untrusted content at point of use (defense-in-depth).
    safe_fix_request = sanitize_untrusted_content(fix_request)
    safe_original_prompt = sanitize_untrusted_content(original_prompt)

    if pr_review_context is not None:
        # Use PR review specific template with rich context
        template = _load_instruction("thread_fix_pr_review.md")
        # Sanitize all PR review context values
        safe_context = {
            k: sanitize_untrusted_content(str(v)) if isinstance(v, str) else v
            for k, v in pr_review_context.items()
        }
        system = _format_base(config) + "\n\n" + template.format(
            branch_name=branch_name,
            prd_path=prd_rel,
            task_path=task_rel,
            file_path=safe_context.get("file_path", ""),
            line_number=safe_context.get("line_number", 0),
            reviewer_username=safe_context.get("reviewer_username", "unknown"),
            comment_url=safe_context.get("comment_url", ""),
            review_comment=safe_context.get("review_comment", safe_fix_request),
            original_prompt=safe_original_prompt,
        )
        user = (
            f"Address the PR review comment from @{safe_context.get('reviewer_username', 'reviewer')} "
            f"on file `{safe_context.get('file_path', '')}` line {safe_context.get('line_number', 0)}. "
            f"The review feedback is: {safe_fix_request}"
        )
    else:
        # Use generic Slack thread-fix template
        template = _load_instruction("thread_fix.md")
        system = _format_base(config) + "\n\n" + template.format(
            branch_name=branch_name,
            prd_path=prd_rel,
            task_path=task_rel,
            fix_request=safe_fix_request,
            original_prompt=safe_original_prompt,
        )
        user = (
            f"Apply the requested fix on branch `{branch_name}`. "
            f"The fix request is: {safe_fix_request}"
        )

    if repo_root is not None:
        learnings = load_learnings_for_injection(repo_root)
        if learnings:
            system += f"\n\n## Learnings from Past Runs\n\n{learnings}"

    return system, user


def run_thread_fix(
    fix_prompt: str,
    *,
    branch_name: str,
    pr_url: str | None,
    original_prompt: str,
    prd_rel: str,
    task_rel: str,
    repo_root: Path,
    config: ColonyConfig,
    verbose: bool = False,
    quiet: bool = False,
    ui_factory: UIFactory | Callable[..., object] | None = None,
    expected_head_sha: str | None = None,
    source_type: str | None = None,
    review_comment_id: str | None = None,
    pr_review_context: dict[str, str | int] | None = None,
) -> RunLog:
    """Execute a lightweight fix pipeline for a Slack thread-fix or PR review fix.

    Skips Plan and triage phases. Runs:
    1. Validate branch name, branch exists, and PR is open
    2. Clean working tree check (stash if needed)
    3. Checkout existing branch and verify HEAD SHA (force-push defense)
    4. Implement phase with fix instructions
    5. Verify phase (test suite)
    6. Deliver phase (push to existing branch, skip PR creation)

    When ``pr_review_context`` is provided (for PR review fixes), uses a
    specialized instruction template with file/line context and reviewer info.

    Returns a RunLog with phase results and cost.

    .. warning:: Concurrency

       This function modifies the git working tree (checkout, commit, push).
       Callers **must** serialize access — e.g., via the ``pipeline_semaphore``
       in ``QueueExecutor``. Concurrent invocations will cause working tree
       corruption.
    """

    def _make_ui(
        prefix: str = "",
        *,
        task_id: str | None = None,
        badge: StreamBadge | None = None,
    ) -> PhaseUI | NullUI | None:
        if ui_factory is not None:
            return _invoke_ui_factory(
                ui_factory,
                prefix=prefix,
                task_id=task_id,
                badge=badge,
            )  # type: ignore[return-value]
        if quiet:
            return None
        return PhaseUI(verbose=verbose, prefix=prefix, task_id=task_id, badge=badge)

    run_id = _build_run_id(f"fix-{fix_prompt}")
    log = RunLog(
        run_id=run_id,
        prompt=fix_prompt,
        status=RunStatus.RUNNING,
        branch_name=branch_name,
        prd_rel=prd_rel,
        task_rel=task_rel,
        pr_url=pr_url,
        source_type=source_type,
        review_comment_id=review_comment_id,
    )

    # FR-3.2: Register the PR for outcome tracking.  Uses INSERT OR IGNORE
    # so duplicate registrations (e.g. from the main run() path) are safe.
    if pr_url:
        _register_pr_outcome(repo_root, run_id, pr_url, branch_name)

    # --- Defense-in-depth: validate branch name at point of use ---
    if not is_valid_git_ref(branch_name):
        return _fail_run_log(
            repo_root, log,
            f"Thread fix: invalid branch name: {branch_name[:100]}",
        )

    # --- Validate branch exists ---
    branch_ok, branch_err = validate_branch_exists(branch_name, repo_root)
    if not branch_ok:
        return _fail_run_log(
            repo_root, log,
            f"Thread fix: branch validation failed: {branch_err}",
        )

    # --- Validate PR is still open ---
    # NOTE: TOCTOU race — the PR could be merged/closed between this check
    # and the push in the Deliver phase. The window is small and the worst
    # case is a push to a branch whose PR is already closed, which is benign.
    if pr_url:
        pr_number, _ = check_open_pr(branch_name, repo_root)
        if pr_number is None:
            return _fail_run_log(
                repo_root, log,
                f"Thread fix: no open PR found for branch {branch_name}",
            )

    # --- Ensure working tree is clean before checkout ---
    tree_clean, dirty_output = _check_working_tree_clean(repo_root)
    if not tree_clean:
        _log(
            f"Thread fix: working tree not clean, stashing changes: "
            f"{dirty_output[:200]}"
        )
        try:
            # Only stash tracked files to avoid capturing sensitive
            # untracked files (.env.local, credential files).
            subprocess.run(
                ["git", "stash", "push", "-m",
                 f"colonyos-thread-fix-{branch_name}"],
                capture_output=True, text=True, cwd=repo_root, timeout=30,
            )
        except Exception as exc:
            return _fail_run_log(
                repo_root, log,
                f"Thread fix: stash failed: {exc}",
            )

    # --- Checkout branch ---
    original_branch = _get_current_branch(repo_root)
    try:
        checkout_result = subprocess.run(
            ["git", "checkout", branch_name],
            capture_output=True, text=True, cwd=repo_root, timeout=30,
        )
        if checkout_result.returncode != 0:
            return _fail_run_log(
                repo_root, log,
                f"Thread fix: checkout failed: {checkout_result.stderr.strip()}",
            )
    except Exception as exc:
        return _fail_run_log(
            repo_root, log,
            f"Thread fix: checkout error: {exc}",
        )

    try:
        # --- Verify HEAD SHA (defense against force-push tampering, FR-7) ---
        if expected_head_sha:
            current_sha = _get_head_sha(repo_root)
            if current_sha and current_sha != expected_head_sha:
                return _fail_run_log(
                    repo_root, log,
                    f"Thread fix: HEAD SHA mismatch — expected "
                    f"{expected_head_sha[:12]}, got {current_sha[:12]}. "
                    f"Branch may have been force-pushed.",
                )

        # --- Phase: Implement (with thread-fix instructions) ---
        _touch_heartbeat(repo_root)
        impl_ui = _make_ui()
        if impl_ui is not None:
            impl_ui.phase_header(
                "Implement (fix)", config.budget.per_phase,
                config.get_model(Phase.IMPLEMENT), branch_name,
            )
        else:
            _log("=== Thread Fix: Implement ===")

        system, user = _build_thread_fix_prompt(
            config, branch_name, prd_rel, task_rel,
            fix_prompt, original_prompt, repo_root=repo_root,
            pr_review_context=pr_review_context,
        )
        impl_result = run_phase_sync(
            Phase.IMPLEMENT,
            user,
            cwd=repo_root,
            system_prompt=system,
            model=config.get_model(Phase.IMPLEMENT),
            budget_usd=config.budget.per_phase,
            ui=impl_ui,
            retry_config=config.retry,
            timeout_seconds=config.budget.phase_timeout_seconds,
        )
        log.phases.append(impl_result)

        if not impl_result.success:
            return _fail_run_log(repo_root, log, "Thread fix: Implement phase failed")

        # --- Phase: Verify (test suite, FR-7) ---
        _touch_heartbeat(repo_root)
        verify_ui = _make_ui()
        if verify_ui is not None:
            verify_ui.phase_header(
                "Verify (tests)", config.budget.per_phase,
                config.get_model(Phase.VERIFY),
            )
        else:
            _log("=== Thread Fix: Verify ===")

        verify_system = _load_instruction("thread_fix_verify.md")
        # Restrict Verify to read-only tools — it should run tests and
        # report results, not modify code.  Bash is needed for test runners.
        verify_result = run_phase_sync(
            Phase.VERIFY,
            (
                f"Run the full test suite for this project to verify the changes "
                f"on branch `{branch_name}` do not introduce regressions. "
                f"If any tests fail, report the failures but do NOT attempt fixes."
            ),
            cwd=repo_root,
            system_prompt=verify_system,
            model=config.get_model(Phase.VERIFY),
            budget_usd=config.budget.per_phase,
            ui=verify_ui,
            allowed_tools=["Read", "Bash", "Glob", "Grep"],
            retry_config=config.retry,
            timeout_seconds=config.budget.phase_timeout_seconds,
        )
        log.phases.append(verify_result)

        if not verify_result.success:
            return _fail_run_log(repo_root, log, "Thread fix: Verify phase failed")

        # --- Phase: Deliver (push to existing branch, no new PR) ---
        if config.phases.deliver:
            _touch_heartbeat(repo_root)
            deliver_ui = _make_ui()
            if deliver_ui is not None:
                deliver_ui.phase_header(
                    "Deliver (push)", config.budget.per_phase,
                    config.get_model(Phase.DELIVER),
                )
            else:
                _log("=== Thread Fix: Deliver ===")

            system, user = _build_deliver_prompt(
                config, prd_rel, branch_name,
                skip_pr_creation=True,
            )
            deliver_result = run_phase_sync(
                Phase.DELIVER,
                user,
                cwd=repo_root,
                system_prompt=system,
                model=config.get_model(Phase.DELIVER),
                budget_usd=config.budget.per_phase,
                ui=deliver_ui,
                retry_config=config.retry,
                timeout_seconds=config.budget.phase_timeout_seconds,
            )
            log.phases.append(deliver_result)

            if not deliver_result.success:
                return _fail_run_log(repo_root, log, "Thread fix: Deliver phase failed")

        log.status = RunStatus.COMPLETED
        log.mark_finished()
        _save_run_log(repo_root, log)
        _log(f"Thread fix complete. Total cost: ${log.total_cost_usd:.4f}")
        return log

    except KeyboardInterrupt:
        _log("Interrupted — saving run state...")
        _fail_run_log(repo_root, log, "Run interrupted by user (Ctrl+C)")
        raise

    finally:
        # Restore original branch — raise BranchRestoreError on failure
        # to halt the queue executor.  Running subsequent items on the
        # wrong branch is a data-corruption risk.
        if original_branch:
            try:
                restore = subprocess.run(
                    ["git", "checkout", original_branch],
                    capture_output=True, text=True, cwd=repo_root, timeout=30,
                )
                if restore.returncode != 0:
                    raise BranchRestoreError(
                        f"git checkout '{original_branch}' exited "
                        f"{restore.returncode}: {restore.stderr.strip()}"
                    )
            except BranchRestoreError:
                raise
            except Exception as exc:
                raise BranchRestoreError(
                    f"Failed to restore original branch '{original_branch}': {exc}"
                ) from exc


def run(
    prompt: str,
    *,
    repo_root: Path,
    config: ColonyConfig,
    plan_only: bool = False,
    skip_planning: bool = False,
    from_prd: str | None = None,
    resume_from: ResumeState | None = None,
    verbose: bool = False,
    quiet: bool = False,
    source_issue: int | None = None,
    source_issue_url: str | None = None,
    ui_factory: UIFactory | Callable[..., object] | None = None,
    user_injection_provider: Callable[[], list[str]] | None = None,
    offline: bool = False,
    force: bool = False,
    base_branch: str | None = None,
    branch_name_override: str | None = None,
    _nuke_depth: int = 0,
) -> RunLog:
    """Execute the full orchestration loop: plan -> implement -> review -> deliver.

    Args:
        ui_factory: Optional callable conforming to ``UIFactory`` protocol that
            overrides the default terminal UI.  Used by the Slack watcher to
            inject :class:`SlackUI` so phase progress appears as threaded
            replies.
    """

    def _make_ui(
        prefix: str = "",
        *,
        task_id: str | None = None,
        badge: StreamBadge | None = None,
    ) -> PhaseUI | NullUI | None:
        if ui_factory is not None:
            return _invoke_ui_factory(
                ui_factory,
                prefix=prefix,
                task_id=task_id,
                badge=badge,
            )  # type: ignore[return-value]
        if quiet:
            return None
        return PhaseUI(verbose=verbose, prefix=prefix, task_id=task_id, badge=badge)

    is_resume = resume_from is not None
    # Track original branch for rollback if we checkout a base branch.
    original_branch: str | None = None

    # Open memory store for capture + injection (closed at function exit)
    memory_store = _get_memory_store(repo_root, config)

    # --- Resume mode ---
    if resume_from:
        log = resume_from.log
        branch_name = resume_from.branch_name
        prd_rel = resume_from.prd_rel
        task_rel = resume_from.task_rel
        last_successful = resume_from.last_successful_phase
        skip_phases = _SKIP_MAP.get(last_successful, set())
        next_phase = _compute_next_phase(last_successful)
        log.status = RunStatus.RUNNING
        _log(f"Resuming from phase: {next_phase}")

        # Lightweight pre-flight for resume: only check clean working tree
        expected_sha = None
        if not force and log.preflight and log.preflight.head_sha:
            expected_sha = log.preflight.head_sha
        preflight = _resume_preflight(repo_root, branch_name, expected_head_sha=expected_sha)
        log.preflight = preflight

        # Record resume event for audit trail
        _save_run_log(repo_root, log, resumed=True)
    else:
        run_id = _build_run_id(prompt)
        log = RunLog(
            run_id=run_id,
            prompt=prompt,
            status=RunStatus.RUNNING,
            source_issue=source_issue,
            source_issue_url=source_issue_url,
        )
        skip_phases: set[str] = set()

        slug = slugify(prompt)
        names = planning_names(prompt)
        branch_name = branch_name_override or f"{config.branch_prefix}{slug}"

        # --- Base branch validation ---
        # Save original branch so we can restore on failure (critical for
        # long-running watch processes where the next queue item must start
        # from a known state).
        if base_branch:
            # Defense-in-depth: validate at the point of use, not just at entry.
            # This protects against callers that bypass triage (e.g. future CLI
            # commands or hand-edited queue JSON files).
            if not is_valid_git_ref(base_branch):
                raise PreflightError(
                    f"Base branch '{base_branch[:100]}' contains invalid characters"
                )

            original_branch = _get_current_branch(repo_root)

            branch_ok, branch_err = validate_branch_exists(base_branch, repo_root)
            if not branch_ok:
                # Try fetching from remote
                if not offline:
                    try:
                        subprocess.run(
                            ["git", "fetch", "origin", base_branch],
                            capture_output=True, text=True, cwd=repo_root, timeout=30,
                        )
                        # Try to create local tracking branch
                        subprocess.run(
                            ["git", "branch", "--track", base_branch, f"origin/{base_branch}"],
                            capture_output=True, text=True, cwd=repo_root, timeout=30,
                        )
                        branch_ok, branch_err = validate_branch_exists(base_branch, repo_root)
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        _log(f"Failed to fetch base branch '{base_branch}': {exc}")
                if not branch_ok:
                    raise PreflightError(
                        f"Base branch '{base_branch}' does not exist: {branch_err}"
                    )

            # Check out the base branch so the feature branch is created
            # from the correct starting point (FR-13).
            try:
                checkout_result = subprocess.run(
                    ["git", "checkout", base_branch],
                    capture_output=True, text=True, cwd=repo_root, timeout=30,
                )
                if checkout_result.returncode != 0:
                    raise PreflightError(
                        f"Failed to checkout base branch '{base_branch}': "
                        f"{checkout_result.stderr.strip()}"
                    )
            except subprocess.TimeoutExpired:
                raise PreflightError(
                    f"Timeout checking out base branch '{base_branch}'"
                )

            # Pull latest after checking out the base branch so the
            # feature branch starts from up-to-date remote state.
            if not offline:
                pull_ok, pull_err = pull_branch(repo_root)
                if not pull_ok and pull_err is not None:
                    raise PreflightError(
                        f"Failed to pull latest for base branch "
                        f"'{base_branch}': {pull_err}"
                    )

        # --- Pre-flight git state check ---
        preflight = _preflight_check(
            repo_root, branch_name, config, offline=offline, force=force,
        )
        log.preflight = preflight
        for warning in preflight.warnings:
            _log(f"Pre-flight warning: {warning}")

        prd_rel = f"{config.prds_dir}/{names.prd_filename}"
        task_rel = f"{config.tasks_dir}/{names.task_filename}"
        if skip_planning:
            _write_fast_path_artifacts(repo_root, config, prd_rel, task_rel, prompt)

    log.branch_name = branch_name
    log.prd_rel = prd_rel
    log.task_rel = task_rel

    try:
        return _run_pipeline(
            log=log,
            repo_root=repo_root,
            config=config,
            branch_name=branch_name,
            prd_rel=prd_rel,
            task_rel=task_rel,
            skip_phases=skip_phases,
            plan_only=plan_only,
            skip_planning=skip_planning,
            from_prd=from_prd,
            is_resume=is_resume,
            prompt=prompt,
            offline=offline,
            quiet=quiet,
            base_branch=base_branch,
            user_injection_provider=user_injection_provider,
            _make_ui=_make_ui,
            memory_store=memory_store,
            nuke_depth=_nuke_depth,
        )
    except KeyboardInterrupt:
        _log("Interrupted — saving run state...")
        _fail_run_log(repo_root, log, "Run interrupted by user (Ctrl+C)")
        raise
    finally:
        if original_branch:
            try:
                # Check for dirty working tree before attempting checkout
                status_result = subprocess.run(
                    ["git", "status", "--porcelain"],
                    capture_output=True, text=True, cwd=repo_root, timeout=30,
                )
                if status_result.stdout.strip():
                    stash_msg = f"colonyos-{branch_name}"
                    _log(
                        f"WARNING: Working tree is dirty, stashing changes "
                        f"before restoring branch '{original_branch}' "
                        f"(stash message: '{stash_msg}')"
                    )
                    # Only stash tracked files to avoid capturing sensitive
                    # untracked files (.env.local, credential files).
                    subprocess.run(
                        ["git", "stash", "push", "-m", stash_msg],
                        capture_output=True, text=True, cwd=repo_root, timeout=30,
                    )
                checkout_result = subprocess.run(
                    ["git", "checkout", original_branch],
                    capture_output=True, text=True, cwd=repo_root, timeout=30,
                )
                if checkout_result.returncode != 0:
                    raise BranchRestoreError(
                        f"Failed to restore original branch '{original_branch}': "
                        f"{checkout_result.stderr.strip()}"
                    )
            except BranchRestoreError:
                raise
            except Exception as exc:
                raise BranchRestoreError(
                    f"Failed to restore original branch '{original_branch}': {exc}"
                ) from exc


def _run_pipeline(
    *,
    log: RunLog,
    repo_root: Path,
    config: ColonyConfig,
    branch_name: str,
    prd_rel: str,
    task_rel: str,
    skip_phases: set[str],
    plan_only: bool,
    skip_planning: bool,
    from_prd: str | None,
    is_resume: bool,
    prompt: str,
    offline: bool,
    quiet: bool,
    base_branch: str | None,
    user_injection_provider: Callable[[], list[str]] | None,
    _make_ui: Callable[..., PhaseUI | NullUI | None],
    memory_store: MemoryStore | None = None,
    nuke_depth: int = 0,
) -> RunLog:
    """Execute the pipeline phases. Extracted from run() for try/finally branch rollback."""
    try:

        # Generate repo map once for the entire pipeline run (FR-15).
        # The prompt text is passed for relevance ranking (FR-8, Task 5.5).
        repo_map_text = ""
        if config.repo_map.enabled:
            try:
                repo_map_text = generate_repo_map(
                    repo_root, config.repo_map, prompt_text=prompt
                )
            except Exception as exc:
                _log(f"Warning: repo map generation failed: {exc}")

        def _append_phase(result: PhaseResult) -> None:
            """Append a phase result and persist immediately so progress survives crashes."""
            log.phases.append(result)
            _save_run_log(repo_root, log)

        def _run_nuke_recovery(failed_phase: Phase, failure_reason: str) -> RunLog | None:
            """Escalate to last-resort recovery on a fresh branch."""
            if not config.recovery.enabled or not config.recovery.allow_nuke:
                return None
            if nuke_depth >= config.recovery.max_nuke_attempts:
                return None

            summary_ui = _make_ui()
            summary_result = run_nuke_summary(
                repo_root,
                config,
                phase=failed_phase,
                branch_name=branch_name,
                original_prompt=prompt,
                failure_reason=failure_reason,
                ui=summary_ui,
            )
            _append_phase(summary_result)

            summary_text = (
                summary_result.artifacts.get("result")
                or summary_result.error
                or failure_reason
            )[:config.recovery.incident_char_cap]
            label = incident_slug(f"{failed_phase.value}-nuke")
            summary_path = write_incident_summary(
                repo_root,
                label,
                summary=summary_text,
                metadata={
                    "run_id": log.run_id,
                    "failed_phase": failed_phase.value,
                    "branch_name": branch_name,
                },
            )
            preserve_result = preserve_and_reset_worktree(repo_root, label)
            checkout_branch(repo_root, "main")
            recovery_branch = (
                f"{config.branch_prefix}recovery-"
                f"{sha1(f'{log.run_id}-{failed_phase.value}-{nuke_depth}'.encode()).hexdigest()[:10]}"
            )
            create_branch(repo_root, recovery_branch)

            _record_recovery_event(
                log,
                kind="nuke",
                details={
                    "phase": failed_phase.value,
                    "summary_path": str(summary_path),
                    "preservation_mode": preserve_result.preservation_mode,
                    "stash_message": preserve_result.stash_message,
                    "recovery_branch": recovery_branch,
                },
            )
            _save_run_log(repo_root, log)
            _fail_run_log(repo_root, log, f"Escalating to nuke recovery from {failed_phase.value}")

            recovery_prompt = (
                f"{prompt}\n\n"
                "Recovery context:\n"
                f"- Previous branch: {branch_name}\n"
                f"- Failed phase: {failed_phase.value}\n"
                f"- Incident summary: {summary_path}\n"
                f"- Preservation mode: {preserve_result.preservation_mode}\n\n"
                "Replan from scratch on this clean recovery branch and avoid the prior failure.\n\n"
                f"{summary_text}"
            )
            return run(
                recovery_prompt,
                repo_root=repo_root,
                config=config,
                plan_only=False,
                skip_planning=False,
                from_prd=None,
                resume_from=None,
                quiet=quiet,
                source_issue=log.source_issue,
                source_issue_url=log.source_issue_url,
                ui_factory=_make_ui,
                user_injection_provider=user_injection_provider,
                offline=offline,
                force=True,
                base_branch=None,
                branch_name_override=recovery_branch,
                _nuke_depth=nuke_depth + 1,
            )

        def _attempt_phase_recovery(
            failed_phase: Phase,
            failed_result: PhaseResult,
            *,
            rerun_phase: Callable[[], PhaseResult],
        ) -> tuple[PhaseResult | None, RunLog | None]:
            """Try automatic recovery, then optionally escalate to nuke."""
            if not config.recovery.enabled:
                return None, None

            prior_attempts = sum(
                1
                for event in log.recovery_events
                if event.get("kind") == "auto_recovery" and event.get("phase") == failed_phase.value
            )
            if prior_attempts >= config.recovery.max_phase_retries:
                return None, _run_nuke_recovery(
                    failed_phase,
                    failed_result.error or f"{failed_phase.value} phase failed",
                )

            recovery_ui = _make_ui()
            recovery_result = run_auto_recovery(
                repo_root,
                config,
                phase=failed_phase,
                branch_name=branch_name,
                prd_rel=prd_rel,
                task_rel=task_rel,
                original_prompt=prompt,
                failure_reason=failed_result.error or f"{failed_phase.value} phase failed",
                ui=recovery_ui,
            )
            _append_phase(recovery_result)
            _record_recovery_event(
                log,
                kind="auto_recovery",
                details={
                    "phase": failed_phase.value,
                    "success": recovery_result.success,
                    "error": recovery_result.error or "",
                },
            )
            _save_run_log(repo_root, log)

            if not recovery_result.success:
                return None, _run_nuke_recovery(
                    failed_phase,
                    recovery_result.error or failed_result.error or f"{failed_phase.value} phase failed",
                )

            rerun_result = rerun_phase()
            _append_phase(rerun_result)
            _capture_phase_memory(memory_store, rerun_result, log.run_id, config)
            _record_recovery_event(
                log,
                kind="phase_retry",
                details={
                    "phase": failed_phase.value,
                    "success": rerun_result.success,
                    "error": rerun_result.error or "",
                },
            )
            _save_run_log(repo_root, log)

            if rerun_result.success:
                return rerun_result, None
            return None, _run_nuke_recovery(
                failed_phase,
                rerun_result.error or failed_result.error or f"{failed_phase.value} phase failed",
            )

        # --- Phase 1: Plan ---
        _touch_heartbeat(repo_root)
        if "plan" in skip_phases:
            _log("Skipping plan phase (already completed in previous run)")
        elif skip_planning and not from_prd:
            _log("Skipping plan phase for small-fix fast path")
        elif from_prd:
            _log(f"Skipping plan phase, using existing PRD: {from_prd}")
            prd_rel = from_prd
            prd_stem = Path(from_prd).stem
            task_rel = f"{config.tasks_dir}/{prd_stem.replace('_prd_', '_tasks_')}.md"
        else:
            plan_ui = _make_ui()
            if plan_ui is not None:
                extra = ""
                persona_agents = _build_persona_agents(config.personas) or None
                if persona_agents:
                    extra = f"{len(persona_agents)} persona subagents"
                plan_ui.phase_header("Plan", config.budget.per_phase, config.get_model(Phase.PLAN), extra)
            else:
                _log("=== Phase 1: Plan ===")
                persona_agents = _build_persona_agents(config.personas) or None
                if persona_agents:
                    _log(f"  {len(persona_agents)} persona subagents configured for parallel Q&A")

            prd_filename = Path(prd_rel).name
            task_filename = Path(task_rel).name
            system, user = _build_plan_prompt(
                prompt, config, prd_filename, task_filename,
                source_issue=log.source_issue,
                source_issue_url=log.source_issue_url,
            )
            system = _inject_repo_map(system, repo_map_text)
            system = _inject_memory_block(system, memory_store, "plan", user, config)
            plan_result = run_phase_sync(
                Phase.PLAN,
                user,
                cwd=repo_root,
                system_prompt=system,
                model=config.get_model(Phase.PLAN),
                budget_usd=config.budget.per_phase,
                agents=persona_agents,
                ui=plan_ui,
                retry_config=config.retry,
                timeout_seconds=config.budget.phase_timeout_seconds,
            )
            _append_phase(plan_result)
            _capture_phase_memory(memory_store, plan_result, log.run_id, config)

            if not plan_result.success:
                if plan_ui is None:
                    _fail_run_log(repo_root, log, f"Plan phase failed: {plan_result.error}")
                else:
                    _fail_run_log(repo_root, log, "Plan phase failed")
                return log

        if plan_only:
            log.status = RunStatus.COMPLETED
            log.mark_finished()
            _save_run_log(repo_root, log)
            _log("Plan-only mode: stopping after plan phase.")
            return log

        # --- Phase 2: Implement ---
        _touch_heartbeat(repo_root)
        if "implement" in skip_phases:
            _log("Skipping implement phase (already completed in previous run)")
        else:
            impl_ui = _make_ui()
            if impl_ui is not None:
                impl_ui.phase_header("Implement", config.budget.per_phase, config.get_model(Phase.IMPLEMENT), branch_name)
                task_outline = _load_task_outline(repo_root, task_rel)
                task_outline_note = _format_task_outline_note(task_outline)
                if task_outline_note and impl_ui is not None:
                    impl_ui.slack_note(task_outline_note)  # type: ignore[union-attr]
            else:
                _log("=== Phase 2: Implement ===")

            def _execute_implement_phase() -> PhaseResult:
                """Run implement once, preferring parallel mode when enabled."""
                attempt_result = None

                if config.parallel_implement.enabled:
                    # Parallel mode (opt-in)
                    attempt_result = _run_parallel_implement(
                        log=log,
                        repo_root=repo_root,
                        config=config,
                        branch_name=branch_name,
                        prd_rel=prd_rel,
                        task_rel=task_rel,
                        _make_ui=_make_ui,
                    )
                    if attempt_result is not None:
                        _log(
                            "Parallel implement completed: "
                            f"{attempt_result.artifacts.get('parallelism_ratio', '1.0x')}"
                        )
                        if impl_ui is not None:
                            impl_ui.slack_note(_format_implement_result_note(attempt_result))  # type: ignore[union-attr]
                            if attempt_result.success:
                                completed_tasks = int(attempt_result.artifacts.get("completed", "0"))
                                impl_ui.phase_complete(
                                    attempt_result.cost_usd or 0.0,
                                    completed_tasks,
                                    attempt_result.duration_ms,
                                )
                            else:
                                message = attempt_result.error or "Parallel implement phase failed"
                                impl_ui.phase_error(message)
                        return attempt_result
                else:
                    # Sequential mode (default): one task at a time
                    _log("Using sequential (per-task) implement mode")
                    attempt_result = _run_sequential_implement(
                        log=log,
                        repo_root=repo_root,
                        config=config,
                        branch_name=branch_name,
                        prd_rel=prd_rel,
                        task_rel=task_rel,
                        _make_ui=_make_ui,
                        memory_store=memory_store,
                        user_injection_provider=user_injection_provider,
                        repo_map_text=repo_map_text,
                    )
                    if attempt_result is not None:
                        _log(
                            f"Sequential implement completed: "
                            f"{attempt_result.artifacts.get('completed', '0')}/"
                            f"{attempt_result.artifacts.get('total_tasks', '?')} tasks"
                        )
                        if impl_ui is not None:
                            impl_ui.slack_note(_format_implement_result_note(attempt_result))  # type: ignore[union-attr]
                            if attempt_result.success:
                                completed_tasks = int(attempt_result.artifacts.get("completed", "0"))
                                impl_ui.phase_complete(
                                    attempt_result.cost_usd or 0.0,
                                    completed_tasks,
                                    attempt_result.duration_ms,
                                )
                            else:
                                message = attempt_result.error or "Sequential implement phase failed"
                                impl_ui.phase_error(message)
                        return attempt_result

                # Last-resort fallback: single-prompt sequential mode
                mode_attempted = "parallel" if config.parallel_implement.enabled else "sequential"
                _log(f"Falling back to single-prompt implement mode ({mode_attempted} returned None)")
                system, user = _build_implement_prompt(
                    config,
                    prd_rel,
                    task_rel,
                    branch_name,
                    repo_root=repo_root,
                )
                system = _inject_repo_map(system, repo_map_text)
                system = _inject_memory_block(system, memory_store, "implement", user, config)
                user += _drain_injected_context(user_injection_provider)
                attempt_result = run_phase_sync(
                    Phase.IMPLEMENT,
                    user,
                    cwd=repo_root,
                    system_prompt=system,
                    model=config.get_model(Phase.IMPLEMENT),
                    budget_usd=config.budget.per_phase,
                    ui=impl_ui,
                    retry_config=config.retry,
                    timeout_seconds=config.budget.phase_timeout_seconds,
                )
                return attempt_result

            impl_result = _execute_implement_phase()

            _append_phase(impl_result)
            _capture_phase_memory(memory_store, impl_result, log.run_id, config)

            if not impl_result.success:
                recovered_result, recovery_log = _attempt_phase_recovery(
                    Phase.IMPLEMENT,
                    impl_result,
                    rerun_phase=_execute_implement_phase,
                )
                if recovery_log is not None:
                    return recovery_log
                if recovered_result is None:
                    if impl_ui is None:
                        _fail_run_log(repo_root, log, f"Implement phase failed: {impl_result.error}")
                    else:
                        _fail_run_log(repo_root, log, "Implement phase failed")
                    return log

        # --- Phase 3: Review/Fix Loop ---
        _touch_heartbeat(repo_root)
        if "review" in skip_phases:
            _log("Skipping review phase (already completed in previous run)")
        elif config.phases.review:
            reviewers = reviewer_personas(config)
            if not reviewers:
                _log("No reviewer personas configured, skipping review phase")
            else:
                review_header_ui = _make_ui()
                if review_header_ui is not None:
                    review_header_ui.phase_header(
                        f"Review ({len(reviewers)} reviewers)",
                        config.budget.per_phase,
                        config.get_model(Phase.REVIEW),
                    )
                else:
                    _log(f"=== Phase 3: Review ({len(reviewers)} reviewers) ===")
                review_tools = ["Read", "Glob", "Grep", "Bash"]
                last_findings: list[tuple[str, str]] = []

                for iteration in range(config.max_fix_iterations + 1):
                    # Budget guard
                    cost_so_far = sum(
                        p.cost_usd for p in log.phases if p.cost_usd is not None
                    )
                    remaining = config.budget.per_run - cost_so_far
                    if remaining < config.budget.per_phase:
                        _log(
                            f"Review loop: budget exhausted "
                            f"({remaining:.2f} remaining). Stopping reviews."
                        )
                        break

                    _log(f"  Review round {iteration + 1}/{config.max_fix_iterations + 1}")
                    if not quiet:
                        print_reviewer_legend([(i, p.role) for i, p in enumerate(reviewers)])

                    review_calls = []
                    for i, persona in enumerate(reviewers):
                        sys_prompt, usr_prompt = _build_persona_review_prompt(
                            persona, config, prd_rel, branch_name
                        )
                        sys_prompt = _inject_repo_map(sys_prompt, repo_map_text)
                        # FR-3: Inject memory context into review phase prompts
                        sys_prompt = _inject_memory_block(sys_prompt, memory_store, "review", usr_prompt, config)
                        usr_prompt += _drain_injected_context(user_injection_provider)
                        persona_ui = _make_ui(badge=make_reviewer_badge(i))
                        review_calls.append(dict(
                            phase=Phase.REVIEW,
                            prompt=usr_prompt,
                            cwd=repo_root,
                            system_prompt=sys_prompt,
                            model=config.get_model(Phase.REVIEW),
                            budget_usd=config.budget.per_phase,
                            allowed_tools=review_tools,
                            ui=persona_ui,
                            retry_config=config.retry,
                        ))

                    # Create progress tracker for real-time status updates
                    progress_tracker: ParallelProgressLine | None = None
                    if not quiet:
                        is_tty = sys.stderr.isatty()
                        reviewer_list = [(i, p.role) for i, p in enumerate(reviewers)]
                        progress_tracker = ParallelProgressLine(reviewer_list, is_tty=is_tty)

                    results = run_phases_parallel_sync(
                        review_calls,
                        on_complete=progress_tracker.on_reviewer_complete if progress_tracker else None,
                    )

                    # Persist review results before any post-review notifications so
                    # resume metadata stays up to date even if a mirror UI blocks.
                    for persona, result in zip(reviewers, results):
                        _append_phase(result)
                        _capture_phase_memory(memory_store, result, log.run_id, config)
                        p_slug = _persona_slug(persona.role)
                        text = result.artifacts.get("result", "")
                        artifact = persona_review_artifact_path(
                            prompt, p_slug, iteration + 1,
                        )
                        _save_review_artifact(
                            repo_root,
                            config.reviews_dir,
                            artifact.filename,
                            f"# Review by {persona.role} (Round {iteration + 1})\n\n{text}",
                            subdirectory=artifact.subdirectory,
                        )

                    # Print summary after all reviewers complete
                    if progress_tracker is not None:
                        progress_tracker.print_summary(round_num=iteration + 1)
                    if review_header_ui is not None:
                        review_header_ui.slack_note(  # type: ignore[union-attr]
                            _format_review_round_note(
                                results,
                                reviewers,
                                round_num=iteration + 1,
                                total_rounds=config.max_fix_iterations + 1,
                            )
                        )

                    last_findings = _collect_review_findings(results, reviewers)

                    if not last_findings:
                        _log("  All reviewers approve")
                        break

                    _log(
                        f"  {len(last_findings)} reviewer(s) requested changes: "
                        + ", ".join(role for role, _ in last_findings)
                    )

                    if iteration < config.max_fix_iterations:
                        findings_text = "\n\n---\n\n".join(
                            f"### {role}\n\n{text}" for role, text in last_findings
                        )
                        fix_system, fix_user = _build_fix_prompt(
                            config,
                            prd_rel,
                            task_rel,
                            branch_name,
                            findings_text,
                            iteration + 1,
                            repo_root=repo_root,
                        )
                        fix_system = _inject_repo_map(fix_system, repo_map_text)
                        fix_system = _inject_memory_block(fix_system, memory_store, "fix", fix_user, config)
                        fix_user += _drain_injected_context(user_injection_provider)
                        fix_ui = _make_ui()
                        if fix_ui is not None:
                            fix_ui.phase_header(
                                f"Fix (iteration {iteration + 1})",
                                config.budget.per_phase,
                                config.get_model(Phase.FIX),
                                _format_fix_iteration_extra(reviewers, last_findings),
                            )
                        else:
                            _log(f"  Running fix agent (iteration {iteration + 1})...")
                        fix_result = run_phase_sync(
                            Phase.FIX,
                            fix_user,
                            cwd=repo_root,
                            system_prompt=fix_system,
                            model=config.get_model(Phase.FIX),
                            budget_usd=config.budget.per_phase,
                            ui=fix_ui,
                            retry_config=config.retry,
                            timeout_seconds=config.budget.phase_timeout_seconds,
                        )
                        _append_phase(fix_result)
                        _capture_phase_memory(memory_store, fix_result, log.run_id, config)
                        if not fix_result.success:
                            if fix_ui is None:
                                _log(f"  Fix phase failed: {fix_result.error}")
                            break

                # --- Decision Gate ---
                decision_ui = _make_ui()
                if decision_ui is not None:
                    decision_ui.phase_header("Decision Gate", config.budget.per_phase, config.get_model(Phase.DECISION))
                else:
                    _log("=== Decision Gate ===")
                system, user = _build_decision_prompt(config, prd_rel, branch_name)
                system = _inject_repo_map(system, repo_map_text)
                user += _drain_injected_context(user_injection_provider)
                decision_result = run_phase_sync(
                    Phase.DECISION,
                    user,
                    cwd=repo_root,
                    system_prompt=system,
                    model=config.get_model(Phase.DECISION),
                    budget_usd=config.budget.per_phase,
                    allowed_tools=["Read", "Glob", "Grep", "Bash"],
                    ui=decision_ui,
                    retry_config=config.retry,
                    timeout_seconds=config.budget.phase_timeout_seconds,
                )
                _append_phase(decision_result)

                verdict_text = decision_result.artifacts.get("result", "")
                verdict = _extract_verdict(verdict_text)
                _log(f"  Decision: {verdict}")

                decision_art = decision_artifact_path(prompt)
                _save_review_artifact(
                    repo_root,
                    config.reviews_dir,
                    decision_art.filename,
                    f"# Decision Gate\n\nVerdict: **{verdict}**\n\n{verdict_text}",
                    subdirectory=decision_art.subdirectory,
                )

                if verdict == "NO-GO":
                    _run_learn_phase(config, repo_root, log, prompt, _make_ui, memory_store=memory_store)
                    _fail_run_log(repo_root, log, "Decision gate: NO-GO. Pipeline stopped before deliver.")
                    return log

                if verdict == "UNKNOWN":
                    _log("  Warning: could not parse verdict, proceeding with caution")

        # --- Learn Phase ---
        _run_learn_phase(config, repo_root, log, prompt, _make_ui, memory_store=memory_store)

        # --- Deliver Phase ---
        _touch_heartbeat(repo_root)
        if config.phases.deliver:
            deliver_ui = _make_ui()
            if deliver_ui is not None:
                deliver_ui.phase_header("Deliver", config.budget.per_phase, config.get_model(Phase.DELIVER))
            else:
                phase_num = 5 if config.phases.review else 3
                _log(f"=== Phase {phase_num}: Deliver ===")

            def _execute_deliver_phase() -> PhaseResult:
                system, user = _build_deliver_prompt(
                    config, prd_rel, branch_name,
                    source_issue=log.source_issue,
                    base_branch=base_branch,
                )
                system = _inject_repo_map(system, repo_map_text)
                user += _drain_injected_context(user_injection_provider)
                return run_phase_sync(
                    Phase.DELIVER,
                    user,
                    cwd=repo_root,
                    system_prompt=system,
                    model=config.get_model(Phase.DELIVER),
                    budget_usd=config.budget.per_phase,
                    ui=deliver_ui,
                    retry_config=config.retry,
                    timeout_seconds=config.budget.phase_timeout_seconds,
                )

            deliver_result = _execute_deliver_phase()
            _append_phase(deliver_result)

            # Extract PR URL from deliver artifacts
            pr_url = deliver_result.artifacts.get("pr_url", "")
            if pr_url:
                log.pr_url = pr_url
                # Register the PR for outcome tracking (non-blocking)
                _register_pr_outcome(repo_root, log.run_id, pr_url, branch_name)

            if not deliver_result.success:
                recovered_result, recovery_log = _attempt_phase_recovery(
                    Phase.DELIVER,
                    deliver_result,
                    rerun_phase=_execute_deliver_phase,
                )
                if recovery_log is not None:
                    return recovery_log
                if recovered_result is None:
                    if deliver_ui is None:
                        _fail_run_log(repo_root, log, f"Deliver phase failed: {deliver_result.error}")
                    else:
                        _fail_run_log(repo_root, log, "Deliver phase failed")
                    return log
                recovered_pr_url = recovered_result.artifacts.get("pr_url", "")
                if recovered_pr_url:
                    log.pr_url = recovered_pr_url
                    # Register the recovered PR for outcome tracking (non-blocking)
                    _register_pr_outcome(repo_root, log.run_id, recovered_pr_url, branch_name)

        # --- CI Fix Phase (post-deliver) ---
        if config.ci_fix.enabled and config.phases.deliver:
            # Persist the run log before entering the CI fix loop so that
            # prior phase results are not lost if the loop crashes.
            _save_run_log(repo_root, log)
            _run_ci_fix_loop(config, repo_root, log, branch_name)

        log.status = RunStatus.COMPLETED
        log.mark_finished()
        _save_run_log(repo_root, log)
        _log(f"Run complete. Total cost: ${log.total_cost_usd:.4f}")
        return log
    finally:
        if memory_store is not None:
            memory_store.close()

        # Safety net: if the pipeline didn't complete cleanly, commit any
        # dirty working-tree state so that subsequent runs aren't blocked
        # by the preflight "dirty worktree" check.  On feature branches
        # this preserves partial work; on main/master it stashes instead.
        if log.status != RunStatus.COMPLETED:
            try:
                from colonyos.recovery import safety_commit_partial_work

                ctx: list[str] = [f"Run: {log.run_id}"]
                if log.prompt:
                    ctx.append(f"Prompt: {log.prompt[:200]}")
                if log.phases:
                    last_phase = log.phases[-1]
                    ctx.append(f"Last phase: {last_phase.phase.value}")
                    if last_phase.error:
                        ctx.append(f"Error: {last_phase.error[:300]}")
                ctx.append(f"Cost so far: ${log.total_cost_usd:.2f}")
                result = safety_commit_partial_work(
                    repo_root, context_lines=ctx
                )
                if result:
                    _log(f"Post-failure cleanup: {result}")
            except Exception:
                logger.warning(
                    "Post-failure safety commit failed", exc_info=True
                )
