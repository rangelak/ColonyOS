"""Full-screen REPL powered by prompt_toolkit.

Provides a persistent input bar pinned at the bottom, a scrollable output pane
on top, and a separator/status line between them.  Agent output streams into
the output pane from any thread via :meth:`ReplApp.write`.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import shlex
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import TextArea

if TYPE_CHECKING:
    from prompt_toolkit.key_binding import KeyPressEvent

    from colonyos.config import ColonyConfig
    from colonyos.models import RunLog

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    """Remove ANSI SGR escape sequences from *s*."""
    return _ANSI_RE.sub("", s)


# Symbolic ANSI tokens — stripped at the write boundary by _strip_ansi(),
# but kept in the code so intent is clear when reading callers.
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_MAGENTA = "\033[35m"
_BLUE = "\033[34m"
_RED = "\033[31m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"

_TOOL_COLOR: dict[str, str] = {
    "Read": _CYAN,
    "Write": _GREEN,
    "Edit": _GREEN,
    "Bash": _YELLOW,
    "Grep": _MAGENTA,
    "Glob": _MAGENTA,
    "Agent": _BLUE,
    "Dispatch": _BLUE,
    "Task": _BLUE,
}

_TOOL_ARG_KEYS: dict[str, list[str]] = {
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

_AGENT_TOOLS = {"Agent", "Dispatch", "Task"}


def _truncate(s: str, maxlen: int) -> str:
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"


def _first_meaningful_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped and len(stripped) > 5:
            return stripped
    return text.split("\n", 1)[0].strip()


def _format_duration(ms: int) -> str:
    secs = ms // 1000
    if secs < 60:
        return f"{secs}s"
    mins, secs = divmod(secs, 60)
    return f"{mins}m {secs}s"


# ---------------------------------------------------------------------------
# ReplUI — PhaseUI-compatible adapter that writes to the output pane
# ---------------------------------------------------------------------------


class ReplUI:
    """PhaseUI-compatible adapter that writes to a :class:`ReplApp` output pane.

    Uses ANSI escape codes for styling since the output pane is plain text.
    """

    def __init__(self, write_fn: Callable[[str], None], *, prefix: str = "") -> None:
        self._write = write_fn
        self._prefix = prefix
        self._tool_name: str | None = None
        self._tool_json: str = ""
        self._tool_displayed: bool = False
        self._text_buf: str = ""
        self._in_tool: bool = False

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
        width = max(os.get_terminal_size().columns - 2, 40)
        pad = width - len(label) - 2
        left = pad // 2
        right = pad - left
        line = f"{_DIM}{'─' * left}{_RESET}{_BOLD}{label}{_RESET}{_DIM}{'─' * right}{_RESET}"
        self._write(f"\n{line}\n")

    def phase_complete(self, cost: float, turns: int, duration_ms: int) -> None:
        self._flush_text()
        elapsed = _format_duration(duration_ms)
        self._write(
            f"\n  {_GREEN}✓{_RESET} Phase completed  "
            f"${cost:.2f} · {turns} turns · {elapsed}\n\n"
        )

    def phase_error(self, error: str) -> None:
        self._flush_text()
        self._write(f"\n  {_RED}✗{_RESET} Phase failed: {error}\n\n")

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

    def _flush_text(self) -> None:
        raw = self._text_buf.strip()
        self._text_buf = ""
        if not raw:
            return
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped:
                self._write(f"  {self._prefix}{_DIM}{_truncate(stripped, 120)}{_RESET}\n")

    def _print_tool_line(self, arg: str) -> None:
        name = self._tool_name or "?"
        color = _TOOL_COLOR.get(name, _DIM)
        label = f"{name} {arg}".rstrip() if arg else name
        self._write(f"  {self._prefix}{color}●{_RESET} {label}\n")

    def _try_extract_arg(self) -> str | None:
        if not self._tool_name:
            return None
        keys = _TOOL_ARG_KEYS.get(self._tool_name)
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


# ---------------------------------------------------------------------------
# ReplApp — full-screen prompt_toolkit Application
# ---------------------------------------------------------------------------


class ReplApp:
    """Full-screen REPL with persistent input bar and scrollable output pane."""

    def __init__(
        self,
        *,
        config: "ColonyConfig",
        repo_root: Path,
        command_names: set[str],
        history_path: Path,
    ) -> None:
        self._config = config
        self._repo_root = repo_root
        self._command_names = command_names
        self._session_cost = 0.0
        self._is_running = False
        self._cancel_event = threading.Event()

        # asyncio.Queue for the accept_handler -> dispatch coroutine pipeline
        self._input_queue: asyncio.Queue[str | None] = asyncio.Queue()

        # --- Output pane (read-only, scrollable) ---
        self._output_buffer = Buffer(read_only=True)
        self._output_area = Window(
            content=BufferControl(buffer=self._output_buffer),
            wrap_lines=True,
        )

        # --- Separator line showing state ---
        self._separator = Window(
            height=1,
            content=FormattedTextControl(self._get_separator_text),
            style="class:separator",
        )

        # --- Input area (pinned at bottom) ---
        all_completions = sorted(command_names | {"help", "exit", "quit"})
        self._input_area = TextArea(
            height=1,
            multiline=False,
            dont_extend_height=True,
            completer=WordCompleter(all_completions, sentence=True),
            history=FileHistory(str(history_path)),
            accept_handler=self._on_accept,
            style="class:input-area",
            prompt=[("class:input-prompt", " › ")],
        )

        # --- Status bar ---
        self._status_bar = Window(
            height=1,
            content=FormattedTextControl(self._get_status_text),
            style="class:status-bar",
        )

        # --- Layout ---
        root = HSplit([
            self._output_area,
            self._separator,
            self._input_area,
            self._status_bar,
        ])

        # --- Key bindings ---
        kb = KeyBindings()

        @kb.add("c-c")
        def _ctrl_c(event: "KeyPressEvent") -> None:
            if self._is_running:
                self._cancel_event.set()
                self.write(f"\n{_DIM}Cancelling…{_RESET}\n")
            else:
                self._input_queue.put_nowait(None)

        @kb.add("c-d")
        def _ctrl_d(event: "KeyPressEvent") -> None:
            self._cancel_event.set()
            self._input_queue.put_nowait(None)

        from prompt_toolkit.styles import Style

        style = Style.from_dict({
            "separator": "#7f5af0",
            "status-bar": "#555555",
            "input-area": "",
            "input-prompt": "fg:#7f5af0 bold",
        })

        self._app: Application[None] = Application(
            layout=Layout(root, focused_element=self._input_area),
            key_bindings=kb,
            style=style,
            full_screen=True,
            mouse_support=False,
        )

    # -- Thread-safe output --------------------------------------------------

    def write(self, text: str) -> None:
        """Append *text* to the output pane. Safe to call from any thread."""
        loop = self._app.loop
        if loop is not None:
            loop.call_soon_threadsafe(self._append_output, text)
        else:
            self._append_output(text)

    def _append_output(self, text: str) -> None:
        clean = _strip_ansi(text)
        old = self._output_buffer.text
        new_text = old + clean
        self._output_buffer.set_document(
            Document(new_text, len(new_text)),
            bypass_readonly=True,
        )
        self._app.invalidate()

    # -- UI factory for the orchestrator ------------------------------------

    def make_ui(self, prefix: str = "") -> ReplUI:
        """Create a ReplUI instance for a phase."""
        return ReplUI(self.write, prefix=prefix)

    # -- Separator / status bar text ----------------------------------------

    def _get_separator_text(self) -> HTML:
        cost = f"${self._session_cost:.2f}"
        if self._is_running:
            return HTML(
                f' ─── [{cost}]'
                f' <ansiyellow>agent running</ansiyellow> '
                f'{"─" * 40}'
            )
        return HTML(
            f' ─── [{cost}]'
            f' <ansigreen>idle</ansigreen> '
            f'{"─" * 40}'
        )

    def _get_status_text(self) -> HTML:
        if self._is_running:
            return HTML(
                " <b>Enter</b>: send message to agent  "
                "<b>Ctrl+C</b>: interrupt  "
                "<b>Ctrl+D</b>: exit"
            )
        return HTML(
            " <b>Enter</b>: send  "
            "<b>↑↓</b>: history  "
            "<b>Tab</b>: complete  "
            "<b>Ctrl+C</b>: exit"
        )

    # -- Accept handler (fires on Enter) ------------------------------------

    def _on_accept(self, buf: Buffer) -> bool:
        text = buf.text.strip()
        if not text and self._is_running:
            return False
        if text:
            self._input_queue.put_nowait(text)
        return False

    # -- Main run loop -------------------------------------------------------

    def _render_banner(self) -> None:
        """Write a compact ANSI welcome banner into the output pane."""
        from colonyos import __version__
        from colonyos.cli import app as cli_app

        home = Path.home()
        try:
            display_path = "~/" + str(self._repo_root.relative_to(home))
        except ValueError:
            display_path = str(self._repo_root)

        model = self._config.model or "unknown"
        lines: list[str] = []

        lines.append(f"\n  {_YELLOW}    ░▒▓██▓▒░{_RESET}")
        lines.append(f"  {_YELLOW}   ████████{_RESET}   {_BOLD}ColonyOS{_RESET} {_DIM}v{__version__}{_RESET}")
        lines.append(f"  {_YELLOW}  ██●███●██{_RESET}   {_DIM}{model} · {display_path}{_RESET}")
        lines.append(f"  {_YELLOW}   ████████{_RESET}")
        lines.append(f"  {_YELLOW}    ██████{_RESET}    {_BOLD}Commands{_RESET}")

        max_name_len = max((len(n) for n in cli_app.commands), default=0)
        cmd_items = sorted(cli_app.commands.items())
        ant_legs = [
            f"  {_YELLOW}   ██ ██ ██{_RESET}",
            f"  {_YELLOW}  ██  ██  ██{_RESET}",
        ]

        for i, (name, cmd) in enumerate(cmd_items):
            summary = (cmd.get_short_help_str(limit=50) or "").strip()
            pad = " " * (max_name_len - len(name) + 2)
            prefix = ant_legs[i] if i < len(ant_legs) else " " * 14
            lines.append(f"{prefix}    {_GREEN}{name}{_RESET}{pad}{_DIM}{summary}{_RESET}")

        lines.append("")
        lines.append(f"  {_DIM}Type a command, a feature to build, or \"help\".{_RESET}")
        lines.append("")

        self.write("\n".join(lines) + "\n")

    async def run(self) -> None:
        """Start the full-screen REPL. Returns when the user quits."""
        self._render_banner()

        dispatch_task = asyncio.create_task(self._dispatch_loop())

        try:
            await self._app.run_async()
        finally:
            self._input_queue.put_nowait(None)
            dispatch_task.cancel()
            try:
                await dispatch_task
            except asyncio.CancelledError:
                pass

    async def _dispatch_loop(self) -> None:
        """Read from input queue and dispatch commands."""
        while True:
            text = await self._input_queue.get()
            if text is None:
                self._app.exit()
                return

            if self._is_running:
                self.write(f"  {_DIM}[you] {text}{_RESET}\n")
                self._mid_run_queue.put(text)
                continue

            self.write(f"{_GREEN}[${self._session_cost:.2f}]{_RESET}{_CYAN}{_BOLD} › {_RESET}{text}\n")

            if text.lower() in ("quit", "exit"):
                self._app.exit()
                return

            if text.lower() == "help":
                self._print_help()
                continue
            if text.lower().startswith("help "):
                self._print_help(text.split(None, 1)[1].strip())
                continue

            try:
                tokens = shlex.split(text)
            except ValueError:
                tokens = text.split()

            if tokens and tokens[0] in self._command_names:
                if tokens[0] in ("run", "r"):
                    self.write(
                        f"  {_YELLOW}Tip: just type your prompt directly — "
                        f"the REPL handles routing automatically.{_RESET}\n"
                    )
                    if len(tokens) > 1:
                        text = " ".join(tokens[1:])
                    else:
                        continue
                else:
                    await self._run_cli_command(tokens)
                    continue

            await self._run_feature_prompt(text)

    # -- Command dispatch helpers -------------------------------------------

    def _print_help(self, command_name: str | None = None) -> None:
        if command_name:
            from colonyos.cli import app as cli_app
            cmd = cli_app.commands.get(command_name)
            if cmd is None:
                self.write(f"Unknown command: {command_name}\n")
                return
            self.write(f"{_DIM}{cmd.get_short_help_str(limit=120)}{_RESET}\n")
            return

        from colonyos.cli import app as cli_app
        lines: list[str] = ["\n"]
        for name in sorted(cli_app.commands):
            cmd = cli_app.commands[name]
            summary = (cmd.get_short_help_str(limit=60) or "").strip()
            lines.append(f"  {_GREEN}{name:<16}{_RESET} {_DIM}{summary}{_RESET}\n")
        lines.append(f"\n{_DIM}Type a command with args, or type a feature description to build it.{_RESET}\n\n")
        self.write("".join(lines))

    async def _run_cli_command(self, tokens: list[str]) -> None:
        from colonyos.cli import _invoke_cli_command
        try:
            await asyncio.to_thread(_invoke_cli_command, tokens)
        except KeyboardInterrupt:
            self.write(f"\n{_DIM}Command interrupted.{_RESET}\n")

    async def _run_feature_prompt(self, prompt: str) -> None:
        """Route a feature prompt through triage -> orchestrator."""
        config = self._config

        if config.router.enabled:
            self.write(f"{_DIM}Classifying intent…{_RESET}\n")
            try:
                handled = await asyncio.to_thread(
                    self._handle_routed_query, prompt,
                )
            except KeyboardInterrupt:
                self.write(f"\n{_DIM}Interrupted.{_RESET}\n")
                return
            if handled is not None:
                text, cost = handled
                self._session_cost += cost
                self.write(f"\n{text}\n")
                self._app.invalidate()
                return

        per_run_cap = config.budget.per_run
        if not config.auto_approve:
            self.write(
                f"Max cost: {_GREEN}${per_run_cap:.2f}{_RESET} (per_run cap). Proceed? [Y/n] "
            )
            response = await self._input_queue.get()
            if response is None:
                self._app.exit()
                return
            if response.strip().lower() in ("n", "no"):
                return

        await self._run_orchestrator(prompt)

    def _handle_routed_query(self, prompt: str) -> tuple[str, float] | None:
        from colonyos.cli import _handle_routed_query
        return _handle_routed_query(
            prompt, self._config, self._repo_root,
            source="repl", quiet=True,
        )

    async def _run_orchestrator(self, prompt: str) -> None:
        """Run the full pipeline in a background thread."""
        from colonyos.orchestrator import run as run_orchestrator

        self._is_running = True
        self._cancel_event.clear()
        self._mid_run_queue: queue.Queue[str] = queue.Queue()
        self._app.invalidate()

        def _run() -> "RunLog":
            return run_orchestrator(
                prompt,
                repo_root=self._repo_root,
                config=self._config,
                verbose=True,
                interactive=True,
                external_input_queue=self._mid_run_queue,
                ui_factory=lambda prefix="": self.make_ui(prefix),
                cancel_event=self._cancel_event,
            )

        try:
            log = await asyncio.to_thread(_run)
            self._session_cost += log.total_cost_usd
            self.write(
                f"\n  {_GREEN}✓{_RESET} Run completed — "
                f"${log.total_cost_usd:.2f} total, "
                f"{len(log.phases)} phases\n\n"
            )
        except KeyboardInterrupt:
            self.write(f"\n{_DIM}Run interrupted.{_RESET}\n")
        except Exception as exc:
            self.write(f"\n{_RED}Run failed: {exc}{_RESET}\n")
        finally:
            self._is_running = False
            self._cancel_event.clear()
            self._app.invalidate()
