"""``colonyos run`` command — the primary CLI entry point for executing prompts.

Handles prompt validation, intent routing, issue integration, resume support,
and TUI delegation before handing off to the orchestrator.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from colonyos.config import ColonyConfig, load_config
from colonyos.cli._app import app
from colonyos.cli._helpers import (
    _announce_mode_cli,
    _find_repo_root,
    _interactive_stdio,
    _tui_available,
)


def _resolve_latest_prd_path(repo_root: Path, config: ColonyConfig) -> str:
    """Return the latest PRD that also has a matching tasks file."""
    from colonyos.naming import task_filename_from_prd

    prd_dir = repo_root / config.prds_dir
    tasks_dir = repo_root / config.tasks_dir
    if not prd_dir.exists():
        raise click.ClickException(f"No PRD directory found at `{config.prds_dir}`.")
    if not tasks_dir.exists():
        raise click.ClickException(f"No tasks directory found at `{config.tasks_dir}`.")

    candidates = sorted(prd_dir.glob("*_prd_*.md"), reverse=True)
    for prd_path in candidates:
        task_name = task_filename_from_prd(prd_path.name)
        task_path = tasks_dir / task_name
        if task_path.exists():
            return str(Path(config.prds_dir) / prd_path.name)

    raise click.ClickException(
        "No PRD/task pair found. Generate a plan first or use an explicit command."
    )


@app.command()
@click.argument("prompt", required=False)
@click.option("--plan-only", is_flag=True, help="Stop after PRD + task generation.")
@click.option("--from-prd", type=click.Path(exists=True), help="Skip planning, implement an existing PRD.")
@click.option("--resume", "resume_run_id", default=None, help="Resume a failed run from its last successful phase.")
@click.option("--issue", "issue_ref", default=None, help="GitHub issue number or URL to use as the prompt source.")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output alongside tool activity.")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output (no streaming, just phase start/end).")
@click.option("--offline", is_flag=True, help="Skip network calls in pre-flight checks.")
@click.option("--force", is_flag=True, help="Bypass pre-flight checks (for power users).")
@click.option("--no-triage", is_flag=True, help="Skip intent routing and run the full pipeline directly.")
@click.option("--no-tui", is_flag=True, help="Force plain streaming output even in interactive terminals.")
def run(prompt: str | None, plan_only: bool, from_prd: str | None, resume_run_id: str | None, issue_ref: str | None, verbose: bool, quiet: bool, offline: bool, force: bool, no_triage: bool, no_tui: bool = False) -> None:
    """Run the autonomous agent loop for a feature prompt."""
    from colonyos.models import RunStatus
    from colonyos.orchestrator import (
        prepare_resume,
        run as run_orchestrator,
    )

    from colonyos.cli._display import _print_run_summary
    from colonyos.cli._routing import (
        _route_prompt,
        _run_cleanup_loop,
        _run_direct_agent,
        _run_review_only_flow,
    )
    from colonyos.cli._tui_launcher import _launch_tui

    # Mutual exclusivity checks
    if resume_run_id:
        if prompt or plan_only or from_prd or issue_ref:
            click.echo(
                "Error: --resume cannot be combined with a prompt, --plan-only, --from-prd, or --issue.",
                err=True,
            )
            sys.exit(1)

    if issue_ref:
        if from_prd:
            click.echo(
                "Error: --issue cannot be combined with --from-prd.",
                err=True,
            )
            sys.exit(1)

    if not resume_run_id and not issue_ref and not prompt and not from_prd:
        click.echo("Error: provide a prompt, --from-prd path, or --issue.", err=True)
        sys.exit(1)

    repo_root = _find_repo_root()
    config = load_config(repo_root)

    if not config.project:
        click.echo(
            "No ColonyOS config found. Run `colonyos init` first.",
            err=True,
        )
        sys.exit(1)

    use_tui = (
        not no_tui
        and not quiet
        and prompt is not None
        and from_prd is None
        and resume_run_id is None
        and issue_ref is None
        and _interactive_stdio()
        and _tui_available()
    )
    if use_tui:
        _launch_tui(repo_root, config, prompt=prompt, verbose=verbose)
        return

    if resume_run_id:
        resume_state = prepare_resume(repo_root, resume_run_id)

        log = run_orchestrator(
            resume_state.log.prompt,
            repo_root=repo_root,
            config=config,
            resume_from=resume_state,
            verbose=verbose,
            quiet=quiet,
            force=force,
        )
        _print_run_summary(log)
    else:
        source_issue: int | None = None
        source_issue_url: str | None = None

        if issue_ref:
            from colonyos.github import (
                fetch_issue,
                format_issue_as_prompt,
                parse_issue_ref,
            )

            number = parse_issue_ref(issue_ref)
            issue = fetch_issue(number, repo_root)
            source_issue = issue.number
            source_issue_url = issue.url

            issue_prompt = format_issue_as_prompt(issue)
            if prompt:
                effective_prompt = issue_prompt + f"\n\n## Additional Context\n\n{prompt}"
            else:
                effective_prompt = issue_prompt
        else:
            effective_prompt = prompt or f"Implement the PRD at {from_prd}"

        # Intent routing: classify the prompt before running the full pipeline
        # Skip routing when: --no-triage flag, --from-prd, --issue, or router disabled
        should_route = (
            config.router.enabled
            and not no_triage
            and not from_prd
            and not issue_ref
            and prompt  # Only route freeform prompts
        )

        skip_planning = False
        if should_route:
            try:
                route_outcome = _route_prompt(
                    effective_prompt, config, repo_root, source="cli", quiet=quiet,
                )
            except KeyboardInterrupt:
                click.echo(click.style("\nInterrupted.", dim=True))
                return
            _announce_mode_cli(route_outcome.announcement, quiet=quiet)
            if route_outcome.display_text is not None:
                click.echo()
                click.echo(route_outcome.display_text)
                return
            if route_outcome.mode == "direct_agent":
                from colonyos.ui import PhaseUI

                success, _session_id = _run_direct_agent(
                    effective_prompt,
                    repo_root=repo_root,
                    config=config,
                    ui=None if quiet else PhaseUI(verbose=verbose),
                )
                if not success:
                    sys.exit(1)
                return
            if route_outcome.mode == "review_only":
                try:
                    approved = _run_review_only_flow(
                        repo_root=repo_root,
                        config=config,
                        verbose=verbose,
                        quiet=quiet,
                    )
                except click.ClickException as exc:
                    click.echo(f"Error: {exc.format_message()}", err=True)
                    sys.exit(1)
                if not approved:
                    sys.exit(1)
                return
            if route_outcome.mode == "cleanup_loop":
                _run_cleanup_loop()
                return
            if route_outcome.mode == "implement_only":
                try:
                    from_prd = _resolve_latest_prd_path(repo_root, config)
                except click.ClickException as exc:
                    click.echo(f"Error: {exc.format_message()}", err=True)
                    sys.exit(1)
                click.echo(click.style(f"Using latest PRD: {from_prd}", dim=True))
            skip_planning = route_outcome.skip_planning

        log = run_orchestrator(
            effective_prompt,
            repo_root=repo_root,
            config=config,
            plan_only=plan_only,
            skip_planning=skip_planning,
            from_prd=from_prd,
            verbose=verbose,
            quiet=quiet,
            source_issue=source_issue,
            source_issue_url=source_issue_url,
            offline=offline,
            force=force,
        )
        _print_run_summary(log)

    if log.status == RunStatus.FAILED:
        sys.exit(1)
