from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import click

from colonyos import __version__
from colonyos.config import load_config, runs_dir_path
from colonyos.init import run_init
from colonyos.models import LoopState, RunLog, RunStatus
from colonyos.orchestrator import (
    run as run_orchestrator,
    run_ceo,
    prepare_resume,
)


def _find_repo_root() -> Path:
    """Walk up from cwd to find a .git directory, or use cwd."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            return parent
    return cwd


def _print_run_summary(log: RunLog) -> None:
    """Print a formatted run summary to stdout."""
    click.echo(f"\n{'=' * 60}")
    click.echo(f"Run: {log.run_id}")
    click.echo(f"Status: {log.status.value}")
    click.echo(f"Total cost: ${log.total_cost_usd:.4f}")
    for phase in log.phases:
        status = "ok" if phase.success else "FAILED"
        click.echo(
            f"  {phase.phase.value}: {status} "
            f"(${phase.cost_usd or 0:.4f}, {phase.duration_ms}ms)"
        )
    click.echo(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------

def run_doctor_checks(repo_root: Path) -> list[tuple[str, bool, str]]:
    """Run all prerequisite checks and return a list of (name, passed, fix_hint).

    This is extracted as a reusable function so ``colonyos init`` can call it
    as a pre-check.
    """
    results: list[tuple[str, bool, str]] = []

    # 1. Python >= 3.11
    py_ok = sys.version_info.major >= 3 and sys.version_info.minor >= 11
    results.append((
        "Python ≥ 3.11",
        py_ok,
        f"Current: {sys.version_info.major}.{sys.version_info.minor}. "
        "Install Python 3.11+: https://www.python.org/downloads/"
    ))

    # 2. claude CLI reachable
    try:
        subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        results.append(("Claude Code CLI", True, ""))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        results.append((
            "Claude Code CLI",
            False,
            "Install Claude Code: npm install -g @anthropic-ai/claude-code",
        ))

    # 3. git reachable
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        results.append(("Git", True, ""))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        results.append(("Git", False, "Install Git: https://git-scm.com/downloads"))

    # 4. gh auth status
    try:
        gh = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=10,
        )
        gh_ok = gh.returncode == 0
        results.append((
            "GitHub CLI auth",
            gh_ok,
            "Run: gh auth login (install: https://cli.github.com/)" if not gh_ok else "",
        ))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        results.append((
            "GitHub CLI auth",
            False,
            "Install GitHub CLI: https://cli.github.com/ then run: gh auth login",
        ))

    # 5. Config file (soft check)
    config_path = repo_root / ".colonyos" / "config.yaml"
    if config_path.exists():
        try:
            import yaml
            yaml.safe_load(config_path.read_text(encoding="utf-8"))
            results.append(("ColonyOS config", True, ""))
        except Exception:
            results.append((
                "ColonyOS config",
                False,
                f"Config file at {config_path} is invalid YAML. "
                "Run `colonyos init` to regenerate.",
            ))
    else:
        results.append((
            "ColonyOS config",
            False,
            "No config found. Run `colonyos init` to set up.",
        ))

    return results


@click.group()
@click.version_option(version=__version__, prog_name="colonyos")
def app() -> None:
    """ColonyOS — autonomous agent loop that turns prompts into shipped PRs."""


@app.command()
def doctor() -> None:
    """Check prerequisites and environment health."""
    repo_root = _find_repo_root()
    checks = run_doctor_checks(repo_root)

    all_passed = True
    # Config is a soft check — doesn't cause exit 1 on its own
    hard_check_names = {"Python ≥ 3.11", "Claude Code CLI", "Git", "GitHub CLI auth"}

    for name, passed, hint in checks:
        if passed:
            click.echo(f"  ✓ {name}")
        else:
            click.echo(f"  ✗ {name}")
            if hint:
                click.echo(f"    → {hint}")
            if name in hard_check_names:
                all_passed = False

    if all_passed:
        click.echo("\nAll checks passed! You're ready to go.")
        sys.exit(0)
    else:
        click.echo("\nSome checks failed. Fix the issues above and re-run `colonyos doctor`.")
        sys.exit(1)


@app.command()
@click.option("--personas", is_flag=True, help="Re-run only the persona setup.")
@click.option("--quick", is_flag=True, help="Skip interactive prompts, use defaults.")
@click.option("--name", "project_name", default=None, help="Project name (for --quick).")
@click.option("--description", "project_description", default=None, help="Project description (for --quick).")
@click.option("--stack", "project_stack", default=None, help="Tech stack (for --quick).")
def init(
    personas: bool,
    quick: bool,
    project_name: str | None,
    project_description: str | None,
    project_stack: str | None,
) -> None:
    """Initialize ColonyOS in the current repository."""
    repo_root = _find_repo_root()
    run_init(
        repo_root,
        personas_only=personas,
        quick=quick,
        project_name=project_name,
        project_description=project_description,
        project_stack=project_stack,
    )


@app.command()
@click.argument("prompt", required=False)
@click.option("--plan-only", is_flag=True, help="Stop after PRD + task generation.")
@click.option("--from-prd", type=click.Path(exists=True), help="Skip planning, implement an existing PRD.")
@click.option("--resume", "resume_run_id", default=None, help="Resume a failed run from its last successful phase.")
def run(prompt: str | None, plan_only: bool, from_prd: str | None, resume_run_id: str | None) -> None:
    """Run the autonomous agent loop for a feature prompt."""
    # Mutual exclusivity check
    if resume_run_id:
        if prompt or plan_only or from_prd:
            click.echo(
                "Error: --resume cannot be combined with a prompt, --plan-only, or --from-prd.",
                err=True,
            )
            sys.exit(1)
    elif not prompt and not from_prd:
        click.echo("Error: provide a prompt or --from-prd path.", err=True)
        sys.exit(1)

    repo_root = _find_repo_root()
    config = load_config(repo_root)

    if not config.project:
        click.echo(
            "No ColonyOS config found. Run `colonyos init` first.",
            err=True,
        )
        sys.exit(1)

    if resume_run_id:
        resume_state = prepare_resume(repo_root, resume_run_id)

        log = run_orchestrator(
            resume_state.log.prompt,
            repo_root=repo_root,
            config=config,
            resume_from=resume_state,
        )
    else:
        effective_prompt = prompt or f"Implement the PRD at {from_prd}"

        log = run_orchestrator(
            effective_prompt,
            repo_root=repo_root,
            config=config,
            plan_only=plan_only,
            from_prd=from_prd,
        )

    _print_run_summary(log)

    if log.status == RunStatus.FAILED:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Loop state helpers
# ---------------------------------------------------------------------------

def _save_loop_state(repo_root: Path, state: LoopState) -> Path:
    """Persist loop state to .colonyos/runs/loop_state_{loop_id}.json."""
    runs_dir = runs_dir_path(repo_root)
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"loop_state_{state.loop_id}.json"
    path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    return path


def _load_latest_loop_state(repo_root: Path) -> LoopState | None:
    """Load the most recent loop state file, or None if none exists."""
    runs_dir = runs_dir_path(repo_root)
    if not runs_dir.exists():
        return None
    files = sorted(runs_dir.glob("loop_state_*.json"), reverse=True)
    if not files:
        return None
    data = json.loads(files[0].read_text(encoding="utf-8"))
    return LoopState.from_dict(data)


# ---------------------------------------------------------------------------
# Auto command
# ---------------------------------------------------------------------------

@app.command()
@click.option("--no-confirm", is_flag=True, help="Skip human approval checkpoint.")
@click.option("--propose-only", is_flag=True, help="Generate CEO proposal only, don't run pipeline.")
@click.option("--loop", "loop_count", type=int, default=1, help="Number of autonomous iterations.")
@click.option("--max-hours", type=float, default=None, help="Maximum wall-clock hours for the loop.")
@click.option("--max-budget", type=float, default=None, help="Maximum aggregate USD spend for the loop.")
@click.option("--resume-loop", is_flag=True, help="Resume the most recent interrupted loop.")
def auto(
    no_confirm: bool,
    propose_only: bool,
    loop_count: int,
    max_hours: float | None,
    max_budget: float | None,
    resume_loop: bool,
) -> None:
    """Autonomously decide what to build next and run the pipeline."""
    repo_root = _find_repo_root()
    config = load_config(repo_root)

    if not config.project:
        click.echo(
            "No ColonyOS config found. Run `colonyos init` first.",
            err=True,
        )
        sys.exit(1)

    # Resolve budget/time caps: CLI flags > config > defaults
    effective_max_hours = max_hours if max_hours is not None else config.budget.max_duration_hours
    effective_max_budget = max_budget if max_budget is not None else config.budget.max_total_usd

    # --- Resume loop ---
    start_iteration = 1
    loop_state: LoopState | None = None

    if resume_loop:
        loop_state = _load_latest_loop_state(repo_root)
        if loop_state is None:
            click.echo("No loop state file found to resume.", err=True)
            sys.exit(1)

        start_iteration = loop_state.current_iteration + 1
        loop_count = loop_state.total_iterations
        aggregate_cost = loop_state.aggregate_cost_usd
        loop_id = loop_state.loop_id
        loop_state.status = "running"
        click.echo(
            f"Resuming loop {loop_id} from iteration {start_iteration}/{loop_count} "
            f"(${aggregate_cost:.4f} spent so far)"
        )
    else:
        aggregate_cost = 0.0
        from colonyos.naming import generate_timestamp
        loop_id = f"loop-{generate_timestamp()}"
        loop_state = LoopState(
            loop_id=loop_id,
            total_iterations=loop_count,
        )

    loop_start_time = time.time()
    completed_iterations = 0

    for iteration in range(start_iteration, loop_count + 1):
        # --- Time cap check ---
        elapsed_hours = (time.time() - loop_start_time) / 3600.0
        if elapsed_hours >= effective_max_hours:
            click.echo(
                f"\nTime limit reached ({elapsed_hours:.1f}h / {effective_max_hours:.1f}h). "
                f"Duration cap hit. Stopping autonomous loop."
            )
            loop_state.status = "interrupted"
            _save_loop_state(repo_root, loop_state)
            break

        # --- Budget cap check ---
        if aggregate_cost >= effective_max_budget:
            click.echo(
                f"\nBudget limit reached (${aggregate_cost:.2f} / ${effective_max_budget:.2f}). "
                f"Stopping autonomous loop.",
                err=True,
            )
            loop_state.status = "interrupted"
            _save_loop_state(repo_root, loop_state)
            break

        if loop_count > 1:
            click.echo(f"\n{'=' * 60}")
            click.echo(f"Autonomous iteration {iteration}/{loop_count}")
            click.echo(f"{'=' * 60}")

        if iteration > 1:
            config = load_config(repo_root)

        prompt, ceo_result = run_ceo(repo_root, config)
        aggregate_cost += ceo_result.cost_usd or 0

        if not ceo_result.success:
            click.echo("CEO phase failed.", err=True)
            if ceo_result.error:
                click.echo(f"Error: {ceo_result.error}", err=True)
            # Continue on failure instead of sys.exit(1)
            loop_state.current_iteration = iteration
            loop_state.aggregate_cost_usd = aggregate_cost
            loop_state.failed_run_ids.append(f"ceo-fail-iter-{iteration}")
            _save_loop_state(repo_root, loop_state)
            continue

        click.echo(f"\n{'=' * 60}")
        click.echo("CEO Proposal:")
        click.echo(f"{'=' * 60}")
        click.echo(prompt)
        click.echo(f"{'=' * 60}")

        if propose_only:
            click.echo("\nPropose-only mode: proposal saved, pipeline not triggered.")
            loop_state.current_iteration = iteration
            loop_state.aggregate_cost_usd = aggregate_cost
            _save_loop_state(repo_root, loop_state)
            continue

        if not (no_confirm or config.auto_approve):
            if not click.confirm("\nProceed with this feature?", default=False):
                click.echo("Proposal rejected. Exiting.")
                sys.exit(0)

        if aggregate_cost >= effective_max_budget:
            click.echo(
                f"\nBudget limit reached (${aggregate_cost:.2f} / ${effective_max_budget:.2f}). "
                f"Stopping autonomous loop.",
                err=True,
            )
            loop_state.status = "interrupted"
            _save_loop_state(repo_root, loop_state)
            break

        log = run_orchestrator(
            prompt,
            repo_root=repo_root,
            config=config,
        )
        aggregate_cost += log.total_cost_usd

        log.phases.insert(0, ceo_result)
        log.total_cost_usd = sum(
            p.cost_usd for p in log.phases if p.cost_usd is not None
        )

        _print_run_summary(log)

        # Update loop state
        loop_state.current_iteration = iteration
        loop_state.aggregate_cost_usd = aggregate_cost

        if log.status == RunStatus.FAILED:
            loop_state.failed_run_ids.append(log.run_id)
            _save_loop_state(repo_root, loop_state)
            # Continue to next iteration instead of exiting
            click.echo(f"  Iteration {iteration} failed. Continuing to next iteration...")
            continue

        loop_state.completed_run_ids.append(log.run_id)
        completed_iterations += 1
        _save_loop_state(repo_root, loop_state)

        if aggregate_cost >= effective_max_budget:
            click.echo(
                f"\nBudget limit reached (${aggregate_cost:.2f} / ${effective_max_budget:.2f}). "
                f"Stopping autonomous loop.",
                err=True,
            )
            break

    # Mark loop completed if we finished all iterations
    if loop_state.current_iteration >= loop_count and loop_state.status == "running":
        loop_state.status = "completed"
    _save_loop_state(repo_root, loop_state)

    if loop_count > 1:
        click.echo(
            f"\nCompleted {completed_iterations}/{loop_count} iterations. "
            f"Total spend: ${aggregate_cost:.4f}"
        )


# ---------------------------------------------------------------------------
# Status command
# ---------------------------------------------------------------------------

@app.command()
@click.option("-n", "--limit", default=10, help="Number of recent runs to show.")
def status(limit: int) -> None:
    """Show recent ColonyOS runs and loop summaries."""
    repo_root = _find_repo_root()
    runs_dir = runs_dir_path(repo_root)

    if not runs_dir.exists():
        click.echo("No runs yet. Run `colonyos run \"<feature>\"` to start.")
        return

    # --- Loop state summaries ---
    loop_files = sorted(runs_dir.glob("loop_state_*.json"), reverse=True)
    if loop_files:
        click.echo("=== Loop Summaries ===\n")
        for lf in loop_files[:3]:
            try:
                data = json.loads(lf.read_text(encoding="utf-8"))
                lid = data.get("loop_id", "?")
                cur = data.get("current_iteration", 0)
                total = data.get("total_iterations", 0)
                cost = data.get("aggregate_cost_usd", 0)
                st = data.get("status", "unknown")
                click.echo(
                    f"  Loop {lid}: {cur}/{total} iterations, "
                    f"${cost:.4f} spent, status: {st}"
                )
            except (json.JSONDecodeError, KeyError):
                click.echo(f"  {lf.name}: (corrupted)")

        # Heartbeat staleness check
        heartbeat = runs_dir / "heartbeat"
        if heartbeat.exists():
            import os
            age_seconds = time.time() - os.path.getmtime(heartbeat)
            if age_seconds > 300:  # 5 minutes
                click.echo(
                    f"\n  ⚠ Warning: Heartbeat file is stale "
                    f"({age_seconds / 60:.0f} minutes old). "
                    f"A running loop may be stuck."
                )

        click.echo()

    # --- Individual run logs ---
    log_files = sorted(
        [f for f in runs_dir.glob("*.json") if not f.name.startswith("loop_state_")],
        reverse=True,
    )[:limit]

    if not log_files and not loop_files:
        click.echo("No runs found.")
        return

    if log_files:
        click.echo("=== Recent Runs ===\n")
        for log_file in log_files:
            try:
                data = json.loads(log_file.read_text(encoding="utf-8"))
                status_val = data.get("status", "unknown")
                cost = data.get("total_cost_usd", 0)
                prompt_preview = (data.get("prompt", "")[:60] + "...") if len(data.get("prompt", "")) > 60 else data.get("prompt", "")

                # Check if this failed run is resumable
                resumable_tag = ""
                if (
                    status_val == "failed"
                    and data.get("branch_name")
                    and data.get("prd_rel")
                    and data.get("task_rel")
                    and any(p.get("success") for p in data.get("phases", []))
                ):
                    resumable_tag = " [resumable]"

                click.echo(
                    f"  {data.get('run_id', '?'):40s} "
                    f"{status_val:10s}{resumable_tag} "
                    f"${cost:>7.4f}  "
                    f"{prompt_preview}"
                )
            except (json.JSONDecodeError, KeyError):
                click.echo(f"  {log_file.name}: (corrupted)")
