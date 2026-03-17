from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from colonyos import __version__
from colonyos.config import load_config, runs_dir_path
from colonyos.init import run_init
from colonyos.models import RunLog, RunStatus
from colonyos.orchestrator import run as run_orchestrator, run_ceo


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


MAX_LOOP_ITERATIONS = 10


@click.group()
@click.version_option(version=__version__, prog_name="colonyos")
def app() -> None:
    """ColonyOS — autonomous agent loop that turns prompts into shipped PRs."""


@app.command()
@click.option("--personas", is_flag=True, help="Re-run only the persona setup.")
def init(personas: bool) -> None:
    """Initialize ColonyOS in the current repository."""
    repo_root = _find_repo_root()
    run_init(repo_root, personas_only=personas)


@app.command()
@click.argument("prompt", required=False)
@click.option("--plan-only", is_flag=True, help="Stop after PRD + task generation.")
@click.option("--from-prd", type=click.Path(exists=True), help="Skip planning, implement an existing PRD.")
def run(prompt: str | None, plan_only: bool, from_prd: str | None) -> None:
    """Run the autonomous agent loop for a feature prompt."""
    if not prompt and not from_prd:
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


@app.command()
@click.option("--no-confirm", is_flag=True, help="Skip human approval checkpoint.")
@click.option("--propose-only", is_flag=True, help="Generate CEO proposal only, don't run pipeline.")
@click.option("--loop", "loop_count", type=int, default=1, help="Number of autonomous iterations.")
def auto(no_confirm: bool, propose_only: bool, loop_count: int) -> None:
    """Autonomously decide what to build next and run the pipeline."""
    repo_root = _find_repo_root()
    config = load_config(repo_root)

    if not config.project:
        click.echo(
            "No ColonyOS config found. Run `colonyos init` first.",
            err=True,
        )
        sys.exit(1)

    if loop_count > MAX_LOOP_ITERATIONS:
        click.echo(
            f"Error: --loop capped at {MAX_LOOP_ITERATIONS} iterations.",
            err=True,
        )
        sys.exit(1)

    aggregate_cost = 0.0
    budget_limit = config.budget.per_run

    for iteration in range(1, loop_count + 1):
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
            sys.exit(1)

        click.echo(f"\n{'=' * 60}")
        click.echo("CEO Proposal:")
        click.echo(f"{'=' * 60}")
        click.echo(prompt)
        click.echo(f"{'=' * 60}")

        if propose_only:
            click.echo("\nPropose-only mode: proposal saved, pipeline not triggered.")
            continue

        if not no_confirm:
            if not click.confirm("\nProceed with this feature?", default=False):
                click.echo("Proposal rejected. Exiting.")
                sys.exit(0)

        if aggregate_cost >= budget_limit:
            click.echo(
                f"\nBudget limit reached (${aggregate_cost:.2f} / ${budget_limit:.2f}). "
                f"Stopping autonomous loop.",
                err=True,
            )
            sys.exit(1)

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

        if log.status == RunStatus.FAILED:
            sys.exit(1)

        if aggregate_cost >= budget_limit:
            click.echo(
                f"\nBudget limit reached (${aggregate_cost:.2f} / ${budget_limit:.2f}). "
                f"Stopping autonomous loop.",
                err=True,
            )
            break

    if loop_count > 1:
        click.echo(f"\nCompleted {loop_count} iterations. Total spend: ${aggregate_cost:.4f}")


@app.command()
@click.option("-n", "--limit", default=10, help="Number of recent runs to show.")
def status(limit: int) -> None:
    """Show recent ColonyOS runs."""
    repo_root = _find_repo_root()
    runs_dir = runs_dir_path(repo_root)

    if not runs_dir.exists():
        click.echo("No runs yet. Run `colonyos run \"<feature>\"` to start.")
        return

    log_files = sorted(runs_dir.glob("*.json"), reverse=True)[:limit]

    if not log_files:
        click.echo("No runs found.")
        return

    for log_file in log_files:
        try:
            data = json.loads(log_file.read_text(encoding="utf-8"))
            status_val = data.get("status", "unknown")
            cost = data.get("total_cost_usd", 0)
            prompt_preview = (data.get("prompt", "")[:60] + "...") if len(data.get("prompt", "")) > 60 else data.get("prompt", "")
            click.echo(
                f"  {data.get('run_id', '?'):40s} "
                f"{status_val:10s} "
                f"${cost:>7.4f}  "
                f"{prompt_preview}"
            )
        except (json.JSONDecodeError, KeyError):
            click.echo(f"  {log_file.name}: (corrupted)")
