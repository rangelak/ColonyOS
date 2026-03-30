"""Sweep command: autonomous codebase quality analysis and fixes."""

from __future__ import annotations

import logging
import sys

import click

from colonyos.cli._app import app
from colonyos.cli._helpers import _find_repo_root

logger = logging.getLogger(__name__)


@app.command()
@click.argument("path", required=False, default=None)
@click.option("--execute", is_flag=True, help="Run the implement\u2192review pipeline on findings (default: dry-run report only).")
@click.option("--plan-only", is_flag=True, help="Generate analysis + task file but stop before implementation.")
@click.option("--max-tasks", type=int, default=None, help="Cap the number of findings (default: from config).")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output.")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output.")
@click.option("--no-tui", is_flag=True, help="Force plain streaming output.")
@click.option("--force", is_flag=True, help="Bypass pre-flight checks.")
def sweep(path: str | None, execute: bool, plan_only: bool, max_tasks: int | None, verbose: bool, quiet: bool, no_tui: bool, force: bool) -> None:
    """Analyze codebase for quality issues and optionally fix them.

    By default, runs in dry-run mode: prints a prioritized findings report.
    Use --execute to feed findings through the implement\u2192review pipeline.
    Use --execute --plan-only to generate the task file without running the pipeline.

    Optionally pass a PATH to scope analysis to a specific file or directory.
    """
    from datetime import datetime, timezone

    from colonyos.config import load_config, runs_dir_path
    from colonyos.models import PreflightError

    repo_root = _find_repo_root()
    config = load_config(repo_root)

    if not config.project:
        click.echo(
            "No ColonyOS config found. Run `colonyos init` first.",
            err=True,
        )
        sys.exit(1)

    # Validate target path if provided
    if path:
        target = repo_root / path
        if not target.exists():
            click.echo(f"Error: path '{path}' does not exist.", err=True)
            sys.exit(1)

    if plan_only and not execute:
        click.echo(
            "Error: --plan-only requires --execute (it stops the execute pipeline after task generation).",
            err=True,
        )
        sys.exit(1)

    try:
        from colonyos.orchestrator import run_sweep as _run_sweep, parse_sweep_findings

        ui = None
        if not quiet:
            from colonyos.ui import PhaseUI

            ui = PhaseUI(verbose=verbose)

        findings_text, phase_result = _run_sweep(
            repo_root,
            config,
            target_path=path,
            max_tasks=max_tasks,
            execute=execute,
            plan_only=plan_only,
            verbose=verbose,
            quiet=quiet,
            force=force,
            ui=ui,
        )

        if not phase_result.success:
            click.echo(f"Sweep analysis failed: {phase_result.error}", err=True)
            sys.exit(1)

        # Print dry-run report
        if not execute or plan_only:
            findings = parse_sweep_findings(findings_text)

            if findings:
                from rich.console import Console
                from rich.table import Table

                con = Console()
                table = Table(
                    title="Sweep Findings",
                    show_header=True,
                    header_style="bold",
                    padding=(0, 2),
                )
                table.add_column("#", justify="right", style="dim")
                table.add_column("Category", style="cyan")
                table.add_column("Impact", justify="center")
                table.add_column("Risk", justify="center")
                table.add_column("Score", justify="center")
                table.add_column("Description")

                for f in findings:
                    score = f["score"]
                    if score >= 16:
                        score_style = "bold red"
                    elif score >= 9:
                        score_style = "yellow"
                    else:
                        score_style = "dim"
                    table.add_row(
                        f["number"],
                        f["category"],
                        str(f["impact"]),
                        str(f["risk"]),
                        f"[{score_style}]{score}[/{score_style}]",
                        f["title"],
                    )

                con.print(table)
                click.echo(f"\n{len(findings)} finding(s) identified.")

                if not execute:
                    click.echo("\nRun with --execute to fix these issues automatically.")
            else:
                click.echo("No actionable findings identified.")

            if phase_result.artifacts.get("task_file"):
                click.echo(f"Task file: {phase_result.artifacts['task_file']}")

        # Print cost
        if phase_result.cost_usd:
            click.echo(f"Analysis cost: ${phase_result.cost_usd:.2f}")

        # Audit log
        try:
            from colonyos.cleanup import write_cleanup_log

            log_data = {
                "mode": "execute" if execute else "dry-run",
                "target_path": path,
                "max_tasks": max_tasks or config.sweep.max_tasks,
                "findings_count": len(parse_sweep_findings(findings_text)),
                "cost_usd": phase_result.cost_usd,
                "plan_only": plan_only,
            }
            write_cleanup_log(runs_dir_path(repo_root), "sweep", log_data)
        except Exception:
            logger.debug("Failed to write sweep audit log", exc_info=True)

    except PreflightError as exc:
        click.echo(f"Preflight error: {exc.format_message()}", err=True)
        sys.exit(1)
