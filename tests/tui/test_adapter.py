"""Tests for TextualUI adapter — queue contract only, no Textual dependency."""

from __future__ import annotations

import json
import queue
import threading
from unittest.mock import MagicMock

import pytest

from colonyos.tui.adapter import (
    PhaseCompleteMsg,
    PhaseErrorMsg,
    PhaseHeaderMsg,
    TextBlockMsg,
    TextualUI,
    ToolLineMsg,
    TurnCompleteMsg,
)


class FakeSyncQueue:
    """Minimal stand-in for ``janus.SyncQueue`` using stdlib ``queue.Queue``.

    Only implements ``put`` and ``get`` — enough for adapter tests without
    requiring a running asyncio event loop.
    """

    def __init__(self) -> None:
        self._q: queue.Queue[object] = queue.Queue()

    def put(self, item: object) -> None:
        self._q.put(item)

    def get(self, timeout: float = 1.0) -> object:
        return self._q.get(timeout=timeout)

    def get_nowait(self) -> object:
        return self._q.get_nowait()

    @property
    def empty(self) -> bool:
        return self._q.empty()

    def drain(self) -> list[object]:
        """Drain all items currently in the queue."""
        items: list[object] = []
        while not self._q.empty():
            items.append(self._q.get_nowait())
        return items


@pytest.fixture()
def fake_queue() -> FakeSyncQueue:
    return FakeSyncQueue()


@pytest.fixture()
def ui(fake_queue: FakeSyncQueue) -> TextualUI:
    return TextualUI(sync_queue=fake_queue)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# phase_header
# ---------------------------------------------------------------------------


class TestPhaseHeader:
    def test_emits_phase_header_msg(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.phase_header("planning", budget=1.50, model="opus")
        msg = fake_queue.get()
        assert isinstance(msg, PhaseHeaderMsg)
        assert msg.phase_name == "planning"
        assert msg.budget == 1.50
        assert msg.model == "opus"
        assert msg.extra == ""

    def test_emits_extra_when_provided(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.phase_header("review", budget=0.5, model="sonnet", extra="round 2")
        msg = fake_queue.get()
        assert isinstance(msg, PhaseHeaderMsg)
        assert msg.extra == "round 2"

    def test_sanitizes_phase_name(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.phase_header("plan\x1b[31mning", budget=1.0, model="opus")
        msg = fake_queue.get()
        assert isinstance(msg, PhaseHeaderMsg)
        assert "\x1b" not in msg.phase_name
        assert "planning" in msg.phase_name


# ---------------------------------------------------------------------------
# phase_complete
# ---------------------------------------------------------------------------


class TestPhaseComplete:
    def test_emits_phase_complete_msg(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.phase_complete(cost=0.42, turns=5, duration_ms=12000)
        msg = fake_queue.get()
        assert isinstance(msg, PhaseCompleteMsg)
        assert msg.cost == 0.42
        assert msg.turns == 5
        assert msg.duration_ms == 12000

    def test_flushes_text_before_complete(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.on_text_delta("some text")
        ui.phase_complete(cost=0.1, turns=1, duration_ms=1000)
        msgs = fake_queue.drain()
        assert len(msgs) == 2
        assert isinstance(msgs[0], TextBlockMsg)
        assert isinstance(msgs[1], PhaseCompleteMsg)


# ---------------------------------------------------------------------------
# phase_error
# ---------------------------------------------------------------------------


class TestPhaseError:
    def test_emits_phase_error_msg(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.phase_error("something broke")
        msg = fake_queue.get()
        assert isinstance(msg, PhaseErrorMsg)
        assert msg.error == "something broke"

    def test_sanitizes_error(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.phase_error("err\x1b[0mor")
        msg = fake_queue.get()
        assert isinstance(msg, PhaseErrorMsg)
        assert "\x1b" not in msg.error

    def test_flushes_text_before_error(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.on_text_delta("buffered")
        ui.phase_error("fail")
        msgs = fake_queue.drain()
        assert len(msgs) == 2
        assert isinstance(msgs[0], TextBlockMsg)
        assert isinstance(msgs[1], PhaseErrorMsg)


# ---------------------------------------------------------------------------
# Tool callbacks
# ---------------------------------------------------------------------------


class TestToolCallbacks:
    def test_tool_start_done_emits_tool_line(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.on_tool_start("Bash")
        ui.on_tool_input_delta(json.dumps({"command": "ls -la"}))
        ui.on_tool_done()
        msgs = fake_queue.drain()
        tool_msgs = [m for m in msgs if isinstance(m, ToolLineMsg)]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].tool_name == "Bash"
        assert tool_msgs[0].arg == "ls -la"
        assert tool_msgs[0].style == "yellow"

    def test_tool_read_extracts_file_path(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.on_tool_start("Read")
        ui.on_tool_input_delta(json.dumps({"file_path": "/src/main.py"}))
        ui.on_tool_done()
        msgs = fake_queue.drain()
        tool_msgs = [m for m in msgs if isinstance(m, ToolLineMsg)]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].arg == "/src/main.py"
        assert tool_msgs[0].style == "cyan"

    def test_tool_done_without_parsed_arg(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.on_tool_start("Bash")
        ui.on_tool_input_delta("{invalid json")
        ui.on_tool_done()
        msgs = fake_queue.drain()
        tool_msgs = [m for m in msgs if isinstance(m, ToolLineMsg)]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].tool_name == "Bash"
        assert tool_msgs[0].arg == ""

    def test_tool_with_unknown_name_uses_default_style(
        self, ui: TextualUI, fake_queue: FakeSyncQueue
    ) -> None:
        ui.on_tool_start("CustomTool")
        ui.on_tool_done()
        msgs = fake_queue.drain()
        tool_msgs = [m for m in msgs if isinstance(m, ToolLineMsg)]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].style == "dim"

    def test_incremental_json_emits_early(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        """Tool line is emitted as soon as the arg is extractable from partial JSON."""
        ui.on_tool_start("Read")
        # Partial JSON that becomes parseable
        ui.on_tool_input_delta('{"file_path": "/foo/bar.py"')
        # Not parseable yet — no message
        assert fake_queue.empty
        ui.on_tool_input_delta("}")
        # Now parseable — should emit
        msgs = fake_queue.drain()
        tool_msgs = [m for m in msgs if isinstance(m, ToolLineMsg)]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].arg == "/foo/bar.py"

    def test_text_during_tool_is_ignored(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.on_tool_start("Bash")
        ui.on_text_delta("this should be ignored")
        ui.on_tool_done()
        ui.on_turn_complete()
        msgs = fake_queue.drain()
        # Should only have ToolLineMsg and TurnCompleteMsg, no TextBlockMsg
        text_msgs = [m for m in msgs if isinstance(m, TextBlockMsg)]
        assert len(text_msgs) == 0

    def test_flushes_text_before_tool(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.on_text_delta("agent reasoning ")
        ui.on_tool_start("Bash")
        ui.on_tool_done()
        msgs = fake_queue.drain()
        assert isinstance(msgs[0], TextBlockMsg)
        assert msgs[0].text == "agent reasoning"

    def test_agent_tool_extracts_first_meaningful_line(
        self, ui: TextualUI, fake_queue: FakeSyncQueue
    ) -> None:
        ui.on_tool_start("Agent")
        ui.on_tool_input_delta(json.dumps({
            "prompt": "##\n\nPlease implement the feature"
        }))
        ui.on_tool_done()
        msgs = fake_queue.drain()
        tool_msgs = [m for m in msgs if isinstance(m, ToolLineMsg)]
        assert len(tool_msgs) == 1
        assert "implement" in tool_msgs[0].arg.lower()

    def test_tool_arg_sanitized(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.on_tool_start("Bash")
        ui.on_tool_input_delta(json.dumps({"command": "echo \x1b[31mhello"}))
        ui.on_tool_done()
        msgs = fake_queue.drain()
        tool_msgs = [m for m in msgs if isinstance(m, ToolLineMsg)]
        assert "\x1b" not in tool_msgs[0].arg


# ---------------------------------------------------------------------------
# Text streaming
# ---------------------------------------------------------------------------


class TestTextStreaming:
    def test_text_delta_buffers_until_turn_complete(
        self, ui: TextualUI, fake_queue: FakeSyncQueue
    ) -> None:
        ui.on_text_delta("Hello ")
        ui.on_text_delta("world")
        assert fake_queue.empty
        ui.on_turn_complete()
        msgs = fake_queue.drain()
        text_msgs = [m for m in msgs if isinstance(m, TextBlockMsg)]
        assert len(text_msgs) == 1
        assert text_msgs[0].text == "Hello world"

    def test_empty_text_not_emitted(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.on_text_delta("   ")
        ui.on_turn_complete()
        msgs = fake_queue.drain()
        text_msgs = [m for m in msgs if isinstance(m, TextBlockMsg)]
        assert len(text_msgs) == 0

    def test_text_sanitized(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.on_text_delta("clean \x1b[31mred\x1b[0m text")
        ui.on_turn_complete()
        msgs = fake_queue.drain()
        text_msgs = [m for m in msgs if isinstance(m, TextBlockMsg)]
        assert len(text_msgs) == 1
        assert "\x1b" not in text_msgs[0].text


# ---------------------------------------------------------------------------
# on_turn_complete
# ---------------------------------------------------------------------------


class TestTurnComplete:
    def test_emits_turn_complete_msg(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.on_turn_complete()
        msgs = fake_queue.drain()
        turn_msgs = [m for m in msgs if isinstance(m, TurnCompleteMsg)]
        assert len(turn_msgs) == 1
        assert turn_msgs[0].turn_number == 1

    def test_turn_number_increments(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        ui.on_turn_complete()
        ui.on_turn_complete()
        ui.on_turn_complete()
        msgs = fake_queue.drain()
        turn_msgs = [m for m in msgs if isinstance(m, TurnCompleteMsg)]
        assert [m.turn_number for m in turn_msgs] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Message dataclass immutability
# ---------------------------------------------------------------------------


class TestMessageImmutability:
    def test_messages_are_frozen(self) -> None:
        msg = PhaseHeaderMsg(phase_name="test", budget=1.0, model="opus")
        with pytest.raises(AttributeError):
            msg.phase_name = "changed"  # type: ignore[misc]

    def test_all_message_types_frozen(self) -> None:
        msgs = [
            PhaseHeaderMsg(phase_name="p", budget=1.0, model="m"),
            PhaseCompleteMsg(cost=0.5, turns=3, duration_ms=1000),
            PhaseErrorMsg(error="e"),
            ToolLineMsg(tool_name="t", arg="a", style="s"),
            TextBlockMsg(text="t"),
            TurnCompleteMsg(turn_number=1),
        ]
        for msg in msgs:
            assert hasattr(msg, "__dataclass_fields__")


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    def test_complete_phase_lifecycle(self, ui: TextualUI, fake_queue: FakeSyncQueue) -> None:
        """Simulate a realistic phase with header, tools, text, and completion."""
        ui.phase_header("implement", budget=2.00, model="opus")
        ui.on_text_delta("Let me read the file first.")
        ui.on_turn_complete()
        ui.on_tool_start("Read")
        ui.on_tool_input_delta(json.dumps({"file_path": "/src/main.py"}))
        ui.on_tool_done()
        ui.on_text_delta("Now I'll edit it.")
        ui.on_turn_complete()
        ui.phase_complete(cost=0.35, turns=2, duration_ms=8500)

        msgs = fake_queue.drain()
        types = [type(m).__name__ for m in msgs]
        assert types == [
            "PhaseHeaderMsg",
            "TextBlockMsg",
            "TurnCompleteMsg",
            "ToolLineMsg",
            "TextBlockMsg",
            "TurnCompleteMsg",
            "PhaseCompleteMsg",
        ]
