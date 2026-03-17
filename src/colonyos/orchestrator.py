from __future__ import annotations

import json
import re
import subprocess
import sys
from hashlib import sha1
from pathlib import Path

import click
from claude_agent_sdk import AgentDefinition

from colonyos.agent import run_phase_sync, run_phases_parallel_sync
from colonyos.config import ColonyConfig, runs_dir_path
from colonyos.models import Persona, Phase, PhaseResult, ResumeState, RunLog, RunStatus
from colonyos.naming import generate_timestamp, planning_names, proposal_names, slugify
from colonyos.ui import NullUI, PhaseUI, make_reviewer_prefix

# ---------------------------------------------------------------------------
# Branch name validation
# ---------------------------------------------------------------------------

_BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9_./~^-]+$")


def _validate_branch_name(name: str) -> str | None:
    """Validate a branch name for safe use in git commands.

    Returns an error message if invalid, or None if OK.
    Rejects names starting with ``-`` (could be interpreted as flags),
    containing ``..`` (path traversal in git), or using characters
    outside the safe set ``[A-Za-z0-9_./-]``.
    """
    if not name:
        return "Branch name must not be empty."
    if name.startswith("-"):
        return f"Invalid branch name: {name!r}. Must not start with '-'."
    if ".." in name:
        return f"Invalid branch name: {name!r}. Must not contain '..'."
    if not _BRANCH_NAME_RE.match(name):
        return f"Invalid branch name: {name!r}. Contains disallowed characters."
    return None


# ---------------------------------------------------------------------------
# Base-branch detection & pre-flight validation
# ---------------------------------------------------------------------------


def detect_base_branch(repo_root: Path, override: str | None = None) -> str:
    """Auto-detect the base branch for a review.

    Checks (in order): explicit *override*, ``main``, ``master``,
    then falls back to ``HEAD~1``.
    """
    if override:
        return override

    for candidate in ("main", "master"):
        result = subprocess.run(
            ["git", "rev-parse", "--verify", candidate],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        if result.returncode == 0:
            return candidate

    return "HEAD~1"


def validate_review_preconditions(
    repo_root: Path,
    branch: str,
    base_branch: str,
    fix_enabled: bool,
) -> str | None:
    """Validate that a standalone review can proceed.

    Returns an error message string if validation fails, or ``None`` if OK.
    """
    # 0. Validate branch name format (defense-in-depth against flag injection)
    branch_err = _validate_branch_name(branch)
    if branch_err:
        return branch_err
    base_err = _validate_branch_name(base_branch)
    if base_err:
        return base_err

    # 1. Branch exists locally
    result = subprocess.run(
        ["git", "rev-parse", "--verify", branch],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        return f"Branch '{branch}' not found locally."

    # 2. Non-empty diff against base
    diff_result = subprocess.run(
        ["git", "diff", "--stat", f"{base_branch}...{branch}"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if not diff_result.stdout.strip():
        return f"No changes to review on branch {branch} against {base_branch}."

    # 3. Clean working tree when --fix is used
    if fix_enabled:
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        if status_result.stdout.strip():
            return (
                "Working tree has uncommitted changes. "
                "Commit or stash them before using --fix."
            )

    return None


def _build_review_run_id(branch_name: str) -> str:
    """Generate a run ID for standalone review runs."""
    digest = sha1(branch_name.strip().encode()).hexdigest()[:10]
    return f"review-{generate_timestamp()}-{digest}"


# ---------------------------------------------------------------------------
# Standalone prompt builders
# ---------------------------------------------------------------------------


def _build_persona_standalone_review_prompt(
    persona: Persona,
    config: ColonyConfig,
    branch_name: str,
    base_branch: str,
) -> tuple[str, str]:
    """Build a review prompt for a single persona WITHOUT a PRD."""
    review_template = _load_instruction("review_standalone.md")

    system = _format_base(config) + "\n\n" + review_template.format(
        reviewer_role=persona.role,
        reviewer_expertise=persona.expertise,
        reviewer_perspective=persona.perspective,
        branch_name=branch_name,
        base_branch=base_branch,
    )

    user = (
        f"Review the implementation on branch `{branch_name}` against base "
        f"`{base_branch}`. Assess the entire implementation holistically from "
        f"your perspective as {persona.role}."
    )
    return system, user


def _build_standalone_fix_prompt(
    config: ColonyConfig,
    branch_name: str,
    base_branch: str,
    findings_text: str,
    fix_iteration: int,
) -> tuple[str, str]:
    """Build a fix prompt for PRD-less fix iterations."""
    fix_template = _load_instruction("fix_standalone.md")

    system = _format_base(config) + "\n\n" + fix_template.format(
        branch_name=branch_name,
        base_branch=base_branch,
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
    """Build a decision gate prompt WITHOUT a PRD."""
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


# ---------------------------------------------------------------------------
# Reusable review/fix/decision loop
# ---------------------------------------------------------------------------


def run_review_loop(
    repo_root: Path,
    config: ColonyConfig,
    branch_name: str,
    log: RunLog,
    *,
    prd_rel: str | None = None,
    task_rel: str | None = None,
    base_branch: str = "main",
    enable_fix: bool = True,
    artifact_prefix: str = "",
    verbose: bool = False,
    quiet: bool = False,
) -> str:
    """Run the review/fix/decision loop and return the overall verdict.

    This is the shared core used by both ``orchestrator.run()`` (pipeline
    mode) and the standalone ``colonyos review`` command.

    Returns one of: ``"approve"``, ``"request-changes"``, ``"GO"``,
    ``"NO-GO"``, or ``"UNKNOWN"``.
    """

    def _make_ui(prefix: str = "") -> "PhaseUI | NullUI | None":
        if quiet:
            return None
        return PhaseUI(verbose=verbose, prefix=prefix)

    reviewers = _reviewer_personas(config)
    if not reviewers:
        _log("No reviewer personas configured, skipping review phase")
        return "approve"

    review_header_ui = _make_ui()
    if review_header_ui is not None:
        review_header_ui.phase_header(
            f"Review ({len(reviewers)} reviewers)",
            config.budget.per_phase,
            config.model,
        )
    else:
        _log(f"=== Review ({len(reviewers)} reviewers) ===")

    review_tools = ["Read", "Glob", "Grep"]
    last_findings: list[tuple[str, str]] = []
    branch_slug = slugify(branch_name)

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

        review_calls = []
        for i, persona in enumerate(reviewers):
            if prd_rel:
                sys_prompt, usr_prompt = _build_persona_review_prompt(
                    persona, config, prd_rel, branch_name
                )
            else:
                sys_prompt, usr_prompt = _build_persona_standalone_review_prompt(
                    persona, config, branch_name, base_branch
                )
            persona_ui = _make_ui(prefix=make_reviewer_prefix(persona.role, i))
            review_calls.append(dict(
                phase=Phase.REVIEW,
                prompt=usr_prompt,
                cwd=repo_root,
                system_prompt=sys_prompt,
                model=config.model,
                budget_usd=config.budget.per_phase,
                allowed_tools=review_tools,
                ui=persona_ui,
            ))

        results = run_phases_parallel_sync(review_calls)

        # Save each persona's review artifact
        for persona, result in zip(reviewers, results):
            p_slug = _persona_slug(persona.role)
            text = result.artifacts.get("result", "")
            if artifact_prefix:
                fname = f"review_{artifact_prefix}{branch_slug}_round{iteration + 1}_{p_slug}.md"
            else:
                fname = f"review_round{iteration + 1}_{p_slug}.md"
            _save_review_artifact(
                repo_root,
                config.reviews_dir,
                fname,
                f"# Review by {persona.role} (Round {iteration + 1})\n\n{text}",
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

        if enable_fix and iteration < config.max_fix_iterations:
            findings_text = "\n\n---\n\n".join(
                f"### {role}\n\n{text}" for role, text in last_findings
            )
            if prd_rel and task_rel:
                fix_system, fix_user = _build_fix_prompt(
                    config, prd_rel, task_rel, branch_name,
                    findings_text, iteration + 1,
                )
            else:
                fix_system, fix_user = _build_standalone_fix_prompt(
                    config, branch_name, base_branch,
                    findings_text, iteration + 1,
                )
            fix_ui = _make_ui()
            if fix_ui is not None:
                fix_ui.phase_header(
                    f"Fix (iteration {iteration + 1})",
                    config.budget.per_phase,
                    config.model,
                )
            else:
                _log(f"  Running fix agent (iteration {iteration + 1})...")
            fix_result = run_phase_sync(
                Phase.FIX,
                fix_user,
                cwd=repo_root,
                system_prompt=fix_system,
                model=config.model,
                budget_usd=config.budget.per_phase,
                ui=fix_ui,
            )
            log.phases.append(fix_result)
            if not fix_result.success:
                if fix_ui is None:
                    _log(f"  Fix phase failed: {fix_result.error}")
                break
        else:
            # No fix to apply; re-reviewing won't change anything
            break

    # --- Decision Gate ---
    decision_ui = _make_ui()
    if decision_ui is not None:
        decision_ui.phase_header("Decision Gate", config.budget.per_phase, config.model)
    else:
        _log("=== Decision Gate ===")

    if prd_rel:
        system, user = _build_decision_prompt(config, prd_rel, branch_name)
    else:
        system, user = _build_standalone_decision_prompt(config, branch_name, base_branch)

    decision_result = run_phase_sync(
        Phase.DECISION,
        user,
        cwd=repo_root,
        system_prompt=system,
        model=config.model,
        budget_usd=config.budget.per_phase,
        allowed_tools=["Read", "Glob", "Grep"],
        ui=decision_ui,
    )
    log.phases.append(decision_result)

    verdict_text = decision_result.artifacts.get("result", "")
    verdict = _extract_verdict(verdict_text)
    _log(f"  Decision: {verdict}")

    if artifact_prefix:
        decision_fname = f"decision_{artifact_prefix}{branch_slug}.md"
    else:
        decision_fname = f"decision_{branch_slug}.md"
    _save_review_artifact(
        repo_root,
        config.reviews_dir,
        decision_fname,
        f"# Decision Gate\n\nVerdict: **{verdict}**\n\n{verdict_text}",
    )

    return verdict


def _touch_heartbeat(repo_root: Path) -> None:
    """Touch the heartbeat file to signal the orchestrator is alive."""
    heartbeat_path = runs_dir_path(repo_root) / "heartbeat"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.touch()


def _log(msg: str) -> None:
    print(f"[colonyos] {msg}", file=sys.stderr, flush=True)


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

    user = f"Feature request:\n\n{prompt}"
    return system, user


def _build_implement_prompt(
    config: ColonyConfig,
    prd_path: str,
    task_path: str,
    branch_name: str,
) -> tuple[str, str]:
    impl_template = _load_instruction("implement.md")

    system = _format_base(config) + "\n\n" + impl_template.format(
        prd_path=prd_path,
        task_path=task_path,
        branch_name=branch_name,
    )

    user = (
        f"Implement the feature described in the PRD at `{prd_path}`. "
        f"Follow the task list at `{task_path}`. "
        f"Work on branch `{branch_name}`."
    )
    return system, user


def _reviewer_personas(config: ColonyConfig) -> list[Persona]:
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


def _extract_review_verdict(result_text: str) -> str:
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
        verdict = _extract_review_verdict(text)
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

    user = (
        f"Fix the issues identified by reviewers for branch `{branch_name}`. "
        f"This is fix iteration {fix_iteration} of {config.max_fix_iterations}. "
        f"The PRD is at `{prd_path}` and the task file is at `{task_path}`."
    )
    return system, user


def _build_deliver_prompt(
    config: ColonyConfig,
    prd_path: str,
    branch_name: str,
) -> tuple[str, str]:
    deliver_template = _load_instruction("deliver.md")

    system = _format_base(config) + "\n\n" + deliver_template.format(
        prd_path=prd_path,
        branch_name=branch_name,
    )

    user = (
        f"Push branch `{branch_name}` and open a pull request for the "
        f"feature described in `{prd_path}`."
    )
    return system, user


DEFAULT_CEO_PERSONA = Persona(
    role="Product CEO",
    expertise="Product strategy, prioritization, user impact analysis",
    perspective="What is the single most impactful feature to build next that advances the project's goals?",
)


def _build_ceo_prompt(
    config: ColonyConfig,
    proposal_filename: str,
) -> tuple[str, str]:
    """Build the system prompt and user prompt for the CEO phase."""
    ceo_template = _load_instruction("ceo.md")
    persona = config.ceo_persona or DEFAULT_CEO_PERSONA

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
        reviews_dir=config.reviews_dir,
        proposals_dir=config.proposals_dir,
    )

    user = (
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

    system, user = _build_ceo_prompt(config, proposal_filename)

    if ui is not None:
        ui.phase_header("CEO", config.budget.per_phase, config.model)
    else:
        _log("=== CEO Phase ===")
    result = run_phase_sync(
        Phase.CEO,
        user,
        cwd=repo_root,
        system_prompt=system,
        model=config.model,
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
) -> Path:
    """Save a review markdown file to the reviews directory."""
    target_dir = repo_root / reviews_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def _save_run_log(repo_root: Path, log: RunLog, *, resumed: bool = False) -> Path:
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
                "last_successful_phase": last_successful_phase,
                "resume_events": resume_events,
                "phases": [
                    {
                        "phase": p.phase.value,
                        "success": p.success,
                        "cost_usd": p.cost_usd,
                        "duration_ms": p.duration_ms,
                        "session_id": p.session_id,
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
) -> RunLog:
    """Execute the full orchestration loop: plan -> implement -> review -> deliver."""

    def _make_ui(prefix: str = "") -> PhaseUI | NullUI | None:
        if quiet:
            return None
        return PhaseUI(verbose=verbose, prefix=prefix)

    is_resume = resume_from is not None

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
        # Record resume event for audit trail
        _save_run_log(repo_root, log, resumed=True)
    else:
        run_id = _build_run_id(prompt)
        log = RunLog(run_id=run_id, prompt=prompt, status=RunStatus.RUNNING)
        skip_phases: set[str] = set()

        slug = slugify(prompt)
        names = planning_names(prompt)
        branch_name = f"{config.branch_prefix}{slug}"

        prd_rel = f"{config.prds_dir}/{names.prd_filename}"
        task_rel = f"{config.tasks_dir}/{names.task_filename}"

    log.branch_name = branch_name
    log.prd_rel = prd_rel
    log.task_rel = task_rel

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
            plan_ui.phase_header("Plan", config.budget.per_phase, config.model, extra)
        else:
            _log("=== Phase 1: Plan ===")
            persona_agents = _build_persona_agents(config.personas) or None
            if persona_agents:
                _log(f"  {len(persona_agents)} persona subagents configured for parallel Q&A")

        system, user = _build_plan_prompt(
            prompt, config, names.prd_filename, names.task_filename
        )
        plan_result = run_phase_sync(
            Phase.PLAN,
            user,
            cwd=repo_root,
            system_prompt=system,
            model=config.model,
            budget_usd=config.budget.per_phase,
            agents=persona_agents,
            ui=plan_ui,
        )
        log.phases.append(plan_result)

        if not plan_result.success:
            log.status = RunStatus.FAILED
            log.mark_finished()
            _save_run_log(repo_root, log)
            if plan_ui is None:
                _log(f"Plan phase failed: {plan_result.error}")
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
            impl_ui.phase_header("Implement", config.budget.per_phase, config.model, branch_name)
        else:
            _log("=== Phase 2: Implement ===")
        system, user = _build_implement_prompt(config, prd_rel, task_rel, branch_name)
        impl_result = run_phase_sync(
            Phase.IMPLEMENT,
            user,
            cwd=repo_root,
            system_prompt=system,
            model=config.model,
            budget_usd=config.budget.per_phase,
            ui=impl_ui,
        )
        log.phases.append(impl_result)

        if not impl_result.success:
            log.status = RunStatus.FAILED
            log.mark_finished()
            _save_run_log(repo_root, log)
            if impl_ui is None:
                _log(f"Implement phase failed: {impl_result.error}")
            return log

    # --- Phase 3: Review/Fix Loop ---
    _touch_heartbeat(repo_root)
    if "review" in skip_phases:
        _log("Skipping review phase (already completed in previous run)")
    elif config.phases.review:
        verdict = run_review_loop(
            repo_root,
            config,
            branch_name,
            log,
            prd_rel=prd_rel,
            task_rel=task_rel,
            base_branch=detect_base_branch(repo_root),
            enable_fix=True,
            verbose=verbose,
            quiet=quiet,
        )

        if verdict == "NO-GO":
            log.status = RunStatus.FAILED
            log.mark_finished()
            _save_run_log(repo_root, log)
            _log("Decision gate: NO-GO. Pipeline stopped before deliver.")
            return log

        if verdict == "UNKNOWN":
            _log("  Warning: could not parse verdict, proceeding with caution")

    # --- Deliver Phase ---
    _touch_heartbeat(repo_root)
    if config.phases.deliver:
        deliver_ui = _make_ui()
        if deliver_ui is not None:
            deliver_ui.phase_header("Deliver", config.budget.per_phase, config.model)
        else:
            phase_num = 5 if config.phases.review else 3
            _log(f"=== Phase {phase_num}: Deliver ===")
        system, user = _build_deliver_prompt(config, prd_rel, branch_name)
        deliver_result = run_phase_sync(
            Phase.DELIVER,
            user,
            cwd=repo_root,
            system_prompt=system,
            model=config.model,
            budget_usd=config.budget.per_phase,
            ui=deliver_ui,
        )
        log.phases.append(deliver_result)

        if not deliver_result.success:
            log.status = RunStatus.FAILED
            log.mark_finished()
            _save_run_log(repo_root, log)
            if deliver_ui is None:
                _log(f"Deliver phase failed: {deliver_result.error}")
            return log

    log.status = RunStatus.COMPLETED
    log.mark_finished()
    _save_run_log(repo_root, log)
    _log(f"Run complete. Total cost: ${log.total_cost_usd:.4f}")
    return log
