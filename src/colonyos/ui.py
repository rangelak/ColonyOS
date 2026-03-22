"""Terminal UI for streaming agent activity in real-time."""

from __future__ import annotations

import json
import queue
import re
import sys
import threading
import time
from typing import TYPE_CHECKING, TypedDict

from rich.console import Console
from rich.markdown import Markdown
from rich.padding import Padding
from rich.theme import Theme

if TYPE_CHECKING:
    from colonyos.models import PhaseResult

_theme = Theme({
    "markdown.code": "bold cyan",
    "markdown.code_block": "dim",
})

console = Console(stderr=True, theme=_theme)

TOOL_STYLE: dict[str, str] = {
    "Read": "cyan",
    "Write": "green",
    "Edit": "green",
    "Bash": "yellow",
    "Grep": "magenta",
    "Glob": "magenta",
    "Agent": "blue",
    "Dispatch": "blue",
    "Task": "blue",
}

_AGENT_TOOLS = {"Agent", "Dispatch", "Task"}

DEFAULT_TOOL_STYLE = "dim"

TOOL_ARG_KEYS: dict[str, list[str]] = {
    "Read": ["file_path", "path"],
    "Write": ["file_path", "path"],
    "Edit": ["file_path", "path"],
    "Bash": ["command"],
    "Grep": ["pattern", "regex"],
    "Glob": ["glob_pattern", "pattern"],
    "Agent": ["prompt", "task", "message", "description"],
    "Dispatch": ["prompt", "task", "message", "description"],
    "Task": ["prompt", "task", "message", "description"],
}

_MD_PATTERN = re.compile(
    r"(^#{1,4}\s)|(\*\*.*\*\*)|(\n\d+\.\s)|(\n[-*]\s)|(`[^`]+`)",
    re.MULTILINE,
)


class PhaseUI:
    """Renders streaming output for a single agent phase.

    Each phase gets its own instance.  For parallel reviews, each
    reviewer gets an instance with a ``prefix`` like ``"[Linus] "``.
    For parallel tasks, each task gets a ``task_id`` like ``"3.0"``.
    """

    def __init__(
        self,
        *,
        verbose: bool = False,
        prefix: str = "",
        task_id: str | None = None,
    ) -> None:
        self._verbose = verbose
        self._task_id = task_id
        # If task_id is provided, generate a colored prefix
        if task_id is not None:
            self._prefix = make_task_prefix(task_id)
        else:
            self._prefix = prefix
        self._tool_name: str | None = None
        self._tool_json: str = ""
        self._tool_displayed: bool = False
        self._text_buf: str = ""
        self._in_tool: bool = False
        self._start_time: float = time.monotonic()
        self._turn_count: int = 0

    # -- phase-level markers ------------------------------------------------

    def phase_header(
        self,
        phase_name: str,
        budget: float,
        model: str,
        extra: str = "",
    ) -> None:
        label = f" Phase: {phase_name}  ${budget:.2f} budget · {model}"
        if extra:
            label += f" · {extra}"
        console.rule(label, style="bold")

    def phase_complete(
        self,
        cost: float,
        turns: int,
        duration_ms: int,
    ) -> None:
        self._flush_text()
        elapsed = _format_duration(duration_ms)
        console.print(
            f"\n  [green]✓[/green] Phase completed  "
            f"${cost:.2f} · {turns} turns · {elapsed}\n",
            highlight=False,
        )

    def phase_error(self, error: str) -> None:
        self._flush_text()
        console.print(
            f"\n  [red]✗[/red] Phase failed: {error}\n",
            highlight=False,
        )

    # -- streaming callbacks ------------------------------------------------

    def on_tool_start(self, tool_name: str) -> None:
        self._flush_text()
        self._in_tool = True
        self._tool_name = tool_name
        self._tool_json = ""
        self._tool_displayed = False

    def on_tool_input_delta(self, partial_json: str) -> None:
        self._tool_json += partial_json
        if not self._tool_displayed:
            arg = self._try_extract_arg()
            if arg is not None:
                self._print_tool_line(arg)
                self._tool_displayed = True

    def on_tool_done(self) -> None:
        if self._tool_name and not self._tool_displayed:
            arg = self._try_extract_arg() or ""
            self._print_tool_line(arg)
        self._tool_name = None
        self._tool_json = ""
        self._tool_displayed = False
        self._in_tool = False

    def on_text_delta(self, text: str) -> None:
        if self._in_tool:
            return
        self._text_buf += text

    def on_turn_complete(self) -> None:
        self._flush_text()
        self._turn_count += 1

    # -- internals ----------------------------------------------------------

    def _flush_text(self) -> None:
        """Render buffered agent text, then clear the buffer."""
        raw = self._text_buf.strip()
        self._text_buf = ""
        if not raw:
            return
        if _looks_like_markdown(raw):
            if self._prefix:
                console.print(f"\n  {self._prefix}─────", highlight=False)
            else:
                console.print()
            console.print(Padding(Markdown(raw), (0, 4)))
        else:
            for line in raw.splitlines():
                stripped = line.strip()
                if stripped:
                    console.print(
                        f"  {self._prefix}[dim]{_truncate(stripped, 120)}[/dim]",
                        highlight=False,
                    )

    def _print_tool_line(self, arg: str) -> None:
        name = self._tool_name or "?"
        style = TOOL_STYLE.get(name, DEFAULT_TOOL_STYLE)
        label = f"{name} {arg}".rstrip() if arg else name
        console.print(
            f"  {self._prefix}[{style}]●[/{style}] {label}",
            highlight=False,
        )

    def _try_extract_arg(self) -> str | None:
        if not self._tool_name:
            return None
        keys = TOOL_ARG_KEYS.get(self._tool_name)
        if not keys:
            return None
        try:
            data = json.loads(self._tool_json)
            for key in keys:
                val = data.get(key)
                if val:
                    text = str(val)
                    if self._tool_name in _AGENT_TOOLS:
                        text = _first_meaningful_line(text)
                    return _truncate(text, 80)
            return None
        except (json.JSONDecodeError, TypeError):
            return None


class NullUI:
    """Drop-in replacement that discards all output.  Used in tests and --quiet."""

    def phase_header(self, *a: object, **kw: object) -> None: ...
    def phase_complete(self, *a: object, **kw: object) -> None: ...
    def phase_error(self, *a: object, **kw: object) -> None: ...
    def on_tool_start(self, *a: object) -> None: ...
    def on_tool_input_delta(self, *a: object) -> None: ...
    def on_tool_done(self) -> None: ...
    def on_text_delta(self, *a: object) -> None: ...
    def on_turn_complete(self) -> None: ...


# -- reviewer tag helpers --------------------------------------------------

REVIEWER_COLORS = [
    "bright_cyan", "bright_magenta", "bright_yellow", "bright_green",
    "bright_blue", "bright_red", "bright_white",
]


def _reviewer_color(index: int) -> str:
    return REVIEWER_COLORS[index % len(REVIEWER_COLORS)]


def make_reviewer_prefix(index: int) -> str:
    """Build a short numbered prefix like '[cyan]R1[/cyan] '."""
    color = _reviewer_color(index)
    return f"[{color}]R{index + 1}[/{color}] "


def print_reviewer_legend(reviewers: list[tuple[int, str]]) -> None:
    """Print legend mapping R1..RN -> full role name before review starts."""
    console.print()
    for i, role in reviewers:
        color = _reviewer_color(i)
        console.print(
            f"  [{color}]R{i + 1}[/{color}] {role}",
            highlight=False,
        )
    console.print()


# -- parallel task helpers -------------------------------------------------


def _task_color(index: int) -> str:
    """Return a color for the given task index."""
    return REVIEWER_COLORS[index % len(REVIEWER_COLORS)]


def _parse_task_index(task_id: str) -> int:
    """Parse the numeric part of a task ID for color assignment.

    Examples:
        "1.0" -> 0
        "3.0" -> 2
        "10.0" -> 9
    """
    try:
        # Extract the major version number (before the dot)
        major = int(task_id.split(".")[0])
        return major - 1  # 0-indexed for color rotation
    except (ValueError, IndexError):
        return 0


def make_task_prefix(task_id: str) -> str:
    """Build a colored prefix like '[cyan][3.0][/cyan] ' for a task ID."""
    index = _parse_task_index(task_id)
    color = _task_color(index)
    return f"[{color}][{task_id}][/{color}] "


def print_task_legend(tasks: list[tuple[str, str]]) -> None:
    """Print legend mapping task IDs -> task descriptions before parallel execution.

    Args:
        tasks: List of (task_id, description) tuples.
    """
    if not tasks:
        return
    console.print()
    for task_id, description in tasks:
        index = _parse_task_index(task_id)
        color = _task_color(index)
        # Truncate long descriptions
        desc = description[:60] + "…" if len(description) > 60 else description
        console.print(
            f"  [{color}][{task_id}][/{color}] {desc}",
            highlight=False,
        )
    console.print()



def _looks_like_markdown(text: str) -> bool:
    """Return True if text contains markdown formatting worth rendering."""
    return bool(_MD_PATTERN.search(text))


def _first_meaningful_line(text: str) -> str:
    """Extract the first non-blank, non-heading line from an agent prompt."""
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped and len(stripped) > 5:
            return stripped
    return text.split("\n", 1)[0].strip()


def _truncate(s: str, maxlen: int) -> str:
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"


def _format_duration(ms: int) -> str:
    secs = ms // 1000
    if secs < 60:
        return f"{secs}s"
    mins, secs = divmod(secs, 60)
    return f"{mins}m {secs}s"


# -- Verdict extraction for progress tracking ---------------------------------

_VERDICT_PATTERN = re.compile(r"VERDICT:\s*(approve|request-changes)", re.IGNORECASE)


def _extract_review_verdict(result_text: str) -> str:
    """Extract verdict from review result text.

    Returns:
        'approved', 'request-changes', or 'unknown'
    """
    match = _VERDICT_PATTERN.search(result_text)
    if match:
        verdict = match.group(1).lower()
        if verdict == "approve":
            return "approved"
        return verdict
    return "unknown"


# -- Parallel Progress Tracker ------------------------------------------------


def _get_default_console() -> Console:
    """Return the module-level console instance.

    This avoids using globals() for runtime lookup while still allowing
    the console to be overridden in tests.
    """
    return console


class _ReviewerState(TypedDict):
    """Type definition for reviewer state tracking."""

    status: str  # 'pending', 'approved', 'request-changes', 'failed'
    cost_usd: float
    duration_ms: int


class ParallelProgressLine:
    """Real-time progress indicator for parallel reviewer execution.

    Shows a compact single-line status during review phases:
    ``Reviews: R1 ✓ | R2 ✓ | R3 ⏳ (45s) | R4 ⏳ (32s) — 2/4 complete, $0.42``

    In non-TTY mode (CI/logs), outputs one log line per completion event.

    Args:
        reviewers: List of (index, role_name) tuples for each reviewer.
        is_tty: Whether output is a TTY (enables inline rewrite).
        console: Optional Console instance for output (for testing).
    """

    # Status icons (hardcoded, not from user input)
    _ICON_PENDING = "⏳"
    _ICON_APPROVED = "✓"
    _ICON_CHANGES = "⚠"
    _ICON_FAILED = "✗"

    def __init__(
        self,
        reviewers: list[tuple[int, str]],
        is_tty: bool,
        console: Console | None = None,
    ) -> None:
        from colonyos.sanitize import sanitize_display_text

        self._reviewers = reviewers
        self._is_tty = is_tty
        # Use passed console or fall back to module-level console
        self._console: Console = console if console is not None else _get_default_console()
        self._start_time = time.monotonic()

        # Sanitize and store reviewer names
        self._sanitized_names: dict[int, str] = {}
        for idx, name in reviewers:
            self._sanitized_names[idx] = sanitize_display_text(name)

        # State tracking: index -> {status, cost_usd, duration_ms}
        self._states: dict[int, _ReviewerState] = {}
        for idx, _ in reviewers:
            self._states[idx] = {
                "status": "pending",
                "cost_usd": 0.0,
                "duration_ms": 0,
            }

        # Track the most recently completed reviewer for non-TTY rendering
        self._last_completed_index: int | None = None

    @property
    def total_cost_usd(self) -> float:
        """Total cost across all completed reviewers."""
        return sum(
            float(s["cost_usd"])
            for s in self._states.values()
            if s["status"] != "pending"
        )

    @property
    def completed_count(self) -> int:
        """Number of reviewers that have completed."""
        return sum(1 for s in self._states.values() if s["status"] != "pending")

    def on_reviewer_complete(self, index: int, result: "PhaseResult") -> None:
        """Update state when a reviewer completes and render progress.

        Args:
            index: The original call order index of the reviewer.
            result: The PhaseResult from the completed review.
        """
        # Determine status from result
        if not result.success:
            status = "failed"
        else:
            result_text = result.artifacts.get("result", "")
            verdict = _extract_review_verdict(result_text)
            if verdict == "approved":
                status = "approved"
            elif verdict == "request-changes":
                status = "request-changes"
            else:
                # Default to approved if we can't parse (safer assumption)
                status = "approved"

        self._states[index] = {
            "status": status,
            "cost_usd": result.cost_usd or 0.0,
            "duration_ms": result.duration_ms,
        }

        # Track which reviewer just completed for non-TTY rendering
        self._last_completed_index = index

        self._render()

    def _render(self) -> None:
        """Render progress line to console."""
        if self._is_tty:
            self._render_tty()
        else:
            self._render_non_tty()

    def _render_tty(self) -> None:
        """Render single-line progress with inline rewrite for TTY."""
        parts: list[str] = []
        elapsed_now = time.monotonic() - self._start_time

        for idx, _ in self._reviewers:
            state = self._states[idx]
            status = state["status"]
            color = _reviewer_color(idx)
            label = f"[{color}]R{idx + 1}[/{color}]"

            if status == "pending":
                secs = int(elapsed_now)
                parts.append(f"{label} {self._ICON_PENDING} ({secs}s)")
            elif status == "approved":
                parts.append(f"{label} [green]{self._ICON_APPROVED}[/green]")
            elif status == "request-changes":
                parts.append(f"{label} [yellow]{self._ICON_CHANGES}[/yellow]")
            elif status == "failed":
                parts.append(f"{label} [red]{self._ICON_FAILED}[/red]")

        completed = self.completed_count
        total = len(self._reviewers)
        cost = self.total_cost_usd

        line = " | ".join(parts)
        summary = f"{completed}/{total} complete, ${cost:.2f}"

        # Use carriage return to overwrite line, then clear to end of line
        self._console.print(
            f"\r  Reviews: {line} — {summary}",
            end="",
            highlight=False,
        )

        # If all complete, print newline to finalize
        if completed == total:
            self._console.print()

    def _render_non_tty(self) -> None:
        """Render log-style output for non-TTY environments."""
        # Print only the reviewer that just completed (tracked in on_reviewer_complete)
        idx = self._last_completed_index
        if idx is None:
            return

        state = self._states[idx]
        status = state["status"]
        cost = state["cost_usd"]
        duration_ms = state["duration_ms"]
        duration_str = _format_duration(duration_ms)
        name = self._sanitized_names.get(idx, f"R{idx + 1}")

        icon = {
            "approved": self._ICON_APPROVED,
            "request-changes": self._ICON_CHANGES,
            "failed": self._ICON_FAILED,
        }.get(status, "?")

        self._console.print(
            f"  R{idx + 1} {icon} {name} ({status}) ${cost:.2f} in {duration_str}",
            highlight=False,
        )

    def print_summary(self, round_num: int) -> None:
        """Print a summary line after all reviewers complete.

        Args:
            round_num: The review round number (1-indexed).
        """
        approved_count = sum(
            1 for s in self._states.values() if s["status"] == "approved"
        )
        changes_count = sum(
            1 for s in self._states.values() if s["status"] == "request-changes"
        )
        failed_count = sum(
            1 for s in self._states.values() if s["status"] == "failed"
        )

        # Build list of reviewers who requested changes
        changes_names: list[str] = []
        for idx, _ in self._reviewers:
            if self._states[idx]["status"] == "request-changes":
                changes_names.append(self._sanitized_names.get(idx, f"R{idx + 1}"))

        cost = self.total_cost_usd

        # Build summary parts
        parts: list[str] = []
        if approved_count > 0:
            parts.append(f"{approved_count} approved")
        if changes_count > 0:
            names = ", ".join(changes_names)
            parts.append(f"{changes_count} request-changes ({names})")
        if failed_count > 0:
            parts.append(f"{failed_count} failed")

        summary = ", ".join(parts) if parts else "no reviewers"

        self._console.print(
            f"\n  Review round {round_num}: {summary} — ${cost:.2f} total\n",
            highlight=False,
        )


# -- Live Input Reader -------------------------------------------------------


class InputReader:
    """Non-blocking stdin reader using a background daemon thread.

    Only activates when stdin is a TTY.  Call ``start()`` to begin reading and
    ``stop()`` to tear down the daemon thread.  The agent loop drains
    ``input_queue`` (a thread-safe ``queue.Queue``) between turns.
    """

    def __init__(self, cost_fn: "Callable[[], float] | None" = None) -> None:
        self._input_queue: queue.Queue[str] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._active = False
        self._cost_fn = cost_fn

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def input_queue(self) -> queue.Queue[str]:
        return self._input_queue

    def start(self) -> None:
        """Start the background stdin reader if stdin is a TTY."""
        if not sys.stdin.isatty():
            return
        self._active = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        console.print(
            "  [dim]Type a message below and press Enter to send input to the running agent[/dim]",
            highlight=False,
        )
        import sys as _sys
        _sys.stderr.write(self._build_prompt())
        _sys.stderr.flush()

    def stop(self) -> None:
        """Signal the reader thread to stop."""
        self._stop_event.set()
        self._active = False

    def _build_prompt(self) -> str:
        cost = self._cost_fn() if self._cost_fn else 0.0
        return f"\033[32m[${cost:.2f}]\033[0m \033[1;96m›\033[0m "

    def _read_loop(self) -> None:
        """Background thread: read lines from stdin until stopped."""
        import select
        import sys as _sys

        fd = _sys.stdin.fileno()
        prompt_shown = False
        while not self._stop_event.is_set():
            if not prompt_shown:
                _sys.stderr.write(self._build_prompt())
                _sys.stderr.flush()
                prompt_shown = True
            ready, _, _ = select.select([fd], [], [], 0.5)
            if not ready:
                continue
            try:
                line = _sys.stdin.readline()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                break
            stripped = line.strip()
            if stripped:
                self._input_queue.put(stripped)
                console.print(
                    f"  [dim][you][/dim] {_truncate(stripped, 120)}",
                    highlight=False,
                )
            prompt_shown = False
