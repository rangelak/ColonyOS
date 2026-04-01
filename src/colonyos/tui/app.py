"""AssistantApp — the main Textual application shell for ColonyOS TUI.

Assembles the four core widgets (StatusBar, TranscriptView, Composer,
HintBar) into a vertical layout and wires a janus queue consumer loop
that dispatches adapter messages to the appropriate widgets.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import janus
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches

from colonyos.cancellation import request_cancel
from colonyos.models import PreflightError
from colonyos.tui.adapter import (
    CommandOutputMsg,
    IterationHeaderMsg,
    LoopCompleteMsg,
    NoticeMsg,
    PhaseCompleteMsg,
    PhaseErrorMsg,
    PhaseHeaderMsg,
    TextBlockMsg,
    ToolLineMsg,
    TurnCompleteMsg,
    UserInjectionMsg,
)
from colonyos.tui.styles import APP_CSS
from colonyos.tui.widgets.composer import Composer
from colonyos.tui.widgets.hint_bar import HintBar
from colonyos.tui.widgets.status_bar import StatusBar
from colonyos.tui.widgets.transcript import TranscriptView

logger = logging.getLogger(__name__)


class AssistantApp(App):
    """Interactive terminal UI for ColonyOS pipeline runs.

    Layout (top to bottom):
        StatusBar  — current phase, cost, turns, elapsed
        TranscriptView — scrollable agent activity log
        Composer   — multi-line input with auto-grow
        HintBar    — keybinding hints

    The app creates a ``janus.Queue`` on mount.  The sync side is exposed
    as ``event_queue`` so the ``TextualUI`` adapter (running in a worker
    thread) can push messages.  An async consumer drains the queue and
    dispatches each message to the appropriate widget.

    Args:
        run_callback: Optional callable invoked in a worker thread when
            the user submits input from the composer.  Receives the
            submitted text as its only argument.
    """

    CSS = APP_CSS

    BINDINGS = [
        Binding("ctrl+c", "cancel_run", "Cancel current run", show=False),
        Binding("q", "quit_app", "Quit", show=False),
        Binding("ctrl+l", "clear_transcript", "Clear transcript", show=False),
        Binding("escape", "focus_composer", "Focus composer", show=False),
        Binding("end", "scroll_to_end", "Scroll to bottom", show=False),
        Binding("ctrl+s", "export_transcript", "Export transcript", show=False),
    ]

    def __init__(
        self,
        run_callback: Callable[[str], None] | None = None,
        recovery_callback: Callable[[str], None] | None = None,
        inject_callback: Callable[[str], None] | None = None,
        cancel_callback: Callable[[], None] | None = None,
        initial_prompt: str | None = None,
        command_hints: Sequence[str] | None = None,
        log_writer: Any | None = None,
        monitor_mode: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._run_callback = run_callback
        self._recovery_callback = recovery_callback
        self._inject_callback = inject_callback
        self._cancel_callback = cancel_callback
        self._initial_prompt = initial_prompt
        self._command_hints = list(command_hints or [])
        self._log_writer = log_writer
        self._monitor_mode = monitor_mode
        self._event_queue: janus.Queue[object] | None = None
        self._consumer_task: asyncio.Task[None] | None = None
        self._run_active = False
        self._last_cancel_at = 0.0
        self._pending_recovery_error: PreflightError | None = None
        self._pending_recovery_prompt: str | None = None
        self._stop_event = threading.Event()
        self._auto_loop_active = False

    @property
    def event_queue(self) -> janus.Queue[object]:
        """The janus queue used for thread-safe event passing.

        Created on mount; raises RuntimeError if accessed before mount.
        """
        if self._event_queue is None:
            raise RuntimeError("event_queue not available before mount")
        return self._event_queue

    def compose(self) -> ComposeResult:
        """Build the widget tree."""
        yield StatusBar()
        yield TranscriptView()
        if not self._monitor_mode:
            yield Composer()
            yield HintBar()

    async def on_mount(self) -> None:
        """Create the event queue, start the consumer, and auto-submit initial prompt."""
        self._event_queue = janus.Queue()
        self._consumer_task = asyncio.create_task(self._consume_queue())
        if not self._monitor_mode:
            self.query_one(HintBar).set_command_hints(self._command_hints)

        if self._initial_prompt and self._run_callback is not None:
            transcript = self.query_one(TranscriptView)
            transcript.append_user_message(self._initial_prompt)
            self._start_run(self._initial_prompt)
        elif not self._monitor_mode:
            self.query_one(TranscriptView).append_welcome_banner()

    async def on_unmount(self) -> None:
        """Clean up the consumer task, queue, and log writer on exit."""
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        if self._event_queue is not None:
            self._event_queue.close()
        if self._log_writer is not None:
            self._log_writer.close()

    # -----------------------------------------------------------------
    # Queue consumer loop
    # -----------------------------------------------------------------

    async def _consume_queue(self) -> None:
        """Drain the async side of the janus queue and dispatch messages."""
        queue = self.event_queue.async_q
        transcript: TranscriptView = self.query_one(TranscriptView)
        status_bar: StatusBar = self.query_one(StatusBar)
        lw = self._log_writer  # may be None

        while True:
            try:
                msg = await queue.get()
            except asyncio.CancelledError:
                break

            try:
                if isinstance(msg, PhaseHeaderMsg):
                    status_bar.set_phase(msg.phase_name, msg.budget, msg.model, msg.extra)
                    transcript.append_phase_header(
                        msg.phase_name,
                        msg.budget,
                        msg.model,
                        msg.extra,
                    )
                    if lw:
                        lw.write_phase_header(msg.phase_name, msg.budget, msg.model, msg.extra)

                elif isinstance(msg, ToolLineMsg):
                    transcript.append_tool_line(
                        msg.tool_name,
                        msg.arg,
                        msg.style,
                        msg.badge_text,
                        msg.badge_style,
                    )
                    if lw:
                        display_name = (
                            f"{msg.badge_text} {msg.tool_name}".strip()
                            if msg.badge_text else msg.tool_name
                        )
                        lw.write_tool_line(display_name, msg.arg)

                elif isinstance(msg, TextBlockMsg):
                    transcript.append_text_block(
                        msg.text,
                        msg.badge_text,
                        msg.badge_style,
                    )
                    if lw:
                        lw.write_text_block(msg.text)

                elif isinstance(msg, CommandOutputMsg):
                    transcript.append_command_output(msg.text)
                    if lw:
                        lw.write_text_block(msg.text)

                elif isinstance(msg, NoticeMsg):
                    transcript.append_notice(msg.text)
                    if lw:
                        lw.write_notice(msg.text)

                elif isinstance(msg, PhaseCompleteMsg):
                    duration_s = msg.duration_ms / 1000.0
                    mins, secs = divmod(int(duration_s), 60)
                    duration_str = f"{mins}m {secs}s" if mins else f"{secs}s"
                    status_bar.set_complete(msg.cost, msg.turns, duration_s)
                    transcript.append_phase_complete(msg.cost, msg.turns, duration_str)
                    if lw:
                        lw.write_phase_complete(msg.cost, msg.turns, duration_str)

                elif isinstance(msg, PhaseErrorMsg):
                    status_bar.set_error(msg.error)
                    transcript.append_phase_error(msg.error)
                    if lw:
                        lw.write_phase_error(msg.error)

                elif isinstance(msg, TurnCompleteMsg):
                    status_bar.set_turn_count(msg.turn_number)

                elif isinstance(msg, UserInjectionMsg):
                    transcript.append_injected_message(msg.text)
                    if lw:
                        lw.write_user_message(msg.text)

                elif isinstance(msg, IterationHeaderMsg):
                    status_bar.set_iteration(msg.iteration, msg.total)
                    transcript.append_notice(
                        f"Iteration {msg.iteration}/{msg.total}  "
                        f"Persona: {msg.persona_name}  "
                        f"Cost so far: ${msg.aggregate_cost:.2f}"
                    )
                    if lw:
                        lw.write_iteration_header(msg.iteration, msg.total, msg.persona_name, msg.aggregate_cost)

                elif isinstance(msg, LoopCompleteMsg):
                    status_bar.clear_iteration()
                    transcript.append_notice(
                        f"Auto loop complete: {msg.iterations_completed} iterations, "
                        f"${msg.total_cost:.2f} total cost"
                    )
                    if lw:
                        lw.write_notice(f"Auto loop complete: {msg.iterations_completed} iterations, ${msg.total_cost:.2f} total cost")
            except Exception:
                logger.exception("Error dispatching TUI message %r; consumer loop continues", type(msg).__name__)

            queue.task_done()

    # -----------------------------------------------------------------
    # Composer submission handler
    # -----------------------------------------------------------------

    def on_composer_submitted(self, event: Composer.Submitted) -> None:
        """Handle user input from the composer."""
        text = event.text.strip()
        if not text:
            return

        if self._run_active and self._inject_callback is not None:
            self._inject_callback(text)
            return

        if self._run_active:
            self.query_one(TranscriptView).append_notice(
                "A run is already active; wait for it to finish before starting another.",
            )
            return

        self.query_one(TranscriptView).append_user_message(text)
        callback = self._recovery_callback if self._pending_recovery_prompt is not None else None
        self._start_run(text, callback=callback)

    # -----------------------------------------------------------------
    # Keybinding actions
    # -----------------------------------------------------------------

    def action_cancel_run(self) -> None:
        """Cancel the current orchestrator run (Ctrl+C).

        Two-tier cancellation: first press sets the stop event (graceful),
        second press within 2 seconds exits the TUI immediately.
        """
        now = time.monotonic()
        if now - self._last_cancel_at <= 2.0:
            # Second press within 2s — hard exit
            raise SystemExit(1)
        self._last_cancel_at = now

        # First press — graceful stop: signal the daemon or orchestrator first so
        # worker cancellation does not block on a still-running child process.
        self._stop_event.set()
        request_cancel("Cancelled by user from TUI")
        if self._cancel_callback is not None:
            self._cancel_callback()
        self.workers.cancel_all()
        status_bar = self.query_one(StatusBar)
        status_bar.set_error("Cancelled by user")
        transcript = self.query_one(TranscriptView)
        transcript.append_notice("Run cancelled by user (press Ctrl+C again within 2s to exit TUI)")
        self._run_active = False
        self._auto_loop_active = False

    def action_quit_app(self) -> None:
        """Exit the TUI and stop any active daemon/run first."""
        self._stop_event.set()
        request_cancel("Exiting ColonyOS TUI")
        if self._cancel_callback is not None:
            self._cancel_callback()
        self.workers.cancel_all()
        self.exit()

    def action_clear_transcript(self) -> None:
        """Clear all entries from the transcript."""
        self.query_one(TranscriptView).clear_transcript()

    def action_focus_composer(self) -> None:
        """Return focus to the composer text area."""
        if self._monitor_mode:
            return
        try:
            composer = self.query_one(Composer)
        except NoMatches:
            return
        ta = composer.query_one("TextArea")
        ta.focus()

    def action_scroll_to_end(self) -> None:
        """Re-enable auto-scroll and jump to the bottom of the transcript."""
        self.query_one(TranscriptView).re_enable_auto_scroll()

    def action_export_transcript(self) -> None:
        """Export the current transcript to a plain-text file."""
        transcript = self.query_one(TranscriptView)
        text = transcript.get_plain_text()
        if not text.strip():
            transcript.append_notice("Transcript is empty, nothing to export.")
            return
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        logs_dir = Path(".colonyos") / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        export_path = logs_dir / f"transcript_{timestamp}.txt"
        fd = os.open(str(export_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        transcript.append_notice(f"Transcript exported to {export_path}")

    def restore_composer_text(self, text: str) -> None:
        """Put submitted text back into the composer after a blocked run."""
        self.query_one(Composer).restore_text(text)

    def begin_dirty_worktree_recovery(self, text: str, error: PreflightError) -> None:
        """Enter a recovery mode for dirty-worktree preflight failures."""
        self._pending_recovery_prompt = text
        self._pending_recovery_error = error
        self.query_one(StatusBar).set_error("Dirty worktree")
        transcript = self.query_one(TranscriptView)
        transcript.append_notice(
            "Dirty worktree detected. Original prompt saved. Submit `commit` to let ColonyOS prepare a recovery commit and retry automatically, or `cancel` to restore the prompt."
        )
        transcript.append_command_output(str(error))

    def get_dirty_worktree_recovery(self) -> tuple[str, PreflightError] | None:
        """Return the saved prompt and error for a pending recovery flow."""
        if self._pending_recovery_prompt is None or self._pending_recovery_error is None:
            return None
        return self._pending_recovery_prompt, self._pending_recovery_error

    def cancel_dirty_worktree_recovery(self) -> None:
        """Exit recovery mode and put the saved prompt back into the composer."""
        if self._pending_recovery_prompt is None:
            return
        saved_prompt = self._pending_recovery_prompt
        self._pending_recovery_prompt = None
        self._pending_recovery_error = None
        self.query_one(TranscriptView).append_notice(
            "Recovery cancelled. Restored the saved prompt to the composer.",
        )
        self.restore_composer_text(saved_prompt)

    def clear_dirty_worktree_recovery(self) -> None:
        """Clear any saved recovery prompt once recovery has succeeded."""
        self._pending_recovery_prompt = None
        self._pending_recovery_error = None

    def show_run_blocked(self, text: str, error: str) -> None:
        """Render a recoverable run failure and restore the submitted prompt."""
        self._pending_recovery_error = None
        self._pending_recovery_prompt = None
        self.query_one(StatusBar).set_error("Run blocked")
        transcript = self.query_one(TranscriptView)
        transcript.append_notice("Run blocked before start; your prompt was restored in the composer.")
        transcript.append_command_output(error)
        self.restore_composer_text(text)

    def _start_run(
        self,
        text: str,
        *,
        callback: Callable[[str], None] | None = None,
    ) -> None:
        """Start a new worker-backed run if the callback is available."""
        active_callback = callback or self._run_callback
        if active_callback is None:
            return
        self._run_active = True
        self.run_worker(
            lambda: self._run_with_lifecycle(text, callback=active_callback),
            thread=True,
            exclusive=False,
        )

    def _run_with_lifecycle(
        self,
        text: str,
        *,
        callback: Callable[[str], None],
    ) -> None:
        """Run the callback and reset app state when it finishes."""
        try:
            try:
                callback(text)
            except PreflightError as exc:
                logger.info("TUI run blocked by preflight: %s", exc)
                self.call_from_thread(self.show_run_blocked, text, str(exc))
            except Exception as exc:
                logger.exception("Unhandled TUI run failure")
                self.call_from_thread(
                    self.show_run_blocked,
                    text,
                    f"{type(exc).__name__}: {exc}",
                )
        finally:
            self.call_from_thread(self._mark_run_finished)

    def _mark_run_finished(self) -> None:
        """Mark the app as no longer running once the worker finishes."""
        self._run_active = False
