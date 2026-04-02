from __future__ import annotations

import json
from typing import Any, cast

from colonyos.tui.adapter import (
    NoticeMsg,
    PhaseCompleteMsg,
    PhaseErrorMsg,
    PhaseHeaderMsg,
    TextBlockMsg,
    ToolLineMsg,
    TurnCompleteMsg,
)

MONITOR_EVENT_PREFIX = "__COLONYOS_TUI_EVENT__"


def encode_monitor_event(payload: dict[str, Any]) -> str:
    """Serialize a monitor event for transport over daemon stdout."""
    return f"{MONITOR_EVENT_PREFIX}{json.dumps(payload, separators=(',', ':'), ensure_ascii=False)}"


def decode_monitor_event_line(text: str) -> object | None:
    """Decode a monitor event line into a TUI adapter message."""
    if not text.startswith(MONITOR_EVENT_PREFIX):
        return None
    raw = text[len(MONITOR_EVENT_PREFIX):]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    d = cast(dict[str, Any], payload)
    event_type = d.get("type")
    if event_type == "notice":
        return NoticeMsg(text=str(d.get("text", "")))
    if event_type == "phase_header":
        return PhaseHeaderMsg(
            phase_name=str(d.get("phase_name", "")),
            budget=float(d.get("budget", 0.0) or 0.0),
            model=str(d.get("model", "")),
            extra=str(d.get("extra", "")),
        )
    if event_type == "phase_complete":
        return PhaseCompleteMsg(
            cost=float(d.get("cost", 0.0) or 0.0),
            turns=int(d.get("turns", 0) or 0),
            duration_ms=int(d.get("duration_ms", 0) or 0),
        )
    if event_type == "phase_error":
        return PhaseErrorMsg(error=str(d.get("error", "")))
    if event_type == "tool_line":
        return ToolLineMsg(
            tool_name=str(d.get("tool_name", "")),
            arg=str(d.get("arg", "")),
            style=str(d.get("style", "")),
            badge_text=str(d.get("badge_text", "")),
            badge_style=str(d.get("badge_style", "")),
        )
    if event_type == "text_block":
        return TextBlockMsg(
            text=str(d.get("text", "")),
            badge_text=str(d.get("badge_text", "")),
            badge_style=str(d.get("badge_style", "")),
        )
    if event_type == "turn_complete":
        return TurnCompleteMsg(turn_number=int(d.get("turn_number", 0) or 0))
    return None
