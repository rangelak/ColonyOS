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
    validate_branch_exists,
    extract_review_verdict,
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
    """Render the ColonyOS welcome banner (shown when no subcommand is given).

    The command list is generated dynamically from the Click ``app.commands``
    registry so that the banner never drifts from actually registered commands.
    """
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

    # Right column: commands generated from Click registry + flags
    right = Text()
    right.append("Commands\n", style="bold")

    # Dynamically iterate over registered commands
    max_name_len = max((len(name) for name in app.commands), default=0)
    for name in sorted(app.commands):
        cmd = app.commands[name]
        summary = (cmd.get_short_help_str(limit=60) or "").strip()
        padding = " " * (max_name_len - len(name) + 2)
        right.append(f"  {name}", style="green")
        right.append(f"{padding}{summary}\n")
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


REPL_HISTORY_PATH = Path.home() / ".colonyos_history"
REPL_HISTORY_LENGTH = 1000


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="colonyos")
@click.pass_context
def app(ctx: click.Context) -> None:
    """ColonyOS — autonomous agent loop that turns prompts into shipped PRs."""
    if ctx.invoked_subcommand is None:
        _show_welcome()
        if sys.stdin.isatty():
            _run_repl()


def _run_repl() -> None:
    """Interactive REPL loop for running feature prompts.

    When a user types bare ``colonyos`` with no subcommand in an interactive
    terminal, this loop shows a prompt and routes input to the orchestrator.
    """
    try:
        import readline as _readline
    except ImportError:
        _readline = None  # type: ignore[assignment]

    repo_root = _find_repo_root()
    config_path = repo_root / ".colonyos" / "config.yaml"
    if not config_path.exists():
        click.echo('Run `colonyos init` first.')
        return

    config = load_config(repo_root)
    if not config.project:
        click.echo('Run `colonyos init` first.')
        return

    # Set up readline history
    if _readline is not None:
        _readline.set_history_length(REPL_HISTORY_LENGTH)
        history_path = REPL_HISTORY_PATH
        try:
            _readline.read_history_file(str(history_path))
        except (FileNotFoundError, OSError):
            pass

    session_cost = 0.0
    last_interrupt_time = 0.0

    click.echo(click.style(
        'Type a feature to build, or "exit" to quit. Enter to send.',
        dim=True,
    ))

    try:
        while True:
            try:
                prompt_str = click.style(f"[${session_cost:.2f}] > ", fg="green")
                user_input = input(prompt_str)
            except EOFError:
                click.echo()
                break
            except KeyboardInterrupt:
                now = time.time()
                if now - last_interrupt_time < 2.0:
                    click.echo()
                    break
                last_interrupt_time = now
                click.echo(click.style(
                    "\nPress Ctrl+C again to exit",
                    dim=True,
                ))
                continue

            stripped = user_input.strip()
            if not stripped:
                continue
            if stripped.lower() in ("quit", "exit"):
                break

            # Budget confirmation
            per_run_cap = config.budget.per_run
            if not config.auto_approve:
                try:
                    confirm = input(
                        f"Max cost: ${per_run_cap:.2f} (per_run cap). Proceed? [Y/n] "
                    )
                except (EOFError, KeyboardInterrupt):
                    click.echo()
                    break
                if confirm.strip().lower() in ("n", "no"):
                    continue

            try:
                log = run_orchestrator(
                    stripped,
                    repo_root=repo_root,
                    config=config,
                    verbose=True,
                )
                session_cost += log.total_cost_usd
                _print_run_summary(log)
            except KeyboardInterrupt:
                click.echo(click.style(
                    "\nRun interrupted. Returning to prompt.",
                    dim=True,
                ))
                continue
    finally:
        if _readline is not None:
            try:
                _readline.write_history_file(str(REPL_HISTORY_PATH))
            except OSError:
                pass


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
@click.option("--issue", "issue_ref", default=None, help="GitHub issue number or URL to use as the prompt source.")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output alongside tool activity.")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output (no streaming, just phase start/end).")
def run(prompt: str | None, plan_only: bool, from_prd: str | None, resume_run_id: str | None, issue_ref: str | None, verbose: bool, quiet: bool) -> None:
    """Run the autonomous agent loop for a feature prompt."""
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

        log = run_orchestrator(
            effective_prompt,
            repo_root=repo_root,
            config=config,
            plan_only=plan_only,
            from_prd=from_prd,
            verbose=verbose,
            quiet=quiet,
            source_issue=source_issue,
            source_issue_url=source_issue_url,
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
            verdict = extract_review_verdict(text)
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
    ok, err = validate_branch_exists(branch, repo_root)
    if not ok:
        click.echo(f"Error: {err}", err=True)
        sys.exit(1)

    ok, err = validate_branch_exists(base, repo_root)
    if not ok:
        click.echo(f"Error: {err}", err=True)
        sys.exit(1)

    from colonyos.orchestrator import reviewer_personas

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

    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel

    _console = Console()
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

                issue_tag = ""
                si = data.get("source_issue")
                si_url = data.get("source_issue_url")
                if si:
                    issue_tag = f"#{si} {si_url or ''} "

                click.echo(
                    f"  {data.get('run_id', '?'):40s} "
                    f"{status_val:10s}{resumable_tag} "
                    f"${cost:>7.4f}  "
                    f"{issue_tag}"
                    f"{prompt_preview}"
                )
            except (json.JSONDecodeError, KeyError):
                click.echo(f"  {log_file.name}: (corrupted)")

    # --- Slack watch state summaries ---
    watch_files = sorted(runs_dir.glob("watch_state_*.json"), reverse=True)
    if watch_files:
        click.echo("=== Slack Watch Sessions ===\n")
        for wf in watch_files[:3]:
            try:
                data = json.loads(wf.read_text(encoding="utf-8"))
                wid = data.get("watch_id", "?")
                runs_count = data.get("runs_triggered", 0)
                cost = data.get("aggregate_cost_usd", 0)
                click.echo(
                    f"  Watch {wid}: {runs_count} runs triggered, "
                    f"${cost:.4f} spent"
                )
            except (json.JSONDecodeError, KeyError):
                click.echo(f"  {wf.name}: (corrupted)")
        click.echo()

    # --- Learnings ledger ---
    from colonyos.learnings import count_learnings, learnings_path as _learnings_path

    lpath = _learnings_path(repo_root)
    if lpath.exists():
        count = count_learnings(repo_root)
        click.echo(f"\nLearnings ledger: {count} entries")
    else:
        click.echo("\nLearnings ledger: not found")


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


# ---------------------------------------------------------------------------
# Watch command (Slack integration)
# ---------------------------------------------------------------------------


@app.command()
@click.option("--max-hours", type=float, default=None, help="Maximum wall-clock hours for the watcher.")
@click.option("--max-budget", type=float, default=None, help="Maximum aggregate USD spend.")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output alongside tool activity.")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output (no streaming, just phase start/end).")
@click.option("--dry-run", is_flag=True, help="Log triggers without executing pipeline.")
def watch(
    max_hours: float | None,
    max_budget: float | None,
    verbose: bool,
    quiet: bool,
    dry_run: bool,
) -> None:
    """Watch Slack channels and trigger pipeline runs from messages."""
    import signal
    import threading

    repo_root = _find_repo_root()
    config = load_config(repo_root)

    if not config.project:
        click.echo("No ColonyOS config found. Run `colonyos init` first.", err=True)
        sys.exit(1)

    if not config.slack.enabled:
        click.echo(
            "Slack integration is not enabled. "
            "Set `slack.enabled: true` in .colonyos/config.yaml.",
            err=True,
        )
        sys.exit(1)

    if not config.slack.channels:
        click.echo(
            "No Slack channels configured. "
            "Add channels to `slack.channels` in .colonyos/config.yaml.",
            err=True,
        )
        sys.exit(1)

    from colonyos.slack import (
        SlackWatchState,
        check_rate_limit,
        create_slack_app,
        extract_prompt_from_mention,
        format_slack_as_prompt,
        increment_hourly_count,
        post_acknowledgment,
        post_run_summary,
        react_to_message,
        save_watch_state,
        should_process_message,
        start_socket_mode,
        wait_for_approval,
    )

    try:
        bolt_app = create_slack_app(config.slack)
    except (ImportError, RuntimeError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    effective_max_hours = max_hours if max_hours is not None else config.budget.max_duration_hours
    effective_max_budget = max_budget if max_budget is not None else config.budget.max_total_usd

    watch_id = f"watch-{generate_timestamp()}"
    watch_state = SlackWatchState(watch_id=watch_id)

    # Lock guards all watch_state mutations from concurrent event threads.
    state_lock = threading.Lock()
    # Semaphore limits concurrent pipeline runs to 1 to prevent git conflicts.
    pipeline_semaphore = threading.Semaphore(1)
    # Track active pipeline threads for graceful shutdown.
    active_threads: list[threading.Thread] = []

    # Retrieve the bot user ID for mention detection
    try:
        auth_response = bolt_app.client.auth_test()
        bot_user_id = auth_response["user_id"]
    except Exception as exc:
        click.echo(f"Failed to authenticate with Slack: {exc}", err=True)
        sys.exit(1)

    shutdown_event = threading.Event()
    start_time = time.monotonic()

    def _check_budget_exceeded() -> bool:
        """Return True if aggregate spend exceeds the configured budget cap."""
        if effective_max_budget is None:
            return False
        with state_lock:
            return watch_state.aggregate_cost_usd >= effective_max_budget

    def _check_time_exceeded() -> bool:
        """Return True if wall-clock time exceeds the configured max hours."""
        if effective_max_hours is None:
            return False
        elapsed_hours = (time.monotonic() - start_time) / 3600
        return elapsed_hours >= effective_max_hours

    def _handle_event(event: dict, client: object) -> None:
        """Handle app_mention and reaction_added events from Slack."""
        if not should_process_message(event, config.slack, bot_user_id):
            return

        # Enforce time and budget caps
        if _check_time_exceeded():
            logger.warning("Max hours exceeded, ignoring event")
            return
        if _check_budget_exceeded():
            logger.warning("Max budget exceeded, ignoring event")
            return

        channel = event.get("channel", "")
        ts = event.get("ts", "")
        user = event.get("user", "unknown")

        with state_lock:
            if watch_state.is_processed(channel, ts):
                logger.info("Message %s:%s already processed, skipping", channel, ts)
                return

            if not check_rate_limit(watch_state, config.slack):
                logger.warning("Rate limit reached, skipping message %s:%s", channel, ts)
                try:
                    client.chat_postMessage(  # type: ignore[union-attr]
                        channel=channel,
                        thread_ts=ts,
                        text=":warning: Rate limit reached. Try again later.",
                    )
                except Exception:
                    logger.debug("Failed to post rate-limit message", exc_info=True)
                return

            # Mark as processed early (under lock) to prevent TOCTOU races.
            # If the pipeline fails, the message stays marked to prevent
            # retrigger storms; operators can manually retry.
            run_id = f"slack-{generate_timestamp()}"
            watch_state.mark_processed(channel, ts, run_id)
            increment_hourly_count(watch_state)
            watch_state.runs_triggered += 1

        raw_text = event.get("text", "")
        prompt_text = extract_prompt_from_mention(raw_text, bot_user_id)
        if not prompt_text.strip():
            return

        if dry_run:
            click.echo(f"[dry-run] Would trigger pipeline for: {prompt_text[:100]}")
            return

        # Acknowledge
        try:
            react_to_message(client, channel, ts, "eyes")  # type: ignore[arg-type]
        except Exception:
            logger.debug("Failed to add :eyes: reaction", exc_info=True)

        formatted_prompt = format_slack_as_prompt(prompt_text, channel, user)

        # Run pipeline in a background thread so the Bolt handler returns quickly
        def _run_pipeline() -> None:
            # Acquire semaphore to serialize pipeline runs (prevents git conflicts)
            pipeline_semaphore.acquire()
            try:
                # Approval gate: if auto_approve is false, wait for thumbsup
                if not config.slack.auto_approve:
                    try:
                        approval_resp = client.chat_postMessage(  # type: ignore[union-attr]
                            channel=channel,
                            thread_ts=ts,
                            text=":question: Awaiting approval — react with :thumbsup: to proceed.",
                        )
                        approval_ts = approval_resp.get("ts", "")
                        approved = wait_for_approval(
                            client, channel, ts, approval_ts,  # type: ignore[arg-type]
                        )
                        if not approved:
                            try:
                                client.chat_postMessage(  # type: ignore[union-attr]
                                    channel=channel,
                                    thread_ts=ts,
                                    text=":no_entry: Approval timed out. Pipeline not executed.",
                                )
                            except Exception:
                                logger.debug("Failed to post approval timeout message", exc_info=True)
                            return
                    except Exception:
                        logger.debug("Failed to post/poll approval message", exc_info=True)
                        return

                # Re-check budget after approval wait
                if _check_budget_exceeded():
                    logger.warning("Budget exceeded after approval wait")
                    return

                post_acknowledgment(client, channel, ts, prompt_text)  # type: ignore[arg-type]

                _touch_heartbeat(repo_root)
                log = run_orchestrator(
                    formatted_prompt,
                    repo_root=repo_root,
                    config=config,
                    verbose=verbose,
                    quiet=quiet,
                )

                with state_lock:
                    watch_state.aggregate_cost_usd += log.total_cost_usd
                    save_watch_state(repo_root, watch_state)

                emoji = "white_check_mark" if log.status.value == "completed" else "x"
                try:
                    react_to_message(client, channel, ts, emoji)  # type: ignore[arg-type]
                except Exception:
                    logger.debug("Failed to add result reaction", exc_info=True)

                post_run_summary(
                    client,  # type: ignore[arg-type]
                    channel,
                    ts,
                    status=log.status.value,
                    total_cost=log.total_cost_usd,
                    branch_name=log.branch_name,
                    pr_url=getattr(log, "pr_url", None),
                )
            except Exception:
                logger.exception("Pipeline run failed for Slack message %s:%s", channel, ts)
                try:
                    react_to_message(client, channel, ts, "x")  # type: ignore[arg-type]
                except Exception:
                    logger.debug("Failed to add :x: reaction after failure", exc_info=True)
                try:
                    client.chat_postMessage(  # type: ignore[union-attr]
                        channel=channel,
                        thread_ts=ts,
                        text=":x: Pipeline failed. Check server logs for details.",
                    )
                except Exception:
                    logger.debug("Failed to post failure message", exc_info=True)
                with state_lock:
                    save_watch_state(repo_root, watch_state)
            finally:
                pipeline_semaphore.release()

        thread = threading.Thread(target=_run_pipeline, daemon=False)
        active_threads.append(thread)
        thread.start()

    # Register event handlers
    bolt_app.event("app_mention")(_handle_event)

    # Register reaction_added handler (FR-3.2) when trigger_mode includes reactions
    if config.slack.trigger_mode in ("reaction", "all"):
        def _handle_reaction(event: dict, client: object) -> None:
            """Handle reaction_added events — re-fetch the original message and process."""
            item = event.get("item", {})
            if item.get("type") != "message":
                return
            channel = item.get("channel", "")
            ts = item.get("ts", "")
            # Re-fetch the original message to get its text
            try:
                result = client.conversations_history(  # type: ignore[union-attr]
                    channel=channel, latest=ts, inclusive=True, limit=1,
                )
                messages = result.get("messages", [])
                if not messages:
                    return
                msg = messages[0]
                # Build a synthetic event dict compatible with _handle_event
                synthetic_event = {
                    "channel": channel,
                    "ts": ts,
                    "user": msg.get("user", "unknown"),
                    "text": msg.get("text", ""),
                }
                _handle_event(synthetic_event, client)
            except Exception:
                logger.debug("Failed to fetch message for reaction event", exc_info=True)

        bolt_app.event("reaction_added")(_handle_reaction)

    # Graceful shutdown
    def _signal_handler(signum: int, frame: object) -> None:
        click.echo("\nShutting down Slack watcher...")
        shutdown_event.set()
        # Wait for active pipeline threads to complete (up to 60s)
        for t in active_threads:
            t.join(timeout=60)
        with state_lock:
            save_watch_state(repo_root, watch_state)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    click.echo(f"ColonyOS Slack watcher started (ID: {watch_id})")
    click.echo(f"Monitoring channels: {', '.join(config.slack.channels)}")
    click.echo(f"Trigger mode: {config.slack.trigger_mode}")
    if effective_max_hours is not None:
        click.echo(f"Max hours: {effective_max_hours}")
    if effective_max_budget is not None:
        click.echo(f"Max budget: ${effective_max_budget:.2f}")
    if dry_run:
        click.echo("DRY RUN MODE — triggers will be logged but not executed")

    save_watch_state(repo_root, watch_state)

    try:
        handler = start_socket_mode(bolt_app)
        # Use start_async so we can check shutdown_event in a loop
        handler.start_async()
        while not shutdown_event.is_set():
            # Check time/budget caps periodically
            if _check_time_exceeded():
                click.echo("Max hours reached. Shutting down watcher.")
                break
            if _check_budget_exceeded():
                click.echo("Max budget reached. Shutting down watcher.")
                break
            shutdown_event.wait(timeout=5.0)
        handler.close()
    except ImportError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\nShutting down Slack watcher...")
    except Exception as exc:
        click.echo(f"Slack watcher error: {exc}", err=True)
        sys.exit(1)
    finally:
        # Wait for active threads and persist state
        for t in active_threads:
            t.join(timeout=30)
        with state_lock:
            save_watch_state(repo_root, watch_state)
