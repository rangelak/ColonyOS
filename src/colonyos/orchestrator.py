from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path

from claude_agent_sdk import AgentDefinition

from colonyos.agent import run_phase_sync
from colonyos.config import ColonyConfig, runs_dir_path
from colonyos.models import Persona, Phase, PhaseResult, RunLog, RunStatus
from colonyos.naming import planning_names, review_names, slugify


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


def _build_review_persona_agents(personas: list[Persona]) -> dict[str, AgentDefinition]:
    """Build an AgentDefinition per persona for the review phase (read-only tools)."""
    agents: dict[str, AgentDefinition] = {}
    for p in personas:
        key = _persona_slug(p.role)
        agents[key] = AgentDefinition(
            description=f"{p.role} — {p.expertise} (reviewer)",
            prompt=(
                f"You are {p.role}.\n"
                f"Expertise: {p.expertise}\n"
                f"Perspective: {p.perspective}\n\n"
                "You are reviewing an implementation. Examine the code from your "
                "unique perspective. Provide a structured review with a verdict "
                "(approve or request-changes), specific findings with file paths, "
                "and a synthesis paragraph."
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


def _format_review_personas_block(personas: list[Persona]) -> str:
    """Build a persona listing for the review system prompt."""
    if not personas:
        return (
            "No project personas are defined. Review from the perspectives of: "
            "a senior engineer, a security engineer, and a product lead."
        )

    lines = [
        "The following expert personas are available as subagents for review. "
        "Delegate the review to ALL persona subagents IN PARALLEL (call all Agent "
        "tools at once). Each persona has read-only access to the codebase and "
        "will review from their unique perspective.\n"
    ]
    for p in personas:
        key = _persona_slug(p.role)
        lines.append(f"- **`{key}`**: {p.role} — {p.expertise}")
    lines.append("")
    lines.append(
        "After collecting all persona reviews, consolidate them into a single "
        "review document with sections for each persona."
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


def _build_review_prompt(
    config: ColonyConfig,
    prd_path: str,
    branch_name: str,
    task_description: str,
) -> tuple[str, str]:
    """Build the system prompt and user prompt for the review phase."""
    review_template = _load_instruction("review.md")

    system = _format_base(config) + "\n\n" + review_template.format(
        persona_block=_format_review_personas_block(config.personas),
        prd_path=prd_path,
        branch_name=branch_name,
        task_description=task_description,
    )

    user = (
        f"Review the implementation on branch `{branch_name}` for the task: "
        f"{task_description}\n\nPRD is at `{prd_path}`."
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

    # --- Phase 3: Review ---
    if config.phases.review:
        _log("=== Phase 3: Review ===")

        # Read the task file to extract parent tasks
        task_path = repo_root / task_rel
        parent_tasks: list[str] = []
        if task_path.exists():
            task_content = task_path.read_text(encoding="utf-8")
            parent_tasks = _parse_parent_tasks(task_content)

        if not parent_tasks:
            parent_tasks = ["Full implementation review"]

        r_names = review_names(prompt, task_count=len(parent_tasks))
        review_agents = _build_review_persona_agents(config.personas) or None
        if review_agents:
            _log(f"  {len(review_agents)} persona subagents configured for review")

        # Per-task reviews
        for i, task_desc in enumerate(parent_tasks):
            _log(f"  Reviewing task {i + 1}/{len(parent_tasks)}: {task_desc[:60]}")
            system, user_prompt = _build_review_prompt(
                config, prd_rel, branch_name, task_desc
            )
            review_result = run_phase_sync(
                Phase.REVIEW,
                user_prompt,
                cwd=repo_root,
                system_prompt=system,
                model=config.model,
                budget_usd=config.budget.per_phase,
                agents=review_agents,
            )

            # Save per-task review artifact
            result_text = review_result.artifacts.get("result", "")
            _save_review_artifact(
                repo_root,
                config.reviews_dir,
                r_names.task_review_filenames[i],
                f"# Task Review: {task_desc}\n\n{result_text}",
            )

            if not review_result.success:
                log.phases.append(review_result)
                log.status = RunStatus.FAILED
                log.mark_finished()
                _save_run_log(repo_root, log)
                _log(f"Review phase failed on task {i + 1}: {review_result.error}")
                return log

        # Final holistic review
        _log("  Running final holistic review...")
        system, user_prompt = _build_review_prompt(
            config,
            prd_rel,
            branch_name,
            "Final holistic review: assess the entire implementation against the PRD, "
            "covering cross-cutting concerns (security, performance, architecture, UX).",
        )
        final_review_result = run_phase_sync(
            Phase.REVIEW,
            user_prompt,
            cwd=repo_root,
            system_prompt=system,
            model=config.model,
            budget_usd=config.budget.per_phase,
            agents=review_agents,
        )

        # Save final review artifact
        final_text = final_review_result.artifacts.get("result", "")
        _save_review_artifact(
            repo_root,
            config.reviews_dir,
            r_names.final_review_filename,
            f"# Final Holistic Review\n\n{final_text}",
        )

        log.phases.append(final_review_result)

        if not final_review_result.success:
            log.status = RunStatus.FAILED
            log.mark_finished()
            _save_run_log(repo_root, log)
            _log(f"Review phase failed (holistic): {final_review_result.error}")
            return log

    # --- Phase 4: Deliver ---
    if config.phases.deliver:
        phase_num = 4 if config.phases.review else 3
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
