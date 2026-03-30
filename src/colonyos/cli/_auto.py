"""``colonyos auto`` command — autonomous CEO-driven iteration loop.

Contains the loop state management helpers (_save_loop_state,
_load_latest_loop_state, _compute_elapsed_hours, _init_or_resume_loop),
the git housekeeping helper (_ensure_on_main), the single-iteration runner,
and the ``auto`` Click command itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import click

from colonyos.config import ColonyConfig, load_config, runs_dir_path
from colonyos.models import (
    LoopState,
    LoopStatus,
    PreflightError,
    RunStatus,
)
from colonyos.naming import generate_timestamp

from colonyos.cli._app import app
from colonyos.cli._helpers import _find_repo_root


# ---------------------------------------------------------------------------
# Loop state helpers
# ---------------------------------------------------------------------------


def _save_loop_state(repo_root: Path, state: LoopState) -> Path:
    """Persist loop state atomically to .colonyos/runs/loop_state_{loop_id}.json.

    Writes to a temporary file in the same directory then renames, so a
    crash mid-write cannot leave a truncated checkpoint file.
    """
    runs_dir = runs_dir_path(repo_root)
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"loop_state_{state.loop_id}.json"
    fd, tmp_path_str = tempfile.mkstemp(
        dir=str(runs_dir), suffix=".tmp", prefix="loop_state_",
    )
    fd_closed = False
    try:
        os.write(fd, json.dumps(state.to_dict(), indent=2).encode("utf-8"))
        os.close(fd)
        fd_closed = True
        os.replace(tmp_path_str, str(path))
    except BaseException:
        if not fd_closed:
            try:
                os.close(fd)
            except OSError:
                pass
        Path(tmp_path_str).unlink(missing_ok=True)
        raise
    return path


def _load_latest_loop_state(repo_root: Path) -> LoopState | None:
    """Load the most recent loop state file, or None if none exists.

    Sorts by file modification time rather than relying on filename ordering,
    so the result is correct regardless of naming scheme changes.
    """
    runs_dir = runs_dir_path(repo_root)
    if not runs_dir.exists():
        return None
    files = sorted(
        runs_dir.glob("loop_state_*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return None
    data = json.loads(files[0].read_text(encoding="utf-8"))
    return LoopState.from_dict(data)


def _compute_elapsed_hours(
    loop_state: LoopState,
) -> float:
    """Compute total elapsed hours accounting for prior session time.

    When resuming, uses the original ``start_time_iso`` from the persisted
    state so that the time cap applies to *total* loop duration, not just
    the current session.
    """
    original_start = datetime.fromisoformat(loop_state.start_time_iso)
    now = datetime.now(timezone.utc)
    return (now - original_start).total_seconds() / 3600.0


def _init_or_resume_loop(
    repo_root: Path,
    resume_loop: bool,
    loop_count: int,
) -> tuple[LoopState, int, int, float]:
    """Initialise a new loop or resume an existing one.

    Returns (loop_state, start_iteration, loop_count, aggregate_cost).
    """
    if resume_loop:
        loop_state = _load_latest_loop_state(repo_root)
        if loop_state is None:
            click.echo("No loop state file found to resume.", err=True)
            sys.exit(1)

        start_iteration = loop_state.current_iteration + 1
        loop_count = loop_state.total_iterations
        aggregate_cost = loop_state.aggregate_cost_usd
        loop_state.status = LoopStatus.RUNNING
        click.echo(
            f"Resuming loop {loop_state.loop_id} from iteration "
            f"{start_iteration}/{loop_count} "
            f"(${aggregate_cost:.4f} spent so far)"
        )
        return loop_state, start_iteration, loop_count, aggregate_cost

    loop_id = f"loop-{generate_timestamp()}"
    loop_state = LoopState(
        loop_id=loop_id,
        total_iterations=loop_count,
    )
    return loop_state, 1, loop_count, 0.0


def _ensure_on_main(repo_root: Path) -> None:
    """Ensure the working tree is on main with latest changes (for auto mode)."""
    try:
        result = subprocess.run(
            ["git", "checkout", "main"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=10,
        )
        if result.returncode != 0:
            raise click.ClickException(
                f"Failed to checkout main (exit code {result.returncode}): "
                f"{result.stderr.strip() or '(no stderr)'}"
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise click.ClickException(f"Failed to checkout main: {exc}")

    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=30,
        )
        if result.returncode != 0:
            click.echo(
                f"Warning: git pull --ff-only failed: {result.stderr.strip()}",
                err=True,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        click.echo(f"Warning: Failed to pull latest main: {exc}", err=True)


def _run_single_iteration(
    *,
    iteration: int,
    repo_root: Path,
    config: ColonyConfig,
    loop_state: LoopState,
    aggregate_cost: float,
    no_confirm: bool,
    propose_only: bool,
    verbose: bool = False,
    quiet: bool = False,
    offline: bool = False,
) -> tuple[float, bool]:
    """Execute one iteration of the auto loop.

    Returns (updated_aggregate_cost, completed).
    ``completed`` is True when the iteration finished with a successful
    orchestrator run, False otherwise (CEO failure, propose-only, or
    pipeline failure -- all of which allow the loop to continue).
    """
    from colonyos.directions import display_directions, load_directions
    from colonyos.orchestrator import (
        _touch_heartbeat,
        run as run_orchestrator,
        run_ceo,
        update_directions_after_ceo,
    )
    from colonyos.ui import NullUI, PhaseUI

    from colonyos.cli._display import _print_run_summary

    _touch_heartbeat(repo_root)
    _ensure_on_main(repo_root)

    if not quiet:
        dirs_content = load_directions(repo_root)
        if dirs_content.strip():
            display_directions(
                dirs_content,
                title=f"Strategic Directions (iter {iteration})",
            )

    ceo_ui: PhaseUI | NullUI | None = None
    if not quiet:
        ceo_ui = PhaseUI(verbose=verbose)

    prompt, ceo_result = run_ceo(repo_root, config, ui=ceo_ui)
    aggregate_cost += ceo_result.cost_usd or 0

    if not ceo_result.success:
        click.echo("CEO phase failed.", err=True)
        if ceo_result.error:
            click.echo(f"Error: {ceo_result.error}", err=True)
        loop_state.current_iteration = iteration
        loop_state.aggregate_cost_usd = aggregate_cost
        loop_state.failed_run_ids.append(f"ceo-fail-iter-{iteration}")
        _save_loop_state(repo_root, loop_state)
        return aggregate_cost, False

    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.theme import Theme

    _md_theme = Theme({
        "markdown.code": "bold cyan",
        "markdown.code_block": "dim",
    })
    _console = Console(theme=_md_theme)
    _console.print()
    _console.print(
        Panel(
            Markdown(prompt),
            title="[bold]CEO Proposal[/bold]",
            title_align="left",
            border_style="bright_black",
            padding=(1, 2),
            expand=True,
        )
    )

    if config.directions_auto_update:
        update_ui: PhaseUI | NullUI | None = None
        if verbose and not quiet:
            update_ui = PhaseUI(verbose=True)
        directions_cost = update_directions_after_ceo(
            repo_root, config, prompt, iteration, ui=update_ui,
        )
        aggregate_cost += directions_cost

    if propose_only:
        click.echo("\nPropose-only mode: proposal saved, pipeline not triggered.")
        loop_state.current_iteration = iteration
        loop_state.aggregate_cost_usd = aggregate_cost
        _save_loop_state(repo_root, loop_state)
        return aggregate_cost, False

    if not (no_confirm or config.auto_approve):
        if not click.confirm("\nProceed with this feature?", default=False):
            click.echo("Proposal rejected. Exiting.")
            sys.exit(0)

    try:
        log = run_orchestrator(
            prompt,
            repo_root=repo_root,
            config=config,
            verbose=verbose,
            quiet=quiet,
            offline=offline,
        )
    except PreflightError as exc:
        # Pre-flight failure in autonomous mode -- mark as failed and continue
        click.echo(f"  Pre-flight failed: {exc.format_message()}", err=True)
        loop_state.current_iteration = iteration
        loop_state.aggregate_cost_usd = aggregate_cost
        loop_state.failed_run_ids.append(f"preflight-fail-iter-{iteration}")
        _save_loop_state(repo_root, loop_state)
        return aggregate_cost, False

    aggregate_cost += log.total_cost_usd

    log.phases.insert(0, ceo_result)
    log.total_cost_usd = sum(
        p.cost_usd for p in log.phases if p.cost_usd is not None
    )

    _print_run_summary(log)

    loop_state.current_iteration = iteration
    loop_state.aggregate_cost_usd = aggregate_cost

    if log.status == RunStatus.FAILED:
        loop_state.failed_run_ids.append(log.run_id)
        _save_loop_state(repo_root, loop_state)
        click.echo(f"  Iteration {iteration} failed. Continuing to next iteration...")
        return aggregate_cost, False

    loop_state.completed_run_ids.append(log.run_id)
    _save_loop_state(repo_root, loop_state)
    return aggregate_cost, True


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
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output alongside tool activity.")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output (no streaming, just phase start/end).")
@click.option("--offline", is_flag=True, help="Skip network calls in pre-flight checks.")
def auto(
    no_confirm: bool,
    propose_only: bool,
    loop_count: int,
    max_hours: float | None,
    max_budget: float | None,
    resume_loop: bool,
    verbose: bool,
    quiet: bool,
    offline: bool,
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

    loop_state, start_iteration, loop_count, aggregate_cost = _init_or_resume_loop(
        repo_root, resume_loop, loop_count,
    )

    completed_iterations = 0

    for iteration in range(start_iteration, loop_count + 1):
        # --- Time cap check (total elapsed across all sessions) ---
        elapsed_hours = _compute_elapsed_hours(loop_state)
        if elapsed_hours >= effective_max_hours:
            click.echo(
                f"\nTime limit reached ({elapsed_hours:.1f}h / {effective_max_hours:.1f}h). "
                f"Duration cap hit. Stopping autonomous loop."
            )
            loop_state.status = LoopStatus.INTERRUPTED
            _save_loop_state(repo_root, loop_state)
            break

        # --- Budget cap check ---
        if aggregate_cost >= effective_max_budget:
            click.echo(
                f"\nBudget limit reached (${aggregate_cost:.2f} / ${effective_max_budget:.2f}). "
                f"Stopping autonomous loop.",
                err=True,
            )
            loop_state.status = LoopStatus.INTERRUPTED
            _save_loop_state(repo_root, loop_state)
            break

        if loop_count > 1:
            from rich.console import Console
            from rich.panel import Panel
            from rich.text import Text

            _iter_console = Console()
            label = Text()
            label.append("  Iteration ", style="dim")
            label.append(f"{iteration}", style="bold bright_cyan")
            label.append(f" / {loop_count}", style="dim")
            _iter_console.print()
            _iter_console.print(
                Panel(
                    label,
                    title="[bold bright_cyan]Autonomous Loop[/bold bright_cyan]",
                    title_align="left",
                    border_style="bright_black",
                    padding=(0, 2),
                    expand=True,
                )
            )

        if iteration > 1:
            config = load_config(repo_root)

        aggregate_cost, completed = _run_single_iteration(
            iteration=iteration,
            repo_root=repo_root,
            config=config,
            loop_state=loop_state,
            aggregate_cost=aggregate_cost,
            no_confirm=no_confirm,
            propose_only=propose_only,
            verbose=verbose,
            quiet=quiet,
            offline=offline,
        )

        if completed:
            completed_iterations += 1

        # --- Post-iteration budget cap check ---
        if aggregate_cost >= effective_max_budget:
            click.echo(
                f"\nBudget limit reached (${aggregate_cost:.2f} / ${effective_max_budget:.2f}). "
                f"Stopping autonomous loop.",
                err=True,
            )
            loop_state.status = LoopStatus.INTERRUPTED
            _save_loop_state(repo_root, loop_state)
            break

    # Mark loop completed if we finished all iterations
    if loop_state.current_iteration >= loop_count and loop_state.status == LoopStatus.RUNNING:
        loop_state.status = LoopStatus.COMPLETED
    _save_loop_state(repo_root, loop_state)

    if loop_count > 1:
        click.echo(
            f"\nCompleted {completed_iterations}/{loop_count} iterations. "
            f"Total spend: ${aggregate_cost:.4f}"
        )
