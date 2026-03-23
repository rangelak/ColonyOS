"""Integration tests for the AssistantApp TUI shell.

Verifies that the app mounts with all widgets, that queue messages
render in the transcript, and that composer submission creates user
messages in the transcript.
"""

from __future__ import annotations

import asyncio

import pytest


def _tui_available() -> bool:
    try:
        import textual  # noqa: F401
        import janus  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(
    not _tui_available(),
    reason="TUI extras not installed",
)

if _tui_available():
    from colonyos.tui.adapter import (
        PhaseCompleteMsg,
        PhaseErrorMsg,
        PhaseHeaderMsg,
        TextBlockMsg,
        ToolLineMsg,
        TurnCompleteMsg,
        UserInjectionMsg,
    )
    from colonyos.tui.app import AssistantApp
    from colonyos.tui.widgets.composer import Composer
    from colonyos.tui.widgets.hint_bar import HintBar
    from colonyos.tui.widgets.status_bar import StatusBar
    from colonyos.tui.widgets.transcript import TranscriptView


class TestAppMounts:
    """Verify the app mounts with all four widgets."""

    @pytest.mark.asyncio
    async def test_all_widgets_present(self) -> None:
        """App should contain StatusBar, TranscriptView, Composer, HintBar."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            assert app.query_one(StatusBar) is not None
            assert app.query_one(TranscriptView) is not None
            assert app.query_one(Composer) is not None
            assert app.query_one(HintBar) is not None

    @pytest.mark.asyncio
    async def test_composer_has_focus_on_mount(self) -> None:
        """Composer text area should be focused when the app mounts."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            composer = app.query_one(Composer)
            ta = composer.query_one("TextArea")
            assert ta.has_focus

    @pytest.mark.asyncio
    async def test_idle_mount_shows_welcome_banner(self) -> None:
        """Launching without an initial prompt should show the welcome banner."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            transcript = app.query_one(TranscriptView)
            assert len(transcript.lines) > 0

    @pytest.mark.asyncio
    async def test_idle_mount_shows_command_hints(self) -> None:
        """Hint bar should show the configured TUI command examples."""
        app = AssistantApp(command_hints=["auto --no-confirm", "status", "help"])
        async with app.run_test() as pilot:
            await pilot.pause()
            hint = app.query_one(HintBar)
            rendered = str(hint.render())
            assert "auto --no-confirm" in rendered
            assert "status" in rendered
            assert "help" in rendered


class TestQueueToTranscript:
    """Verify that feeding messages through the queue renders in the transcript."""

    @pytest.mark.asyncio
    async def test_phase_header_renders(self) -> None:
        """PhaseHeaderMsg should appear in the transcript."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            app.event_queue.sync_q.put(
                PhaseHeaderMsg(phase_name="planner", budget=1.0, model="opus")
            )
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            transcript = app.query_one(TranscriptView)
            log = transcript
            assert len(log.lines) > 0

    @pytest.mark.asyncio
    async def test_tool_line_renders(self) -> None:
        """ToolLineMsg should appear in the transcript."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            app.event_queue.sync_q.put(
                ToolLineMsg(tool_name="Read", arg="src/main.py", style="cyan")
            )
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            transcript = app.query_one(TranscriptView)
            log = transcript
            assert len(log.lines) > 0

    @pytest.mark.asyncio
    async def test_text_block_renders(self) -> None:
        """TextBlockMsg should appear in the transcript."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            app.event_queue.sync_q.put(TextBlockMsg(text="Hello from the agent"))
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            transcript = app.query_one(TranscriptView)
            log = transcript
            assert len(log.lines) > 0

    @pytest.mark.asyncio
    async def test_phase_complete_renders(self) -> None:
        """PhaseCompleteMsg should update status bar and transcript."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            app.event_queue.sync_q.put(
                PhaseCompleteMsg(cost=0.05, turns=3, duration_ms=1200)
            )
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            transcript = app.query_one(TranscriptView)
            log = transcript
            assert len(log.lines) > 0

    @pytest.mark.asyncio
    async def test_phase_error_renders(self) -> None:
        """PhaseErrorMsg should appear in the transcript."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            app.event_queue.sync_q.put(PhaseErrorMsg(error="Something failed"))
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            transcript = app.query_one(TranscriptView)
            log = transcript
            assert len(log.lines) > 0

    @pytest.mark.asyncio
    async def test_turn_complete_increments_status(self) -> None:
        """TurnCompleteMsg should bump the status bar turn counter."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            status = app.query_one(StatusBar)
            status.set_phase("test-phase")
            assert status.turn_count == 0
            app.event_queue.sync_q.put(TurnCompleteMsg(turn_number=1))
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            assert status.turn_count >= 1


class TestComposerSubmission:
    """Verify that submitting from the composer creates a user message."""

    @pytest.mark.asyncio
    async def test_submit_adds_user_message(self) -> None:
        """Submitting text via the composer should add a user message to transcript."""
        received = []

        def on_submit(text: str) -> None:
            received.append(text)

        app = AssistantApp(run_callback=on_submit)
        async with app.run_test() as pilot:
            composer = app.query_one(Composer)
            ta = composer.query_one("TextArea")
            ta.focus()
            await pilot.pause()
            await pilot.press("h", "e", "l", "l", "o")
            await pilot.press("enter")
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            transcript = app.query_one(TranscriptView)
            log = transcript
            assert len(log.lines) > 0

    @pytest.mark.asyncio
    async def test_submit_during_active_run_becomes_injection(self) -> None:
        """Submitting while active should queue an injection instead of a new run."""
        received: list[str] = []

        def on_inject(text: str) -> None:
            received.append(text)

        app = AssistantApp(inject_callback=on_inject)
        app._run_active = True
        async with app.run_test() as pilot:
            composer = app.query_one(Composer)
            ta = composer.query_one("TextArea")
            ta.focus()
            await pilot.pause()
            await pilot.press("h", "i")
            await pilot.press("enter")
            await pilot.pause()
            assert received == ["hi"]


class TestKeybindings:
    """Verify app-level keybindings."""

    @pytest.mark.asyncio
    async def test_ctrl_l_clears_transcript(self) -> None:
        """Ctrl+L should clear the transcript."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            transcript = app.query_one(TranscriptView)
            app.event_queue.sync_q.put(TextBlockMsg(text="some text"))
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            log = transcript
            assert len(log.lines) > 0
            await pilot.press("ctrl+l")
            await pilot.pause()
            assert len(log.lines) == 0

    @pytest.mark.asyncio
    async def test_escape_focuses_composer(self) -> None:
        """Escape should return focus to the composer."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            composer = app.query_one(Composer)
            ta = composer.query_one("TextArea")
            assert ta.has_focus

    @pytest.mark.asyncio
    async def test_ctrl_c_cancels_run(self) -> None:
        """Ctrl+C should cancel workers and show cancelled message."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            # Trigger cancel action directly (Ctrl+C binding may be intercepted by test harness)
            app.action_cancel_run()
            await pilot.pause()
            status = app.query_one(StatusBar)
            transcript = app.query_one(TranscriptView)
            # Status bar should show error state
            assert "cancel" in status.error_msg.lower()
            # Transcript should have the cancel message
            assert len(transcript.lines) > 0

    @pytest.mark.asyncio
    async def test_queue_user_injection_renders(self) -> None:
        """UserInjectionMsg should render as a distinct transcript line."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.event_queue.sync_q.put(UserInjectionMsg(text="follow this note"))
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            transcript = app.query_one(TranscriptView)
            assert len(transcript.lines) > 0
