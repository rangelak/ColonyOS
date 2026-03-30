"""Small standalone commands: doctor, init, stats, show, directions, ui, tui."""

from __future__ import annotations

import os
import sys

import click

from colonyos.cli._app import app
from colonyos.cli._helpers import _find_repo_root
from colonyos.config import load_config, runs_dir_path, save_config
from colonyos.doctor import run_doctor_checks
from colonyos.init import run_ai_init, run_init


@app.command()
def doctor() -> None:
    """Check prerequisites and environment health."""
    repo_root = _find_repo_root()
    checks = run_doctor_checks(repo_root)

    all_passed = True
    # Config is a soft check — doesn't cause exit 1 on its own
    hard_check_names = {"Python \u2265 3.11", "Claude Code CLI", "Git", "GitHub CLI auth"}

    for name, passed, hint in checks:
        if passed:
            click.echo(f"  \u2713 {name}")
        else:
            click.echo(f"  \u2717 {name}")
            if hint:
                click.echo(f"    \u2192 {hint}")
            if name in hard_check_names:
                all_passed = False

    if all_passed:
        click.echo("\nAll checks passed! You're ready to go.")
        sys.exit(0)
    else:
        click.echo("\nSome checks failed. Fix the issues above and re-run `colonyos doctor`.")
        sys.exit(1)


@app.command()
@click.option("--manual", is_flag=True, help="Use the classic interactive wizard instead of AI-assisted setup.")
@click.option("--personas", is_flag=True, help="Re-run only the persona setup.")
@click.option("--quick", is_flag=True, help="Skip interactive prompts, use defaults.")
@click.option("--name", "project_name", default=None, help="Project name (for --quick).")
@click.option("--description", "project_description", default=None, help="Project description (for --quick).")
@click.option("--stack", "project_stack", default=None, help="Tech stack (for --quick).")
def init(
    manual: bool,
    personas: bool,
    quick: bool,
    project_name: str | None,
    project_description: str | None,
    project_stack: str | None,
) -> None:
    """Initialize ColonyOS in the current repository.

    By default, uses AI-assisted setup: Claude reads your repo and proposes
    a configuration for you to confirm.  Use --manual for the classic
    interactive wizard.
    """
    if manual and (quick or personas):
        raise click.UsageError("--manual cannot be combined with --quick or --personas.")

    repo_root = _find_repo_root()

    if quick or personas or manual:
        run_init(
            repo_root,
            personas_only=personas,
            quick=quick,
            project_name=project_name,
            project_description=project_description,
            project_stack=project_stack,
            doctor_check=True,
        )
    else:
        run_ai_init(repo_root, doctor_check=True)


@app.command()
@click.option("-n", "--last", default=None, type=int, help="Limit to the N most recent runs.")
@click.option("--phase", default=None, type=str, help="Drill into a specific phase.")
def stats(last: int | None, phase: str | None) -> None:
    """Show aggregate analytics dashboard across all runs."""
    from colonyos.stats import (
        compute_stats,
        filter_runs,
        load_run_logs,
        render_dashboard,
    )

    repo_root = _find_repo_root()
    runs_dir = runs_dir_path(repo_root)

    runs = load_run_logs(runs_dir)
    runs = filter_runs(runs, last=last, phase=phase)

    if not runs:
        click.echo("No runs found.")
        return

    from rich.console import Console as RichConsole

    console = RichConsole()
    result = compute_stats(runs, phase_filter=phase)
    render_dashboard(console, result)


@app.command()
@click.argument("run_id")
@click.option("--json", "as_json", is_flag=True, help="Output run data as JSON.")
@click.option("--phase", default=None, type=str, help="Show detail for a specific phase.")
def show(run_id: str, as_json: bool, phase: str | None) -> None:
    """Show detailed inspection of a single run."""
    import json as json_mod

    from colonyos.show import (
        compute_show_result,
        load_single_run,
        render_show,
        resolve_run_id,
    )

    repo_root = _find_repo_root()
    runs_dir = runs_dir_path(repo_root)

    try:
        resolved = resolve_run_id(runs_dir, run_id)
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)
    except ValueError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)

    if isinstance(resolved, list):
        click.echo(f"Ambiguous run ID '{run_id}'. Matches:", err=True)
        for match in resolved:
            click.echo(f"  {match}", err=True)
        raise SystemExit(1)

    try:
        run_data = load_single_run(runs_dir, resolved)
    except (FileNotFoundError, json_mod.JSONDecodeError) as exc:
        click.echo(f"Error loading run: {exc}", err=True)
        raise SystemExit(1)

    if as_json:
        click.echo(json_mod.dumps(run_data, indent=2))
        return

    from rich.console import Console as RichConsole

    console = RichConsole()
    result = compute_show_result(run_data, phase_filter=phase)
    render_show(console, result)


@app.command()
@click.option("--regenerate", is_flag=True, help="Regenerate directions from scratch.")
@click.option("--static", is_flag=True, help="Lock directions so they don't auto-update after CEO iterations.")
@click.option("--auto-update", is_flag=True, help="Unlock directions to auto-update after CEO iterations.")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output.")
def directions(regenerate: bool, static: bool, auto_update: bool, verbose: bool) -> None:
    """View, regenerate, or configure CEO strategic directions.

    \b
    Examples:
      colonyos directions              # view current directions
      colonyos directions --regenerate  # regenerate from scratch
      colonyos directions --static      # keep directions read-only
      colonyos directions --auto-update # let CEO evolve directions each iteration
    """
    from colonyos.directions import (
        directions_path,
        display_directions,
        load_directions,
    )
    from colonyos.init import _collect_strategic_goals, generate_directions

    repo_root = _find_repo_root()
    config = load_config(repo_root)

    from colonyos.ui import console as ui_console

    if not config.project:
        ui_console.print(
            "  [red]\u2717[/red] No ColonyOS config found. Run [green]colonyos init[/green] first.",
            highlight=False,
        )
        sys.exit(1)

    if static and auto_update:
        ui_console.print("  [red]\u2717[/red] Cannot use --static and --auto-update together.", highlight=False)
        sys.exit(1)

    if static:
        config.directions_auto_update = False
        save_config(repo_root, config)
        ui_console.print(
            "  [green]\u2713[/green] Directions [bold]locked[/bold] \u2014 CEO reads but never rewrites.",
            highlight=False,
        )
        return

    if auto_update:
        config.directions_auto_update = True
        save_config(repo_root, config)
        ui_console.print(
            "  [green]\u2713[/green] Directions [bold]unlocked[/bold] \u2014 will evolve after each CEO iteration.",
            highlight=False,
        )
        return

    if regenerate or not directions_path(repo_root).exists():
        goals = _collect_strategic_goals()
        if goals.strip():
            generate_directions(repo_root, config, goals, verbose=verbose)
        else:
            ui_console.print("  [dim]No goals provided. Aborting.[/dim]", highlight=False)
        return

    content = load_directions(repo_root)
    if content.strip():
        mode_label = "[green]auto-update[/green]" if config.directions_auto_update else "[yellow]static[/yellow]"
        display_directions(content, title=f"Strategic Directions  [dim]mode:[/dim] {mode_label}")
    else:
        ui_console.print(
            "  [dim]No directions found. Run[/dim] [green]colonyos directions --regenerate[/green] [dim]to create them.[/dim]",
            highlight=False,
        )


@app.command()
@click.option("--port", default=7400, type=int, help="Port to serve on (default: 7400)")
@click.option("--no-open", is_flag=True, help="Don't auto-open browser")
@click.option("--write", is_flag=True, help="Enable write endpoints (config editing, run launching)")
def ui(port: int, no_open: bool, write: bool) -> None:
    """Launch the local web dashboard (requires colonyos[ui])."""
    if write:
        os.environ["COLONYOS_WRITE_ENABLED"] = "1"
    try:
        import uvicorn  # noqa: F811
    except ImportError:
        click.echo(
            "The web dashboard requires extra dependencies.\n"
            "Install them with:  pip install colonyos[ui]",
            err=True,
        )
        sys.exit(1)

    try:
        from colonyos.server import create_app
    except ImportError as exc:
        click.echo(f"Failed to import server module: {exc}", err=True)
        sys.exit(1)

    repo_root = _find_repo_root()
    fast_app, auth_token = create_app(repo_root)

    url = f"http://127.0.0.1:{port}"
    click.echo(f"[colonyos] Starting dashboard at {url}")
    if os.environ.get("COLONYOS_WRITE_ENABLED"):
        click.echo(f"[colonyos] Write mode ENABLED \u2014 auth token: {auth_token}")

    if not no_open:
        import webbrowser

        webbrowser.open(url)

    try:
        uvicorn.run(fast_app, host="127.0.0.1", port=port, log_level="warning")
    except KeyboardInterrupt:
        click.echo("\n[colonyos] Dashboard stopped.")


@app.command()
@click.argument("prompt", required=False)
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output alongside tool activity.")
def tui(prompt: str | None, verbose: bool) -> None:
    """Launch the interactive terminal UI (Textual TUI).

    Provides a scrollable transcript, multi-line composer, and status bar
    for real-time pipeline interaction. Requires the ``tui`` extra::

        pip install colonyos[tui]
    """
    repo_root = _find_repo_root()
    config = load_config(repo_root)

    if not config.project:
        click.echo(
            "No ColonyOS config found. Run `colonyos init` first.",
            err=True,
        )
        sys.exit(1)

    click.echo(click.style("`colonyos tui` is deprecated; use `colonyos run` instead.", dim=True))
    try:
        from colonyos.cli._tui_launcher import _launch_tui

        _launch_tui(repo_root, config, prompt=prompt, verbose=verbose)
    except ImportError as exc:
        click.echo(
            f"Error: {exc}\n\nInstall the TUI extra: pip install colonyos[tui]",
            err=True,
        )
        sys.exit(1)
