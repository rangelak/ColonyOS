"""AssistantApp — the main Textual application shell for ColonyOS TUI.

Assembles the four core widgets (StatusBar, TranscriptView, Composer,
HintBar) into a vertical layout and wires a janus queue consumer loop
that dispatches adapter messages to the appropriate widgets.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Sequence

import janus
from textual.app import App, ComposeResult
from textual.binding import Binding

from colonyos.tui.adapter import (
    CommandOutputMsg,
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
        Binding("ctrl+l", "clear_transcript", "Clear transcript", show=False),
        Binding("escape", "focus_composer", "Focus composer", show=False),
    ]

    def __init__(
        self,
        run_callback: Callable[[str], None] | None = None,
        inject_callback: Callable[[str], None] | None = None,
        cancel_callback: Callable[[], None] | None = None,
        initial_prompt: str | None = None,
        command_hints: Sequence[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._run_callback = run_callback
        self._inject_callback = inject_callback
        self._cancel_callback = cancel_callback
        self._initial_prompt = initial_prompt
        self._command_hints = list(command_hints or [])
        self._event_queue: janus.Queue[object] | None = None
        self._consumer_task: asyncio.Task[None] | None = None
        self._run_active = False
        self._last_cancel_at = 0.0

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
        yield Composer()
        yield HintBar()

    async def on_mount(self) -> None:
        """Create the event queue, start the consumer, and auto-submit initial prompt."""
        self._event_queue = janus.Queue()
        self._consumer_task = asyncio.create_task(self._consume_queue())
        self.query_one(HintBar).set_command_hints(self._command_hints)

        if self._initial_prompt and self._run_callback is not None:
            transcript = self.query_one(TranscriptView)
            transcript.append_user_message(self._initial_prompt)
            self._start_run(self._initial_prompt)
        else:
            self.query_one(TranscriptView).append_welcome_banner()

    async def on_unmount(self) -> None:
        """Clean up the consumer task and queue on exit."""
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        if self._event_queue is not None:
            self._event_queue.close()

    # -----------------------------------------------------------------
    # Queue consumer loop
    # -----------------------------------------------------------------

    async def _consume_queue(self) -> None:
        """Drain the async side of the janus queue and dispatch messages."""
        queue = self.event_queue.async_q
        transcript: TranscriptView = self.query_one(TranscriptView)
        status_bar: StatusBar = self.query_one(StatusBar)

        while True:
            try:
                msg = await queue.get()
            except asyncio.CancelledError:
                break

            if isinstance(msg, PhaseHeaderMsg):
                status_bar.set_phase(msg.phase_name, msg.budget, msg.model, msg.extra)
                transcript.append_phase_header(
                    msg.phase_name,
                    msg.budget,
                    msg.model,
                    msg.extra,
                )

            elif isinstance(msg, ToolLineMsg):
                transcript.append_tool_line(msg.tool_name, msg.arg, msg.style)

            elif isinstance(msg, TextBlockMsg):
                transcript.append_text_block(msg.text)

            elif isinstance(msg, CommandOutputMsg):
                transcript.append_command_output(msg.text)

            elif isinstance(msg, PhaseCompleteMsg):
                duration_s = msg.duration_ms / 1000.0
                mins, secs = divmod(int(duration_s), 60)
                duration_str = f"{mins}m {secs}s" if mins else f"{secs}s"
                status_bar.set_complete(msg.cost, msg.turns, duration_s)
                transcript.append_phase_complete(msg.cost, msg.turns, duration_str)

            elif isinstance(msg, PhaseErrorMsg):
                status_bar.set_error(msg.error)
                transcript.append_phase_error(msg.error)

            elif isinstance(msg, TurnCompleteMsg):
                status_bar.set_turn_count(msg.turn_number)

            elif isinstance(msg, UserInjectionMsg):
                transcript.append_injected_message(msg.text)

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
        self._start_run(text)

    # -----------------------------------------------------------------
    # Keybinding actions
    # -----------------------------------------------------------------

    def action_cancel_run(self) -> None:
        """Cancel the current orchestrator run (Ctrl+C)."""
        now = time.monotonic()
        if now - self._last_cancel_at <= 2.0:
            raise SystemExit(1)
        self._last_cancel_at = now

        self.workers.cancel_all()
        status_bar = self.query_one(StatusBar)
        status_bar.set_error("Cancelled by user")
        transcript = self.query_one(TranscriptView)
        transcript.append_notice("Run cancelled by user")
        self._run_active = False
        if self._cancel_callback is not None:
            self._cancel_callback()
        self.exit()

    def action_clear_transcript(self) -> None:
        """Clear all entries from the transcript."""
        self.query_one(TranscriptView).clear_transcript()

    def action_focus_composer(self) -> None:
        """Return focus to the composer text area."""
        composer = self.query_one(Composer)
        ta = composer.query_one("TextArea")
        ta.focus()

    def _start_run(self, text: str) -> None:
        """Start a new worker-backed run if the callback is available."""
        if self._run_callback is None:
            return
        self._run_active = True
        self.run_worker(
            lambda: self._run_with_lifecycle(text),
            thread=True,
            exclusive=True,
        )

    def _run_with_lifecycle(self, text: str) -> None:
        """Run the callback and reset app state when it finishes."""
        try:
            if self._run_callback is not None:
                self._run_callback(text)
        finally:
            self.call_from_thread(self._mark_run_finished)

    def _mark_run_finished(self) -> None:
        """Mark the app as no longer running once the worker finishes."""
        self._run_active = False
