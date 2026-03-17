from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path

from claude_agent_sdk import AgentDefinition

from colonyos.agent import run_phase_sync, run_phases_parallel_sync
from colonyos.config import ColonyConfig, runs_dir_path
from colonyos.models import Persona, Phase, PhaseResult, RunLog, RunStatus
from colonyos.naming import planning_names, proposal_names, slugify


def _log(msg: str) -> None:
    print(f"[colonyos] {msg}", file=sys.stderr, flush=True)


def _build_run_id(prompt: str) -> str:
    digest = sha1(prompt.strip().encode()).hexdigest()[:10]
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"run-{ts}-{digest}"


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
) -> tuple[str, PhaseResult]:
    """Run the CEO phase: analyze the project and propose the next feature.

    Returns a tuple of (proposed_prompt, phase_result).
    """
    names = proposal_names("ceo_proposal")
    proposal_filename = names.proposal_filename

    system, user = _build_ceo_prompt(config, proposal_filename)

    _log("=== CEO Phase ===")
    result = run_phase_sync(
        Phase.CEO,
        user,
        cwd=repo_root,
        system_prompt=system,
        model=config.model,
        budget_usd=config.budget.per_phase,
        allowed_tools=["Read", "Glob", "Grep"],
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


def _save_run_log(repo_root: Path, log: RunLog) -> Path:
    runs = runs_dir_path(repo_root)
    runs.mkdir(parents=True, exist_ok=True)
    log_path = runs / f"{log.run_id}.json"
    log_path.write_text(
        json.dumps(
            {
                "run_id": log.run_id,
                "prompt": log.prompt,
                "status": log.status.value,
                "total_cost_usd": log.total_cost_usd,
                "started_at": log.started_at,
                "finished_at": log.finished_at,
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


def run(
    prompt: str,
    *,
    repo_root: Path,
    config: ColonyConfig,
    plan_only: bool = False,
    from_prd: str | None = None,
) -> RunLog:
    """Execute the full orchestration loop: plan -> implement -> review -> deliver."""
    run_id = _build_run_id(prompt)
    log = RunLog(run_id=run_id, prompt=prompt, status=RunStatus.RUNNING)

    slug = slugify(prompt)
    names = planning_names(prompt)
    branch_name = f"{config.branch_prefix}{slug}"

    prd_rel = f"{config.prds_dir}/{names.prd_filename}"
    task_rel = f"{config.tasks_dir}/{names.task_filename}"

    # --- Phase 1: Plan ---
    if from_prd:
        _log(f"Skipping plan phase, using existing PRD: {from_prd}")
        prd_rel = from_prd
        prd_stem = Path(from_prd).stem
        task_rel = f"{config.tasks_dir}/{prd_stem.replace('_prd_', '_tasks_')}.md"
    else:
        _log("=== Phase 1: Plan ===")
        system, user = _build_plan_prompt(
            prompt, config, names.prd_filename, names.task_filename
        )
        persona_agents = _build_persona_agents(config.personas) or None
        if persona_agents:
            _log(f"  {len(persona_agents)} persona subagents configured for parallel Q&A")
        plan_result = run_phase_sync(
            Phase.PLAN,
            user,
            cwd=repo_root,
            system_prompt=system,
            model=config.model,
            budget_usd=config.budget.per_phase,
            agents=persona_agents,
        )
        log.phases.append(plan_result)

        if not plan_result.success:
            log.status = RunStatus.FAILED
            log.mark_finished()
            _save_run_log(repo_root, log)
            _log(f"Plan phase failed: {plan_result.error}")
            return log

    if plan_only:
        log.status = RunStatus.COMPLETED
        log.mark_finished()
        _save_run_log(repo_root, log)
        _log("Plan-only mode: stopping after plan phase.")
        return log

    # --- Phase 2: Implement ---
    _log("=== Phase 2: Implement ===")
    system, user = _build_implement_prompt(config, prd_rel, task_rel, branch_name)
    impl_result = run_phase_sync(
        Phase.IMPLEMENT,
        user,
        cwd=repo_root,
        system_prompt=system,
        model=config.model,
        budget_usd=config.budget.per_phase,
    )
    log.phases.append(impl_result)

    if not impl_result.success:
        log.status = RunStatus.FAILED
        log.mark_finished()
        _save_run_log(repo_root, log)
        _log(f"Implement phase failed: {impl_result.error}")
        return log

    # --- Phase 3: Review/Fix Loop ---
    if config.phases.review:
        reviewers = _reviewer_personas(config)
        if not reviewers:
            _log("No reviewer personas configured, skipping review phase")
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

                review_calls = []
                for persona in reviewers:
                    sys_prompt, usr_prompt = _build_persona_review_prompt(
                        persona, config, prd_rel, branch_name
                    )
                    review_calls.append(dict(
                        phase=Phase.REVIEW,
                        prompt=usr_prompt,
                        cwd=repo_root,
                        system_prompt=sys_prompt,
                        model=config.model,
                        budget_usd=config.budget.per_phase,
                        allowed_tools=review_tools,
                    ))

                results = run_phases_parallel_sync(review_calls)

                # Save each persona's review artifact
                for persona, result in zip(reviewers, results):
                    p_slug = _persona_slug(persona.role)
                    text = result.artifacts.get("result", "")
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
                    )
                    _log(f"  Running fix agent (iteration {iteration + 1})...")
                    fix_result = run_phase_sync(
                        Phase.FIX,
                        fix_user,
                        cwd=repo_root,
                        system_prompt=fix_system,
                        model=config.model,
                        budget_usd=config.budget.per_phase,
                    )
                    log.phases.append(fix_result)
                    if not fix_result.success:
                        _log(f"  Fix phase failed: {fix_result.error}")
                        break

            # --- Decision Gate ---
            _log("=== Decision Gate ===")
            system, user = _build_decision_prompt(config, prd_rel, branch_name)
            decision_result = run_phase_sync(
                Phase.DECISION,
                user,
                cwd=repo_root,
                system_prompt=system,
                model=config.model,
                budget_usd=config.budget.per_phase,
                allowed_tools=["Read", "Glob", "Grep", "Bash"],
            )
            log.phases.append(decision_result)

            verdict_text = decision_result.artifacts.get("result", "")
            verdict = _extract_verdict(verdict_text)
            _log(f"  Decision: {verdict}")

            _save_review_artifact(
                repo_root,
                config.reviews_dir,
                f"decision_{slugify(prompt)}.md",
                f"# Decision Gate\n\nVerdict: **{verdict}**\n\n{verdict_text}",
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
    if config.phases.deliver:
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
        )
        log.phases.append(deliver_result)

        if not deliver_result.success:
            log.status = RunStatus.FAILED
            log.mark_finished()
            _save_run_log(repo_root, log)
            _log(f"Deliver phase failed: {deliver_result.error}")
            return log

    log.status = RunStatus.COMPLETED
    log.mark_finished()
    _save_run_log(repo_root, log)
    _log(f"Run complete. Total cost: ${log.total_cost_usd:.4f}")
    return log
