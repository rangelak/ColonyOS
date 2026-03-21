from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable
from hashlib import sha1
from pathlib import Path

import click
from claude_agent_sdk import AgentDefinition

from colonyos.agent import run_phase_sync, run_phases_parallel_sync
from colonyos.config import ColonyConfig, runs_dir_path
from colonyos.learnings import (
    LearningEntry,
    append_learnings,
    learnings_path,
    load_learnings_for_injection,
    parse_learnings,
)
from colonyos.models import BranchRestoreError, Persona, Phase, PhaseResult, PreflightError, PreflightResult, ResumeState, RunLog, RunStatus
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
from colonyos.sanitize import sanitize_untrusted_content
from colonyos.slack import is_valid_git_ref
from colonyos.ui import NullUI, PhaseUI, make_reviewer_prefix, print_reviewer_legend


def _touch_heartbeat(repo_root: Path) -> None:
    """Touch the heartbeat file to signal the orchestrator is alive."""
    heartbeat_path = runs_dir_path(repo_root) / "heartbeat"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.touch()


def _log(msg: str) -> None:
    print(f"[colonyos] {msg}", file=sys.stderr, flush=True)


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


_COLONYOS_OUTPUT_PREFIXES = (
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
                if not any(ln[3:].startswith(p) for p in _COLONYOS_OUTPUT_PREFIXES)
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
            "Please commit or stash your changes before running colonyos."
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
                f"Use --resume to continue existing work, or --force to bypass this check."
            )
        raise PreflightError(
            f"Branch '{branch_name}' already exists locally.\n\n"
            "Use --resume to continue existing work, or --force to bypass this check."
        )

    # Check if main is behind origin/main
    main_behind_count: int | None = None
    fetch_succeeded = False
    if not offline:
        try:
            subprocess.run(
                ["git", "fetch", "origin", "main"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=repo_root,
            )
            fetch_succeeded = True
        except (OSError, subprocess.TimeoutExpired) as exc:
            warnings.append(f"Failed to fetch origin/main: {exc}")

        if fetch_succeeded:
            try:
                result = subprocess.run(
                    ["git", "rev-list", "--count", "main..origin/main"],
                    capture_output=True,
                    text=True,
                    cwd=repo_root,
                )
                if result.returncode == 0 and result.stdout.strip().isdigit():
                    main_behind_count = int(result.stdout.strip())
                    if main_behind_count > 0:
                        warnings.append(
                            f"Local main is {main_behind_count} commit(s) behind origin/main. "
                            "Consider running: git pull"
                        )
            except OSError:
                pass

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
            "Please commit or stash your changes before resuming."
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
    return base.format(
        prds_dir=config.prds_dir,
        tasks_dir=config.tasks_dir,
        reviews_dir=config.reviews_dir,
        branch_prefix=config.branch_prefix,
    )


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


def reviewer_personas(config: ColonyConfig) -> list[Persona]:
    """Return only personas that have reviewer=True."""
    return [p for p in config.personas if p.reviewer]


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
) -> tuple[str, str]:
    """Build the system prompt and user prompt for the CEO phase."""
    from colonyos.directions import load_directions

    ceo_template = _load_instruction("ceo.md")
    persona = config.ceo_persona or DEFAULT_CEO_PERSONA

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

    user = (
        "## Development History\n\n"
        "Below is the complete changelog of features already built. "
        "Your proposal MUST NOT duplicate any of these. "
        "Your proposal MUST build upon or complement existing work.\n\n"
        f"{changelog}\n\n---\n\n"
        f"{prs_section}"
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
) -> tuple[str, PhaseResult]:
    """Run the CEO phase: analyze the project and propose the next feature.

    Returns a tuple of (proposed_prompt, phase_result).
    """
    names = proposal_names("ceo_proposal")
    proposal_filename = names.proposal_filename

    system, user = _build_ceo_prompt(config, proposal_filename, repo_root)

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
                "preflight": log.preflight.to_dict() if log.preflight else None,
                "last_successful_phase": last_successful_phase,
                "resume_events": resume_events,
                "phases": [
                    {
                        "phase": p.phase.value,
                        "success": p.success,
                        "cost_usd": p.cost_usd,
                        "duration_ms": p.duration_ms,
                        "session_id": p.session_id,
                        "model": p.model,
                        "error": p.error,
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

    return ResumeState(
        log=log,
        branch_name=log.branch_name,  # type: ignore[arg-type]
        prd_rel=log.prd_rel,  # type: ignore[arg-type]
        task_rel=log.task_rel,  # type: ignore[arg-type]
        last_successful_phase=last_successful_phase,
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

    def _make_ui(prefix: str = "") -> PhaseUI | NullUI | None:
        if quiet:
            return None
        return PhaseUI(verbose=verbose, prefix=prefix)

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
            persona_ui = _make_ui(prefix=make_reviewer_prefix(i))
            review_calls.append(dict(
                phase=Phase.REVIEW,
                prompt=usr_prompt,
                cwd=repo_root,
                system_prompt=sys_prompt,
                model=config.get_model(Phase.REVIEW),
                budget_usd=config.budget.per_phase,
                allowed_tools=review_tools,
                ui=persona_ui,
            ))

        results = run_phases_parallel_sync(review_calls)

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
) -> None:
    """Execute the learn phase: extract patterns from reviews into the ledger.

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
        )
        log.phases.append(learn_result)

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
    ui_factory: object | None = None,
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

    def _make_ui(prefix: str = "") -> PhaseUI | NullUI | None:
        if ui_factory is not None:
            return ui_factory(prefix)  # type: ignore[operator]
        if quiet:
            return None
        return PhaseUI(verbose=verbose, prefix=prefix)

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
            )
            log.phases.append(deliver_result)

            if not deliver_result.success:
                return _fail_run_log(repo_root, log, "Thread fix: Deliver phase failed")

        log.status = RunStatus.COMPLETED
        log.mark_finished()
        _save_run_log(repo_root, log)
        _log(f"Thread fix complete. Total cost: ${log.total_cost_usd:.4f}")
        return log

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
    from_prd: str | None = None,
    resume_from: ResumeState | None = None,
    verbose: bool = False,
    quiet: bool = False,
    source_issue: int | None = None,
    source_issue_url: str | None = None,
    ui_factory: object | None = None,
    offline: bool = False,
    force: bool = False,
    base_branch: str | None = None,
) -> RunLog:
    """Execute the full orchestration loop: plan -> implement -> review -> deliver.

    Args:
        ui_factory: Optional callable ``(prefix: str) -> UI | None`` that
            overrides the default terminal UI.  Used by the Slack watcher to
            inject :class:`SlackUI` so phase progress appears as threaded
            replies.
    """

    def _make_ui(prefix: str = "") -> PhaseUI | NullUI | None:
        if ui_factory is not None:
            return ui_factory(prefix)  # type: ignore[operator]
        if quiet:
            return None
        return PhaseUI(verbose=verbose, prefix=prefix)

    is_resume = resume_from is not None
    # Track original branch for rollback if we checkout a base branch.
    original_branch: str | None = None

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
        if log.preflight and log.preflight.head_sha:
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
        branch_name = f"{config.branch_prefix}{slug}"

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

        # --- Pre-flight git state check ---
        preflight = _preflight_check(
            repo_root, branch_name, config, offline=offline, force=force,
        )
        log.preflight = preflight
        for warning in preflight.warnings:
            _log(f"Pre-flight warning: {warning}")

        prd_rel = f"{config.prds_dir}/{names.prd_filename}"
        task_rel = f"{config.tasks_dir}/{names.task_filename}"

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
            from_prd=from_prd,
            is_resume=is_resume,
            prompt=prompt,
            offline=offline,
            quiet=quiet,
            base_branch=base_branch,
            _make_ui=_make_ui,
        )
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
    from_prd: str | None,
    is_resume: bool,
    prompt: str,
    offline: bool,
    quiet: bool,
    base_branch: str | None,
    _make_ui: Callable[..., PhaseUI | NullUI | None],
) -> RunLog:
    """Execute the pipeline phases. Extracted from run() for try/finally branch rollback."""

    # --- Phase 1: Plan ---
    _touch_heartbeat(repo_root)
    if "plan" in skip_phases:
        _log("Skipping plan phase (already completed in previous run)")
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
        plan_result = run_phase_sync(
            Phase.PLAN,
            user,
            cwd=repo_root,
            system_prompt=system,
            model=config.get_model(Phase.PLAN),
            budget_usd=config.budget.per_phase,
            agents=persona_agents,
            ui=plan_ui,
        )
        log.phases.append(plan_result)

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
        else:
            _log("=== Phase 2: Implement ===")
        system, user = _build_implement_prompt(config, prd_rel, task_rel, branch_name, repo_root=repo_root)
        impl_result = run_phase_sync(
            Phase.IMPLEMENT,
            user,
            cwd=repo_root,
            system_prompt=system,
            model=config.get_model(Phase.IMPLEMENT),
            budget_usd=config.budget.per_phase,
            ui=impl_ui,
        )
        log.phases.append(impl_result)

        if not impl_result.success:
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
                    persona_ui = _make_ui(prefix=make_reviewer_prefix(i))
                    review_calls.append(dict(
                        phase=Phase.REVIEW,
                        prompt=usr_prompt,
                        cwd=repo_root,
                        system_prompt=sys_prompt,
                        model=config.get_model(Phase.REVIEW),
                        budget_usd=config.budget.per_phase,
                        allowed_tools=review_tools,
                        ui=persona_ui,
                    ))

                results = run_phases_parallel_sync(review_calls)

                # Save each persona's review artifact
                for persona, result in zip(reviewers, results):
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
                    log.phases.append(result)

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
                    )
                    log.phases.append(fix_result)
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
            decision_result = run_phase_sync(
                Phase.DECISION,
                user,
                cwd=repo_root,
                system_prompt=system,
                model=config.get_model(Phase.DECISION),
                budget_usd=config.budget.per_phase,
                allowed_tools=["Read", "Glob", "Grep", "Bash"],
                ui=decision_ui,
            )
            log.phases.append(decision_result)

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
                _run_learn_phase(config, repo_root, log, prompt, _make_ui)
                _fail_run_log(repo_root, log, "Decision gate: NO-GO. Pipeline stopped before deliver.")
                return log

            if verdict == "UNKNOWN":
                _log("  Warning: could not parse verdict, proceeding with caution")

    # --- Learn Phase ---
    _run_learn_phase(config, repo_root, log, prompt, _make_ui)

    # --- Deliver Phase ---
    _touch_heartbeat(repo_root)
    if config.phases.deliver:
        deliver_ui = _make_ui()
        if deliver_ui is not None:
            deliver_ui.phase_header("Deliver", config.budget.per_phase, config.get_model(Phase.DELIVER))
        else:
            phase_num = 5 if config.phases.review else 3
            _log(f"=== Phase {phase_num}: Deliver ===")
        system, user = _build_deliver_prompt(
            config, prd_rel, branch_name,
            source_issue=log.source_issue,
            base_branch=base_branch,
        )
        deliver_result = run_phase_sync(
            Phase.DELIVER,
            user,
            cwd=repo_root,
            system_prompt=system,
            model=config.get_model(Phase.DELIVER),
            budget_usd=config.budget.per_phase,
            ui=deliver_ui,
        )
        log.phases.append(deliver_result)

        # Extract PR URL from deliver artifacts
        pr_url = deliver_result.artifacts.get("pr_url", "")
        if pr_url:
            log.pr_url = pr_url

        if not deliver_result.success:
            if deliver_ui is None:
                _fail_run_log(repo_root, log, f"Deliver phase failed: {deliver_result.error}")
            else:
                _fail_run_log(repo_root, log, "Deliver phase failed")
            return log

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
