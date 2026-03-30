"""``colonyos review`` command — standalone multi-persona code review."""

from __future__ import annotations

import sys

import click

from colonyos.config import load_config
from colonyos.cli._app import app
from colonyos.cli._helpers import _find_repo_root


@app.command()
@click.argument("branch")
@click.option("--base", default="main", help="Base branch to compare against.")
@click.option("--no-fix", is_flag=True, help="Skip fix loop, review only.")
@click.option("--decide", is_flag=True, help="Run decision gate after reviews.")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output alongside tool activity.")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output (no streaming, just phase start/end).")
def review(branch: str, base: str, no_fix: bool, decide: bool, verbose: bool, quiet: bool) -> None:
    """Run standalone multi-persona code review on a branch."""
    from colonyos.orchestrator import (
        reviewer_personas,
        run_standalone_review,
        validate_branch_exists,
    )

    from colonyos.cli._display import _print_review_summary

    repo_root = _find_repo_root()
    config = load_config(repo_root)

    if not config.project:
        click.echo(
            "No ColonyOS config found. Run `colonyos init` first.",
            err=True,
        )
        sys.exit(1)

    # Validate branches
    ok, err = validate_branch_exists(branch, repo_root)
    if not ok:
        click.echo(f"Error: {err}", err=True)
        sys.exit(1)

    ok, err = validate_branch_exists(base, repo_root)
    if not ok:
        click.echo(f"Error: {err}", err=True)
        sys.exit(1)

    reviewers = reviewer_personas(config)
    if not reviewers:
        click.echo("No reviewer personas configured. Add personas with reviewer=true to config.", err=True)
        sys.exit(1)

    all_approved, phase_results, total_cost, decision_verdict = run_standalone_review(
        branch,
        base,
        repo_root,
        config,
        verbose=verbose,
        quiet=quiet,
        no_fix=no_fix,
        decide=decide,
    )

    _print_review_summary(phase_results, reviewers, total_cost, decision_verdict=decision_verdict)

    if all_approved:
        sys.exit(0)
    else:
        sys.exit(1)
