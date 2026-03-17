from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import click

from colonyos import __version__
from colonyos.config import ColonyConfig, load_config, runs_dir_path
from colonyos.doctor import run_doctor_checks
from colonyos.init import run_init
from colonyos.models import LoopState, LoopStatus, RunLog, RunStatus
from colonyos.naming import generate_timestamp
from colonyos.orchestrator import (
    _touch_heartbeat,
    _validate_branch_exists,
    _extract_review_verdict,
    run as run_orchestrator,
    run_ceo,
    run_standalone_review,
    prepare_resume,
)

logger = logging.getLogger(__name__)


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


def _show_welcome() -> None:
    """Render the ColonyOS welcome banner (shown when no subcommand is given)."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    console = Console()

    repo_root = _find_repo_root()
    config_path = repo_root / ".colonyos" / "config.yaml"
    initialized = config_path.exists()

    model = "unknown"
    if initialized:
        try:
            config = load_config(repo_root)
            model = config.model or "unknown"
        except Exception:
            pass

    home = Path.home()
    try:
        display_path = "~/" + str(repo_root.relative_to(home))
    except ValueError:
        display_path = str(repo_root)

    # Left column: ant icon, branding, context
    left = Text(justify="center")
    left.append("\n")
    left.append("    \u2591\u2592\u2593\u2588\u2588\u2593\u2592\u2591\n", style="yellow")
    left.append("   \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\n", style="yellow")
    left.append("  \u2588\u2588\u25cf\u2588\u2588\u2588\u25cf\u2588\u2588\n", style="yellow")
    left.append("   \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\n", style="yellow")
    left.append("    \u2588\u2588\u2588\u2588\u2588\u2588\n", style="yellow")
    left.append("   \u2588\u2588 \u2588\u2588 \u2588\u2588\n", style="yellow")
    left.append("  \u2588\u2588  \u2588\u2588  \u2588\u2588\n", style="yellow")
    left.append("\n")
    left.append(f"  {model} \u00b7 v{__version__}\n", style="dim")
    left.append(f"  {display_path}\n", style="dim")

    # Right column: commands + flags
    right = Text()
    right.append("Commands\n", style="bold")
    right.append("  init", style="green")
    right.append("      Set up this repo\n")
    right.append("  doctor", style="green")
    right.append("    Check prerequisites\n")
    right.append("  run", style="green")
    right.append("       Run the agent pipeline\n")
    right.append("  auto", style="green")
    right.append("      CEO \u2192 full pipeline\n")
    right.append("  review", style="green")
    right.append("    Standalone code review\n")
    right.append("  status", style="green")
    right.append("    Show recent runs\n")
    right.append("\u2500" * 34 + "\n", style="bright_black")
    right.append("Flags\n", style="bold")
    right.append("  -v, --verbose", style="green")
    right.append("   Stream text\n")
    right.append("  -q, --quiet", style="green")
    right.append("     Minimal output\n")
    right.append("  --version", style="green")
    right.append("       Show version\n")

    if not initialized:
        right.append("\u2500" * 34 + "\n", style="bright_black")
        right.append("  Run ")
        right.append("colonyos init", style="green bold")
        right.append(" to get started\n")

    grid = Table.grid(padding=(0, 2))
    grid.add_column(width=34, justify="center")
    grid.add_column(justify="left", no_wrap=True)
    grid.add_row(left, right)

    console.print()
    console.print(
        Panel(
            grid,
            title=f"[bold]ColonyOS[/bold] [dim]v{__version__}[/dim]",
            title_align="left",
            border_style="bright_black",
            padding=(1, 2),
            expand=True,
        )
    )
    console.print()


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="colonyos")
@click.pass_context
def app(ctx: click.Context) -> None:
    """ColonyOS — autonomous agent loop that turns prompts into shipped PRs."""
    if ctx.invoked_subcommand is None:
        _show_welcome()


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
        doctor_check=True,
    )


@app.command()
@click.argument("prompt", required=False)
@click.option("--plan-only", is_flag=True, help="Stop after PRD + task generation.")
@click.option("--from-prd", type=click.Path(exists=True), help="Skip planning, implement an existing PRD.")
@click.option("--resume", "resume_run_id", default=None, help="Resume a failed run from its last successful phase.")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output alongside tool activity.")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output (no streaming, just phase start/end).")
def run(prompt: str | None, plan_only: bool, from_prd: str | None, resume_run_id: str | None, verbose: bool, quiet: bool) -> None:
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
            verbose=verbose,
            quiet=quiet,
        )
    else:
        effective_prompt = prompt or f"Implement the PRD at {from_prd}"

        log = run_orchestrator(
            effective_prompt,
            repo_root=repo_root,
            config=config,
            plan_only=plan_only,
            from_prd=from_prd,
            verbose=verbose,
            quiet=quiet,
        )

    _print_run_summary(log)

    if log.status == RunStatus.FAILED:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Standalone review command
# ---------------------------------------------------------------------------


def _print_review_summary(
    phase_results: list,
    reviewers: list,
    total_cost: float,
    decision_verdict: str | None = None,
) -> None:
    """Print a formatted review summary table to stdout."""
    from colonyos.models import Phase

    click.echo(f"\n{'=' * 60}")
    click.echo("Review Summary")
    click.echo(f"{'=' * 60}")

    review_results = [r for r in phase_results if r.phase == Phase.REVIEW]
    # Match reviewers to review results (may be multiple rounds)
    num_reviewers = len(reviewers)
    if review_results and num_reviewers:
        # Show the last round of results
        last_round = review_results[-num_reviewers:]
        for persona, result in zip(reviewers, last_round):
            text = result.artifacts.get("result", "")
            verdict = _extract_review_verdict(text)
            # Extract first finding line
            finding = ""
            for line in text.split("\n"):
                stripped = line.strip()
                if stripped.startswith("- [") and "]:" in stripped:
                    finding = stripped[:80]
                    break
            status = "✓ approve" if verdict == "approve" else "✗ request-changes"
            click.echo(f"  {persona.role:30s} {status}")
            if finding:
                click.echo(f"    {finding}")

    click.echo(f"\nTotal cost: ${total_cost:.4f}")

    if decision_verdict:
        click.echo(f"Decision: {decision_verdict}")

    click.echo(f"{'=' * 60}")


@app.command()
@click.argument("branch")
@click.option("--base", default="main", help="Base branch to compare against.")
@click.option("--no-fix", is_flag=True, help="Skip fix loop, review only.")
@click.option("--decide", is_flag=True, help="Run decision gate after reviews.")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output alongside tool activity.")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output (no streaming, just phase start/end).")
def review(branch: str, base: str, no_fix: bool, decide: bool, verbose: bool, quiet: bool) -> None:
    """Run standalone multi-persona code review on a branch."""
    repo_root = _find_repo_root()
    config = load_config(repo_root)

    if not config.project:
        click.echo(
            "No ColonyOS config found. Run `colonyos init` first.",
            err=True,
        )
        sys.exit(1)

    # Validate branches
    ok, err = _validate_branch_exists(branch, repo_root)
    if not ok:
        click.echo(f"Error: {err}", err=True)
        sys.exit(1)

    ok, err = _validate_branch_exists(base, repo_root)
    if not ok:
        click.echo(f"Error: {err}", err=True)
        sys.exit(1)

    from colonyos.orchestrator import _reviewer_personas

    reviewers = _reviewer_personas(config)
    if not reviewers:
        click.echo("No reviewer personas configured. Add personas with reviewer=true to config.", err=True)
        sys.exit(1)

    all_approved, phase_results, total_cost = run_standalone_review(
        branch,
        base,
        repo_root,
        config,
        verbose=verbose,
        quiet=quiet,
        no_fix=no_fix,
        decide=decide,
    )

    _print_review_summary(phase_results, reviewers, total_cost)

    if all_approved:
        sys.exit(0)
    else:
        sys.exit(1)


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


# ---------------------------------------------------------------------------
# Auto command — helper functions
# ---------------------------------------------------------------------------

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
) -> tuple[float, bool]:
    """Execute one iteration of the auto loop.

    Returns (updated_aggregate_cost, completed).
    ``completed`` is True when the iteration finished with a successful
    orchestrator run, False otherwise (CEO failure, propose-only, or
    pipeline failure — all of which allow the loop to continue).
    """
    from colonyos.ui import NullUI, PhaseUI

    _touch_heartbeat(repo_root)

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
        return aggregate_cost, False

    if not (no_confirm or config.auto_approve):
        if not click.confirm("\nProceed with this feature?", default=False):
            click.echo("Proposal rejected. Exiting.")
            sys.exit(0)

    log = run_orchestrator(
        prompt,
        repo_root=repo_root,
        config=config,
        verbose=verbose,
        quiet=quiet,
    )
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
def auto(
    no_confirm: bool,
    propose_only: bool,
    loop_count: int,
    max_hours: float | None,
    max_budget: float | None,
    resume_loop: bool,
    verbose: bool,
    quiet: bool,
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
            click.echo(f"\n{'=' * 60}")
            click.echo(f"Autonomous iteration {iteration}/{loop_count}")
            click.echo(f"{'=' * 60}")

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
            age_seconds = time.time() - heartbeat.stat().st_mtime
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
