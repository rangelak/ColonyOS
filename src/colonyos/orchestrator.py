from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path

from claude_agent_sdk import AgentDefinition

from colonyos.agent import run_phase_sync
from colonyos.config import ColonyConfig, runs_dir_path
from colonyos.models import Persona, Phase, PhaseResult, RunLog, RunStatus
from colonyos.naming import planning_names, slugify


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
    base = _load_instruction("base.md")
    plan_template = _load_instruction("plan.md")

    system = base.format(
        prds_dir=config.prds_dir,
        tasks_dir=config.tasks_dir,
        branch_prefix=config.branch_prefix,
    ) + "\n\n" + plan_template.format(
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
    base = _load_instruction("base.md")
    impl_template = _load_instruction("implement.md")

    system = base.format(
        prds_dir=config.prds_dir,
        tasks_dir=config.tasks_dir,
        branch_prefix=config.branch_prefix,
    ) + "\n\n" + impl_template.format(
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


def _build_deliver_prompt(
    config: ColonyConfig,
    prd_path: str,
    branch_name: str,
) -> tuple[str, str]:
    base = _load_instruction("base.md")
    deliver_template = _load_instruction("deliver.md")

    system = base.format(
        prds_dir=config.prds_dir,
        tasks_dir=config.tasks_dir,
        branch_prefix=config.branch_prefix,
    ) + "\n\n" + deliver_template.format(
        prd_path=prd_path,
        branch_name=branch_name,
    )

    user = (
        f"Push branch `{branch_name}` and open a pull request for the "
        f"feature described in `{prd_path}`."
    )
    return system, user


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
    """Execute the full orchestration loop: plan -> implement -> deliver."""
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

    # --- Phase 3: Deliver ---
    if config.phases.deliver:
        _log("=== Phase 3: Deliver ===")
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
