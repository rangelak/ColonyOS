"""StatusBar widget — persistent phase/cost/turns/elapsed display.

Shows the current pipeline status in a single dense line at the top
of the TUI.  Displays phase name, cumulative cost, turn count, and
elapsed time with a cycling spinner during active phases.
"""

from __future__ import annotations

import time

from rich.text import Text
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Static

from colonyos.tui.styles import (
    COLOR_DIM,
    COLOR_ERROR,
    COLOR_SUCCESS,
    SPINNER_FRAMES,
)


class StatusBar(Static):
    """Single-line status bar showing phase, cost, turns, and elapsed time.

    Methods:
        set_phase(name, budget, model) — start tracking a new phase
        set_complete(cost, turns, duration) — mark current phase done
        set_error(msg) — display an error state
        increment_turn() — bump the turn counter for the active phase
    """

    DEFAULT_CSS = """
    StatusBar {
        dock: top;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    # Reactive attributes drive automatic re-render
    phase_name: reactive[str] = reactive("")
    phase_model: reactive[str] = reactive("")
    total_cost: reactive[float] = reactive(0.0)
    turn_count: reactive[int] = reactive(0)
    is_running: reactive[bool] = reactive(False)
    error_msg: reactive[str] = reactive("")

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        super().__init__(**kwargs)
        self._phase_start: float | None = None
        self._spinner_index: int = 0
        self._spinner_timer: Timer | None = None
        self._last_duration: float = 0.0
        self._last_rendered: str = ""

    def on_mount(self) -> None:
        """Render initial idle state on mount."""
        self._render_bar()

    def _advance_spinner(self) -> None:
        """Cycle through spinner frames (only called while timer is active)."""
        self._spinner_index = (self._spinner_index + 1) % len(SPINNER_FRAMES)
        self._render_bar()

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def _start_spinner(self) -> None:
        """Start the spinner timer (idempotent)."""
        if self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.1, self._advance_spinner)

    def _stop_spinner(self) -> None:
        """Stop the spinner timer (idempotent)."""
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def set_phase(self, name: str, budget: float | None = None, model: str = "") -> None:
        """Begin tracking a new phase."""
        self.phase_name = name
        self.phase_model = model
        self.turn_count = 0
        self.is_running = True
        self.error_msg = ""
        self._phase_start = time.monotonic()
        self._spinner_index = 0
        self._start_spinner()
        self._render_bar()

    def set_complete(self, cost: float, turns: int, duration: float) -> None:
        """Mark the current phase as complete."""
        self._stop_spinner()
        self.total_cost += cost
        self.turn_count = turns
        self.is_running = False
        self._last_duration = duration
        self._phase_start = None
        self._render_bar()

    def set_error(self, msg: str) -> None:
        """Display an error state on the status bar."""
        self._stop_spinner()
        self.is_running = False
        self.error_msg = msg
        self._phase_start = None
        self._render_bar()

    def increment_turn(self) -> None:
        """Bump the turn counter for the active phase."""
        self.turn_count += 1
        self._render_bar()

    # -----------------------------------------------------------------
    # Rendering
    # -----------------------------------------------------------------

    def _format_elapsed(self) -> str:
        """Return a human-friendly elapsed string."""
        if self._phase_start is not None:
            elapsed = time.monotonic() - self._phase_start
        elif self._last_duration:
            elapsed = self._last_duration
        else:
            return ""
        mins, secs = divmod(int(elapsed), 60)
        if mins:
            return f"{mins}m {secs}s"
        return f"{secs}s"

    def _render_bar(self) -> None:
        """Recompose the status bar content."""
        if self.error_msg:
            text = Text()
            text.append("✗ ", style=COLOR_ERROR)
            text.append(self.error_msg, style=COLOR_ERROR)
            self._last_rendered = text.plain
            self.update(text)
            return

        if not self.phase_name and not self.is_running:
            text = Text()
            text.append("idle", style=COLOR_DIM)
            if self.total_cost > 0:
                text.append(f"  ·  ${self.total_cost:.2f}", style=COLOR_DIM)
            self._last_rendered = text.plain
            self.update(text)
            return

        text = Text()

        # Spinner or check mark
        if self.is_running:
            spinner = SPINNER_FRAMES[self._spinner_index % len(SPINNER_FRAMES)]
            text.append(f"{spinner} ", style="bold bright_cyan")
        else:
            text.append("✓ ", style=COLOR_SUCCESS)

        # Phase name
        text.append(self.phase_name, style="bold")

        # Model
        if self.phase_model:
            text.append(f"  ·  {self.phase_model}", style=COLOR_DIM)

        # Cost
        text.append(f"  ·  ${self.total_cost:.2f}", style=COLOR_DIM)

        # Turns
        if self.turn_count > 0:
            turns_label = "turn" if self.turn_count == 1 else "turns"
            text.append(f"  ·  {self.turn_count} {turns_label}", style=COLOR_DIM)

        # Elapsed time
        elapsed = self._format_elapsed()
        if elapsed:
            text.append(f"  ·  {elapsed}", style=COLOR_DIM)

        self._last_rendered = text.plain
        self.update(text)

