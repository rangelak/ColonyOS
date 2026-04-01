from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import signal
import io
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager, redirect_stderr, redirect_stdout, suppress
from dataclasses import dataclass, replace as dataclass_replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import click

from colonyos import __version__
from colonyos.cancellation import (
    cancellation_scope,
    install_signal_cancel_handlers,
)
from colonyos.config import ColonyConfig, load_config, save_config, runs_dir_path
from colonyos.doctor import run_doctor_checks
from colonyos.repo_map import generate_repo_map
from colonyos.init import is_git_repo, run_ai_init, run_init
from colonyos.models import (
    BranchRestoreError,
    LoopState,
    LoopStatus,
    PreflightError,
    QueueItem,
    QueueItemStatus,
    QueueState,
    QueueStatus,
    RunLog,
    RunStatus,
    compute_priority,
)
from colonyos.naming import generate_timestamp, slugify
from colonyos.orchestrator import (
    _touch_heartbeat,
    validate_branch_exists,
    extract_review_verdict,
    run as run_orchestrator,
    run_preflight_recovery,
    run_ceo,
    run_standalone_review,
    prepare_resume,
    update_directions_after_ceo,
)
from colonyos.queue_runtime import (
    archive_terminal_queue_items,
    build_similarity_context,
    find_related_history_items,
    notification_targets,
    pending_queue_snapshot,
    reprioritize_queue_item,
    select_next_pending_item,
    sorted_pending_items,
)
from colonyos.runtime_lock import RepoRuntimeGuard, RuntimeBusyError

logger = logging.getLogger(__name__)
_DAEMON_MONITOR_ENV = "COLONYOS_DAEMON_MONITOR"
_ACTIVE_RUNTIME_SESSION_COUNTS: dict[str, int] = {}


@dataclass(frozen=True)
class RouteOutcome:
    """Structured result of mode selection before request execution."""

    mode: str = "plan_implement_loop"
    announcement: str | None = None
    display_text: str | None = None
    skip_planning: bool = False
    from_prd: str | None = None


def _find_repo_root() -> Path:
    """Walk up from cwd to find a .git directory, or use cwd."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            return parent
    return cwd


def _tui_available() -> bool:
    """Return True when the optional TUI dependencies are importable."""
    try:
        import colonyos.tui  # noqa: F401
        import janus  # noqa: F401
        import textual  # noqa: F401
        return True
    except ImportError:
        return False


def _interactive_stdio() -> bool:
    """Return True when both stdin and stdout are interactive terminals."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _print_run_summary(log: RunLog) -> None:
    """Print a formatted run summary to stdout."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    con = Console()

    status_style = "green" if log.status == RunStatus.COMPLETED else "red"
    status_icon = "✓" if log.status == RunStatus.COMPLETED else "✗"

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Phase", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Priority", justify="right")
    table.add_column("Why", style="dim")
    table.add_column("Cost", justify="right")
    table.add_column("Duration", justify="right")

    for phase in log.phases:
        if phase.success:
            st = Text("✓ ok", style="green")
        else:
            st = Text("✗ FAIL", style="red bold")
        cost = f"${phase.cost_usd or 0:.2f}"
        dur_ms = phase.duration_ms or 0
        if dur_ms >= 60_000:
            mins, secs = divmod(dur_ms // 1000, 60)
            dur = f"{mins}m {secs}s"
        else:
            dur = f"{dur_ms // 1000}s"
        table.add_row(phase.phase.value, st, cost, dur)

    header = Text()
    header.append(f" {status_icon} ", style=status_style)
    header.append(log.run_id, style="bold")
    header.append(f"  │  ", style="dim")
    header.append(f"${log.total_cost_usd:.2f}", style="bold cyan")
    header.append(f"  │  ", style="dim")
    header.append(log.status.value, style=f"bold {status_style}")

    con.print()
    con.print(
        Panel(
            table,
            title=header,
            title_align="left",
            border_style="bright_black",
            padding=(1, 2),
            expand=True,
        )
    )


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


def _format_budget_cap(cap: float | None) -> str:
    """Format a daemon budget cap for display."""
    if cap is None:
        return "unlimited"
    return f"${cap:.2f}/day"


@contextmanager
def _repo_runtime_guard(repo_root: Path, mode: str):
    """Acquire the shared repo lock for repo-mutating ColonyOS runtimes."""
    repo_key = str(repo_root.resolve())
    if _ACTIVE_RUNTIME_SESSION_COUNTS.get(repo_key, 0) > 0:
        yield None
        return
    guard = RepoRuntimeGuard(repo_root, mode)
    try:
        guard.acquire()
    except RuntimeBusyError as exc:
        raise click.ClickException(str(exc)) from exc
    try:
        yield guard
    finally:
        guard.release()


@contextmanager
def _mark_repo_runtime_session(repo_root: Path):
    """Mark the current process as already holding the repo runtime lock."""
    repo_key = str(repo_root.resolve())
    _ACTIVE_RUNTIME_SESSION_COUNTS[repo_key] = _ACTIVE_RUNTIME_SESSION_COUNTS.get(repo_key, 0) + 1
    try:
        yield
    finally:
        remaining = _ACTIVE_RUNTIME_SESSION_COUNTS.get(repo_key, 0) - 1
        if remaining > 0:
            _ACTIVE_RUNTIME_SESSION_COUNTS[repo_key] = remaining
        else:
            _ACTIVE_RUNTIME_SESSION_COUNTS.pop(repo_key, None)


@contextmanager
def _repo_runtime_session(repo_root: Path, mode: str):
    """Acquire the shared repo lock for an interactive session."""
    with _repo_runtime_guard(repo_root, mode):
        with _mark_repo_runtime_session(repo_root):
            yield


def _print_daemon_banner(
    *,
    repo_root: Path,
    config: ColonyConfig,
    budget_cap: float | None,
    max_hours: float | None,
    dry_run: bool,
    allow_all_control_users: bool,
) -> None:
    """Render a compact startup banner for daemon mode."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    con = Console()
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold green")
    table.add_column()
    table.add_row("mode", "daemon")
    table.add_row("repo", str(repo_root))
    table.add_row("budget", _format_budget_cap(budget_cap))
    table.add_row("max hours", "unlimited" if max_hours is None else f"{max_hours:.1f}h")
    table.add_row("slack", "enabled" if config.slack.enabled else "disabled")
    table.add_row(
        "control",
        "all Slack users"
        if allow_all_control_users
        else ", ".join(config.daemon.allowed_control_user_ids) or "allowlist empty",
    )
    table.add_row("dry run", "yes" if dry_run else "no")

    title = Text()
    title.append(" ColonyOS Daemon ", style="bold")
    title.append(f"v{__version__}", style="dim")

    con.print()
    con.print(
        Panel(
            table,
            title=title,
            title_align="left",
            border_style="bright_black",
            padding=(1, 2),
            expand=True,
        )
    )
    con.print()


def _parse_duration_label_to_ms(label: str) -> int:
    """Best-effort parse for PhaseUI duration labels like '14s' or '2m 03s'."""
    total_ms = 0
    for value, unit in re.findall(r"(\d+)(ms|s|m|h)", label.lower()):
        amount = int(value)
        if unit == "ms":
            total_ms += amount
        elif unit == "s":
            total_ms += amount * 1000
        elif unit == "m":
            total_ms += amount * 60_000
        elif unit == "h":
            total_ms += amount * 3_600_000
    return total_ms


def _parse_daemon_tui_output_line(text: str) -> object | None:
    """Map daemon subprocess stdout lines back into structured TUI messages."""
    from colonyos.tui.adapter import (
        NoticeMsg,
        PhaseCompleteMsg,
        PhaseErrorMsg,
        PhaseHeaderMsg,
        TextBlockMsg,
        ToolLineMsg,
    )
    from colonyos.tui.monitor_protocol import decode_monitor_event_line
    from colonyos.ui import DEFAULT_TOOL_STYLE, TOOL_STYLE

    structured = decode_monitor_event_line(text)
    if structured is not None:
        return structured

    stripped = text.strip()
    if not stripped:
        return None
    if set(stripped) <= {"─", " "}:
        return None
    if "Phase:" in stripped and "budget" in stripped:
        match = re.search(
            r"Phase:\s*(?P<name>.*?)\s+\$(?P<budget>\d+(?:\.\d+)?)\s+budget\s+·\s+(?P<model>[^·]+?)(?:\s+·\s+(?P<extra>.*?))?(?:\s*─+)?$",
            stripped,
        )
        if match:
            extra = (match.group("extra") or "").strip()
            return PhaseHeaderMsg(
                phase_name=match.group("name").strip(),
                budget=float(match.group("budget")),
                model=match.group("model").strip(),
                extra=extra,
            )
    if stripped.startswith("[colonyos]"):
        return NoticeMsg(text=stripped.removeprefix("[colonyos]").strip())

    tool_match = re.match(
        r"^\s*(?:(?P<prefix>\[[^\]]+\]|R\d+)\s+)?[●•]\s+(?P<name>[A-Za-z][A-Za-z0-9_-]*)(?:\s+(?P<arg>.*))?$",
        text,
    )
    if tool_match:
        prefix = (tool_match.group("prefix") or "").strip()
        tool_name = tool_match.group("name")
        arg = (tool_match.group("arg") or "").strip()
        if prefix:
            tool_name = f"{prefix} {tool_name}"
        return ToolLineMsg(
            tool_name=tool_name,
            arg=arg,
            style=TOOL_STYLE.get(tool_match.group("name"), DEFAULT_TOOL_STYLE),
        )

    complete_match = re.match(
        r"^\s*✓\s+Phase completed\s+\$(?P<cost>\d+(?:\.\d+)?)\s+·\s+(?P<turns>\d+)\s+turns\s+·\s+(?P<duration>.+?)\s*$",
        stripped,
    )
    if complete_match:
        return PhaseCompleteMsg(
            cost=float(complete_match.group("cost")),
            turns=int(complete_match.group("turns")),
            duration_ms=_parse_duration_label_to_ms(complete_match.group("duration")),
        )

    error_match = re.match(r"^\s*✗\s+Phase failed:\s*(?P<error>.+?)\s*$", stripped)
    if error_match:
        return PhaseErrorMsg(error=error_match.group("error"))

    return TextBlockMsg(text=text)


def _queue_item_branch_name_override(
    item: "QueueItem",
    config: "ColonyConfig",
) -> str | None:
    """Build a stable, unique branch override for queue-driven work."""
    if item.source_type != "slack":
        return item.branch_name
    if item.branch_name:
        return item.branch_name
    if not item.raw_prompt:
        return None
    prompt_slug = slugify(item.raw_prompt, max_len=48)
    suffix = hashlib.sha1(item.id.encode("utf-8")).hexdigest()[:10]
    return f"{config.branch_prefix}{prompt_slug}_{suffix}"


REPL_HISTORY_PATH = Path.home() / ".colonyos_history"
REPL_HISTORY_LENGTH = 1000


_DOTENV_ALLOWLIST_PREFIX = "COLONYOS_"


def _load_dotenv() -> None:
    """Load COLONYOS_* vars from .env; ignore everything else.

    Other keys (e.g. ANTHROPIC_API_KEY) are left alone so they don't
    override the Claude CLI's own auth.
    """
    try:
        from dotenv import dotenv_values
    except ImportError:
        return
    repo_root = _find_repo_root()
    env_path = repo_root / ".env"
    if not env_path.is_file():
        return
    for key, value in dotenv_values(env_path).items():
        if key.startswith(_DOTENV_ALLOWLIST_PREFIX) and value is not None:
            os.environ.setdefault(key, value)


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="colonyos")
@click.pass_context
def app(ctx: click.Context) -> None:
    """ColonyOS — autonomous agent loop that turns prompts into shipped PRs."""
    _load_dotenv()
    if ctx.invoked_subcommand is None:
        repo_root = _find_repo_root()
        config = load_config(repo_root)
        if (
            _interactive_stdio()
            and _tui_available()
            and config.project is not None
        ):
            with _repo_runtime_session(repo_root, "interactive-tui"), install_signal_cancel_handlers(
                include_sighup=True,
            ):
                _launch_tui(repo_root, config)
            return
        _show_welcome()
        if sys.stdin.isatty():
            with _repo_runtime_session(repo_root, "interactive-repl"):
                _run_repl()


def _repl_command_names() -> set[str]:
    """Return the set of registered Click command names (including groups)."""
    names: set[str] = set()
    for name, cmd in app.commands.items():
        names.add(name)
        if isinstance(cmd, click.Group):
            for sub in cmd.commands:
                names.add(f"{name} {sub}")
    return names


def _repl_top_level_names() -> set[str]:
    """Return just the top-level command names for first-token matching."""
    return set(app.commands.keys())


def _invoke_cli_command(tokens: list[str]) -> None:
    """Invoke a Click command from REPL tokens, catching exits and errors."""
    try:
        app.main(args=tokens, standalone_mode=False)
    except SystemExit:
        pass
    except click.exceptions.UsageError as exc:
        click.echo(f"Usage error: {exc}", err=True)
    except click.exceptions.Abort:
        click.echo()
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)


def _capture_click_output(callback, *args, **kwargs) -> str:  # noqa: ANN001, ANN002, ANN003
    """Capture stdout/stderr produced by a Click-oriented callback."""
    output, _ = _capture_click_output_and_result(callback, *args, **kwargs)
    return output


def _capture_click_output_and_result(callback, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
    """Capture stdout/stderr and return both the output and callback result."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = callback(*args, **kwargs)
    output = stdout.getvalue().strip()
    error = stderr.getvalue().strip()
    return "\n".join(part for part in (output, error) if part), result


def _dirty_recovery_help() -> str:
    """Return the in-TUI help text for dirty-worktree recovery mode."""
    return (
        "Dirty-worktree recovery is pending.\n"
        "Submit `commit` to let ColonyOS prepare a recovery commit and retry the saved prompt,\n"
        "or submit `cancel` to restore the saved prompt to the composer."
    )


def _current_branch_name(repo_root: Path) -> str:
    """Return the current git branch, or ``main`` on lookup failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return "main"
    branch = result.stdout.strip()
    return branch or "main"


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


def _announce_mode_cli(message: str | None, *, quiet: bool = False) -> None:
    """Print a short mode announcement for non-TUI flows."""
    if message and not quiet:
        click.echo(click.style(message, dim=True))


def _run_direct_agent(
    request: str,
    *,
    repo_root: Path,
    config: ColonyConfig,
    ui: Any | None,
    resume_session_id: str | None = None,
) -> tuple[bool, str | None]:
    """Handle a request directly with a lightweight general coding agent.

    Returns a ``(success, session_id)`` tuple.  The *session_id* can be
    passed back as *resume_session_id* on the next call to continue the
    conversation via the SDK's native session-resume mechanism.
    """
    import re
    from colonyos.agent import run_phase_sync
    from colonyos.models import Phase
    from colonyos.router import build_direct_agent_prompt

    # Defense-in-depth: validate session ID format before passing to the SDK.
    # Session IDs should be alphanumeric with hyphens/underscores only.
    if resume_session_id is not None and not re.fullmatch(
        r"[A-Za-z0-9_-]+", resume_session_id
    ):
        resume_session_id = None
    # Inject memory context if enabled
    memory_block = ""
    if config.memory.enabled:
        try:
            from colonyos.memory import MemoryStore, load_memory_for_injection
            with MemoryStore(repo_root, max_entries=config.memory.max_entries) as mem_store:
                memory_block = load_memory_for_injection(
                    mem_store, "direct_agent", request,
                    max_tokens=config.memory.max_inject_tokens,
                )
        except Exception:
            logger.warning("Failed to load memory for injection, continuing without memory")

    system, user = build_direct_agent_prompt(
        request,
        project_name=config.project.name if config.project else "",
        project_description=config.project.description if config.project else "",
        project_stack=config.project.stack if config.project else "",
        memory_block=memory_block,
    )
    model = config.router.model or config.get_model(Phase.IMPLEMENT)
    budget = config.budget.per_phase

    if ui is not None:
        ui.phase_header("Direct", budget, model)

    result = run_phase_sync(
        Phase.QA,
        user,
        cwd=repo_root,
        system_prompt=system,
        model=model,
        budget_usd=budget,
        ui=ui,
        resume=resume_session_id,
        timeout_seconds=config.budget.phase_timeout_seconds,
    )

    # Graceful fallback: if the run failed and we were resuming a session,
    # retry once without resume to start a fresh conversation.
    if not result.success and resume_session_id is not None:
        result = run_phase_sync(
            Phase.QA,
            user,
            cwd=repo_root,
            system_prompt=system,
            model=model,
            budget_usd=budget,
            ui=ui,
            resume=None,
            timeout_seconds=config.budget.phase_timeout_seconds,
        )

    return (result.success, result.session_id or None)


def _run_review_only_flow(
    *,
    repo_root: Path,
    config: ColonyConfig,
    verbose: bool,
    quiet: bool,
) -> bool:
    """Review the current branch against main without entering the plan loop."""
    from colonyos.orchestrator import reviewer_personas

    branch = _current_branch_name(repo_root)
    base = "main"
    if branch == base:
        raise click.ClickException(
            "Review-only mode expects a feature branch. Switch branches or use `review <branch>`."
        )

    all_approved, phase_results, total_cost, decision_verdict = run_standalone_review(
        branch,
        base,
        repo_root,
        config,
        verbose=verbose,
        quiet=quiet,
        no_fix=True,
        decide=False,
    )
    _print_review_summary(phase_results, reviewer_personas(config), total_cost, decision_verdict=decision_verdict)
    return all_approved


def _run_cleanup_loop() -> None:
    """Run the default cleanup loop inside the current repository."""
    repo_root = _find_repo_root()
    config = load_config(repo_root)
    _run_cleanup_scan_impl(
        repo_root,
        config,
        max_lines=None,
        max_functions=None,
        use_ai=True,
        refactor_file=None,
    )


# Sentinel value returned by _handle_tui_command when the user resets the conversation.
# Used to detect /new without fragile substring matching on user-facing text.
_NEW_CONVERSATION_SIGNAL = "Conversation cleared."
_AUTO_COMMAND_SIGNAL = "__AUTO_COMMAND__"
_SAFE_TUI_COMMANDS = {
    "auto",
    "doctor",
    "help",
    "new",
    "queue",
    "show",
    "stats",
    "status",
}


def _handle_tui_command(text: str, *, config: ColonyConfig) -> tuple[bool, str | None, bool]:
    """Handle REPL-style commands from the Textual TUI.

    Returns ``(handled, output, should_exit)``. When ``handled`` is False,
    the caller should treat the input as a normal feature prompt.
    """
    import shlex

    stripped = text.strip()
    if not stripped:
        return False, None, False

    lowered = stripped.lower()
    if lowered in {"quit", "exit"}:
        return True, "Exiting ColonyOS TUI.", True

    if lowered == "new":
        return True, _NEW_CONVERSATION_SIGNAL, False
    if lowered == "help":
        return True, _capture_click_output(_print_repl_help), False

    if lowered.startswith("help "):
        command_name = stripped.split(None, 1)[1].strip()
        return True, _capture_click_output(_print_repl_help, command_name), False

    try:
        tokens = shlex.split(stripped)
    except ValueError:
        tokens = stripped.split()

    if not tokens or tokens[0] not in _repl_top_level_names():
        return False, None, False

    command_name = tokens[0]
    if command_name in {"run", "tui"}:
        return (
            True,
            "Use the TUI directly: type a feature prompt instead of `run`, and "
            "you are already inside `tui`.",
            False,
        )
    if command_name in {"ui", "watch"}:
        return (
            True,
            f"`{command_name}` is not launched inside the TUI. Run "
            f"`colonyos {command_name}` from a normal shell.",
            False,
        )
    if command_name == "auto":
        if not (config.auto_approve or "--no-confirm" in tokens):
            return (
                True,
                "`auto` inside the TUI needs `--no-confirm` unless `auto_approve` is enabled.",
                False,
            )
        return True, _AUTO_COMMAND_SIGNAL, False
    if command_name not in _SAFE_TUI_COMMANDS:
        return (
            True,
            f"`{command_name}` is not supported inside the TUI. Run "
            f"`colonyos {command_name}` from a normal shell.",
            False,
        )

    output = _capture_click_output(_invoke_cli_command, tokens)
    if not output:
        output = f"`{' '.join(tokens)}` completed."
    return True, output, False


def _print_repl_help(command_name: str | None = None) -> None:
    """Print help for a specific command, or list all commands."""
    from rich.console import Console
    from rich.table import Table

    con = Console()

    if command_name:
        cmd = app.commands.get(command_name)
        if cmd is None:
            click.echo(f"Unknown command: {command_name}")
            return
        try:
            app.main(args=[command_name, "--help"], standalone_mode=False)
        except SystemExit:
            pass
        return

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold green", min_width=16)
    table.add_column(style="dim")

    for name in sorted(app.commands):
        cmd = app.commands[name]
        summary = (cmd.get_short_help_str(limit=60) or "").strip()
        table.add_row(name, summary)

    con.print()
    con.print(table)
    con.print()
    con.print("[dim]Type a command with args, or type a feature description to build it.[/dim]")
    con.print()


def _route_prompt(
    prompt: str,
    config: ColonyConfig,
    repo_root: Path,
    source: str,
    quiet: bool = False,
    continuation_active: bool = False,
) -> RouteOutcome:
    """Choose a TUI/CLI execution mode for the incoming prompt."""
    from colonyos.router import (
        ModeAgentMode,
        choose_tui_mode,
        log_mode_selection,
    )

    if not quiet:
        click.echo(click.style("Choosing the best mode...", dim=True))

    decision = choose_tui_mode(
        prompt,
        repo_root=repo_root,
        project_name=config.project.name if config.project else "",
        project_description=config.project.description if config.project else "",
        project_stack=config.project.stack if config.project else "",
        vision=config.vision,
        source=source,
        continuation_active=continuation_active,
    )

    log_mode_selection(
        repo_root=repo_root,
        prompt=prompt,
        result=decision,
        source=source,
    )

    if decision.confidence < config.router.confidence_threshold:
        if continuation_active:
            return RouteOutcome(
                mode=ModeAgentMode.DIRECT_AGENT.value,
                announcement="Continuing conversation.",
            )
        if not quiet:
            click.echo(click.style(
                f"Low confidence ({decision.confidence:.0%}), entering feature planning mode...",
                dim=True,
            ))
        return RouteOutcome(
            mode=ModeAgentMode.PLAN_IMPLEMENT_LOOP.value,
            announcement="Entering feature planning mode.",
        )

    if decision.mode == ModeAgentMode.DIRECT_AGENT:
        return RouteOutcome(
            mode=decision.mode.value,
            announcement=decision.announcement,
        )

    if decision.mode == ModeAgentMode.IMPLEMENT_ONLY:
        return RouteOutcome(
            mode=decision.mode.value,
            announcement=decision.announcement,
        )

    if decision.mode == ModeAgentMode.REVIEW_ONLY:
        return RouteOutcome(
            mode=decision.mode.value,
            announcement=decision.announcement,
        )

    if decision.mode == ModeAgentMode.CLEANUP_LOOP:
        return RouteOutcome(
            mode=decision.mode.value,
            announcement=decision.announcement,
        )

    if decision.mode == ModeAgentMode.FALLBACK:
        return RouteOutcome(
            mode=decision.mode.value,
            announcement=decision.announcement,
            display_text=(
                "I need a bit more direction before I choose a workflow. "
                "Try asking a concrete coding question or describing the change you want."
            ),
        )

    return RouteOutcome(
        mode=ModeAgentMode.PLAN_IMPLEMENT_LOOP.value,
        announcement=decision.announcement,
        skip_planning=decision.skip_planning,
    )


def _handle_routed_query(
    prompt: str,
    config: ColonyConfig,
    repo_root: Path,
    source: str,
    quiet: bool = False,
) -> str | None:
    """Compatibility wrapper preserving the legacy category-based helper behavior."""
    from colonyos.router import (
        RouterCategory,
        answer_question,
        log_router_decision,
        route_query,
    )

    if not quiet:
        click.echo(click.style("Classifying intent...", dim=True))

    router_result = route_query(
        prompt,
        repo_root=repo_root,
        project_name=config.project.name if config.project else "",
        project_description=config.project.description if config.project else "",
        project_stack=config.project.stack if config.project else "",
        vision=config.vision,
        source=source,
    )
    log_router_decision(
        repo_root=repo_root,
        prompt=prompt,
        result=router_result,
        source=source,
    )

    if router_result.confidence < config.router.confidence_threshold:
        return None
    if router_result.category == RouterCategory.QUESTION:
        return answer_question(
            prompt,
            repo_root=repo_root,
            project_name=config.project.name if config.project else "",
            project_description=config.project.description if config.project else "",
            project_stack=config.project.stack if config.project else "",
            model=config.router.qa_model,
            qa_budget=config.router.qa_budget,
        )
    if router_result.category == RouterCategory.STATUS:
        return router_result.suggested_command or "colonyos status"
    if router_result.category == RouterCategory.OUT_OF_SCOPE:
        return (
            "This request doesn't seem related to coding or this project. "
            "For code changes, describe the feature you want to build."
        )
    return None


def _tui_command_hints() -> list[str]:
    """Return a short set of natural-language examples for the TUI footer."""
    return [
        "what does this do?",
        "change this button to red",
        "continue the last plan",
        "review this branch",
        "cleanup the repo",
        "help",
    ]


def _run_repl() -> None:
    """Interactive REPL that routes both commands and feature prompts.

    When a user types bare ``colonyos`` with no subcommand in an interactive
    terminal, this loop shows a prompt. If the first token matches a
    registered CLI command, it invokes that command. Otherwise the entire
    line is treated as a feature prompt and sent to the orchestrator.
    """
    import shlex

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

    command_names = _repl_top_level_names()

    # --- Readline: history + tab completion ---
    if _readline is not None:
        _readline.set_history_length(REPL_HISTORY_LENGTH)
        try:
            _readline.read_history_file(str(REPL_HISTORY_PATH))
        except (FileNotFoundError, OSError):
            pass

        all_completions = sorted(command_names | {"help", "exit", "quit"})

        def _completer(text: str, state: int) -> str | None:
            buf = _readline.get_line_buffer().lstrip()
            # Only complete the first token
            if " " not in buf:
                matches = [c + " " for c in all_completions if c.startswith(text)]
            else:
                matches = []
            return matches[state] if state < len(matches) else None

        _readline.set_completer(_completer)
        _readline.set_completer_delims(" \t")
        # macOS uses libedit which needs a different parse command
        if "libedit" in (_readline.__doc__ or ""):
            _readline.parse_and_bind("bind ^I rl_complete")
        else:
            _readline.parse_and_bind("tab: complete")

    session_cost = 0.0
    last_direct_session_id: str | None = None

    click.echo(click.style(
        'Type a command, a feature to build, or "help" for available commands.',
        dim=True,
    ))

    try:
        while True:
            try:
                click.echo(click.style(f"[${session_cost:.2f}]", fg="green"), nl=False)
                user_input = input(" > ")
            except EOFError:
                click.echo()
                break
            except KeyboardInterrupt:
                click.echo()
                break

            stripped = user_input.strip()
            if not stripped:
                continue
            if stripped.lower() in ("quit", "exit"):
                break

            # --- /new: clear conversation state ---
            if stripped.lower() in ("new", "/new"):
                last_direct_session_id = None
                click.echo(click.style("Conversation cleared. Next message starts a fresh session.", dim=True))
                continue

            # --- help ---
            if stripped.lower() == "help":
                _print_repl_help()
                continue
            if stripped.lower().startswith("help "):
                _print_repl_help(stripped.split(None, 1)[1].strip())
                continue

            # --- command routing ---
            try:
                tokens = shlex.split(stripped)
            except ValueError:
                tokens = stripped.split()

            if tokens and tokens[0] in command_names:
                try:
                    _invoke_cli_command(tokens)
                except KeyboardInterrupt:
                    click.echo(click.style(
                        "\nCommand interrupted. Returning to prompt.",
                        dim=True,
                    ))
                continue

            # --- intent routing for feature prompts ---
            from_prd: str | None = None
            skip_planning = False
            if config.router.enabled:
                try:
                    route_outcome = _route_prompt(
                        stripped,
                        config,
                        repo_root,
                        source="repl",
                        continuation_active=last_direct_session_id is not None,
                    )
                except KeyboardInterrupt:
                    click.echo(click.style(
                        "\nInterrupted. Returning to prompt.",
                        dim=True,
                    ))
                    continue
                _announce_mode_cli(route_outcome.announcement)
                if route_outcome.display_text is not None:
                    click.echo()
                    click.echo(route_outcome.display_text)
                    continue
                if route_outcome.mode == "direct_agent":
                    from colonyos.ui import PhaseUI

                    if last_direct_session_id is not None:
                        click.echo(click.style("Continuing conversation...", dim=True))
                    with _repo_runtime_guard(repo_root, "direct-agent"), install_signal_cancel_handlers():
                        _success, _session_id = _run_direct_agent(
                            stripped,
                            repo_root=repo_root,
                            config=config,
                            ui=PhaseUI(verbose=True),
                            resume_session_id=last_direct_session_id,
                        )
                    if _success and _session_id:
                        last_direct_session_id = _session_id
                    continue
                # Non-direct-agent mode: clear session state
                last_direct_session_id = None
                if route_outcome.mode == "review_only":
                    try:
                        _run_review_only_flow(
                            repo_root=repo_root,
                            config=config,
                            verbose=True,
                            quiet=False,
                        )
                    except click.ClickException as exc:
                        click.echo(f"Error: {exc.format_message()}", err=True)
                    continue
                if route_outcome.mode == "cleanup_loop":
                    _run_cleanup_loop()
                    continue
                if route_outcome.mode == "implement_only":
                    try:
                        from_prd = _resolve_latest_prd_path(repo_root, config)
                        click.echo(click.style(f"Using latest PRD: {from_prd}", dim=True))
                    except click.ClickException as exc:
                        click.echo(f"Error: {exc.format_message()}", err=True)
                        continue
                skip_planning = route_outcome.skip_planning

            # --- feature prompt (default) ---
            # Running the full pipeline means we're not in direct-agent mode
            last_direct_session_id = None
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
                with _repo_runtime_guard(repo_root, "interactive-repl"), install_signal_cancel_handlers():
                    log = run_orchestrator(
                        stripped,
                        repo_root=repo_root,
                        config=config,
                        skip_planning=skip_planning,
                        from_prd=from_prd,
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
@click.option("--max-tokens", type=int, default=None, help="Override the max token budget for the repo map.")
@click.option("--prompt", "prompt_text", default="", help="Prompt text to demonstrate relevance-based truncation.")
def map(max_tokens: int | None, prompt_text: str) -> None:
    """Generate and display a structural map of the repository.

    Shows file paths, class names, and function signatures — the same
    context that gets injected into agent phase prompts. Useful for
    debugging what the agent sees.
    """
    repo_root = _find_repo_root()
    config = load_config(repo_root)
    repo_map_config = config.repo_map

    if max_tokens is not None:
        # Override the configured max_tokens
        repo_map_config = dataclass_replace(repo_map_config, max_tokens=max_tokens)

    output = generate_repo_map(repo_root, repo_map_config, prompt_text=prompt_text)
    if not output:
        click.echo("No tracked files found or repo map is empty.")
        return
    click.echo(output)


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

    if not is_git_repo(repo_root):
        click.secho(
            "⚠  Warning: Not inside a git repository. "
            "ColonyOS works per-project — please cd into a git repo.",
            fg="yellow",
            err=True,
        )
        if not click.confirm("  Continue anyway?", default=False):
            raise SystemExit(0)

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

    try:
        with _repo_runtime_guard(repo_root, "run"), install_signal_cancel_handlers(
            include_sighup=True,
        ):
            if use_tui:
                with _mark_repo_runtime_session(repo_root):
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
    except KeyboardInterrupt:
        click.echo(click.style("\nInterrupted.", dim=True))
        sys.exit(130)

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
# Queue state helpers
# ---------------------------------------------------------------------------

QUEUE_FILE = "queue.json"


def _save_queue_state(repo_root: Path, state: QueueState) -> Path:
    """Persist queue state atomically to .colonyos/queue.json.

    Writes to a temporary file then renames to avoid truncated files on crash.
    """
    colonyos_dir = repo_root / ".colonyos"
    colonyos_dir.mkdir(parents=True, exist_ok=True)
    archive_terminal_queue_items(repo_root, state)
    path = colonyos_dir / QUEUE_FILE
    fd, tmp_path_str = tempfile.mkstemp(
        dir=str(colonyos_dir), suffix=".tmp", prefix="queue_",
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


def _load_queue_state(repo_root: Path) -> QueueState | None:
    """Load queue state from .colonyos/queue.json, or None if absent."""
    path = repo_root / ".colonyos" / QUEUE_FILE
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return QueueState.from_dict(data)


def _compute_queue_elapsed_hours(state: QueueState) -> float:
    """Compute elapsed hours from the queue's start_time_iso."""
    if not state.start_time_iso:
        return 0.0
    original_start = datetime.fromisoformat(state.start_time_iso)
    now = datetime.now(timezone.utc)
    return (now - original_start).total_seconds() / 3600.0


_NOGO_VERDICT_RE = re.compile(r"VERDICT:\s*NO-GO", re.IGNORECASE)


def _is_nogo_verdict(log: RunLog) -> bool:
    """Check if a run log has a NO-GO decision verdict.

    Uses the same ``VERDICT: NO-GO`` regex pattern as the orchestrator's
    ``_extract_verdict()`` to stay in sync with the decision phase output
    contract.
    """
    for phase in log.phases:
        if phase.phase.value == "decision":
            verdict_text = phase.artifacts.get("result", "")
            if _NOGO_VERDICT_RE.search(verdict_text):
                return True
    return False


def _extract_pr_url_from_log(log: RunLog) -> str | None:
    """Extract PR URL from the deliver phase artifacts."""
    for phase in log.phases:
        if phase.phase.value == "deliver":
            pr_url = phase.artifacts.get("pr_url", "")
            if pr_url:
                return pr_url
    return None


def _print_queue_summary(state: QueueState) -> None:
    """Print a comprehensive summary table after queue execution."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    con = Console()

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("#", style="dim", justify="right")
    table.add_column("Source", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Cost", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("PR", style="dim")

    completed = failed = rejected = 0
    total_cost = 0.0
    total_duration_ms = 0

    for idx, item in enumerate(state.items, 1):
        source = _format_queue_item_source(item)

        status_styles = {
            QueueItemStatus.COMPLETED: ("✓ completed", "green"),
            QueueItemStatus.FAILED: ("✗ failed", "red"),
            QueueItemStatus.REJECTED: ("⊘ rejected", "yellow"),
            QueueItemStatus.PENDING: ("○ pending", "dim"),
            QueueItemStatus.RUNNING: ("◉ running", "blue"),
        }
        status_text, style = status_styles.get(item.status, ("?", "dim"))

        cost = f"${item.cost_usd:.2f}" if item.cost_usd else "-"
        dur_ms = item.duration_ms or 0
        if dur_ms >= 60_000:
            mins, secs = divmod(dur_ms // 1000, 60)
            dur = f"{mins}m {secs}s"
        elif dur_ms > 0:
            dur = f"{dur_ms // 1000}s"
        else:
            dur = "-"

        pr = item.pr_url or "-"

        table.add_row(
            str(idx),
            source,
            Text(status_text, style=style),
            f"P{item.priority}",
            (item.priority_reason or "-")[:40],
            cost,
            dur,
            pr,
        )

        if item.status == QueueItemStatus.COMPLETED:
            completed += 1
        elif item.status == QueueItemStatus.FAILED:
            failed += 1
        elif item.status == QueueItemStatus.REJECTED:
            rejected += 1
        total_cost += item.cost_usd
        total_duration_ms += item.duration_ms

    # Aggregate totals
    total_items = len(state.items)
    if total_duration_ms >= 60_000:
        t_mins, t_secs = divmod(total_duration_ms // 1000, 60)
        total_dur = f"{t_mins}m {t_secs}s"
    elif total_duration_ms > 0:
        total_dur = f"{total_duration_ms // 1000}s"
    else:
        total_dur = "-"

    header = Text()
    header.append(" Queue Summary ", style="bold")
    header.append(f" │ ", style="dim")
    header.append(f"{completed} completed", style="green")
    if failed:
        header.append(f", {failed} failed", style="red")
    if rejected:
        header.append(f", {rejected} rejected", style="yellow")
    pending = total_items - completed - failed - rejected
    if pending:
        header.append(f", {pending} pending", style="dim")
    header.append(f" │ ", style="dim")
    header.append(f"${total_cost:.2f} total", style="bold cyan")

    con.print()
    con.print(
        Panel(
            table,
            title=header,
            title_align="left",
            border_style="bright_black",
            padding=(1, 2),
            expand=True,
        )
    )


def _format_queue_item_source(item: QueueItem, max_len: int = 60) -> str:
    """Format a queue item's source for display."""
    if item.source_type == "issue":
        title = item.issue_title or ""
        return f"#{item.source_value} {title}"[:max_len]
    if item.source_type in ("slack", "slack_fix"):
        channel = item.slack_channel or "?"
        label = "fix" if item.source_type == "slack_fix" else "slack"
        text = item.source_value
        prefix = f"[{label}:{channel}] "
        remaining = max_len - len(prefix)
        if remaining > 0 and len(text) > remaining:
            text = text[: remaining - 3] + "..."
        return f"{prefix}{text}"[:max_len]
    text = item.source_value
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


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
    pipeline failure — all of which allow the loop to continue).
    """
    from colonyos.directions import display_directions, load_directions
    from colonyos.ui import NullUI, PhaseUI

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
        # Pre-flight failure in autonomous mode — mark as failed and continue
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

    try:
        with _repo_runtime_guard(repo_root, "auto"), install_signal_cancel_handlers():
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
    except KeyboardInterrupt:
        click.echo("\nAutonomous loop interrupted.")
        loop_state.status = LoopStatus.INTERRUPTED
        _save_loop_state(repo_root, loop_state)
    except SystemExit as exc:
        if exc.code != 128 + signal.SIGTERM:
            raise
        click.echo("\nAutonomous loop interrupted.")
        loop_state.status = LoopStatus.INTERRUPTED
        _save_loop_state(repo_root, loop_state)
        raise
    finally:
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

    # --- PR Review state summaries (FR-17) ---
    pr_review_files = sorted(runs_dir.glob("pr_review_state_*.json"), reverse=True)
    if pr_review_files:
        click.echo("=== PR Review Sessions ===\n")
        for prf in pr_review_files[:5]:
            try:
                data = json.loads(prf.read_text(encoding="utf-8"))
                pr_num = data.get("pr_number", "?")
                fix_rounds = data.get("fix_rounds", 0)
                cost = data.get("cumulative_cost_usd", 0)
                processed = len(data.get("processed_comment_ids", {}))
                paused = data.get("queue_paused", False)
                status_tag = " [paused]" if paused else ""
                click.echo(
                    f"  PR #{pr_num}: {fix_rounds} fixes applied, "
                    f"{processed} comments processed, "
                    f"${cost:.4f} spent{status_tag}"
                )
            except (json.JSONDecodeError, KeyError):
                click.echo(f"  {prf.name}: (corrupted)")
        click.echo()

    # --- Learnings ledger ---
    from colonyos.learnings import count_learnings, learnings_path as _learnings_path

    lpath = _learnings_path(repo_root)
    if lpath.exists():
        count = count_learnings(repo_root)
        click.echo(f"\nLearnings ledger: {count} entries")
    else:
        click.echo("\nLearnings ledger: not found")

    # --- Queue summary ---
    queue_state = _load_queue_state(repo_root)
    if queue_state and queue_state.items:
        total = len(queue_state.items)
        completed = sum(1 for i in queue_state.items if i.status == QueueItemStatus.COMPLETED)
        failed = sum(1 for i in queue_state.items if i.status == QueueItemStatus.FAILED)
        rejected = sum(1 for i in queue_state.items if i.status == QueueItemStatus.REJECTED)
        running = sum(1 for i in queue_state.items if i.status == QueueItemStatus.RUNNING)
        cost = queue_state.aggregate_cost_usd

        parts = [f"Queue: {completed}/{total} completed"]
        if running:
            parts.append(f"{running} running")
        if failed:
            parts.append(f"{failed} failed")
        if rejected:
            parts.append(f"{rejected} rejected")
        parts.append(f"${cost:.2f} spent")
        click.echo("\n" + ", ".join(parts))


# ---------------------------------------------------------------------------
# Memory command group
# ---------------------------------------------------------------------------


@app.group(invoke_without_command=True)
@click.pass_context
def memory(ctx: click.Context) -> None:
    """Manage the persistent memory store."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


app.add_command(memory)


@memory.command("list")
@click.option("--category", type=click.Choice(["codebase", "failure", "preference", "review_pattern"]), default=None, help="Filter by category.")
@click.option("--limit", "limit_", default=20, show_default=True, help="Max entries to show.")
def memory_list(category: str | None, limit_: int) -> None:
    """List recent memory entries."""
    from rich.console import Console
    from rich.table import Table

    from colonyos.memory import MemoryCategory, MemoryStore

    repo_root = _find_repo_root()
    config = load_config(repo_root)
    if not config.memory.enabled:
        click.echo("Memory is disabled in config (memory.enabled: false).")
        return

    with MemoryStore(repo_root, max_entries=config.memory.max_entries) as store:
        categories = [MemoryCategory(category)] if category else None
        entries = store.query_memories(categories=categories, limit=limit_)

    if not entries:
        click.echo("No memories found.")
        return

    con = Console()
    table = Table(title="Memory Entries", show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("ID", style="dim", justify="right")
    table.add_column("Category", style="cyan")
    table.add_column("Phase")
    table.add_column("Text", max_width=60)
    table.add_column("Created", style="dim")

    for entry in entries:
        text_preview = entry.text[:80] + "..." if len(entry.text) > 80 else entry.text
        table.add_row(
            str(entry.id),
            entry.category.value,
            entry.phase,
            text_preview,
            entry.created_at[:19],
        )

    con.print(table)


@memory.command("search")
@click.argument("query")
@click.option("--limit", "limit_", default=20, show_default=True, help="Max results.")
def memory_search(query: str, limit_: int) -> None:
    """Search memories by keyword."""
    from rich.console import Console
    from rich.table import Table

    from colonyos.memory import MemoryStore

    repo_root = _find_repo_root()
    config = load_config(repo_root)
    if not config.memory.enabled:
        click.echo("Memory is disabled in config (memory.enabled: false).")
        return

    with MemoryStore(repo_root, max_entries=config.memory.max_entries) as store:
        entries = store.query_memories(keyword=query, limit=limit_)

    if not entries:
        click.echo(f"No memories matching '{query}'.")
        return

    con = Console()
    table = Table(title=f"Search: {query}", show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("ID", style="dim", justify="right")
    table.add_column("Category", style="cyan")
    table.add_column("Text", max_width=60)

    for entry in entries:
        text_preview = entry.text[:80] + "..." if len(entry.text) > 80 else entry.text
        table.add_row(str(entry.id), entry.category.value, text_preview)

    con.print(table)


@memory.command("delete")
@click.argument("memory_id", type=int)
def memory_delete(memory_id: int) -> None:
    """Delete a memory entry by ID."""
    from colonyos.memory import MemoryStore

    repo_root = _find_repo_root()
    config = load_config(repo_root)

    with MemoryStore(repo_root, max_entries=config.memory.max_entries) as store:
        deleted = store.delete_memory(memory_id)

    if deleted:
        click.echo(f"Deleted memory #{memory_id}.")
    else:
        click.echo(f"Memory #{memory_id} not found.", err=True)
        raise SystemExit(1)


@memory.command("clear")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def memory_clear(yes: bool) -> None:
    """Delete all memory entries."""
    from colonyos.memory import MemoryStore

    repo_root = _find_repo_root()
    config = load_config(repo_root)

    if not yes:
        if not click.confirm("Delete ALL memory entries?", default=False):
            click.echo("Aborted.")
            return

    with MemoryStore(repo_root, max_entries=config.memory.max_entries) as store:
        count = store.count_memories()
        store.clear_memories()

    click.echo(f"Cleared {count} memory entries.")


@memory.command("stats")
def memory_stats() -> None:
    """Show memory store statistics."""
    from colonyos.memory import MemoryStore

    repo_root = _find_repo_root()
    config = load_config(repo_root)
    if not config.memory.enabled:
        click.echo("Memory is disabled in config (memory.enabled: false).")
        return

    with MemoryStore(repo_root, max_entries=config.memory.max_entries) as store:
        total = store.count_memories()
        by_category = store.count_by_category()

    click.echo(f"Total memories: {total} / {config.memory.max_entries}")
    click.echo(f"Token budget:   {config.memory.max_inject_tokens}")
    if by_category:
        click.echo("\nBy category:")
        for cat, count in sorted(by_category.items(), key=lambda x: x[0].value):
            click.echo(f"  {cat.value}: {count}")
    else:
        click.echo("\nNo memories stored yet.")


# ---------------------------------------------------------------------------
# Outcomes command group
# ---------------------------------------------------------------------------


def _render_outcomes_table(outcomes: list) -> None:
    """Render a Rich table of PR outcome records.

    Accepts a list of sqlite3.Row objects from OutcomeStore.get_outcomes().
    Columns displayed: PR#, Status (colored), Branch, Age, Reviews, CI, Close Context.

    Parameters
    ----------
    outcomes:
        List of sqlite3.Row objects with pr_outcomes schema.
    """
    from datetime import datetime, timezone

    from rich.console import Console
    from rich.table import Table

    con = Console()
    table = Table(
        title="PR Outcomes",
        show_header=True,
        header_style="bold",
        padding=(0, 1),
    )
    table.add_column("PR#", style="dim", justify="right")
    table.add_column("Status")
    table.add_column("Branch", style="cyan", max_width=40)
    table.add_column("Age", justify="right")
    table.add_column("Reviews", justify="right")
    table.add_column("CI")
    table.add_column("Close Context", max_width=50)

    # Status → color mapping
    _status_styles = {
        "merged": "green",
        "closed": "red",
        "open": "yellow",
    }

    now = datetime.now(timezone.utc)
    for row in outcomes:
        status = row["status"]
        status_style = _status_styles.get(status, "")

        # Compute age from created_at
        age_str = ""
        created_at = row["created_at"]
        if created_at:
            try:
                created = datetime.fromisoformat(created_at)
                delta = now - created
                hours = delta.total_seconds() / 3600
                if hours < 1:
                    age_str = f"{int(delta.total_seconds() / 60)}m"
                elif hours < 24:
                    age_str = f"{hours:.1f}h"
                else:
                    age_str = f"{delta.days}d"
            except (ValueError, TypeError):
                pass

        # CI status display
        ci_val = row["ci_passed"]
        if ci_val is None:
            ci_str = "—"
        elif ci_val:
            ci_str = "✓"
        else:
            ci_str = "✗"

        # Close context (truncated)
        close_ctx = row["close_context"] or ""
        if len(close_ctx) > 50:
            close_ctx = close_ctx[:47] + "..."

        table.add_row(
            str(row["pr_number"]),
            f"[{status_style}]{status}[/{status_style}]" if status_style else status,
            row["branch_name"],
            age_str,
            str(row["review_comment_count"] or 0),
            ci_str,
            close_ctx,
        )

    con.print(table)


@app.group(invoke_without_command=True)
@click.pass_context
def outcomes(ctx: click.Context) -> None:
    """View and manage PR outcome tracking."""
    if ctx.invoked_subcommand is not None:
        return

    # Default action: show the outcomes table
    from colonyos.outcomes import OutcomeStore

    repo_root = _find_repo_root()
    with OutcomeStore(repo_root) as store:
        rows = store.get_outcomes()

    if not rows:
        click.echo("No tracked PR outcomes yet. PRs are tracked automatically when created by ColonyOS.")
        return

    _render_outcomes_table(rows)


app.add_command(outcomes)


@outcomes.command("poll")
def outcomes_poll() -> None:
    """Poll GitHub for latest PR statuses, then display the updated table."""
    from colonyos.outcomes import OutcomeStore, poll_outcomes

    repo_root = _find_repo_root()

    # Poll GitHub for updates
    try:
        poll_outcomes(repo_root)
        click.echo("Polled GitHub for PR status updates.")
    except Exception as exc:
        click.echo(f"Warning: polling failed: {exc}", err=True)

    # Display updated table
    with OutcomeStore(repo_root) as store:
        rows = store.get_outcomes()

    if not rows:
        click.echo("No tracked PR outcomes yet.")
        return

    _render_outcomes_table(rows)


# ---------------------------------------------------------------------------
# Queue command group
# ---------------------------------------------------------------------------


@app.group()
def queue():
    """Manage the feature execution queue."""
    pass


@queue.command()
@click.argument("prompts", nargs=-1)
@click.option("--issue", "issue_refs", multiple=True, help="GitHub issue number or URL to enqueue.")
def add(prompts: tuple[str, ...], issue_refs: tuple[str, ...]) -> None:
    """Add items (prompts and/or issue refs) to the execution queue."""
    if not prompts and not issue_refs:
        click.echo("Error: provide at least one prompt or --issue.", err=True)
        raise SystemExit(1)

    repo_root = _find_repo_root()

    state = _load_queue_state(repo_root)
    if state is None:
        state = QueueState(
            queue_id=f"queue-{generate_timestamp()}",
        )

    new_items: list[QueueItem] = []

    # Add free-text prompts
    for prompt_text in prompts:
        item = QueueItem(
            id=str(uuid.uuid4()),
            source_type="prompt",
            source_value=prompt_text,
            raw_prompt=prompt_text,
            summary=prompt_text[:160],
            status=QueueItemStatus.PENDING,
            priority=compute_priority("prompt"),
            priority_reason="base:prompt",
            related_item_ids=[
                related.id
                for related in find_related_history_items(state, prompt_text=prompt_text)
            ],
        )
        reprioritize_queue_item(item)
        new_items.append(item)

    # Add issue references (validate at add-time)
    for ref in issue_refs:
        from colonyos.github import fetch_issue, parse_issue_ref

        number = parse_issue_ref(ref)
        issue = fetch_issue(number, repo_root)

        item = QueueItem(
            id=str(uuid.uuid4()),
            source_type="issue",
            source_value=str(issue.number),
            status=QueueItemStatus.PENDING,
            issue_title=issue.title,
            summary=issue.title,
            priority=compute_priority("issue", issue.labels),
            priority_reason="base:issue",
            related_item_ids=[
                related.id
                for related in find_related_history_items(state, prompt_text=issue.title)
            ],
        )
        reprioritize_queue_item(item)
        new_items.append(item)

    state.items.extend(new_items)
    _save_queue_state(repo_root, state)

    pending_count = sum(1 for i in state.items if i.status == QueueItemStatus.PENDING)
    click.echo(f"Added {len(new_items)} item(s) to queue. Total pending: {pending_count}")


@queue.command("start")
@click.option("--max-cost", type=float, default=None, help="Maximum aggregate USD spend for the queue.")
@click.option("--max-hours", type=float, default=None, help="Maximum wall-clock hours for the queue.")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output.")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output.")
def queue_start(
    max_cost: float | None,
    max_hours: float | None,
    verbose: bool,
    quiet: bool,
) -> None:
    """Process pending queue items sequentially through the pipeline."""
    repo_root = _find_repo_root()
    config = load_config(repo_root)

    if not config.project:
        click.echo("No ColonyOS config found. Run `colonyos init` first.", err=True)
        sys.exit(1)

    state = _load_queue_state(repo_root)
    if state is None:
        click.echo("No queue found. Run `colonyos queue add` first.", err=True)
        sys.exit(1)

    # Recover any items left in RUNNING state from a prior crash/interrupt.
    # A RUNNING item in persisted state always means the prior run was killed.
    recovered = 0
    for item in state.items:
        if item.status == QueueItemStatus.RUNNING:
            item.status = QueueItemStatus.PENDING
            recovered += 1
    if recovered:
        _save_queue_state(repo_root, state)
        click.echo(f"Recovered {recovered} interrupted item(s) back to pending.")

    pending_items = [i for i in state.items if i.status == QueueItemStatus.PENDING]
    if not pending_items:
        click.echo("No pending items in queue.")
        _print_queue_summary(state)
        return

    current_item: QueueItem | None = None

    try:
        with _repo_runtime_guard(repo_root, "queue-start"), install_signal_cancel_handlers():
            effective_max_cost = max_cost if max_cost is not None else config.budget.max_total_usd
            effective_max_hours = max_hours if max_hours is not None else config.budget.max_duration_hours

            if not state.start_time_iso:
                state.start_time_iso = datetime.now(timezone.utc).isoformat()
            state.status = QueueStatus.RUNNING
            _save_queue_state(repo_root, state)

            click.echo(f"Starting queue {state.queue_id}: {len(pending_items)} pending item(s)")
            while True:
                item = select_next_pending_item(state)
                if item is None:
                    break

                # --- Time cap check ---
                elapsed = _compute_queue_elapsed_hours(state)
                if elapsed >= effective_max_hours:
                    click.echo(
                        f"\nTime limit reached ({elapsed:.1f}h / {effective_max_hours:.1f}h). "
                        f"Halting queue."
                    )
                    state.status = QueueStatus.INTERRUPTED
                    _save_queue_state(repo_root, state)
                    break

                # --- Budget cap check ---
                if state.aggregate_cost_usd >= effective_max_cost:
                    click.echo(
                        f"\nBudget limit reached (${state.aggregate_cost_usd:.2f} / "
                        f"${effective_max_cost:.2f}). Halting queue."
                    )
                    state.status = QueueStatus.INTERRUPTED
                    _save_queue_state(repo_root, state)
                    break

                # Mark item as running
                item.status = QueueItemStatus.RUNNING
                current_item = item
                _save_queue_state(repo_root, state)

                source_display = _format_queue_item_source(item)
                click.echo(f"\n--- Processing: {source_display} ---")

                start_ms = int(time.time() * 1000)

                try:
                    # Resolve prompt
                    if item.source_type == "issue":
                        from colonyos.github import fetch_issue, format_issue_as_prompt

                        issue = fetch_issue(int(item.source_value), repo_root)
                        prompt_text = format_issue_as_prompt(issue)
                        source_issue = issue.number
                        source_issue_url = issue.url
                    else:
                        prompt_text = item.source_value
                        source_issue = None
                        source_issue_url = None

                    log = run_orchestrator(
                        prompt_text,
                        repo_root=repo_root,
                        config=config,
                        verbose=verbose,
                        quiet=quiet,
                        source_issue=source_issue,
                        source_issue_url=source_issue_url,
                    )

                    end_ms = int(time.time() * 1000)
                    item.run_id = log.run_id
                    item.cost_usd = log.total_cost_usd
                    item.duration_ms = end_ms - start_ms

                    # Determine outcome
                    if log.status == RunStatus.FAILED and _is_nogo_verdict(log):
                        item.status = QueueItemStatus.REJECTED
                        click.echo("  Item rejected (NO-GO verdict).")
                    elif log.status == RunStatus.FAILED:
                        item.status = QueueItemStatus.FAILED
                        item.error = "Pipeline failed"
                        click.echo("  Item failed.")
                    else:
                        item.status = QueueItemStatus.COMPLETED
                        item.pr_url = _extract_pr_url_from_log(log)
                        click.echo(f"  Item completed. PR: {item.pr_url or 'N/A'}")

                except Exception as exc:
                    end_ms = int(time.time() * 1000)
                    item.status = QueueItemStatus.FAILED
                    # Truncate error to avoid persisting sensitive info from tracebacks.
                    item.error = str(exc)[:500]
                    item.duration_ms = end_ms - start_ms
                    click.echo(f"  Item failed: {exc}", err=True)

                current_item = None
                state.aggregate_cost_usd += item.cost_usd
                _save_queue_state(repo_root, state)

                # --- Post-item budget cap check ---
                if state.aggregate_cost_usd >= effective_max_cost:
                    click.echo(
                        f"\nBudget limit reached (${state.aggregate_cost_usd:.2f} / "
                        f"${effective_max_cost:.2f}). Halting queue."
                    )
                    state.status = QueueStatus.INTERRUPTED
                    _save_queue_state(repo_root, state)
                    break

    except KeyboardInterrupt:
        click.echo("\nQueue interrupted by user.")
        # Revert the in-progress item back to PENDING so it can be retried.
        if current_item is not None and current_item.status == QueueItemStatus.RUNNING:
            current_item.status = QueueItemStatus.PENDING
        state.status = QueueStatus.INTERRUPTED
        _save_queue_state(repo_root, state)
        _print_queue_summary(state)
        return

    # Mark completed if all items processed
    all_done = all(
        i.status in (QueueItemStatus.COMPLETED, QueueItemStatus.FAILED, QueueItemStatus.REJECTED)
        for i in state.items
    )
    if all_done and state.status == QueueStatus.RUNNING:
        state.status = QueueStatus.COMPLETED
    _save_queue_state(repo_root, state)

    _print_queue_summary(state)


@queue.command("status")
def queue_status() -> None:
    """Show the current state of the execution queue."""
    repo_root = _find_repo_root()
    state = _load_queue_state(repo_root)

    if state is None or not state.items:
        click.echo("No queue found or queue is empty.")
        return

    _print_queue_summary(state)


@queue.command()
def clear() -> None:
    """Remove all pending items from the queue."""
    repo_root = _find_repo_root()
    state = _load_queue_state(repo_root)

    if state is None:
        click.echo("No queue found. Nothing to clear.")
        return

    before = len(state.items)
    state.items = [i for i in state.items if i.status != QueueItemStatus.PENDING]
    removed = before - len(state.items)

    _save_queue_state(repo_root, state)
    click.echo(f"Cleared {removed} pending item(s). {len(state.items)} item(s) remaining.")


@queue.command()
def unpause() -> None:
    """Unpause the queue after a circuit breaker trip.

    Resets the circuit breaker state so the queue executor resumes
    processing items.
    """
    from colonyos.config import runs_dir_path
    from colonyos.slack import load_watch_state, save_watch_state

    repo_root = _find_repo_root()
    runs_dir = runs_dir_path(repo_root)
    if not runs_dir.exists():
        click.echo("No watch state found.")
        return

    # Find the most recent watch state file
    watch_files = sorted(runs_dir.glob("watch_state_*.json"), reverse=True)
    if not watch_files:
        click.echo("No watch state found.")
        return

    import json

    for wf in watch_files:
        data = json.loads(wf.read_text(encoding="utf-8"))
        watch_id = data.get("watch_id", "")
        state = load_watch_state(repo_root, watch_id)
        if state and state.queue_paused:
            state.queue_paused = False
            state.queue_paused_at = None
            state.consecutive_failures = 0
            save_watch_state(repo_root, state)
            click.echo(f"Queue unpaused for watch session '{watch_id}'.")
            return

    click.echo("Queue is not currently paused.")


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
    result = compute_stats(runs, phase_filter=phase, repo_root=repo_root)
    render_dashboard(console, result)


# ---------------------------------------------------------------------------
# Show command (single-run inspector)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Directions command
# ---------------------------------------------------------------------------


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
            "  [red]✗[/red] No ColonyOS config found. Run [green]colonyos init[/green] first.",
            highlight=False,
        )
        sys.exit(1)

    if static and auto_update:
        ui_console.print("  [red]✗[/red] Cannot use --static and --auto-update together.", highlight=False)
        sys.exit(1)

    if static:
        config.directions_auto_update = False
        save_config(repo_root, config)
        ui_console.print(
            "  [green]✓[/green] Directions [bold]locked[/bold] — CEO reads but never rewrites.",
            highlight=False,
        )
        return

    if auto_update:
        config.directions_auto_update = True
        save_config(repo_root, config)
        ui_console.print(
            "  [green]✓[/green] Directions [bold]unlocked[/bold] — will evolve after each CEO iteration.",
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


# ---------------------------------------------------------------------------
# Watch command (Slack integration)
# ---------------------------------------------------------------------------


def _watch_slack_impl(
    max_hours: float | None,
    max_budget: float | None,
    verbose: bool,
    quiet: bool,
    dry_run: bool,
) -> None:
    """Watch Slack channels and trigger pipeline runs from messages."""
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

    if config.slack.enabled and not config.slack.allowed_user_ids:
        logger.warning(
            "slack.allowed_user_ids is empty — any user in the configured "
            "channels can trigger triage and approve pipelines."
        )
    if config.slack.auto_approve:
        if not config.slack.allowed_user_ids:
            logger.warning(
                "slack.auto_approve is on with no allowed_user_ids — "
                "any channel member can trigger autonomous code execution."
            )

    from colonyos.slack import (
        FanoutSlackUI,
        SlackClient,
        SlackUI,
        SlackWatchState,
        check_rate_limit,
        create_slack_app,
        extract_base_branch,
        extract_prompt_from_mention,
        extract_raw_from_formatted_prompt,
        find_parent_queue_item,
        format_phase_breakdown_line,
        is_valid_git_ref,
        format_fix_acknowledgment,
        format_fix_error,
        format_fix_round_limit,
        format_slack_as_prompt,
        format_triage_skip,
        increment_hourly_count,
        post_acknowledgment,
        post_run_summary,
        post_triage_acknowledgment,
        post_triage_skip,
        react_to_message,
        remove_reaction,
        resolve_channel_names,
        sanitize_slack_content,
        save_watch_state,
        should_process_message,
        should_process_thread_fix,
        start_socket_mode,
        triage_message,
        wait_for_approval,
    )
    from colonyos.slack_queue import SlackQueueEngine

    try:
        bolt_app = create_slack_app(config.slack)
    except (ImportError, RuntimeError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    effective_max_hours = max_hours if max_hours is not None else config.budget.max_duration_hours
    effective_max_budget = max_budget if max_budget is not None else config.budget.max_total_usd

    watch_id = f"watch-{generate_timestamp()}"
    watch_state = SlackWatchState(watch_id=watch_id)

    # Queue state for unified watch+queue flow
    queue_state = _load_queue_state(repo_root) or QueueState(queue_id=f"watch-queue-{watch_id}")

    # Detect orphaned processed-but-never-queued messages from prior runs
    # (can happen if the process died during daemon triage).
    if queue_state.items:
        queued_ids = {item.id for item in queue_state.items}
        for key, rid in list(watch_state.processed_messages.items()):
            if rid and rid not in queued_ids:
                logger.warning(
                    "AUDIT: orphan_detected processed_key=%s run_id=%s — "
                    "message was marked processed but has no matching queue item "
                    "(possible daemon triage crash in prior session)",
                    key, rid,
                )

    # Lock guards all watch_state and queue_state mutations from concurrent event threads.
    state_lock = threading.Lock()
    # Semaphore limits concurrent pipeline runs to 1 to prevent git conflicts.
    pipeline_semaphore = threading.Semaphore(1)
    # Circuit breaker state is stored in watch_state and always accessed under
    # state_lock for thread safety between the executor and event handler threads.

    # Retrieve the bot user ID for mention detection
    try:
        auth_response = bolt_app.client.auth_test()
        bot_user_id = auth_response["user_id"]
    except Exception as exc:
        click.echo(f"Failed to authenticate with Slack: {exc}", err=True)
        sys.exit(1)

    try:
        resolved_channels = resolve_channel_names(
            bolt_app.client, config.slack.channels
        )
        config.slack.channels = [ch.id for ch in resolved_channels]
        channel_display = {ch.id: ch.name for ch in resolved_channels}
    except RuntimeError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    shutdown_event = threading.Event()
    start_time = time.monotonic()
    # Thread-safe Slack client sharing: the client is set by the first event
    # handler invocation and the executor blocks until it becomes available.
    _slack_client: SlackClient | None = None
    _slack_client_ready = threading.Event()

    def _check_budget_exceeded() -> bool:
        """Return True if aggregate spend exceeds the configured budget cap."""
        if effective_max_budget is None:
            return False
        with state_lock:
            return watch_state.aggregate_cost_usd >= effective_max_budget

    def _check_daily_budget_exceeded() -> bool:
        """Return True if daily spend exceeds the configured daily budget cap."""
        if config.slack.daily_budget_usd is None:
            return False
        with state_lock:
            watch_state.reset_daily_cost_if_needed()
            return watch_state.daily_cost_usd >= config.slack.daily_budget_usd

    def _check_time_exceeded() -> bool:
        """Return True if wall-clock time exceeds the configured max hours."""
        if effective_max_hours is None:
            return False
        elapsed_hours = (time.monotonic() - start_time) / 3600
        return elapsed_hours >= effective_max_hours

    def _handle_thread_fix(event: dict, client: object) -> None:
        """Handle a thread-fix request from Slack.

        Looks up the parent QueueItem, validates fix round limits, enqueues
        a ``slack_fix`` item, and acknowledges in the thread.
        """
        channel = event.get("channel", "")
        ts = event.get("ts", "")
        thread_ts = event.get("thread_ts", "")
        user = event.get("user", "unknown")
        raw_text = event.get("text", "")

        fix_prompt_text = extract_prompt_from_mention(raw_text, bot_user_id)
        if not fix_prompt_text.strip():
            return

        # Note: sanitize_slack_content is called inside format_slack_as_prompt
        # below, so we do not double-sanitize here.

        with state_lock:
            parent_item = find_parent_queue_item(thread_ts, queue_state.items)
            if parent_item is None:
                logger.warning("Thread fix: no completed parent for thread_ts=%s", thread_ts)
                return

            # Check fix round limit
            if parent_item.fix_rounds >= config.slack.max_fix_rounds_per_thread:
                # Sum cumulative cost across parent + all fix items for this thread (FR-17)
                cumulative_cost = parent_item.cost_usd + sum(
                    qi.cost_usd for qi in queue_state.items
                    if qi.parent_item_id == parent_item.id
                )
                try:
                    client.chat_postMessage(  # type: ignore[union-attr]
                        channel=channel,
                        thread_ts=thread_ts,
                        text=format_fix_round_limit(cumulative_cost),
                    )
                except Exception:
                    logger.debug("Failed to post fix round limit message", exc_info=True)
                return

            # Check branch_name and pr_url exist on parent
            if not parent_item.branch_name:
                try:
                    client.chat_postMessage(  # type: ignore[union-attr]
                        channel=channel,
                        thread_ts=thread_ts,
                        text=format_fix_error("No branch", "No branch name recorded for the original run."),
                    )
                except Exception:
                    logger.debug("Failed to post no-branch message", exc_info=True)
                return

            # Increment fix rounds on parent
            parent_item.fix_rounds += 1

            # Create fix queue item
            fix_run_id = f"slack-fix-{generate_timestamp()}"
            formatted_prompt = format_slack_as_prompt(fix_prompt_text, channel, user)
            fix_item = QueueItem(
                id=fix_run_id,
                source_type="slack_fix",
                source_value=formatted_prompt,
                raw_prompt=fix_prompt_text,
                status=QueueItemStatus.PENDING,
                slack_ts=thread_ts,
                slack_channel=channel,
                branch_name=parent_item.branch_name,
                parent_item_id=parent_item.id,
                pr_url=parent_item.pr_url,
                base_branch=parent_item.base_branch,
                head_sha=parent_item.head_sha,
            )
            queue_state.items.append(fix_item)
            _save_queue_state(repo_root, queue_state)
            save_watch_state(repo_root, watch_state)

        # Structured audit log for security-relevant Slack-triggered execution
        logger.info(
            "AUDIT: thread_fix_enqueued item_id=%s user=%s channel=%s "
            "parent_id=%s branch=%s fix_round=%d",
            fix_run_id, user, channel,
            parent_item.id, parent_item.branch_name, parent_item.fix_rounds,
        )

        # Acknowledge
        try:
            react_to_message(client, channel, ts, "eyes")  # type: ignore[arg-type]
        except Exception:
            logger.debug("Failed to add :eyes: reaction to fix request", exc_info=True)

        try:
            client.chat_postMessage(  # type: ignore[union-attr]
                channel=channel,
                thread_ts=thread_ts,
                text=format_fix_acknowledgment(parent_item.branch_name),
            )
        except Exception:
            logger.debug("Failed to post fix acknowledgment", exc_info=True)

    def _handle_event(event: dict, client: object) -> None:
        """Handle app_mention and reaction_added events from Slack.

        Triage → queue insertion flow (FR-6, FR-7).
        """
        nonlocal _slack_client
        # Publish the Slack client for the executor thread (idempotent).
        # Bolt types `client` as object; at runtime it's a WebClient that
        # satisfies SlackClient.
        if not _slack_client_ready.is_set():
            _slack_client = client  # type: ignore[assignment]
            _slack_client_ready.set()

        if not should_process_message(event, config.slack, bot_user_id):
            # Check if this is a thread-fix request — snapshot items to avoid
            # iterating shared mutable state without holding state_lock.
            with state_lock:
                items_snapshot = list(queue_state.items)
            if should_process_thread_fix(event, config.slack, bot_user_id, items_snapshot):
                # Enforce rate limiting and budget checks for thread-fix requests
                # to prevent unbounded cost accumulation across many threads.
                if _check_time_exceeded():
                    logger.warning("Thread fix: max hours exceeded, ignoring")
                    return
                if _check_budget_exceeded():
                    logger.warning("Thread fix: max budget exceeded, ignoring")
                    return
                if _check_daily_budget_exceeded():
                    logger.warning("Thread fix: daily budget exceeded, ignoring")
                    return
                _handle_thread_fix(event, client)
            return

        # Enforce time and budget caps
        if _check_time_exceeded():
            logger.warning("Max hours exceeded, ignoring event")
            return
        if _check_budget_exceeded():
            logger.warning("Max budget exceeded, ignoring event")
            return
        if _check_daily_budget_exceeded():
            logger.warning("Daily budget exceeded, ignoring event")
            return

        channel = event.get("channel", "")
        ts = event.get("ts", "")
        user = event.get("user", "unknown")

        # Extract prompt before acquiring lock so a bare @mention with no
        # text does not burn a rate-limit slot (review finding #2).
        raw_text = event.get("text", "")
        prompt_text = extract_prompt_from_mention(raw_text, bot_user_id)
        if not prompt_text.strip():
            return

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

            # Check queue depth limit
            pending_count = sum(
                1 for item in queue_state.items
                if item.status == QueueItemStatus.PENDING
            )
            if pending_count >= config.slack.max_queue_depth:
                logger.warning("Queue depth limit reached (%d), skipping", pending_count)
                try:
                    client.chat_postMessage(  # type: ignore[union-attr]
                        channel=channel,
                        thread_ts=ts,
                        text=f":warning: Queue is full ({pending_count} pending items). Try again later.",
                    )
                except Exception:
                    logger.debug("Failed to post queue-full message", exc_info=True)
                return

            # Mark as processed early (under lock) to prevent TOCTOU races.
            run_id = f"slack-{generate_timestamp()}"
            watch_state.mark_processed(channel, ts, run_id)
            increment_hourly_count(watch_state)
            watch_state.runs_triggered += 1

        if dry_run:
            click.echo(f"[dry-run] Would trigger pipeline for: {prompt_text[:100]}")
            return

        # Acknowledge receipt
        try:
            react_to_message(client, channel, ts, "eyes")  # type: ignore[arg-type]
        except Exception:
            logger.debug("Failed to add :eyes: reaction", exc_info=True)

        # --- Triage phase (runs in background thread to avoid Slack ack timeout) ---
        def _triage_and_enqueue() -> None:
            if shutdown_event.is_set():
                return
            triage_kwargs: dict[str, str] = {}
            if config.project:
                triage_kwargs["project_name"] = config.project.name
                triage_kwargs["project_description"] = config.project.description
                triage_kwargs["project_stack"] = config.project.stack
            if config.vision:
                triage_kwargs["vision"] = config.vision
            if config.slack.triage_scope:
                triage_kwargs["triage_scope"] = config.slack.triage_scope

            try:
                triage_result = triage_message(prompt_text, repo_root=repo_root, **triage_kwargs)
            except Exception:
                logger.exception("Triage failed for message %s:%s", channel, ts)
                try:
                    client.chat_postMessage(  # type: ignore[union-attr]
                        channel=channel,
                        thread_ts=ts,
                        text=":warning: Triage failed. Check server logs for details.",
                    )
                except Exception:
                    logger.debug("Failed to post triage failure message", exc_info=True)
                return

            if shutdown_event.is_set():
                logger.info(
                    "Watcher shutdown in progress; dropping triaged message %s:%s before enqueue",
                    channel,
                    ts,
                )
                return

            if not triage_result.actionable:
                # If the router answered a question, post the answer back
                if triage_result.answer:
                    if shutdown_event.is_set():
                        return
                    try:
                        client.chat_postMessage(  # type: ignore[union-attr]
                            channel=channel,
                            thread_ts=ts,
                            text=triage_result.answer,
                        )
                    except Exception:
                        logger.debug("Failed to post Q&A answer to Slack", exc_info=True)
                    return

                logger.info("Triage skipped message %s:%s: %s", channel, ts, triage_result.reasoning[:100])
                if config.slack.triage_verbose:
                    try:
                        post_triage_skip(client, channel, ts, triage_result.reasoning)  # type: ignore[arg-type]
                    except Exception:
                        logger.debug("Failed to post triage skip message", exc_info=True)
                return

            # Extract base branch (from triage or explicit syntax)
            base_branch = triage_result.base_branch or extract_base_branch(prompt_text)

            formatted_prompt = format_slack_as_prompt(prompt_text, channel, user)

            # --- Insert into queue ---
            with state_lock:
                if shutdown_event.is_set():
                    return
                queue_item = QueueItem(
                    id=run_id,
                    source_type="slack",
                    source_value=formatted_prompt,
                    raw_prompt=prompt_text,
                    status=QueueItemStatus.PENDING,
                    slack_ts=ts,
                    slack_channel=channel,
                    base_branch=base_branch,
                )
                queue_state.items.append(queue_item)
                _save_queue_state(repo_root, queue_state)
                save_watch_state(repo_root, watch_state)

                pending_items = [
                    i for i in queue_state.items
                    if i.status == QueueItemStatus.PENDING
                ]
                position = len(pending_items)
                total = len(pending_items)

            # Structured audit log for security-relevant Slack-triggered execution
            logger.info(
                "AUDIT: pipeline_enqueued item_id=%s user=%s channel=%s "
                "base_branch=%s",
                run_id, user, channel, base_branch or "default",
            )

            needs_approval = not config.slack.auto_approve
            if shutdown_event.is_set():
                return
            try:
                post_triage_acknowledgment(
                    client,  # type: ignore[arg-type]
                    channel,
                    ts,
                    triage_result.summary,
                    needs_approval=needs_approval,
                    queue_position=position,
                    queue_total=total,
                )
            except Exception:
                logger.debug("Failed to post triage acknowledgment", exc_info=True)

        # NOTE: Daemon thread — if the process shuts down while triage is
        # in flight, the message may be mark_processed but never queued.
        # This is an acceptable trade-off for v1; the window is very small.
        # Recovery: on startup, processed messages with no matching queue item
        # are logged at WARNING level so operators can detect orphans.
        if not shutdown_event.is_set():
            threading.Thread(
                target=_triage_and_enqueue, daemon=True, name=f"triage-{ts}",
            ).start()

    class _DualUI:
        """Forwards UI calls to both terminal and Slack UIs.

        Error isolation: if the Slack API call fails, the terminal UI
        still receives the call.  Slack errors are logged at DEBUG level
        to avoid masking the actual pipeline output.
        """

        def __init__(self, terminal: object, slack: object) -> None:
            self._terminal = terminal
            self._slack = slack

        def _safe_slack_call(self, method: str, *a: object, **kw: object) -> None:
            """Invoke a method on the Slack UI, swallowing exceptions."""
            try:
                getattr(self._slack, method)(*a, **kw)
            except Exception:
                logger.debug("Slack UI call %s failed", method, exc_info=True)

        def phase_header(self, *a: object, **kw: object) -> None:
            self._terminal.phase_header(*a, **kw)  # type: ignore[union-attr]
            self._safe_slack_call("phase_header", *a, **kw)

        def phase_complete(self, *a: object, **kw: object) -> None:
            self._terminal.phase_complete(*a, **kw)  # type: ignore[union-attr]
            self._safe_slack_call("phase_complete", *a, **kw)

        def phase_error(self, *a: object, **kw: object) -> None:
            self._terminal.phase_error(*a, **kw)  # type: ignore[union-attr]
            self._safe_slack_call("phase_error", *a, **kw)

        def phase_note(self, *a: object, **kw: object) -> None:
            self._terminal.phase_note(*a, **kw)  # type: ignore[union-attr]
            self._safe_slack_call("phase_note", *a, **kw)

        def slack_note(self, text: str) -> None:
            self._safe_slack_call("phase_note", text)

        def on_tool_start(self, *a: object) -> None:
            self._terminal.on_tool_start(*a)  # type: ignore[union-attr]

        def on_tool_input_delta(self, *a: object) -> None:
            self._terminal.on_tool_input_delta(*a)  # type: ignore[union-attr]

        def on_tool_done(self) -> None:
            self._terminal.on_tool_done()  # type: ignore[union-attr]

        def on_text_delta(self, *a: object) -> None:
            self._terminal.on_text_delta(*a)  # type: ignore[union-attr]

        def on_turn_complete(self) -> None:
            self._terminal.on_turn_complete()  # type: ignore[union-attr]

    class QueueExecutor:
        """Drains QueueState items sequentially in a background thread.

        Encapsulates all executor state to avoid a deeply nested closure
        capturing 10+ variables from the enclosing ``watch()`` scope.
        """

        def __init__(
            self,
            *,
            repo_root: Path,
            watch_state: SlackWatchState,
            queue_state: QueueState,
            state_lock: threading.Lock,
            shutdown_event: threading.Event,
            pipeline_semaphore: threading.Semaphore,
            slack_client_ready: threading.Event,
            verbose: bool,
            quiet: bool,
            circuit_breaker_cooldown_minutes: int,
        ) -> None:
            self._repo_root = repo_root
            self._watch_state = watch_state
            self._queue_state = queue_state
            self._state_lock = state_lock
            self._shutdown = shutdown_event
            self._semaphore = pipeline_semaphore
            self._slack_client_ready = slack_client_ready
            self._verbose = verbose
            self._quiet = quiet
            self._circuit_breaker_cooldown_minutes = circuit_breaker_cooldown_minutes
            # Compute recovery deadline once when pause is first detected
            self._recovery_monotonic: float | None = None

        def _get_client(self) -> SlackClient:
            """Return the shared Slack client, blocking until available.

            Waits on ``_slack_client_ready`` to ensure the client has been
            published by the event handler thread before returning.
            """
            self._slack_client_ready.wait()
            assert _slack_client is not None
            return _slack_client

        def run(self) -> None:
            """Main loop — intended as a ``threading.Thread`` target."""
            while not self._shutdown.is_set():
                if _check_time_exceeded() or _check_budget_exceeded() or _check_daily_budget_exceeded():
                    self._shutdown.wait(timeout=5.0)
                    continue

                if self._is_paused():
                    self._shutdown.wait(timeout=5.0)
                    continue

                item_to_run = self._next_pending_item()
                if item_to_run is None:
                    self._shutdown.wait(timeout=2.0)
                    continue

                self._semaphore.acquire()
                try:
                    if item_to_run.source_type == "slack_fix":
                        self._execute_fix_item(item_to_run)
                    else:
                        self._execute_item(item_to_run)
                except BranchRestoreError:
                    # FATAL — running subsequent items on the wrong branch
                    # risks data corruption.  Halt the queue immediately.
                    logger.critical(
                        "Branch restore failed for item %s — halting queue "
                        "to prevent data corruption. Manual intervention required.",
                        item_to_run.id,
                    )
                    with self._state_lock:
                        item_to_run.status = QueueItemStatus.FAILED
                        item_to_run.error = "Branch restore failed — queue halted"
                        self._watch_state.queue_paused = True
                        self._watch_state.queue_paused_at = (
                            datetime.now(timezone.utc).isoformat()
                        )
                        _save_queue_state(self._repo_root, self._queue_state)
                        save_watch_state(self._repo_root, self._watch_state)
                    self._shutdown.set()
                    return
                except Exception:
                    logger.exception(
                        "Queue executor error for item %s (channel=%s, ts=%s)",
                        item_to_run.id,
                        item_to_run.slack_channel or "?",
                        item_to_run.slack_ts or "?",
                    )
                    with self._state_lock:
                        item_to_run.status = QueueItemStatus.FAILED
                        item_to_run.error = "Executor error"
                        self._watch_state.consecutive_failures += 1
                        _save_queue_state(self._repo_root, self._queue_state)
                        save_watch_state(self._repo_root, self._watch_state)
                finally:
                    self._semaphore.release()

        # -- helpers -------------------------------------------------------

        def _is_paused(self) -> bool:
            with self._state_lock:
                if not self._watch_state.queue_paused:
                    self._recovery_monotonic = None
                    return False
                # Compute recovery deadline once per pause episode
                if self._recovery_monotonic is None and self._watch_state.queue_paused_at:
                    try:
                        paused_at = datetime.fromisoformat(self._watch_state.queue_paused_at)
                        cooldown_sec = self._circuit_breaker_cooldown_minutes * 60
                        elapsed_since_pause = (datetime.now(timezone.utc) - paused_at).total_seconds()
                        self._recovery_monotonic = time.monotonic() + max(0, cooldown_sec - elapsed_since_pause)
                    except (ValueError, TypeError):
                        return True  # Malformed timestamp; remain paused

                if self._recovery_monotonic is not None and time.monotonic() >= self._recovery_monotonic:
                    self._watch_state.queue_paused = False
                    self._watch_state.queue_paused_at = None
                    self._watch_state.consecutive_failures = 0
                    self._recovery_monotonic = None
                    save_watch_state(self._repo_root, self._watch_state)
                    logger.info("Circuit breaker auto-recovered")
                    return False
                return True

        def _next_pending_item(self) -> QueueItem | None:
            with self._state_lock:
                return select_next_pending_item(self._queue_state)

        def _notification_targets(self, item: QueueItem) -> list[tuple[str, str]]:
            return notification_targets(item)

        def _post_run_summary_to_targets(
            self,
            client: SlackClient,
            item: QueueItem,
            *,
            status: str,
            total_cost: float,
            branch_name: str | None,
            pr_url: str | None,
            phase_breakdown: list[str],
        ) -> None:
            for channel, thread_ts in self._notification_targets(item):
                post_run_summary(
                    client,
                    channel,
                    thread_ts,
                    status=status,
                    total_cost=total_cost,
                    branch_name=branch_name,
                    pr_url=pr_url,
                    summary=item.summary,
                    phase_breakdown=phase_breakdown,
                    demand_count=item.demand_count,
                )

        def _execute_item(self, item_to_run: QueueItem) -> None:
            try:
                current_config = load_config(self._repo_root)
            except Exception:
                logger.exception(
                    "Failed to load config.yaml — check for syntax errors"
                )
                with self._state_lock:
                    item_to_run.status = QueueItemStatus.FAILED
                    item_to_run.error = "Config load failed — check config.yaml for syntax errors"
                    self._watch_state.consecutive_failures += 1
                    _save_queue_state(self._repo_root, self._queue_state)
                    save_watch_state(self._repo_root, self._watch_state)
                return

            with self._state_lock:
                item_to_run.status = QueueItemStatus.RUNNING
                item_to_run.run_id = item_to_run.id
                _save_queue_state(self._repo_root, self._queue_state)

            slack_ts = item_to_run.slack_ts
            slack_channel = item_to_run.slack_channel
            slack_targets = self._notification_targets(item_to_run)

            # Wait for the Slack client with a timeout instead of silently deferring
            if not self._slack_client_ready.wait(timeout=10.0):
                logger.warning("Slack client not available after 10s, deferring item %s", item_to_run.id)
                with self._state_lock:
                    item_to_run.status = QueueItemStatus.PENDING
                    _save_queue_state(self._repo_root, self._queue_state)
                return
            client = self._get_client()

            # Approval gate for Slack-sourced items
            if not current_config.slack.auto_approve and client and slack_ts and slack_channel:
                if not self._run_approval_gate(
                    client, slack_channel, slack_ts, item_to_run,
                    allowed_approver_ids=current_config.slack.allowed_user_ids or None,
                ):
                    return

            # Build UI factory — streams to both terminal and Slack thread
            ui_factory = None
            if client and slack_ts and slack_channel:
                from colonyos.ui import PhaseUI, NullUI

                def _dual_ui_factory(
                    prefix: str = "",
                    *,
                    badge: object | None = None,
                    task_id: str | None = None,
                ) -> object:
                    is_nested_stream = badge is not None or task_id is not None or bool(prefix)
                    slack_ui_targets = [SlackUI(client, channel, thread_ts) for channel, thread_ts in slack_targets]
                    slack_ui: SlackUI | FanoutSlackUI
                    if len(slack_ui_targets) == 1:
                        slack_ui = slack_ui_targets[0]
                    else:
                        slack_ui = FanoutSlackUI(*slack_ui_targets)
                    if is_nested_stream:
                        if self._quiet:
                            return NullUI()
                        return PhaseUI(
                            verbose=self._verbose,
                            prefix=prefix,
                            task_id=task_id,
                            badge=badge,  # type: ignore[arg-type]
                        )
                    if self._quiet:
                        return slack_ui
                    terminal_ui = PhaseUI(
                        verbose=self._verbose,
                        prefix=prefix,
                        task_id=task_id,
                        badge=badge,  # type: ignore[arg-type]
                    )
                    return _DualUI(terminal_ui, slack_ui)

                ui_factory = _dual_ui_factory

                try:
                    for channel, thread_ts in slack_targets:
                        post_acknowledgment(client, channel, thread_ts, item_to_run.source_value[:200])  # type: ignore[arg-type]
                except Exception:
                    logger.debug("Failed to post pipeline start", exc_info=True)

            start_ms = int(time.time() * 1000)
            _touch_heartbeat(self._repo_root)

            log = run_orchestrator(
                item_to_run.source_value,
                repo_root=self._repo_root,
                config=current_config,
                verbose=self._verbose,
                quiet=self._quiet,
                ui_factory=ui_factory,
                base_branch=item_to_run.base_branch,
            )

            elapsed_ms = int(time.time() * 1000) - start_ms

            with self._state_lock:
                item_to_run.cost_usd = log.total_cost_usd
                item_to_run.duration_ms = elapsed_ms
                item_to_run.run_id = log.run_id
                item_to_run.pr_url = log.pr_url
                # Persist branch_name for thread-fix lookups (Task 1.3)
                if log.branch_name:
                    item_to_run.branch_name = log.branch_name
                # Persist HEAD SHA for force-push tamper detection (FR-7)
                if log.preflight and log.preflight.head_sha:
                    item_to_run.head_sha = log.preflight.head_sha

                if log.status == RunStatus.COMPLETED:
                    item_to_run.status = QueueItemStatus.COMPLETED
                    self._watch_state.consecutive_failures = 0
                else:
                    item_to_run.status = QueueItemStatus.FAILED
                    item_to_run.error = (log.phases[-1].error[:200] if log.phases and log.phases[-1].error else "Pipeline failed")
                    self._watch_state.consecutive_failures += 1

                self._watch_state.aggregate_cost_usd += log.total_cost_usd
                self._watch_state.reset_daily_cost_if_needed()
                self._watch_state.daily_cost_usd += log.total_cost_usd
                self._queue_state.aggregate_cost_usd += log.total_cost_usd
                current_failures = self._watch_state.consecutive_failures
                _save_queue_state(self._repo_root, self._queue_state)
                save_watch_state(self._repo_root, self._watch_state)

            # Post result to Slack thread
            if client and slack_targets:
                emoji = "white_check_mark" if log.status == RunStatus.COMPLETED else "x"
                for channel, thread_ts in slack_targets:
                    try:
                        remove_reaction(client, channel, thread_ts, "eyes")  # type: ignore[arg-type]
                    except Exception:
                        logger.debug("Failed to remove eyes reaction", exc_info=True)
                    try:
                        react_to_message(client, channel, thread_ts, emoji)  # type: ignore[arg-type]
                    except Exception:
                        logger.debug("Failed to add result reaction", exc_info=True)
                    if log.status == RunStatus.COMPLETED:
                        try:
                            react_to_message(client, channel, thread_ts, "tada")  # type: ignore[arg-type]
                        except Exception:
                            logger.debug("Failed to add tada reaction", exc_info=True)

                self._post_run_summary_to_targets(
                    client,  # type: ignore[arg-type]
                    item_to_run,
                    status=log.status.value,
                    total_cost=log.total_cost_usd,
                    branch_name=log.branch_name,
                    pr_url=log.pr_url,
                    phase_breakdown=[format_phase_breakdown_line(phase) for phase in log.phases],
                )

            # Check consecutive failure circuit breaker
            if current_failures >= current_config.slack.max_consecutive_failures:
                with self._state_lock:
                    self._watch_state.queue_paused = True
                    self._watch_state.queue_paused_at = datetime.now(timezone.utc).isoformat()
                    save_watch_state(self._repo_root, self._watch_state)
                logger.warning(
                    "Queue paused: %d consecutive failures (will auto-recover after %d minutes)",
                    current_failures,
                    current_config.slack.circuit_breaker_cooldown_minutes,
                )
                if client and current_config.slack.channels:
                    notify_channel = current_config.slack.channels[0]
                    try:
                        cooldown = current_config.slack.circuit_breaker_cooldown_minutes
                        client.chat_postMessage(  # type: ignore[union-attr]
                            channel=notify_channel,
                            text=(
                                f":rotating_light: Queue paused after {current_failures} "
                                f"consecutive failures. Will auto-recover after {cooldown} minutes, "
                                f"or use `colonyos watch unpause` to re-enable manually."
                            ),
                        )
                    except Exception:
                        logger.debug("Failed to post circuit-breaker notification", exc_info=True)

        def _run_approval_gate(
            self, client: object, channel: str, ts: str, item: QueueItem,
            *, allowed_approver_ids: list[str] | None = None,
        ) -> bool:
            """Run the approval gate. Returns True if approved, False otherwise.

            When ``allowed_approver_ids`` is set, only thumbsup reactions from
            those users count as valid approval — prevents unauthorized users
            from approving their own requests.
            """
            try:
                approval_resp = client.chat_postMessage(  # type: ignore[union-attr]
                    channel=channel,
                    thread_ts=ts,
                    text=":question: Awaiting approval — react with :thumbsup: to proceed.",
                )
                approval_ts = approval_resp.get("ts", "")
                approved = wait_for_approval(
                    client, channel, ts, approval_ts,  # type: ignore[arg-type]
                    allowed_approver_ids=allowed_approver_ids,
                )
                if not approved:
                    try:
                        client.chat_postMessage(  # type: ignore[union-attr]
                            channel=channel,
                            thread_ts=ts,
                            text=":no_entry: Approval timed out. Pipeline not executed.",
                        )
                    except Exception:
                        logger.debug("Failed to post approval timeout", exc_info=True)
                    with self._state_lock:
                        item.status = QueueItemStatus.REJECTED
                        _save_queue_state(self._repo_root, self._queue_state)
                    return False
            except Exception:
                logger.debug("Failed to post/poll approval", exc_info=True)
                with self._state_lock:
                    item.status = QueueItemStatus.FAILED
                    item.error = "Approval flow failed"
                    _save_queue_state(self._repo_root, self._queue_state)
                return False
            return True

        def _execute_fix_item(self, item_to_run: QueueItem) -> None:
            """Execute a thread-fix pipeline item (source_type='slack_fix')."""
            from colonyos.orchestrator import run_thread_fix as _run_thread_fix

            try:
                current_config = load_config(self._repo_root)
            except Exception:
                logger.exception("Failed to load config for fix item")
                with self._state_lock:
                    item_to_run.status = QueueItemStatus.FAILED
                    item_to_run.error = "Config load failed"
                    _save_queue_state(self._repo_root, self._queue_state)
                return

            with self._state_lock:
                item_to_run.status = QueueItemStatus.RUNNING
                item_to_run.run_id = item_to_run.id
                _save_queue_state(self._repo_root, self._queue_state)

            slack_ts = item_to_run.slack_ts
            slack_channel = item_to_run.slack_channel
            slack_targets = self._notification_targets(item_to_run)

            # Wait for Slack client
            if not self._slack_client_ready.wait(timeout=10.0):
                logger.warning("Slack client not available for fix item %s", item_to_run.id)
                with self._state_lock:
                    item_to_run.status = QueueItemStatus.PENDING
                    _save_queue_state(self._repo_root, self._queue_state)
                return
            client = self._get_client()

            # Build UI factory for the fix
            ui_factory = None
            if client and slack_ts and slack_channel:
                from colonyos.ui import PhaseUI, NullUI

                def _fix_ui_factory(
                    prefix: str = "",
                    *,
                    badge: object | None = None,
                    task_id: str | None = None,
                ) -> object:
                    is_nested_stream = badge is not None or task_id is not None or bool(prefix)
                    slack_ui_targets = [SlackUI(client, channel, thread_ts) for channel, thread_ts in slack_targets]
                    slack_ui: SlackUI | FanoutSlackUI
                    if len(slack_ui_targets) == 1:
                        slack_ui = slack_ui_targets[0]
                    else:
                        slack_ui = FanoutSlackUI(*slack_ui_targets)
                    if is_nested_stream:
                        if self._quiet:
                            return NullUI()
                        return PhaseUI(
                            verbose=self._verbose,
                            prefix=prefix,
                            task_id=task_id,
                            badge=badge,  # type: ignore[arg-type]
                        )
                    if self._quiet:
                        return slack_ui
                    terminal_ui = PhaseUI(
                        verbose=self._verbose,
                        prefix=prefix,
                        task_id=task_id,
                        badge=badge,  # type: ignore[arg-type]
                    )
                    return _DualUI(terminal_ui, slack_ui)

                ui_factory = _fix_ui_factory

            # Find parent item for context
            parent_item = None
            with self._state_lock:
                if item_to_run.parent_item_id:
                    for qi in self._queue_state.items:
                        if qi.id == item_to_run.parent_item_id:
                            parent_item = qi
                            break

            # Use stored raw_prompt when available; fall back to
            # extract_raw_from_formatted_prompt for legacy queue items.
            from colonyos.sanitize import sanitize_untrusted_content
            raw_prompt = ""
            if parent_item:
                raw_prompt = parent_item.raw_prompt or extract_raw_from_formatted_prompt(parent_item.source_value)
            original_prompt = sanitize_untrusted_content(raw_prompt) if raw_prompt else ""
            prd_rel = ""
            task_rel = ""
            # Try to get PRD/task from parent run log
            if parent_item and parent_item.run_id:
                try:
                    from colonyos.orchestrator import _load_run_log
                    parent_log = _load_run_log(self._repo_root, parent_item.run_id)
                    if parent_log:
                        prd_rel = parent_log.prd_rel or ""
                        task_rel = parent_log.task_rel or ""
                except Exception:
                    logger.debug("Failed to load parent run log for fix item", exc_info=True)

            # Defense-in-depth: re-validate branch name from deserialized queue
            # state before passing to subprocess (FR-7 security requirement).
            fix_branch = item_to_run.branch_name or ""
            if not fix_branch or not is_valid_git_ref(fix_branch):
                logger.warning(
                    "Fix item %s has invalid branch_name %r, marking failed",
                    item_to_run.id, fix_branch[:100],
                )
                with self._state_lock:
                    item_to_run.status = QueueItemStatus.FAILED
                    item_to_run.error = "Invalid branch name in queue state"
                    _save_queue_state(self._repo_root, self._queue_state)
                return

            start_ms = int(time.time() * 1000)
            _touch_heartbeat(self._repo_root)

            log = _run_thread_fix(
                item_to_run.source_value,
                branch_name=fix_branch,
                pr_url=item_to_run.pr_url,
                original_prompt=original_prompt,
                prd_rel=prd_rel,
                task_rel=task_rel,
                repo_root=self._repo_root,
                config=current_config,
                verbose=self._verbose,
                quiet=self._quiet,
                ui_factory=ui_factory,
                expected_head_sha=item_to_run.head_sha,
            )

            elapsed_ms = int(time.time() * 1000) - start_ms

            new_head_sha = log.post_fix_head_sha or ""

            with self._state_lock:
                item_to_run.cost_usd = log.total_cost_usd
                item_to_run.duration_ms = elapsed_ms
                item_to_run.run_id = log.run_id
                item_to_run.pr_url = log.pr_url

                if log.status == RunStatus.COMPLETED:
                    item_to_run.status = QueueItemStatus.COMPLETED
                    self._watch_state.consecutive_failures = 0
                    # Propagate new HEAD SHA to parent so the next fix round
                    # inherits the correct expected SHA (multi-round fix support).
                    if parent_item and new_head_sha:
                        parent_item.head_sha = new_head_sha
                else:
                    item_to_run.status = QueueItemStatus.FAILED
                    item_to_run.error = (
                        log.phases[-1].error[:200]
                        if log.phases and log.phases[-1].error
                        else "Fix pipeline failed"
                    )
                    self._watch_state.consecutive_failures += 1

                self._watch_state.aggregate_cost_usd += log.total_cost_usd
                self._watch_state.reset_daily_cost_if_needed()
                self._watch_state.daily_cost_usd += log.total_cost_usd
                self._queue_state.aggregate_cost_usd += log.total_cost_usd
                current_failures = self._watch_state.consecutive_failures
                _save_queue_state(self._repo_root, self._queue_state)
                save_watch_state(self._repo_root, self._watch_state)

            # Post fix result to Slack thread
            if client and slack_targets:
                emoji = "white_check_mark" if log.status == RunStatus.COMPLETED else "x"
                for channel, thread_ts in slack_targets:
                    try:
                        remove_reaction(client, channel, thread_ts, "eyes")  # type: ignore[arg-type]
                    except Exception:
                        logger.debug("Failed to remove eyes reaction", exc_info=True)
                    try:
                        react_to_message(client, channel, thread_ts, emoji)  # type: ignore[arg-type]
                    except Exception:
                        logger.debug("Failed to add fix result reaction", exc_info=True)
                    if log.status == RunStatus.COMPLETED:
                        try:
                            react_to_message(client, channel, thread_ts, "tada")  # type: ignore[arg-type]
                        except Exception:
                            logger.debug("Failed to add tada reaction", exc_info=True)

                self._post_run_summary_to_targets(
                    client,  # type: ignore[arg-type]
                    item_to_run,
                    status=log.status.value,
                    total_cost=log.total_cost_usd,
                    branch_name=log.branch_name,
                    pr_url=log.pr_url,
                    phase_breakdown=[format_phase_breakdown_line(phase) for phase in log.phases],
                )

    queue_executor = QueueExecutor(
        repo_root=repo_root,
        watch_state=watch_state,
        queue_state=queue_state,
        state_lock=state_lock,
        shutdown_event=shutdown_event,
        pipeline_semaphore=pipeline_semaphore,
        slack_client_ready=_slack_client_ready,
        verbose=verbose,
        quiet=quiet,
        circuit_breaker_cooldown_minutes=config.slack.circuit_breaker_cooldown_minutes,
    )

    def _publish_watch_client(client: SlackClient) -> None:
        nonlocal _slack_client
        _slack_client = client

    def _persist_watch_queue() -> None:
        _save_queue_state(repo_root, queue_state)

    def _persist_watch_runtime_state() -> None:
        save_watch_state(repo_root, watch_state)

    slack_engine = SlackQueueEngine(
        repo_root=repo_root,
        config=config,
        queue_state=queue_state,
        watch_state=watch_state,
        state_lock=state_lock,
        shutdown_event=shutdown_event,
        bot_user_id=bot_user_id,
        slack_client_ready=_slack_client_ready,
        publish_client=_publish_watch_client,
        persist_queue=_persist_watch_queue,
        persist_watch_state=_persist_watch_runtime_state,
        is_time_exceeded=_check_time_exceeded,
        is_budget_exceeded=_check_budget_exceeded,
        is_daily_budget_exceeded=_check_daily_budget_exceeded,
        dry_run=dry_run,
    )
    slack_engine.register(bolt_app)

    shutdown_reason: dict[str, str | None] = {"value": None}

    def _request_shutdown(reason: str) -> None:
        if shutdown_reason["value"] is None:
            shutdown_reason["value"] = reason
        shutdown_event.set()

    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    con = Console()

    trigger_labels = {"mention": "@mention", "reaction": "emoji reaction", "slash_command": "/colonyos", "all": "all"}
    trigger_label = trigger_labels.get(config.slack.trigger_mode, config.slack.trigger_mode)

    channels_text = Text()
    for i, ch in enumerate(resolved_channels):
        if i > 0:
            channels_text.append("  ")
        channels_text.append("#", style="dim")
        channels_text.append(ch.name, style="bold cyan")

    info = Table.grid(padding=(0, 2))
    info.add_column(style="dim", justify="right")
    info.add_column()
    info.add_row("channels", channels_text)
    info.add_row("trigger", Text(trigger_label, style="bold"))
    if effective_max_hours is not None:
        info.add_row("max hours", Text(str(effective_max_hours), style="yellow"))
    if effective_max_budget is not None:
        info.add_row("max budget", Text(f"${effective_max_budget:.2f}", style="yellow"))
    if config.slack.daily_budget_usd is not None:
        info.add_row("daily budget", Text(f"${config.slack.daily_budget_usd:.2f}", style="yellow"))
    if config.slack.max_runs_per_hour:
        info.add_row("rate limit", Text(f"{config.slack.max_runs_per_hour} runs/hour", style="dim"))
    if dry_run:
        info.add_row("mode", Text("DRY RUN — triggers logged, not executed", style="bold red"))

    con.print()
    con.print(Panel(
        info,
        title="[bold]ColonyOS Slack Watcher[/bold]",
        subtitle=f"[dim]{watch_id}[/dim]",
        border_style="cyan",
        padding=(1, 2),
    ))
    con.print()

    save_watch_state(repo_root, watch_state)

    # Start the queue executor thread
    executor_thread = threading.Thread(target=queue_executor.run, daemon=True, name="queue-executor")
    executor_thread.start()

    handler = None
    try:
        with cancellation_scope(_request_shutdown), install_signal_cancel_handlers(
            include_sighup=True,
        ):
            handler = start_socket_mode(bolt_app)
            handler.connect()
            while not shutdown_event.is_set():
                if _check_time_exceeded():
                    click.echo("Max hours reached. Shutting down watcher.")
                    break
                if _check_budget_exceeded():
                    click.echo("Max budget reached. Shutting down watcher.")
                    break
                if _check_daily_budget_exceeded():
                    click.echo("Daily budget reached. Queue executor will skip items until next UTC day.")
                shutdown_event.wait(timeout=5.0)
    except ImportError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"Slack watcher error: {exc}", err=True)
        sys.exit(1)
    finally:
        shutdown_event.set()
        if shutdown_reason["value"] is not None:
            click.echo(f"\nShutting down Slack watcher... ({shutdown_reason['value']})")
        if handler is not None:
            try:
                handler.close()
            except Exception:
                logger.debug("Failed to close Slack socket handler", exc_info=True)
        executor_thread.join(timeout=60)
        with state_lock:
            _save_queue_state(repo_root, queue_state)
            save_watch_state(repo_root, watch_state)


@app.command("watch-slack")
@click.option("--max-hours", type=float, default=None, help="Maximum wall-clock hours for the watcher.")
@click.option("--max-budget", type=float, default=None, help="Maximum aggregate USD spend.")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output alongside tool activity.")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output (no streaming, just phase start/end).")
@click.option("--dry-run", is_flag=True, help="Log triggers without executing pipeline.")
def watch_slack(
    max_hours: float | None,
    max_budget: float | None,
    verbose: bool,
    quiet: bool,
    dry_run: bool,
) -> None:
    """Watch Slack channels and trigger pipeline runs from messages."""
    repo_root = _find_repo_root()
    with _repo_runtime_guard(repo_root, "watch-slack"):
        _watch_slack_impl(max_hours, max_budget, verbose, quiet, dry_run)


@app.command("watch")
@click.option("--max-hours", type=float, default=None, help="Maximum wall-clock hours for the watcher.")
@click.option("--max-budget", type=float, default=None, help="Maximum aggregate USD spend.")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output alongside tool activity.")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output (no streaming, just phase start/end).")
@click.option("--dry-run", is_flag=True, help="Log triggers without executing pipeline.")
def watch_legacy(
    max_hours: float | None,
    max_budget: float | None,
    verbose: bool,
    quiet: bool,
    dry_run: bool,
) -> None:
    """Deprecated alias for `watch-slack`."""
    click.echo(
        click.style(
            "`colonyos watch` is deprecated; use `colonyos watch-slack`.",
            fg="yellow",
        ),
        err=True,
    )
    repo_root = _find_repo_root()
    with _repo_runtime_guard(repo_root, "watch-slack"):
        _watch_slack_impl(max_hours, max_budget, verbose, quiet, dry_run)


# ---------------------------------------------------------------------------
# Daemon – queue-item pipeline helper
# ---------------------------------------------------------------------------


def run_pipeline_for_queue_item(
    *,
    item: "QueueItem",
    repo_root: "Path",
    config: "ColonyConfig",
    verbose: bool = False,
    quiet: bool = False,
    ui_factory: Any | None = None,
    queue_state: "QueueState | None" = None,
) -> RunLog:
    """Execute a single queue item through the orchestration pipeline.

    Returns the full run log. Called by the daemon process
    to drive items that were enqueued via Slack, GitHub issues, CEO
    proposals, etc.
    """
    from colonyos.github import fetch_issue, format_issue_as_prompt

    if item.source_type == "slack_fix":
        from colonyos.orchestrator import _load_run_log, run_thread_fix
        from colonyos.sanitize import sanitize_untrusted_content
        from colonyos.slack import extract_raw_from_formatted_prompt, is_valid_git_ref

        if not item.branch_name or not is_valid_git_ref(item.branch_name):
            raise RuntimeError("Invalid branch name for slack_fix queue item")

        parent_item = None
        if queue_state is not None and item.parent_item_id:
            parent_item = next(
                (queued for queued in queue_state.items if queued.id == item.parent_item_id),
                None,
            )

        raw_prompt = ""
        if parent_item is not None:
            raw_prompt = (
                parent_item.raw_prompt
                or extract_raw_from_formatted_prompt(parent_item.source_value)
            )
        original_prompt = sanitize_untrusted_content(raw_prompt) if raw_prompt else ""
        prd_rel = ""
        task_rel = ""
        if parent_item is not None and parent_item.run_id:
            parent_log = _load_run_log(repo_root, parent_item.run_id)
            if parent_log:
                prd_rel = parent_log.prd_rel or ""
                task_rel = parent_log.task_rel or ""

        return run_thread_fix(
            item.source_value,
            branch_name=item.branch_name,
            pr_url=item.pr_url,
            original_prompt=original_prompt,
            prd_rel=prd_rel,
            task_rel=task_rel,
            repo_root=repo_root,
            config=config,
            verbose=verbose,
            quiet=quiet,
            ui_factory=ui_factory,
            expected_head_sha=item.head_sha,
        )

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

    related_context = ""
    if queue_state is not None:
        related_context = build_similarity_context(item, queue_state)
    if related_context:
        prompt_text = (
            f"{prompt_text}\n\n## Similar Request Context\n"
            f"{related_context}"
        )

    branch_name_override = _queue_item_branch_name_override(item, config)

    log = run_orchestrator(
        prompt_text,
        repo_root=repo_root,
        config=config,
        verbose=verbose,
        quiet=quiet,
        ui_factory=ui_factory,
        base_branch=item.base_branch,
        branch_name_override=branch_name_override,
        source_issue=source_issue,
        source_issue_url=source_issue_url,
    )

    return log


def _launch_daemon_tui(
    repo_root: Path,
    config: ColonyConfig,
    *,
    max_budget: float | None,
    unlimited_budget: bool,
    max_hours: float | None,
    allow_all_control_users: bool,
    verbose: bool,
    dry_run: bool,
) -> None:
    """Launch daemon mode inside the existing Textual shell."""
    import colonyos.tui  # noqa: F401
    import threading

    from colonyos.tui.app import AssistantApp
    from colonyos.tui.adapter import NoticeMsg
    from colonyos.tui.log_writer import TranscriptLogWriter
    from colonyos.tui.widgets.transcript import TranscriptView

    class _DaemonApp(AssistantApp):
        async def on_mount(self) -> None:
            await super().on_mount()
            transcript = self.query_one(TranscriptView)
            transcript.append_daemon_monitor_banner()
            transcript.append_notice(
                "Daemon monitor mode. Press q to quit. Ctrl+C requests shutdown."
            )
            self._start_run("daemon-monitor")

    run_id = datetime.now(timezone.utc).strftime("daemon_%Y%m%d_%H%M%S")
    logs_dir = repo_root / ".colonyos" / "logs"
    log_writer = TranscriptLogWriter(
        logs_dir, run_id, max_log_files=config.max_log_files,
    )

    process_ref: dict[str, subprocess.Popen[str]] = {}
    process_lock = threading.Lock()
    shutdown_requested = threading.Event()

    def _emit_monitor_notice(text: str) -> None:
        queue = getattr(getattr(app_instance, "event_queue", None), "sync_q", None)
        if queue is not None:
            queue.put(NoticeMsg(text=text))

    def _terminate_daemon_process(
        *,
        reason: str,
        force: bool = False,
        mark_shutdown: bool = False,
    ) -> None:
        if mark_shutdown:
            shutdown_requested.set()
        with process_lock:
            process = process_ref.get("instance")
        if process is None or process.poll() is not None:
            return

        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            _emit_monitor_notice(f"{reason}; sending {signal.Signals(sig).name} to daemon subprocess")
            os.killpg(process.pid, sig)
            if not force:
                process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _emit_monitor_notice("Daemon did not exit after SIGTERM; sending SIGKILL")
            with suppress(ProcessLookupError, PermissionError, OSError):
                os.killpg(process.pid, signal.SIGKILL)
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=2)
        except (ProcessLookupError, PermissionError, OSError) as exc:
            logger.debug("Failed to stop daemon subprocess cleanly: %s", exc)
        finally:
            with suppress(Exception):
                stream = process.stdout
                if stream is not None:
                    stream.close()

    def _run_callback(_text: str) -> None:
        queue = app_instance.event_queue.sync_q
        command = [sys.executable, "-m", "colonyos", "daemon", "--no-tui"]
        daemon_env = os.environ.copy()
        daemon_env[_DAEMON_MONITOR_ENV] = "1"
        if max_budget is not None:
            command.extend(["--max-budget", str(max_budget)])
        if unlimited_budget:
            command.append("--unlimited-budget")
        if max_hours is not None:
            command.extend(["--max-hours", str(max_hours)])
        if allow_all_control_users:
            command.append("--allow-all-control-users")
        if verbose:
            command.append("--verbose")
        if dry_run:
            command.append("--dry-run")
        restart_attempt = 0
        while not shutdown_requested.is_set():
            process = subprocess.Popen(
                command,
                cwd=repo_root,
                env=daemon_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            with process_lock:
                process_ref["instance"] = process
            queue.put(NoticeMsg(text=f"Launching daemon subprocess: {' '.join(command)}"))

            def _pump_output() -> None:
                stream = process.stdout
                if stream is None:
                    return
                for line in stream:
                    text = line.rstrip()
                    if text:
                        msg = _parse_daemon_tui_output_line(text)
                        if msg is not None:
                            queue.put(msg)

            pump_thread = threading.Thread(
                target=_pump_output,
                name="daemon-tui-output",
                daemon=True,
            )
            pump_thread.start()

            return_code = process.wait()
            pump_thread.join(timeout=2)
            with process_lock:
                if process_ref.get("instance") is process:
                    process_ref.pop("instance", None)
            queue.put(NoticeMsg(text=f"Daemon exited with code {return_code}"))
            if shutdown_requested.is_set() or return_code == 0:
                break

            restart_attempt += 1
            backoff_seconds = min(30, 2 ** min(restart_attempt - 1, 4))
            queue.put(
                NoticeMsg(
                    text=(
                        f"Daemon exited unexpectedly; restarting in {backoff_seconds}s "
                        f"(attempt {restart_attempt})."
                    )
                )
            )
            logger.warning(
                "Daemon monitor restarting daemon subprocess after exit code %s "
                "(attempt=%d, backoff=%ds)",
                return_code,
                restart_attempt,
                backoff_seconds,
            )
            if shutdown_requested.wait(backoff_seconds):
                break

    def _cancel_callback() -> None:
        _terminate_daemon_process(
            reason="Shutdown requested from TUI",
            mark_shutdown=True,
        )

    app_instance = _DaemonApp(
        run_callback=_run_callback,
        cancel_callback=_cancel_callback,
        monitor_mode=True,
        log_writer=log_writer,
    )

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    previous_sighup = signal.getsignal(signal.SIGHUP) if hasattr(signal, "SIGHUP") else None

    def _sigint_handler(signum, frame) -> None:  # noqa: ANN001
        try:
            app_instance.call_from_thread(app_instance.action_cancel_run)
        except Exception:
            _terminate_daemon_process(
                reason="SIGINT received before TUI was ready",
                mark_shutdown=True,
            )

    def _terminate_handler(signum, frame) -> None:  # noqa: ANN001
        _terminate_daemon_process(
            reason=f"Parent received {signal.Signals(signum).name}",
            force=False,
            mark_shutdown=True,
        )
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, _sigint_handler)
    signal.signal(signal.SIGTERM, _terminate_handler)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, _terminate_handler)
    try:
        app_instance.run()
    finally:
        _terminate_daemon_process(
            reason="TUI exited while daemon subprocess was still running",
            mark_shutdown=True,
        )
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
        if previous_sighup is not None and hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, previous_sighup)


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------


@app.command()
@click.option("--max-budget", type=float, default=None, help="Daily budget cap in USD (overrides config).")
@click.option("--unlimited-budget", is_flag=True, help="Disable the daily daemon budget cap for this session.")
@click.option("--max-hours", type=float, default=None, help="Maximum wall-clock hours before daemon exits.")
@click.option("--allow-all-control-users", is_flag=True, help="Allow Slack control commands from any user for this session.")
@click.option("--tui/--no-tui", default=None, help="Run daemon inside the Textual UI when available.")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging.")
@click.option("--dry-run", is_flag=True, help="Log what would run without executing pipelines.")
def daemon(
    max_budget: float | None,
    unlimited_budget: bool,
    max_hours: float | None,
    allow_all_control_users: bool,
    tui: bool | None,
    verbose: bool,
    dry_run: bool,
) -> None:
    """Start the autonomous daemon — Slack + GitHub + CEO + cleanup in one process."""
    import logging as _logging

    from rich.logging import RichHandler

    from colonyos.config import load_config
    from colonyos.daemon import Daemon, DaemonError

    use_tui = tui if tui is not None else (_interactive_stdio() and _tui_available())
    monitor_mode = os.environ.get(_DAEMON_MONITOR_ENV) == "1"
    log_level = _logging.DEBUG if verbose else _logging.INFO
    if use_tui:
        _logging.basicConfig(
            level=log_level,
            handlers=[_logging.NullHandler()],
            force=True,
        )
    elif monitor_mode:
        _logging.basicConfig(
            level=log_level,
            format="%(message)s",
            handlers=[_logging.StreamHandler(sys.stdout)],
            force=True,
        )
    else:
        _logging.basicConfig(
            level=log_level,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[
                RichHandler(
                    rich_tracebacks=True,
                    markup=True,
                    show_path=verbose,
                    show_time=True,
                )
            ],
            force=True,
        )

    repo_root = Path.cwd()
    config = load_config(repo_root)
    effective_allow_all = allow_all_control_users or config.daemon.allow_all_control_users
    effective_budget = (
        None
        if unlimited_budget
        else max_budget if max_budget is not None else config.daemon.daily_budget_usd
    )
    if allow_all_control_users:
        config.daemon.allow_all_control_users = True

    # Validate daemon prerequisites
    if not config.slack.enabled:
        click.echo("Warning: Slack is not enabled in config. Daemon will run without Slack listener.", err=True)

    if use_tui:
        try:
            _launch_daemon_tui(
                repo_root,
                config,
                max_budget=max_budget,
                unlimited_budget=unlimited_budget,
                max_hours=max_hours,
                allow_all_control_users=allow_all_control_users,
                verbose=verbose,
                dry_run=dry_run,
            )
            return
        except ImportError as exc:
            click.echo(
                f"Error: {exc}\n\nInstall the TUI extra: pip install colonyos[tui]",
                err=True,
            )
            sys.exit(1)

    if not monitor_mode:
        _print_daemon_banner(
            repo_root=repo_root,
            config=config,
            budget_cap=effective_budget,
            max_hours=max_hours,
            dry_run=dry_run,
            allow_all_control_users=effective_allow_all,
        )
        if effective_allow_all:
            click.echo("Control users: all Slack users")
        elif config.daemon.allowed_control_user_ids:
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
        unlimited_budget=unlimited_budget,
        max_hours=max_hours,
        dry_run=dry_run,
        verbose=verbose,
    )

    try:
        d.start()
    except DaemonError as exc:
        raise click.ClickException(str(exc))


# ---------------------------------------------------------------------------
# CI Fix
# ---------------------------------------------------------------------------


@app.command("ci-fix")
@click.argument("pr_ref")
@click.option("--max-retries", default=1, type=int, help="Max fix-push-wait cycles.")
@click.option("--wait/--no-wait", default=False, help="Wait for CI after pushing fix.")
@click.option("--wait-timeout", default=600, type=int, help="Seconds to wait for CI per cycle.")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output.")
def ci_fix(
    pr_ref: str,
    max_retries: int,
    wait: bool,
    wait_timeout: int,
    verbose: bool,
) -> None:
    """Fix CI failures on a pull request.

    PR_REF is a pull request number (e.g. 42) or full GitHub PR URL.
    Fetches failed check logs, runs an AI agent to fix the code, and
    pushes a fix commit.
    """
    from colonyos.ci import (
        all_checks_pass,
        check_pr_author_mismatch,
        collect_ci_failure_context,
        fetch_pr_checks,
        format_ci_failures_as_prompt,
        parse_pr_ref,
        poll_pr_checks,
        validate_branch_not_behind,
        validate_clean_worktree,
        validate_gh_auth,
    )
    from colonyos.orchestrator import _build_ci_fix_prompt, _save_run_log

    repo_root = _find_repo_root()
    config = load_config(repo_root)

    # Parse PR reference
    try:
        pr_number = parse_pr_ref(pr_ref)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    # Pre-flight checks (FR16: validate gh auth upfront)
    validate_gh_auth()
    validate_clean_worktree(repo_root)
    validate_branch_not_behind(repo_root)

    # Warn if PR author differs from authenticated user (prompt injection risk)
    author_warning = check_pr_author_mismatch(pr_number, repo_root)
    if author_warning:
        click.echo(f"[colonyos] {author_warning}", err=True)

    # Create run log for tracking
    ci_run_id = f"ci-fix-{generate_timestamp()}-pr{pr_number}"
    log = RunLog(
        run_id=ci_run_id,
        prompt=f"CI fix for PR #{pr_number}",
        status=RunStatus.RUNNING,
    )

    # Branch name is invariant across retries — resolve once before the loop.
    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, timeout=10, cwd=repo_root,
    )
    branch_name = branch_result.stdout.strip() or "unknown"

    with _repo_runtime_guard(repo_root, "ci-fix"), install_signal_cancel_handlers():
        for attempt in range(1, max_retries + 1):
            click.echo(f"[colonyos] CI fix attempt {attempt}/{max_retries} for PR #{pr_number}")

            # Fetch current checks
            checks = fetch_pr_checks(pr_number, repo_root)
            if all_checks_pass(checks):
                click.echo(f"[colonyos] All CI checks pass on PR #{pr_number}!")
                log.status = RunStatus.COMPLETED
                log.mark_finished()
                _save_run_log(repo_root, log)
                return

            # Collect logs from failed checks (shared helper)
            failures_for_prompt = collect_ci_failure_context(
                checks, repo_root, config.ci_fix.log_char_cap,
            )
            ci_failure_context = format_ci_failures_as_prompt(failures_for_prompt)

            # Build prompt and run agent
            system, user = _build_ci_fix_prompt(
                config, branch_name, ci_failure_context, attempt, max_retries,
            )

            from colonyos.agent import run_phase_sync as _run_phase
            from colonyos.models import Phase
            phase_result = _run_phase(
                Phase.CI_FIX,
                user,
                cwd=repo_root,
                system_prompt=system,
                model=config.get_model(Phase.CI_FIX),
                budget_usd=config.budget.per_phase,
                ui=None,
            )
            log.phases.append(phase_result)

            if not phase_result.success:
                click.echo(f"[colonyos] CI fix agent failed: {phase_result.error}", err=True)
                if attempt >= max_retries:
                    break
                continue

            click.echo("[colonyos] CI fix agent completed. Pushing changes...")

            # Push the fix commit — abort on failure to avoid wasting retries
            push_result = subprocess.run(
                ["git", "push"],
                capture_output=True, text=True, timeout=60, cwd=repo_root,
            )
            if push_result.returncode != 0:
                click.echo(
                    f"[colonyos] Failed to push: {push_result.stderr.strip()}",
                    err=True,
                )
                log.status = RunStatus.COMPLETED
                log.mark_finished()
                _save_run_log(repo_root, log)
                sys.exit(1)

            # If --wait, poll for CI results (unified logic for all attempts)
            if wait:
                click.echo(f"[colonyos] Waiting for CI checks (timeout: {wait_timeout}s)...")
                try:
                    final_checks = poll_pr_checks(pr_number, repo_root, timeout=wait_timeout)
                    if all_checks_pass(final_checks):
                        click.echo(f"[colonyos] CI checks now pass on PR #{pr_number}!")
                        log.status = RunStatus.COMPLETED
                        log.mark_finished()
                        _save_run_log(repo_root, log)
                        return
                    click.echo("[colonyos] CI still failing after fix attempt.")
                except click.ClickException as exc:
                    click.echo(f"[colonyos] {exc.message}", err=True)

    # Retries exhausted
    click.echo(
        f"[colonyos] CI fix retries exhausted ({max_retries} attempts) for PR #{pr_number}.",
        err=True,
    )
    log.status = RunStatus.COMPLETED  # Still COMPLETED per FR20, but with success=False phases
    log.mark_finished()
    _save_run_log(repo_root, log)
    sys.exit(1)


# ---------------------------------------------------------------------------
# colonyos cleanup — codebase hygiene & structural analysis
# ---------------------------------------------------------------------------


@app.group(invoke_without_command=True)
@click.pass_context
def cleanup(ctx: click.Context) -> None:
    """Codebase hygiene: prune branches, clean artifacts, scan for complexity."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cleanup.command("branches")
@click.option("--execute", is_flag=True, help="Actually delete branches (default: dry-run).")
@click.option("--include-remote", is_flag=True, help="Also prune merged branches from origin.")
@click.option("--all-branches", is_flag=True, help="Include all merged branches, not just colonyos/ prefix.")
@click.option("--prefix", default=None, help="Branch prefix to filter (default: from config).")
def cleanup_branches(
    execute: bool,
    include_remote: bool,
    all_branches: bool,
    prefix: str | None,
) -> None:
    """List and prune merged branches."""
    from rich.console import Console
    from rich.table import Table

    from colonyos.cleanup import (
        list_merged_branches,
        delete_branches,
        write_cleanup_log,
    )

    repo_root = _find_repo_root()
    config = load_config(repo_root)
    branch_prefix = prefix if prefix is not None else config.branch_prefix

    branches = list_merged_branches(
        repo_root,
        prefix=branch_prefix,
        include_all=all_branches,
    )

    if not branches:
        click.echo("No merged branches found to clean up.")
        return

    result = delete_branches(
        branches,
        repo_root,
        include_remote=include_remote,
        execute=execute,
    )

    con = Console()
    mode = "EXECUTED" if execute else "DRY-RUN"

    # Display results table
    table = Table(
        title=f"Branch Cleanup [{mode}]",
        show_header=True,
        header_style="bold",
        padding=(0, 2),
    )
    table.add_column("Branch", style="cyan")
    table.add_column("Last Commit", style="dim")
    table.add_column("Action", justify="center")

    for name in result.deleted_local:
        table.add_row(name, "", "[green]delete[/green]" if execute else "[yellow]would delete[/yellow]")

    for info in result.skipped:
        table.add_row(info.name, info.last_commit_date, f"[dim]skip ({info.skip_reason})[/dim]")

    con.print(table)

    # Summary
    click.echo(
        f"\n{len(result.deleted_local)} local branch(es) {'deleted' if execute else 'would be deleted'}"
    )
    if include_remote:
        click.echo(
            f"{len(result.deleted_remote)} remote branch(es) {'deleted' if execute else 'would be deleted'}"
        )
    if result.skipped:
        click.echo(f"{len(result.skipped)} branch(es) skipped")
    for err in result.errors:
        click.echo(f"  Error: {err}", err=True)

    if not execute and result.deleted_local:
        click.echo("\nRe-run with --execute to delete.")

    # Audit log
    log_data = {
        "deleted_local": result.deleted_local,
        "deleted_remote": result.deleted_remote,
        "skipped": [{"name": s.name, "reason": s.skip_reason} for s in result.skipped],
        "errors": result.errors,
        "execute": execute,
    }
    write_cleanup_log(runs_dir_path(repo_root), "branches", log_data)


@cleanup.command("artifacts")
@click.option("--execute", is_flag=True, help="Actually delete artifacts (default: dry-run).")
@click.option("--retention-days", type=int, default=None, help="Override retention period in days.")
def cleanup_artifacts(
    execute: bool,
    retention_days: int | None,
) -> None:
    """Remove old run artifacts beyond the retention period."""
    from rich.console import Console
    from rich.table import Table

    from colonyos.cleanup import (
        list_stale_artifacts,
        delete_artifacts,
        write_cleanup_log,
    )

    repo_root = _find_repo_root()
    config = load_config(repo_root)
    days = retention_days if retention_days is not None else config.cleanup.artifact_retention_days
    runs_dir = runs_dir_path(repo_root)

    stale, skipped = list_stale_artifacts(runs_dir, retention_days=days)

    if not stale:
        click.echo(f"No stale artifacts found (retention: {days} days).")
        return

    result = delete_artifacts(stale, execute=execute)

    con = Console()
    mode = "EXECUTED" if execute else "DRY-RUN"

    table = Table(
        title=f"Artifact Cleanup [{mode}]",
        show_header=True,
        header_style="bold",
        padding=(0, 2),
    )
    table.add_column("Run ID", style="cyan")
    table.add_column("Date", style="dim")
    table.add_column("Status")
    table.add_column("Size", justify="right")

    for artifact in result.removed:
        size_kb = artifact.size_bytes / 1024
        table.add_row(
            artifact.run_id,
            artifact.date[:10] if len(artifact.date) >= 10 else artifact.date,
            artifact.status,
            f"{size_kb:.1f} KB",
        )

    con.print(table)

    total_mb = result.bytes_reclaimed / (1024 * 1024)
    click.echo(
        f"\n{len(result.removed)} artifact(s) {'removed' if execute else 'would be removed'}, "
        f"{total_mb:.2f} MB {'reclaimed' if execute else 'reclaimable'}"
    )
    for err in result.errors:
        click.echo(f"  Error: {err}", err=True)

    if not execute and result.removed:
        click.echo("\nRe-run with --execute to delete.")

    # Audit log
    log_data = {
        "removed": [{"run_id": a.run_id, "size_bytes": a.size_bytes} for a in result.removed],
        "bytes_reclaimed": result.bytes_reclaimed,
        "errors": result.errors,
        "execute": execute,
        "retention_days": days,
    }
    write_cleanup_log(runs_dir, "artifacts", log_data)


def _run_cleanup_scan_impl(
    repo_root: Path,
    config: ColonyConfig,
    *,
    max_lines: int | None,
    max_functions: int | None,
    use_ai: bool,
    refactor_file: str | None,
) -> None:
    """Shared implementation for CLI and TUI cleanup scans."""
    from rich.console import Console
    from rich.table import Table

    from colonyos.cleanup import (
        scan_directory,
        synthesize_refactor_prompt,
        write_cleanup_log,
    )

    lines_threshold = max_lines if max_lines is not None else config.cleanup.scan_max_lines
    funcs_threshold = max_functions if max_functions is not None else config.cleanup.scan_max_functions

    # If --refactor, synthesize prompt and delegate to colonyos run
    if refactor_file:
        results = scan_directory(repo_root, lines_threshold, funcs_threshold)
        prompt = synthesize_refactor_prompt(refactor_file, scan_results=results)
        click.echo(f"Delegating refactoring to `colonyos run`:\n\n{prompt}\n")
        try:
            with _repo_runtime_guard(repo_root, "cleanup-refactor"), install_signal_cancel_handlers():
                log = run_orchestrator(
                    prompt,
                    repo_root=repo_root,
                    config=config,
                )
            _print_run_summary(log)
        except PreflightError as exc:
            click.echo(f"Preflight error: {exc.format_message()}", err=True)
            sys.exit(1)
        return

    results = scan_directory(repo_root, lines_threshold, funcs_threshold)

    con = Console()

    if not results:
        click.echo(
            f"No files exceed thresholds (lines > {lines_threshold}, functions > {funcs_threshold})."
        )
        return

    table = Table(
        title="Structural Scan Results",
        show_header=True,
        header_style="bold",
        padding=(0, 2),
    )
    table.add_column("File", style="cyan")
    table.add_column("Lines", justify="right")
    table.add_column("Functions", justify="right")
    table.add_column("Category", justify="center")

    category_styles = {
        "large": "yellow",
        "very-large": "bold yellow",
        "massive": "bold red",
    }

    for fc in results:
        cat_style = category_styles.get(fc.category.value, "")
        cat_display = f"[{cat_style}]{fc.category.value}[/{cat_style}]"
        table.add_row(
            fc.path,
            str(fc.line_count),
            str(fc.function_count),
            cat_display,
        )

    con.print(table)
    click.echo(f"\n{len(results)} file(s) flagged.")

    # Audit log
    log_data = {
        "files_flagged": len(results),
        "thresholds": {"max_lines": lines_threshold, "max_functions": funcs_threshold},
        "results": [
            {"path": r.path, "lines": r.line_count, "functions": r.function_count, "category": r.category.value}
            for r in results
        ],
    }
    write_cleanup_log(runs_dir_path(repo_root), "scan", log_data)

    # AI scan
    if use_ai:
        click.echo("\nRunning AI structural analysis...")
        try:
            from colonyos.agent import run_phase_sync
            from colonyos.models import Phase

            instructions_dir = Path(__file__).parent / "instructions"
            base_prompt = (instructions_dir / "base.md").read_text(encoding="utf-8")
            scan_prompt = (instructions_dir / "cleanup_scan.md").read_text(encoding="utf-8")
            system_prompt = base_prompt + "\n\n" + scan_prompt

            scan_summary = "\n".join(
                f"- `{r.path}`: {r.line_count} lines, {r.function_count} functions ({r.category.value})"
                for r in results
            )
            prompt = (
                f"Analyze this codebase for structural issues. "
                f"The static scan found these files exceeding thresholds:\n\n{scan_summary}\n\n"
                f"Perform a deep qualitative analysis of the codebase."
            )

            phase_result = run_phase_sync(
                phase=Phase.REVIEW,
                prompt=prompt,
                cwd=repo_root,
                system_prompt=system_prompt,
                model=config.get_model(Phase.REVIEW),
                budget_usd=config.budget.per_phase,
                allowed_tools=["Read", "Glob", "Grep", "Agent"],
                timeout_seconds=config.budget.phase_timeout_seconds,
            )

            if phase_result.success and phase_result.artifacts.get("result"):
                report = phase_result.artifacts["result"]
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                report_path = runs_dir_path(repo_root) / f"cleanup_{timestamp}.md"
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(report, encoding="utf-8")
                click.echo(f"\nAI analysis report saved to: {report_path}")
            else:
                error = phase_result.error or "Unknown error"
                click.echo(f"\nAI scan failed: {error[:200]}", err=True)

        except Exception as exc:
            click.echo(f"\nAI scan error: {exc}", err=True)


@cleanup.command("scan")
@click.option("--max-lines", type=int, default=None, help="Line count threshold (default: from config).")
@click.option("--max-functions", type=int, default=None, help="Function count threshold (default: from config).")
@click.option("--ai", "use_ai", is_flag=True, help="Run AI-powered qualitative analysis (uses budget).")
@click.option("--refactor", "refactor_file", type=click.Path(), default=None, help="Delegate refactoring of FILE to colonyos run.")
def cleanup_scan(
    max_lines: int | None,
    max_functions: int | None,
    use_ai: bool,
    refactor_file: str | None,
) -> None:
    """Scan codebase for structural complexity."""
    repo_root = _find_repo_root()
    config = load_config(repo_root)
    _run_cleanup_scan_impl(
        repo_root,
        config,
        max_lines=max_lines,
        max_functions=max_functions,
        use_ai=use_ai,
        refactor_file=refactor_file,
    )


# ---------------------------------------------------------------------------
# colonyos sweep — autonomous codebase quality agent
# ---------------------------------------------------------------------------


@app.command()
@click.argument("path", required=False, default=None)
@click.option("--execute", is_flag=True, help="Run the implement→review pipeline on findings (default: dry-run report only).")
@click.option("--plan-only", is_flag=True, help="Generate analysis + task file but stop before implementation.")
@click.option("--max-tasks", type=int, default=None, help="Cap the number of findings (default: from config).")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output.")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output.")
@click.option("--no-tui", is_flag=True, help="Force plain streaming output.")
@click.option("--force", is_flag=True, help="Bypass pre-flight checks.")
def sweep(path: str | None, execute: bool, plan_only: bool, max_tasks: int | None, verbose: bool, quiet: bool, no_tui: bool, force: bool) -> None:
    """Analyze codebase for quality issues and optionally fix them.

    By default, runs in dry-run mode: prints a prioritized findings report.
    Use --execute to feed findings through the implement→review pipeline.
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

    runtime_guard = _repo_runtime_guard(repo_root, "sweep")
    signal_guard = install_signal_cancel_handlers()

    try:
        from colonyos.orchestrator import run_sweep as _run_sweep, parse_sweep_findings

        ui = None
        if not quiet:
            from colonyos.ui import PhaseUI

            ui = PhaseUI(verbose=verbose)

        with runtime_guard, signal_guard:
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


# ---------------------------------------------------------------------------
# colonyos ui — local web dashboard
# ---------------------------------------------------------------------------


@app.command()
@click.option("--host", default="127.0.0.1", type=str, help="Host to bind to (default: 127.0.0.1)")
@click.option("--port", default=7400, type=int, help="Port to serve on (default: 7400)")
@click.option("--no-open", is_flag=True, help="Don't auto-open browser")
@click.option("--write", is_flag=True, help="Enable write endpoints (config editing, run launching)")
def ui(host: str, port: int, no_open: bool, write: bool) -> None:
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

    url = f"http://{host}:{port}"
    click.echo(f"[colonyos] Starting dashboard at {url}")
    if os.environ.get("COLONYOS_WRITE_ENABLED"):
        click.echo(f"[colonyos] Write mode ENABLED — auth token: {auth_token}")

    if not no_open and host in ("127.0.0.1", "localhost"):
        import webbrowser

        webbrowser.open(url)

    try:
        uvicorn.run(fast_app, host=host, port=port, log_level="warning")
    except KeyboardInterrupt:
        click.echo("\n[colonyos] Dashboard stopped.")


# ---------------------------------------------------------------------------
# PR Review Command
# ---------------------------------------------------------------------------


@app.command("pr-review")
@click.argument("pr_number", type=int)
@click.option("--watch", is_flag=True, help="Continuously poll for new review comments.")
@click.option("--poll-interval", default=None, type=int, help="Poll interval in seconds (default: 60).")
@click.option("--max-cost", default=None, type=float, help="Override per-PR budget cap (default: $5).")
@click.option("-v", "--verbose", is_flag=True, help="Stream agent text output.")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output.")
def pr_review(
    pr_number: int,
    watch: bool,
    poll_interval: int | None,
    max_cost: float | None,
    verbose: bool,
    quiet: bool,
) -> None:
    """Monitor and auto-fix PR review comments.

    PR_NUMBER is the pull request number to monitor.

    Fetches inline review comments, triages them for actionability,
    and runs the fix pipeline for actionable feedback. Posts replies
    to comment threads with fix commit links.

    Use --watch for continuous monitoring of new comments.
    """
    from colonyos.pr_review import (
        PRReviewState,
        build_commit_url,
        check_budget_cap,
        check_circuit_breaker,
        check_fix_rounds,
        fetch_pr_review_comments,
        fetch_pr_state,
        format_fix_reply,
        format_summary_message,
        load_pr_review_state,
        post_pr_review_reply,
        post_pr_summary_comment,
        save_pr_review_state,
        triage_pr_review_comment,
    )
    from colonyos.orchestrator import run_thread_fix

    repo_root = _find_repo_root()
    config = load_config(repo_root)

    if not config.project:
        click.echo(
            "No ColonyOS config found. Run `colonyos init` first.",
            err=True,
        )
        sys.exit(1)

    # Resolve poll interval and budget
    effective_poll_interval = poll_interval or config.pr_review.poll_interval_seconds
    effective_budget = max_cost or config.pr_review.budget_per_pr

    # Check PR state (FR-14: skip merged/closed PRs)
    try:
        pr_state = fetch_pr_state(pr_number, repo_root)
    except Exception as exc:
        click.echo(f"Error fetching PR #{pr_number}: {exc}", err=True)
        sys.exit(1)

    if pr_state.state in ("merged", "closed"):
        click.echo(f"PR #{pr_number} is {pr_state.state}. Nothing to do.")
        return

    click.echo(f"[colonyos] Monitoring PR #{pr_number} on branch {pr_state.head_ref}")
    click.echo(f"[colonyos] Budget: ${effective_budget:.2f}, Poll interval: {effective_poll_interval}s")

    # Load or create state
    loaded_state = load_pr_review_state(repo_root, pr_number)
    state: PRReviewState
    if loaded_state is None:
        state = PRReviewState(pr_number)
        save_pr_review_state(repo_root, state)
    else:
        state = loaded_state

    def process_comments() -> list[tuple[str, str]]:
        """Process new actionable comments. Returns list of (sha, summary) for fixes."""
        nonlocal state, pr_state
        fixes_applied: list[tuple[str, str]] = []

        # Safety checks
        if not check_budget_cap(state, effective_budget):
            click.echo(
                f"[colonyos] Budget cap reached (${state.cumulative_cost_usd:.2f} spent). "
                "Pausing auto-fixes."
            )
            post_pr_summary_comment(
                pr_number,
                f"Max budget reached (${state.cumulative_cost_usd:.2f} spent), pausing auto-fixes.",
                repo_root,
            )
            return fixes_applied

        if not check_circuit_breaker(state, config.pr_review.circuit_breaker_threshold):
            # Set pause state for circuit breaker cooldown
            if not state.queue_paused:
                state.queue_paused = True
                state.queue_paused_at = datetime.now(timezone.utc).isoformat()
                save_pr_review_state(repo_root, state)
            cooldown = config.pr_review.circuit_breaker_cooldown_minutes
            click.echo(
                f"[colonyos] Circuit breaker triggered ({state.consecutive_failures} failures). "
                f"Will auto-recover after {cooldown} minutes."
            )
            return fixes_applied

        if not check_fix_rounds(state, config.pr_review.max_fix_rounds_per_pr):
            click.echo(
                f"[colonyos] Max fix rounds reached ({state.fix_rounds}). Stopping."
            )
            return fixes_applied

        # Fetch comments
        try:
            comments = fetch_pr_review_comments(pr_number, repo_root)
        except Exception as exc:
            click.echo(f"[colonyos] Error fetching comments: {exc}", err=True)
            state.consecutive_failures += 1
            save_pr_review_state(repo_root, state)
            return fixes_applied

        # Filter to new comments only (FR-8: only comments after watch_started_at)
        # Also exclude already-processed comments for deduplication across restarts
        # Use datetime parsing for robust ISO timestamp comparison
        watch_started_dt = datetime.fromisoformat(state.watch_started_at)
        new_comments = [
            c for c in comments
            if not state.is_processed(c.id)
            and datetime.fromisoformat(c.created_at) >= watch_started_dt
        ]

        if not new_comments:
            if not quiet:
                click.echo(f"[colonyos] No new actionable comments found.")
            return fixes_applied

        click.echo(f"[colonyos] Found {len(new_comments)} new comment(s) to process.")

        for comment in new_comments:
            if not check_budget_cap(state, effective_budget):
                click.echo("[colonyos] Budget cap reached during processing. Stopping.")
                break

            # Triage the comment
            if not quiet:
                click.echo(f"[colonyos] Triaging comment {comment.id} from @{comment.reviewer}...")

            try:
                triage_result = triage_pr_review_comment(
                    comment.body,
                    file_path=comment.path,
                    line_number=comment.line,
                    repo_root=repo_root,
                    project_name=config.project.name if config.project else "",
                    project_description=config.project.description if config.project else "",
                    project_stack=config.project.stack if config.project else "",
                    vision=config.vision,
                )
            except Exception as exc:
                click.echo(f"[colonyos] Triage error: {exc}", err=True)
                state.mark_processed(comment.id, "triage-error")
                save_pr_review_state(repo_root, state)
                continue

            if not triage_result.actionable:
                if not quiet:
                    click.echo(
                        f"[colonyos] Comment {comment.id} not actionable: {triage_result.reasoning[:100]}"
                    )
                state.mark_processed(comment.id, "not-actionable")
                save_pr_review_state(repo_root, state)
                continue

            click.echo(
                f"[colonyos] Comment {comment.id} is actionable ({triage_result.confidence:.0%}): "
                f"{triage_result.summary}"
            )

            # Find PRD and task files for the branch
            prd_rel, task_rel = _find_branch_artifacts(repo_root, config, pr_state.head_ref)

            # Run the fix pipeline (FR-15: use source_type for analytics)
            # Security: Sanitize untrusted comment body before passing to fix agent
            from colonyos.sanitize import sanitize_untrusted_content
            sanitized_comment_body = sanitize_untrusted_content(comment.body)

            try:
                run_log = run_thread_fix(
                    fix_prompt=sanitized_comment_body,
                    branch_name=pr_state.head_ref,
                    pr_url=pr_state.url,
                    original_prompt=triage_result.summary,
                    prd_rel=prd_rel,
                    task_rel=task_rel,
                    repo_root=repo_root,
                    config=config,
                    verbose=verbose,
                    quiet=quiet,
                    expected_head_sha=pr_state.head_sha,
                    source_type="pr_review_fix",
                    review_comment_id=comment.id,
                    # PR review context for template selection and rich prompts
                    pr_review_context={
                        "file_path": comment.path,
                        "line_number": comment.line,
                        "reviewer_username": comment.reviewer,
                        "comment_url": comment.html_url,
                        "review_comment": sanitized_comment_body,
                    },
                )

                # Update state
                state.cumulative_cost_usd += run_log.total_cost_usd
                state.fix_rounds += 1

                if run_log.status == RunStatus.COMPLETED:
                    # Get the commit SHA from the most recent commit
                    commit_sha = _get_latest_commit_sha(repo_root)
                    commit_url = build_commit_url(pr_state.url, commit_sha)

                    # Post reply to comment thread (FR-5)
                    reply_msg = format_fix_reply(
                        commit_sha, commit_url, triage_result.summary
                    )
                    post_pr_review_reply(pr_number, comment.id, reply_msg, repo_root)

                    fixes_applied.append((commit_sha, triage_result.summary))
                    state.consecutive_failures = 0
                    state.mark_processed(comment.id, run_log.run_id)
                    click.echo(f"[colonyos] Fix applied: {commit_sha[:7]}")

                    # Update expected HEAD SHA for subsequent fixes in this cycle
                    # This prevents SHA mismatch errors when processing multiple comments
                    from colonyos.pr_review import PRState
                    pr_state = PRState(
                        state=pr_state.state,
                        head_sha=commit_sha,
                        head_ref=pr_state.head_ref,
                        url=pr_state.url,
                    )
                else:
                    state.consecutive_failures += 1
                    state.mark_processed(comment.id, f"failed-{run_log.run_id}")
                    click.echo(f"[colonyos] Fix failed for comment {comment.id}")

            except Exception as exc:
                click.echo(f"[colonyos] Fix error: {exc}", err=True)
                state.consecutive_failures += 1
                state.mark_processed(comment.id, "fix-error")

            save_pr_review_state(repo_root, state)

        return fixes_applied

    with _repo_runtime_guard(repo_root, "pr-review"), install_signal_cancel_handlers():
        # Single run or watch mode
        if watch:
            click.echo("[colonyos] Watch mode enabled. Press Ctrl+C to stop.")
            try:
                while True:
                    # Re-check PR state each cycle
                    try:
                        pr_state = fetch_pr_state(pr_number, repo_root)
                        if pr_state.state in ("merged", "closed"):
                            click.echo(f"[colonyos] PR #{pr_number} is now {pr_state.state}. Exiting watch mode.")
                            break
                    except Exception as exc:
                        # Log the error but continue watching - transient network issues
                        # shouldn't stop the watch loop. Log for debugging.
                        logger.warning(
                            "Failed to check PR #%d state during watch: %s",
                            pr_number, exc,
                        )
                        # Continue watching

                    # Skip processing if circuit breaker is open (still cooling down)
                    if state.queue_paused:
                        # Check if cooldown has expired for auto-recovery
                        if state.queue_paused_at:
                            try:
                                paused_at = datetime.fromisoformat(state.queue_paused_at)
                                cooldown_sec = config.pr_review.circuit_breaker_cooldown_minutes * 60
                                elapsed = (datetime.now(timezone.utc) - paused_at).total_seconds()
                                if elapsed >= cooldown_sec:
                                    # Auto-recover
                                    state.queue_paused = False
                                    state.queue_paused_at = None
                                    state.consecutive_failures = 0
                                    save_pr_review_state(repo_root, state)
                                    click.echo("[colonyos] Circuit breaker auto-recovered after cooldown.")
                                else:
                                    remaining = (cooldown_sec - elapsed) / 60
                                    if not quiet:
                                        click.echo(f"[colonyos] Circuit breaker paused. {remaining:.0f} minutes remaining.")
                                    time.sleep(effective_poll_interval)
                                    continue
                            except (ValueError, TypeError):
                                # Malformed timestamp; remain paused
                                time.sleep(effective_poll_interval)
                                continue

                    fixes = process_comments()

                    # Post summary if fixes were applied (FR-6)
                    if fixes:
                        summary_msg = format_summary_message(fixes)
                        post_pr_summary_comment(pr_number, summary_msg, repo_root)

                    # Check safety guards before sleeping
                    if not check_budget_cap(state, effective_budget):
                        click.echo("[colonyos] Budget exhausted. Exiting watch mode.")
                        break

                    # Circuit breaker with cooldown/recovery (FR-13)
                    if not check_circuit_breaker(state, config.pr_review.circuit_breaker_threshold):
                        if not state.queue_paused:
                            # First trigger: set pause timestamp
                            state.queue_paused = True
                            state.queue_paused_at = datetime.now(timezone.utc).isoformat()
                            save_pr_review_state(repo_root, state)
                            cooldown = config.pr_review.circuit_breaker_cooldown_minutes
                            click.echo(
                                f"[colonyos] Circuit breaker triggered ({state.consecutive_failures} "
                                f"consecutive failures). Will auto-recover after {cooldown} minutes."
                            )
                        else:
                            # Check if cooldown has expired for auto-recovery
                            if state.queue_paused_at:
                                try:
                                    paused_at = datetime.fromisoformat(state.queue_paused_at)
                                    cooldown_sec = config.pr_review.circuit_breaker_cooldown_minutes * 60
                                    elapsed = (datetime.now(timezone.utc) - paused_at).total_seconds()
                                    if elapsed >= cooldown_sec:
                                        # Auto-recover
                                        state.queue_paused = False
                                        state.queue_paused_at = None
                                        state.consecutive_failures = 0
                                        save_pr_review_state(repo_root, state)
                                        click.echo("[colonyos] Circuit breaker auto-recovered after cooldown.")
                                except (ValueError, TypeError):
                                    pass  # Malformed timestamp; remain paused
                        # Sleep during pause, then loop to re-check
                        time.sleep(effective_poll_interval)
                        continue

                    time.sleep(effective_poll_interval)

            except KeyboardInterrupt:
                click.echo("\n[colonyos] Watch mode stopped.")
        else:
            # Single run
            fixes = process_comments()
            if fixes:
                summary_msg = format_summary_message(fixes)
                post_pr_summary_comment(pr_number, summary_msg, repo_root)
                click.echo(f"[colonyos] Applied {len(fixes)} fix(es).")
            else:
                click.echo("[colonyos] No fixes applied.")

    # Final state save
    save_pr_review_state(repo_root, state)
    click.echo(f"[colonyos] Total cost: ${state.cumulative_cost_usd:.2f}")


def _find_branch_artifacts(
    repo_root: Path,
    config: ColonyConfig,
    branch_name: str,
) -> tuple[str, str]:
    """Find PRD and task files associated with a branch.

    Returns (prd_rel, task_rel) paths relative to repo root.
    Falls back to empty strings if not found.
    """
    prd_dir = repo_root / config.prds_dir
    task_dir = repo_root / config.tasks_dir

    # Try to find files that match the branch slug
    branch_slug = branch_name.replace(config.branch_prefix, "").replace("/", "_")

    prd_rel = ""
    task_rel = ""

    if prd_dir.exists():
        for prd_file in prd_dir.glob("*prd*.md"):
            if branch_slug in prd_file.name or branch_name in prd_file.name:
                prd_rel = str(prd_file.relative_to(repo_root))
                break

    if task_dir.exists():
        for task_file in task_dir.glob("*tasks*.md"):
            if branch_slug in task_file.name or branch_name in task_file.name:
                task_rel = str(task_file.relative_to(repo_root))
                break

    return prd_rel, task_rel


def _get_latest_commit_sha(repo_root: Path) -> str:
    """Get the SHA of the latest commit."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# TUI (Textual) interactive terminal UI
# ---------------------------------------------------------------------------


def _launch_tui(
    repo_root: Path,
    config: ColonyConfig,
    prompt: str | None = None,
    verbose: bool = False,
) -> None:
    """Launch the interactive Textual TUI.

    Imports the ``colonyos.tui`` package lazily so that the ``textual``
    dependency is only required when the TUI is actually used.

    Raises:
        ImportError: If textual or janus is not installed.
    """
    import colonyos.tui  # noqa: F401 — triggers dependency check
    from colonyos.tui.app import AssistantApp
    from colonyos.tui.adapter import CommandOutputMsg, TextBlockMsg, TextualUI

    current_adapter: TextualUI | None = None
    last_direct_session_id: str | None = None
    command_hints = _tui_command_hints()
    def _recovery_callback(text: str) -> None:
        nonlocal current_adapter
        queue = app_instance.event_queue

        recovery_state = app_instance.get_dirty_worktree_recovery()
        if recovery_state is None:
            queue.sync_q.put(CommandOutputMsg(text="No dirty-worktree recovery is pending."))
            app_instance.call_from_thread(app_instance.clear_dirty_worktree_recovery)
            return
        saved_prompt, recovery_error = recovery_state

        command = text.strip().lower()
        if command == "cancel":
            app_instance.call_from_thread(app_instance.cancel_dirty_worktree_recovery)
            return

        if command != "commit":
            queue.sync_q.put(CommandOutputMsg(text=_dirty_recovery_help()))
            return

        queue.sync_q.put(CommandOutputMsg(text="Starting dirty-worktree recovery agent..."))
        adapter = TextualUI(queue.sync_q)
        current_adapter = adapter
        try:
            branch_name = recovery_error.details.get("current_branch")
            dirty_output = str(recovery_error.details.get("dirty_output", "")).strip()
            result = run_preflight_recovery(
                repo_root,
                config,
                blocked_prompt=saved_prompt,
                dirty_output=dirty_output or recovery_error.format_message(),
                branch_name=branch_name if isinstance(branch_name, str) else None,
                ui=cast(Any, adapter),
            )
        except Exception as exc:
            logger.exception("Dirty-worktree recovery failed")
            app_instance.call_from_thread(
                app_instance.show_run_blocked,
                saved_prompt,
                f"{type(exc).__name__}: {exc}",
            )
            return
        finally:
            current_adapter = None

        if not result.success:
            app_instance.call_from_thread(
                app_instance.show_run_blocked,
                saved_prompt,
                result.error or "Preflight recovery failed.",
            )
            return

        app_instance.call_from_thread(app_instance.clear_dirty_worktree_recovery)
        queue.sync_q.put(CommandOutputMsg(text="Recovery commit completed. Retrying saved prompt..."))
        _run_callback(saved_prompt)

    def _run_callback(text: str) -> None:
        """Run the orchestrator in a worker thread when the user submits input.

        Each submission creates a fresh TextualUI adapter so that turn counts
        and tool state are isolated per-run.  The status bar accumulates cost
        across runs independently — this is intentional so users see lifetime
        session cost while each run's turn count starts at zero.
        """
        nonlocal current_adapter, last_direct_session_id
        queue = app_instance.event_queue

        handled, command_output, should_exit = _handle_tui_command(text, config=config)
        if handled:
            if command_output == _AUTO_COMMAND_SIGNAL:
                _run_auto_in_tui(text)
                return
            if command_output:
                queue.sync_q.put(CommandOutputMsg(text=command_output))
            # Clear conversation state on /new command
            if command_output == _NEW_CONVERSATION_SIGNAL:
                last_direct_session_id = None
            current_adapter = None
            if should_exit:
                app_instance.call_from_thread(app_instance.exit)
            return

        adapter = TextualUI(queue.sync_q)
        current_adapter = adapter

        def _ui_factory(
            prefix: str = "",
            *,
            badge: object | None = None,
            task_id: str | None = None,
        ) -> TextualUI:
            if badge is None and task_id is None and not prefix:
                return adapter
            return TextualUI(
                queue.sync_q,
                badge=badge,  # type: ignore[arg-type]
                task_id=task_id,
            )

        route_outcome = _route_prompt(
            text,
            config,
            repo_root,
            source="tui",
            quiet=True,
            continuation_active=last_direct_session_id is not None,
        )
        if route_outcome.announcement:
            queue.sync_q.put(TextBlockMsg(text=route_outcome.announcement))
        if route_outcome.display_text is not None:
            queue.sync_q.put(TextBlockMsg(text=route_outcome.display_text))
            current_adapter = None
            return

        try:
            if route_outcome.mode == "direct_agent":
                # Emit continuation indicator when resuming a prior conversation
                if last_direct_session_id is not None:
                    queue.sync_q.put(TextBlockMsg(text="Continuing conversation..."))

                with _repo_runtime_guard(repo_root, "direct-agent"):
                    success, session_id = _run_direct_agent(
                        text,
                        repo_root=repo_root,
                        config=config,
                        ui=adapter,
                        resume_session_id=last_direct_session_id,
                    )
                if success and session_id:
                    last_direct_session_id = session_id
                elif not success:
                    # Clear stale session on failure to avoid repeated retries
                    last_direct_session_id = None
                return

            # Non-direct-agent mode: clear conversation state
            last_direct_session_id = None
            if route_outcome.mode == "review_only":
                output, _approved = _capture_click_output_and_result(
                    _run_review_only_flow,
                    repo_root=repo_root,
                    config=config,
                    verbose=verbose,
                    quiet=False,
                )
                if output:
                    queue.sync_q.put(CommandOutputMsg(text=output))
                return

            if route_outcome.mode == "cleanup_loop":
                output, _ = _capture_click_output_and_result(_run_cleanup_loop)
                if output:
                    queue.sync_q.put(CommandOutputMsg(text=output))
                return

            from_prd = route_outcome.from_prd
            if route_outcome.mode == "implement_only":
                from_prd = _resolve_latest_prd_path(repo_root, config)
                queue.sync_q.put(CommandOutputMsg(text=f"Using latest PRD: {from_prd}"))

            with _repo_runtime_guard(repo_root, "interactive-tui"):
                run_orchestrator(
                    text,
                    repo_root=repo_root,
                    config=config,
                    verbose=verbose,
                    ui_factory=_ui_factory,
                    skip_planning=route_outcome.skip_planning,
                    from_prd=from_prd,
                    user_injection_provider=adapter.drain_user_injections,
                )
        except PreflightError as exc:
            logger.info("TUI run blocked by preflight: %s", exc)
            if exc.code == "dirty_worktree":
                app_instance.call_from_thread(app_instance.begin_dirty_worktree_recovery, text, exc)
            else:
                app_instance.call_from_thread(app_instance.show_run_blocked, text, str(exc))
        except Exception as exc:
            logger.exception("Unhandled TUI run failure")
            app_instance.call_from_thread(
                app_instance.show_run_blocked,
                text,
                f"{type(exc).__name__}: {exc}",
            )
        finally:
            current_adapter = None

    def _run_auto_in_tui(raw_text: str) -> None:
        """Run the auto loop inside the TUI, using the TextualUI adapter for output."""
        import shlex
        import time as _time

        from colonyos.ceo_profiles import get_ceo_profile
        from colonyos.tui.adapter import IterationHeaderMsg, LoopCompleteMsg, TextualUI

        nonlocal current_adapter

        # Guard against concurrent auto loops (FR-1.7)
        if app_instance._auto_loop_active:
            queue = app_instance.event_queue
            queue.sync_q.put(CommandOutputMsg(
                text="An auto loop is already running. Wait for it to finish or press Ctrl+C to cancel."
            ))
            return

        try:
            tokens = shlex.split(raw_text)
        except ValueError:
            tokens = raw_text.split()

        # Parse auto options from tokens (--loop, --max-budget, --max-hours, --persona)
        loop_count = 1
        max_budget: float | None = None
        max_hours: float | None = None
        persona_name: str | None = None
        for i, tok in enumerate(tokens):
            if tok == "--loop" and i + 1 < len(tokens):
                try:
                    loop_count = int(tokens[i + 1])
                except ValueError:
                    loop_count = 1
            elif tok == "--max-budget" and i + 1 < len(tokens):
                try:
                    max_budget = float(tokens[i + 1])
                except ValueError:
                    pass
            elif tok == "--max-hours" and i + 1 < len(tokens):
                try:
                    max_hours = float(tokens[i + 1])
                except ValueError:
                    pass
            elif tok == "--persona" and i + 1 < len(tokens):
                persona_name = tokens[i + 1]

        # Resolve budget/time caps: CLI flags > config > defaults (mirrors auto command)
        effective_max_budget = max_budget if max_budget is not None else config.budget.max_total_usd
        effective_max_hours = max_hours if max_hours is not None else config.budget.max_duration_hours

        # Resolve custom CEO profiles from config
        custom_profiles = config.ceo_profiles if config.ceo_profiles else None

        queue = app_instance.event_queue
        app_instance._stop_event.clear()
        app_instance._auto_loop_active = True

        aggregate_cost = 0.0
        last_persona_role: str | None = None
        completed = 0
        loop_start = _time.monotonic()

        try:
            for iteration in range(1, loop_count + 1):
                if app_instance._stop_event.is_set():
                    break

                # --- Time cap check ---
                elapsed_hours = (_time.monotonic() - loop_start) / 3600.0
                if elapsed_hours >= effective_max_hours:
                    queue.sync_q.put(CommandOutputMsg(
                        text=f"Time limit reached ({elapsed_hours:.1f}h / {effective_max_hours:.1f}h). Stopping auto loop."
                    ))
                    break

                # --- Budget cap check ---
                if aggregate_cost >= effective_max_budget:
                    queue.sync_q.put(CommandOutputMsg(
                        text=f"Budget limit reached (${aggregate_cost:.2f} / ${effective_max_budget:.2f}). Stopping auto loop."
                    ))
                    break

                persona = get_ceo_profile(
                    name=persona_name,
                    exclude=last_persona_role,
                    custom_profiles=custom_profiles,
                )
                last_persona_role = persona.role

                queue.sync_q.put(IterationHeaderMsg(
                    iteration=iteration,
                    total=loop_count,
                    persona_name=persona.role,
                    aggregate_cost=aggregate_cost,
                ))

                adapter = TextualUI(queue.sync_q)
                current_adapter = adapter

                try:
                    prompt, ceo_result = run_ceo(
                        repo_root,
                        config,
                        ui=cast(Any, adapter),
                        ceo_persona=persona,
                    )
                except Exception as exc:
                    logger.exception("CEO phase failed in auto TUI loop iter %d", iteration)
                    queue.sync_q.put(CommandOutputMsg(
                        text=f"CEO phase failed: {type(exc).__name__}: {exc}"
                    ))
                    continue
                finally:
                    current_adapter = None

                aggregate_cost += ceo_result.cost_usd or 0.0

                # --- Post-CEO budget cap check ---
                if aggregate_cost >= effective_max_budget:
                    queue.sync_q.put(CommandOutputMsg(
                        text=f"Budget limit reached (${aggregate_cost:.2f} / ${effective_max_budget:.2f}). Stopping auto loop."
                    ))
                    break

                if not ceo_result.success or not prompt:
                    queue.sync_q.put(CommandOutputMsg(
                        text=f"CEO phase did not produce a prompt (iter {iteration}). Continuing..."
                    ))
                    continue

                queue.sync_q.put(TextBlockMsg(text=f"CEO Proposal: {prompt[:200]}..."))

                if config.directions_auto_update:
                    try:
                        directions_cost = update_directions_after_ceo(
                            repo_root, config, prompt, iteration,
                            ui=cast(Any, adapter),
                        )
                        aggregate_cost += directions_cost
                    except Exception:
                        logger.exception("Directions update failed in auto TUI loop")

                if app_instance._stop_event.is_set():
                    break

                # Run the orchestrator pipeline
                adapter2 = TextualUI(queue.sync_q)
                current_adapter = adapter2

                def _ui_factory(
                    prefix: str = "",
                    *,
                    badge: object | None = None,
                    task_id: str | None = None,
                ) -> TextualUI:
                    if badge is None and task_id is None and not prefix:
                        return adapter2
                    return TextualUI(
                        queue.sync_q,
                        badge=badge,  # type: ignore[arg-type]
                        task_id=task_id,
                    )

                try:
                    log = run_orchestrator(
                        prompt,
                        repo_root=repo_root,
                        config=config,
                        verbose=False,
                        ui_factory=_ui_factory,
                        user_injection_provider=adapter2.drain_user_injections,
                    )
                    aggregate_cost += log.total_cost_usd
                    completed += 1
                except PreflightError as exc:
                    queue.sync_q.put(CommandOutputMsg(
                        text=f"Pre-flight failed (iter {iteration}): {exc}"
                    ))
                except Exception as exc:
                    logger.exception("Pipeline failed in auto TUI loop iter %d", iteration)
                    queue.sync_q.put(CommandOutputMsg(
                        text=f"Pipeline failed (iter {iteration}): {type(exc).__name__}: {exc}"
                    ))
                finally:
                    current_adapter = None

                # --- Post-pipeline budget cap check ---
                if aggregate_cost >= effective_max_budget:
                    queue.sync_q.put(CommandOutputMsg(
                        text=f"Budget limit reached (${aggregate_cost:.2f} / ${effective_max_budget:.2f}). Stopping auto loop."
                    ))
                    break

        finally:
            app_instance._auto_loop_active = False
            queue.sync_q.put(LoopCompleteMsg(
                iterations_completed=completed,
                total_cost=aggregate_cost,
            ))

    def _inject_callback(text: str) -> None:
        if current_adapter is not None:
            current_adapter.enqueue_user_injection(text)

    # Instantiate TranscriptLogWriter for this TUI session (FR-3)
    from colonyos.tui.log_writer import TranscriptLogWriter
    from datetime import datetime, timezone

    logs_dir = repo_root / ".colonyos" / "logs"
    run_id = datetime.now(timezone.utc).strftime("tui_%Y%m%d_%H%M%S")
    log_writer = TranscriptLogWriter(
        logs_dir, run_id, max_log_files=config.max_log_files,
    )

    app_instance = AssistantApp(
        run_callback=_run_callback,
        recovery_callback=_recovery_callback,
        inject_callback=_inject_callback,
        initial_prompt=prompt,
        command_hints=command_hints,
        log_writer=log_writer,
    )

    previous_handler = signal.getsignal(signal.SIGINT)

    def _sigint_handler(signum, frame) -> None:  # noqa: ANN001
        app_instance.call_from_thread(app_instance.action_cancel_run)

    signal.signal(signal.SIGINT, _sigint_handler)
    try:
        app_instance.run()
    finally:
        signal.signal(signal.SIGINT, previous_handler)


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
        with _repo_runtime_session(repo_root, "tui"), install_signal_cancel_handlers(
            include_sighup=True,
        ):
            _launch_tui(repo_root, config, prompt=prompt, verbose=verbose)
    except ImportError as exc:
        click.echo(
            f"Error: {exc}\n\nInstall the TUI extra: pip install colonyos[tui]",
            err=True,
        )
        sys.exit(1)
