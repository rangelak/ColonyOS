"""Terminal UI for streaming agent activity in real-time."""

from __future__ import annotations

import json
import time

from rich.console import Console

console = Console(stderr=True)

TOOL_STYLE: dict[str, str] = {
    "Read": "cyan",
    "Write": "green",
    "Edit": "green",
    "Bash": "yellow",
    "Grep": "magenta",
    "Glob": "magenta",
    "Agent": "blue",
}

DEFAULT_TOOL_STYLE = "dim"

TOOL_ARG_KEYS: dict[str, list[str]] = {
    "Read": ["file_path", "path"],
    "Write": ["file_path", "path"],
    "Edit": ["file_path", "path"],
    "Bash": ["command"],
    "Grep": ["pattern", "regex"],
    "Glob": ["glob_pattern", "pattern"],
    "Agent": ["agent_name", "name"],
}


class PhaseUI:
    """Renders streaming output for a single agent phase.

    Each phase gets its own instance.  For parallel reviews, each
    reviewer gets an instance with a ``prefix`` like ``"[Linus] "``.
    """

    def __init__(
        self,
        *,
        verbose: bool = False,
        prefix: str = "",
    ) -> None:
        self._verbose = verbose
        self._prefix = prefix
        self._tool_name: str | None = None
        self._tool_json: str = ""
        self._tool_displayed: bool = False
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
        elapsed = _format_duration(duration_ms)
        console.print(
            f"\n  [green]✓[/green] Phase completed  "
            f"${cost:.2f} · {turns} turns · {elapsed}\n",
            highlight=False,
        )

    def phase_error(self, error: str) -> None:
        console.print(
            f"\n  [red]✗[/red] Phase failed: {error}\n",
            highlight=False,
        )

    # -- streaming callbacks ------------------------------------------------

    def on_tool_start(self, tool_name: str) -> None:
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

    def on_text_delta(self, text: str) -> None:
        if self._verbose:
            console.file.write(text)
            console.file.flush()

    def on_turn_complete(self) -> None:
        self._turn_count += 1

    # -- internals ----------------------------------------------------------

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
                    return _truncate(str(val), 80)
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


def _truncate(s: str, maxlen: int) -> str:
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"


def _format_duration(ms: int) -> str:
    secs = ms // 1000
    if secs < 60:
        return f"{secs}s"
    mins, secs = divmod(secs, 60)
    return f"{mins}m {secs}s"
