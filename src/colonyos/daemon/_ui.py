"""Standalone UI classes for the ColonyOS daemon.

These classes have zero coupling to Daemon instance state and can be
imported independently.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
from typing import Any

from colonyos.tui.monitor_protocol import encode_monitor_event

logger = logging.getLogger(__name__)


class DaemonError(RuntimeError):
    """Raised for unrecoverable daemon errors."""


class _CombinedUI:
    """Forward phase UI events to a terminal UI and a secondary mirror UI."""

    _SECONDARY_CALL_TIMEOUT_SECONDS = 3.0

    def __init__(self, primary: Any, secondary: Any) -> None:
        self._primary = primary
        self._secondary = secondary

    def _secondary_call(self, method: str, *args: object, **kwargs: object) -> None:
        done = threading.Event()

        def _invoke() -> None:
            try:
                getattr(self._secondary, method)(*args, **kwargs)
            except Exception:
                logger.debug("Secondary UI call %s failed", method, exc_info=True)
            finally:
                done.set()

        thread = threading.Thread(
            target=_invoke,
            name=f"secondary-ui-{method}",
            daemon=True,
        )
        thread.start()
        if not done.wait(self._SECONDARY_CALL_TIMEOUT_SECONDS):
            logger.warning(
                "Secondary UI call %s timed out after %.1fs; continuing without waiting",
                method,
                self._SECONDARY_CALL_TIMEOUT_SECONDS,
            )

    def phase_header(self, *args: object, **kwargs: object) -> None:
        self._primary.phase_header(*args, **kwargs)
        self._secondary_call("phase_header", *args, **kwargs)

    def phase_complete(self, *args: object, **kwargs: object) -> None:
        self._primary.phase_complete(*args, **kwargs)
        self._secondary_call("phase_complete", *args, **kwargs)

    def phase_error(self, *args: object, **kwargs: object) -> None:
        self._primary.phase_error(*args, **kwargs)
        self._secondary_call("phase_error", *args, **kwargs)

    def phase_note(self, *args: object, **kwargs: object) -> None:
        self._primary.phase_note(*args, **kwargs)
        self._secondary_call("phase_note", *args, **kwargs)

    def slack_note(self, text: str) -> None:
        self._secondary_call("phase_note", text)

    def on_tool_start(self, *args: object) -> None:
        self._primary.on_tool_start(*args)
        self._secondary_call("on_tool_start", *args)

    def on_tool_input_delta(self, *args: object) -> None:
        self._primary.on_tool_input_delta(*args)
        self._secondary_call("on_tool_input_delta", *args)

    def on_tool_done(self) -> None:
        self._primary.on_tool_done()
        self._secondary_call("on_tool_done")

    def on_text_delta(self, *args: object) -> None:
        self._primary.on_text_delta(*args)
        self._secondary_call("on_text_delta", *args)

    def on_turn_complete(self) -> None:
        self._primary.on_turn_complete()
        self._secondary_call("on_turn_complete")


class _DaemonMonitorEventUI:
    """Emit structured TUI events over stdout for the daemon monitor."""

    def __init__(
        self,
        prefix: str = "",
        *,
        badge_text: str = "",
        badge_style: str = "",
    ) -> None:
        self._prefix = prefix
        self._badge_text = badge_text
        self._badge_style = badge_style
        self._tool_name: str | None = None
        self._tool_json = ""
        self._tool_displayed = False
        self._text_buf = ""
        self._in_tool = False
        self._turn_count = 0

    def _emit(self, payload: dict[str, Any]) -> None:
        sys.stdout.write(encode_monitor_event(payload) + "\n")
        sys.stdout.flush()

    def phase_header(
        self,
        phase_name: str,
        budget: float,
        model: str,
        extra: str = "",
    ) -> None:
        self._turn_count = 0
        self._emit({
            "type": "phase_header",
            "phase_name": phase_name,
            "budget": budget,
            "model": model,
            "extra": extra,
        })

    def phase_complete(self, cost: float, turns: int, duration_ms: int) -> None:
        self._flush_text()
        self._emit({
            "type": "phase_complete",
            "cost": cost,
            "turns": turns,
            "duration_ms": duration_ms,
        })

    def phase_error(self, error: str) -> None:
        self._flush_text()
        self._emit({"type": "phase_error", "error": error})

    def phase_note(self, text: str) -> None:
        note = text.strip()
        if not note:
            return
        self._emit({"type": "notice", "text": note})

    def slack_note(self, text: str) -> None:
        """No-op: monitor event UIs are terminal-side only."""

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
        self._emit({"type": "turn_complete", "turn_number": self._turn_count})

    def _flush_text(self) -> None:
        raw = self._text_buf.strip()
        self._text_buf = ""
        if not raw:
            return
        self._emit({
            "type": "text_block",
            "text": raw,
            "badge_text": self._badge_text,
            "badge_style": self._badge_style,
        })

    def _emit_tool_line(self, arg: str) -> None:
        from colonyos.ui import DEFAULT_TOOL_STYLE, TOOL_ARG_KEYS, TOOL_STYLE, _first_meaningful_line, _truncate

        name = self._tool_name or "?"
        style = TOOL_STYLE.get(name, DEFAULT_TOOL_STYLE)
        display_arg = arg
        if name in {"Agent", "Dispatch", "Task"} and display_arg:
            display_arg = _first_meaningful_line(display_arg)
        display_arg = _truncate(display_arg, 80) if display_arg else ""
        self._emit({
            "type": "tool_line",
            "tool_name": name,
            "arg": display_arg,
            "style": style,
            "badge_text": self._badge_text,
            "badge_style": self._badge_style,
        })

    def _try_extract_arg(self) -> str | None:
        from colonyos.ui import TOOL_ARG_KEYS

        if not self._tool_name:
            return None
        keys = TOOL_ARG_KEYS.get(self._tool_name)
        if not keys:
            return None
        try:
            data = json.loads(self._tool_json)
        except (json.JSONDecodeError, TypeError):
            return None
        for key in keys:
            value = data.get(key)
            if value:
                return str(value)
        return None
