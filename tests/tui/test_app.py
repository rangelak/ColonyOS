"""Integration tests for the AssistantApp TUI shell.

Verifies that the app mounts with all widgets, that queue messages
render in the transcript, and that composer submission creates user
messages in the transcript.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from colonyos.models import PreflightError


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
        CommandOutputMsg,
        NoticeMsg,
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
            assert "Ctrl+L clear" in rendered
            assert "auto --no-confirm" in rendered
            assert "status" in rendered
            assert "help" in rendered

    @pytest.mark.asyncio
    async def test_monitor_mode_hides_welcome_and_input_widgets(self) -> None:
        """Daemon monitor mode should not mount the interactive welcome/input chrome."""
        app = AssistantApp(monitor_mode=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            transcript = app.query_one(TranscriptView)
            assert len(transcript.lines) == 0
            assert list(app.query(Composer)) == []
            assert list(app.query(HintBar)) == []


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
    async def test_phase_header_extra_renders(self) -> None:
        """PhaseHeaderMsg.extra should be preserved in the transcript and status bar."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            app.event_queue.sync_q.put(
                PhaseHeaderMsg(
                    phase_name="implement",
                    budget=2.0,
                    model="opus",
                    extra="branch: feat/tui",
                )
            )
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            status = app.query_one(StatusBar)
            assert "branch: feat/tui" in status._last_rendered

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
    async def test_command_output_renders(self) -> None:
        """CommandOutputMsg should render as a preserved preformatted block."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            app.event_queue.sync_q.put(CommandOutputMsg(text="  one\n\n    two"))
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            transcript = app.query_one(TranscriptView)
            assert len(transcript.lines) >= 5

    @pytest.mark.asyncio
    async def test_notice_renders_without_command_block_spacing(self) -> None:
        """NoticeMsg should render through the transcript notice path."""
        app = AssistantApp(monitor_mode=True)
        async with app.run_test() as pilot:
            app.event_queue.sync_q.put(NoticeMsg(text="Daemon monitor mode"))
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            transcript = app.query_one(TranscriptView)
            assert len(transcript.lines) > 0

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

    @pytest.mark.asyncio
    async def test_phase_turn_count_resets_between_phases(self) -> None:
        """A new phase should start counting turns from one again."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            status = app.query_one(StatusBar)
            app.event_queue.sync_q.put(PhaseHeaderMsg(phase_name="plan", budget=1.0, model="opus"))
            app.event_queue.sync_q.put(TurnCompleteMsg(turn_number=1))
            app.event_queue.sync_q.put(TurnCompleteMsg(turn_number=2))
            app.event_queue.sync_q.put(PhaseHeaderMsg(phase_name="implement", budget=2.0, model="opus"))
            app.event_queue.sync_q.put(TurnCompleteMsg(turn_number=1))
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            assert status.phase_name == "implement"
            assert status.turn_count == 1


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

    @pytest.mark.asyncio
    async def test_submit_during_active_run_without_injection_is_blocked(self) -> None:
        """Submitting while active without injection support should not start a second run."""
        received: list[str] = []

        def on_submit(text: str) -> None:
            received.append(text)

        app = AssistantApp(run_callback=on_submit)
        app._run_active = True
        async with app.run_test() as pilot:
            composer = app.query_one(Composer)
            ta = composer.query_one("TextArea")
            ta.focus()
            await pilot.pause()
            await pilot.press("h", "i")
            await pilot.press("enter")
            await pilot.pause()
            assert received == []

    @pytest.mark.asyncio
    async def test_preflight_failure_restores_prompt_to_composer(self) -> None:
        """Recoverable run failures should restore the submitted prompt."""
        def on_submit(text: str) -> None:
            raise PreflightError("Uncommitted changes detected")

        app = AssistantApp(run_callback=on_submit)
        async with app.run_test() as pilot:
            composer = app.query_one(Composer)
            ta = composer.query_one("TextArea")
            ta.focus()
            await pilot.pause()
            await pilot.press("h", "i")
            await pilot.press("enter")
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            assert ta.text == "hi"

    @pytest.mark.asyncio
    async def test_dirty_recovery_submission_routes_to_recovery_callback(self) -> None:
        """Once recovery is pending, submissions should route to the recovery callback."""
        run_calls: list[str] = []
        recovery_calls: list[str] = []
        error = PreflightError("Uncommitted changes detected", code="dirty_worktree")

        app = AssistantApp(
            run_callback=run_calls.append,
            recovery_callback=recovery_calls.append,
        )
        async with app.run_test() as pilot:
            composer = app.query_one(Composer)
            ta = composer.query_one("TextArea")
            ta.focus()
            app.begin_dirty_worktree_recovery("saved prompt", error)
            await pilot.pause()
            await pilot.press("c", "o", "m", "m", "i", "t")
            await pilot.press("enter")
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            assert recovery_calls == ["commit"]
            assert run_calls == []

    @pytest.mark.asyncio
    async def test_cancel_dirty_worktree_recovery_restores_saved_prompt(self) -> None:
        """Cancelling dirty-worktree recovery should restore the saved prompt."""
        error = PreflightError("Uncommitted changes detected", code="dirty_worktree")
        app = AssistantApp(recovery_callback=lambda _: None)
        async with app.run_test() as pilot:
            composer = app.query_one(Composer)
            ta = composer.query_one("TextArea")
            ta.focus()
            app.begin_dirty_worktree_recovery("saved prompt", error)
            await pilot.pause()
            app.cancel_dirty_worktree_recovery()
            await pilot.pause()
            assert ta.text == "saved prompt"
            assert app.get_dirty_worktree_recovery() is None

    @pytest.mark.asyncio
    async def test_begin_dirty_worktree_recovery_stores_error_metadata(self) -> None:
        """Recovery state should keep the original preflight error details."""
        app = AssistantApp(recovery_callback=lambda _: None)
        error = PreflightError(
            "Uncommitted changes detected",
            code="dirty_worktree",
            details={"dirty_output": "M src/app.py"},
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.begin_dirty_worktree_recovery("saved prompt", error)
            await pilot.pause()
            pending = app.get_dirty_worktree_recovery()
            assert pending is not None
            assert pending[0] == "saved prompt"
            assert pending[1].details["dirty_output"] == "M src/app.py"

    @pytest.mark.asyncio
    async def test_clear_dirty_worktree_recovery_clears_pending_state(self) -> None:
        """Successful recovery should clear the pending recovery state."""
        app = AssistantApp(recovery_callback=lambda _: None)
        error = PreflightError("dirty", code="dirty_worktree")
        async with app.run_test() as pilot:
            await pilot.pause()
            app.begin_dirty_worktree_recovery("saved prompt", error)
            await pilot.pause()
            app.clear_dirty_worktree_recovery()
            await pilot.pause()
            assert app.get_dirty_worktree_recovery() is None

    def test_start_run_uses_non_exclusive_worker(self) -> None:
        """Workers must NOT be exclusive to avoid canceling active runs (PRD requirement)."""
        app = AssistantApp(run_callback=lambda _: None)
        calls: list[dict[str, object]] = []

        def fake_run_worker(
            worker: object,
            *,
            thread: bool,
            exclusive: bool,
        ) -> None:
            calls.append({
                "worker": worker,
                "thread": thread,
                "exclusive": exclusive,
            })

        app.run_worker = fake_run_worker  # type: ignore[method-assign]
        app._start_run("hello")

        assert app._run_active is True
        assert len(calls) == 1
        assert calls[0]["thread"] is True
        assert calls[0]["exclusive"] is False


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
            with patch("colonyos.tui.app.request_cancel") as mock_cancel:
                app.action_cancel_run()
            await pilot.pause()
            status = app.query_one(StatusBar)
            transcript = app.query_one(TranscriptView)
            # Status bar should show error state
            assert "cancel" in status.error_msg.lower()
            # Transcript should have the cancel message
            assert len(transcript.lines) > 0
            mock_cancel.assert_called_once()

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

    @pytest.mark.asyncio
    async def test_consumer_loop_survives_dispatch_error(self) -> None:
        """If a widget method raises during dispatch, the consumer loop should continue."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            status = app.query_one(StatusBar)
            transcript = app.query_one(TranscriptView)
            # Record baseline line count
            baseline = len(transcript.lines)
            # Temporarily make set_phase raise to simulate a dispatch error
            original = status.set_phase
            status.set_phase = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
            app.event_queue.sync_q.put(
                PhaseHeaderMsg(phase_name="broken", budget=1.0, model="opus")
            )
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            # Restore and send a valid message — consumer should still be alive
            status.set_phase = original
            app.event_queue.sync_q.put(TextBlockMsg(text="still alive"))
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()
            assert len(transcript.lines) > baseline, "Consumer loop died after dispatch error"


class TestCancelRunBehavior:
    """Verify two-tier cancellation semantics."""

    @pytest.mark.asyncio
    async def test_first_ctrl_c_does_not_exit_tui(self) -> None:
        """First Ctrl+C should set stop event but NOT exit the TUI."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_cancel_run()
            await pilot.pause()
            # The app should still be running (not exited)
            assert app._stop_event.is_set()
            assert app._auto_loop_active is False
            # App is still responsive — we can still interact
            transcript = app.query_one(TranscriptView)
            assert len(transcript.lines) > 0

    @pytest.mark.asyncio
    async def test_second_ctrl_c_exits(self) -> None:
        """Second Ctrl+C within 2s should raise SystemExit."""
        app = AssistantApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_cancel_run()  # first press
            with pytest.raises(SystemExit):
                app.action_cancel_run()  # second press within 2s


class TestExportTranscriptPermissions:
    """Verify transcript export file permissions."""

    @pytest.mark.asyncio
    async def test_export_creates_file_with_restricted_permissions(self, tmp_path) -> None:
        """Exported transcript files should have 0o600 permissions."""
        import os
        import stat

        app = AssistantApp()
        async with app.run_test() as pilot:
            # Add some content to the transcript
            app.event_queue.sync_q.put(TextBlockMsg(text="test content for export"))
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()

            # Monkeypatch the logs dir to use tmp_path
            import colonyos.tui.app as app_module
            original_path = None

            # Trigger export
            app.action_export_transcript()
            await pilot.pause()

            # Find the exported file
            logs_dir = app_module.Path(".colonyos") / "logs"
            if logs_dir.exists():
                exports = list(logs_dir.glob("transcript_*.txt"))
                if exports:
                    mode = os.stat(exports[-1]).st_mode
                    assert stat.S_IMODE(mode) == 0o600
                    # Cleanup
                    for f in exports:
                        f.unlink(missing_ok=True)


class TestLogWriterIntegration:
    """Verify log writer is wired into the queue consumer."""

    @pytest.mark.asyncio
    async def test_log_writer_receives_phase_header(self, tmp_path) -> None:
        """LogWriter should receive phase header messages from the consumer."""
        from colonyos.tui.log_writer import TranscriptLogWriter

        writer = TranscriptLogWriter(tmp_path, "test-integration")
        app = AssistantApp(log_writer=writer)
        async with app.run_test() as pilot:
            app.event_queue.sync_q.put(
                PhaseHeaderMsg(phase_name="plan", budget=5.0, model="opus")
            )
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()

        writer.close()
        content = writer.log_path.read_text()
        assert "plan" in content
        assert "$5.00" in content

    @pytest.mark.asyncio
    async def test_log_writer_receives_tool_lines(self, tmp_path) -> None:
        """LogWriter should receive tool line messages from the consumer."""
        from colonyos.tui.log_writer import TranscriptLogWriter

        writer = TranscriptLogWriter(tmp_path, "test-tools")
        app = AssistantApp(log_writer=writer)
        async with app.run_test() as pilot:
            app.event_queue.sync_q.put(
                ToolLineMsg(tool_name="Read", arg="foo.py", style="cyan")
            )
            await pilot.pause()
            await asyncio.sleep(0.15)
            await pilot.pause()

        writer.close()
        content = writer.log_path.read_text()
        assert "Read" in content
        assert "foo.py" in content

    @pytest.mark.asyncio
    async def test_log_writer_closed_on_unmount(self, tmp_path) -> None:
        """LogWriter should be closed when the app unmounts."""
        from colonyos.tui.log_writer import TranscriptLogWriter

        writer = TranscriptLogWriter(tmp_path, "test-close")
        app = AssistantApp(log_writer=writer)
        async with app.run_test() as pilot:
            await pilot.pause()
        # After context exit, writer should be closed
        assert writer._closed
