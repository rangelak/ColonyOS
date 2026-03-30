"""Daemon command and queue-item pipeline runner."""

from __future__ import annotations

from pathlib import Path

import click

from colonyos.cli._app import app
from colonyos.config import ColonyConfig
from colonyos.models import QueueItem
from colonyos.orchestrator import run as run_orchestrator


def run_pipeline_for_queue_item(
    *,
    item: QueueItem,
    repo_root: Path,
    config: ColonyConfig,
    verbose: bool = False,
) -> float:
    """Execute a single queue item through the orchestration pipeline.

    Returns the total cost (USD) of the run.  Called by the daemon process
    to drive items that were enqueued via Slack, GitHub issues, CEO
    proposals, etc.
    """
    from colonyos.github import fetch_issue, format_issue_as_prompt

    # Build prompt and optional issue metadata
    if item.source_type == "issue":
        issue = fetch_issue(int(item.source_value), repo_root)
        prompt_text = format_issue_as_prompt(issue)
        source_issue: int | None = issue.number
        source_issue_url: str | None = issue.url
    else:
        prompt_text = item.source_value
        source_issue = None
        source_issue_url = None

    log = run_orchestrator(
        prompt_text,
        repo_root=repo_root,
        config=config,
        verbose=verbose,
        quiet=True,
        source_issue=source_issue,
        source_issue_url=source_issue_url,
    )

    return log.total_cost_usd


@app.command()
@click.option("--max-budget", type=float, default=None, help="Daily budget cap in USD (overrides config).")
@click.option("--max-hours", type=float, default=None, help="Maximum wall-clock hours before daemon exits.")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging.")
@click.option("--dry-run", is_flag=True, help="Log what would run without executing pipelines.")
def daemon(max_budget: float | None, max_hours: float | None, verbose: bool, dry_run: bool) -> None:
    """Start the autonomous daemon \u2014 Slack + GitHub + CEO + cleanup in one process."""
    import logging as _logging

    from colonyos.config import load_config
    from colonyos.daemon import Daemon, DaemonError

    if verbose:
        _logging.basicConfig(level=_logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    else:
        _logging.basicConfig(level=_logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    repo_root = Path.cwd()
    config = load_config(repo_root)

    # Validate daemon prerequisites
    if not config.slack.enabled:
        click.echo("Warning: Slack is not enabled in config. Daemon will run without Slack listener.", err=True)

    if config.daemon.allowed_control_user_ids:
        click.echo(f"Control users: {', '.join(config.daemon.allowed_control_user_ids)}")
    else:
        click.echo(
            "Warning: No allowed_control_user_ids configured. "
            "Slack kill switch (pause/resume) will not be available.",
            err=True,
        )

    d = Daemon(
        repo_root=repo_root,
        config=config,
        max_budget=max_budget,
        max_hours=max_hours,
        dry_run=dry_run,
        verbose=verbose,
    )

    try:
        d.start()
    except DaemonError as exc:
        raise click.ClickException(str(exc))
