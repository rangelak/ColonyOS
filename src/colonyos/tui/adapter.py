"""TextualUI adapter: bridges orchestrator PhaseUI callbacks to a Textual message queue.

The orchestrator runs in a background thread and calls the same 8-method
duck-type interface as ``PhaseUI`` / ``NullUI``.  This adapter serializes
each callback into a frozen dataclass and pushes it onto a ``janus.SyncQueue``
so the Textual event loop can consume events asynchronously.
"""

from __future__ import annotations

from collections import deque
import json
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING

from colonyos.sanitize import sanitize_display_text, sanitize_untrusted_content
from colonyos.ui import TOOL_ARG_KEYS, TOOL_STYLE, DEFAULT_TOOL_STYLE, _first_meaningful_line, _truncate

if TYPE_CHECKING:
    import janus

_AGENT_TOOLS = {"Agent", "Dispatch", "Task"}


# ---------------------------------------------------------------------------
# Queue message types – frozen dataclasses for thread-safe transfer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhaseHeaderMsg:
    """A new phase has started."""

    phase_name: str
    budget: float
    model: str
    extra: str = ""


@dataclass(frozen=True)
class PhaseCompleteMsg:
    """A phase has finished successfully."""

    cost: float
    turns: int
    duration_ms: int


@dataclass(frozen=True)
class PhaseErrorMsg:
    """A phase has failed."""

    error: str


@dataclass(frozen=True)
class ToolLineMsg:
    """A tool call with its extracted argument summary."""

    tool_name: str
    arg: str
    style: str


@dataclass(frozen=True)
class TextBlockMsg:
    """A block of agent text (flushed on turn_complete)."""

    text: str


@dataclass(frozen=True)
class CommandOutputMsg:
    """Preformatted CLI command output captured inside the TUI."""

    text: str


@dataclass(frozen=True)
class TurnCompleteMsg:
    """A turn has completed (for status bar turn counting)."""

    turn_number: int


@dataclass(frozen=True)
class UserInjectionMsg:
    """A user message queued during an active run."""

    text: str


# ---------------------------------------------------------------------------
# TextualUI – the adapter
# ---------------------------------------------------------------------------


class TextualUI:
    """PhaseUI-compatible adapter that pushes events onto a janus sync queue.

    Implements the same 8-method duck-type interface as ``PhaseUI`` and
    ``NullUI``:

    - ``phase_header(phase_name, budget, model, extra="")``
    - ``phase_complete(cost, turns, duration_ms)``
    - ``phase_error(error)``
    - ``on_tool_start(tool_name)``
    - ``on_tool_input_delta(partial_json)``
    - ``on_tool_done()``
    - ``on_text_delta(text)``
    - ``on_turn_complete()``

    All text is sanitized via ``sanitize_display_text()`` before queuing.
    """

    def __init__(self, sync_queue: janus.SyncQueue[object]) -> None:
        self._queue = sync_queue
        self._tool_name: str | None = None
        self._tool_json: str = ""
        self._tool_displayed: bool = False
        self._text_buf: str = ""
        self._in_tool: bool = False
        self._turn_count: int = 0
        self._pending_injections: deque[str] = deque()
        self._injection_lock = Lock()

    # -- phase-level markers ------------------------------------------------

    def phase_header(
        self,
        phase_name: str,
        budget: float,
        model: str,
        extra: str = "",
    ) -> None:
        self._turn_count = 0
        self._queue.put(PhaseHeaderMsg(
            phase_name=sanitize_display_text(phase_name),
            budget=budget,
            model=sanitize_display_text(model),
            extra=sanitize_display_text(extra) if extra else "",
        ))

    def phase_complete(
        self,
        cost: float,
        turns: int,
        duration_ms: int,
    ) -> None:
        self._flush_text()
        self._queue.put(PhaseCompleteMsg(
            cost=cost,
            turns=turns,
            duration_ms=duration_ms,
        ))

    def phase_error(self, error: str) -> None:
        self._flush_text()
        self._queue.put(PhaseErrorMsg(
            error=sanitize_display_text(error),
        ))

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
                self._emit_tool_line(arg)
                self._tool_displayed = True

    def on_tool_done(self) -> None:
        if self._tool_name and not self._tool_displayed:
            arg = self._try_extract_arg() or ""
            self._emit_tool_line(arg)
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
        self._queue.put(TurnCompleteMsg(turn_number=self._turn_count))

    def enqueue_user_injection(self, text: str) -> None:
        """Queue sanitized user context for the next phase boundary."""
        sanitized = sanitize_untrusted_content(text).strip()
        if not sanitized:
            return
        with self._injection_lock:
            self._pending_injections.append(sanitized)
        self._queue.put(UserInjectionMsg(text=sanitize_display_text(sanitized)))

    def drain_user_injections(self) -> list[str]:
        """Drain all queued user injections in FIFO order."""
        with self._injection_lock:
            messages = list(self._pending_injections)
            self._pending_injections.clear()
        return messages

    # -- internals ----------------------------------------------------------

    def _flush_text(self) -> None:
        """Sanitize and emit any buffered agent text, then clear the buffer."""
        raw = self._text_buf.strip()
        self._text_buf = ""
        if not raw:
            return
        self._queue.put(TextBlockMsg(text=sanitize_display_text(raw)))

    def _emit_tool_line(self, arg: str) -> None:
        name = self._tool_name or "?"
        style = TOOL_STYLE.get(name, DEFAULT_TOOL_STYLE)
        sanitized_arg = sanitize_display_text(arg) if arg else ""
        self._queue.put(ToolLineMsg(
            tool_name=name,
            arg=sanitized_arg,
            style=style,
        ))

    def _try_extract_arg(self) -> str | None:
        """Extract the most relevant argument from partial tool JSON."""
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
