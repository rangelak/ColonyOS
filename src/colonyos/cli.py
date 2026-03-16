from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from colonyos import __version__
from colonyos.config import load_config, runs_dir_path
from colonyos.init import run_init
from colonyos.models import RunStatus
from colonyos.orchestrator import run as run_orchestrator


def _find_repo_root() -> Path:
    """Walk up from cwd to find a .git directory, or use cwd."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            return parent
    return cwd


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

    if log.status == RunStatus.FAILED:
        sys.exit(1)


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
