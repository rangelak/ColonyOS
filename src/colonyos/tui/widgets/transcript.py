"""TranscriptView widget — scrollable event display for the TUI.

Wraps Textual's built-in ``RichLog`` widget with methods for appending
phase headers, tool calls, text blocks, and status messages.  Uses Rich
renderables for color-coded, structured output.
"""

from __future__ import annotations

from rich.markdown import Markdown
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import RichLog

from colonyos.sanitize import sanitize_display_text
from colonyos.tui.styles import (
    COLOR_DIM,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_USER_MESSAGE,
    DEFAULT_TOOL_COLOR,
    TOOL_COLORS,
)


class TranscriptView(VerticalScroll):
    """Scrollable transcript of agent activity.

    Internally manages a ``RichLog`` for efficient append-only rendering.
    Auto-scrolls to the bottom when the user is near the end; stops
    auto-scrolling when the user has scrolled up.
    """

    DEFAULT_CSS = """
    TranscriptView {
        height: 1fr;
        min-height: 10;
    }
    """

    # Number of lines from the bottom within which auto-scroll stays active.
    _AUTO_SCROLL_THRESHOLD = 3

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._rich_log: RichLog | None = None
        self._auto_scroll = True

    def compose(self):  # noqa: ANN201 — Textual convention
        """Mount the inner RichLog widget."""
        yield RichLog(highlight=False, markup=True, wrap=True, id="transcript-log")

    def on_mount(self) -> None:
        """Cache a reference to the inner RichLog on mount."""
        self._rich_log = self.query_one("#transcript-log", RichLog)

    # -- scroll tracking -----------------------------------------------------

    def on_scroll_y(self) -> None:
        """Track whether the user has scrolled away from the bottom."""
        if self._rich_log is None:
            return
        log = self._rich_log
        max_scroll = log.virtual_size.height - log.size.height
        if max_scroll <= 0:
            self._auto_scroll = True
        else:
            self._auto_scroll = (
                log.scroll_y >= max_scroll - self._AUTO_SCROLL_THRESHOLD
            )

    def _scroll_to_end(self) -> None:
        """Scroll the inner RichLog to the bottom if auto-scroll is active."""
        if self._auto_scroll and self._rich_log is not None:
            self._rich_log.scroll_end(animate=False)

    # -- public API ----------------------------------------------------------

    def append_phase_header(
        self,
        name: str,
        budget: float,
        model: str,
    ) -> None:
        """Render a phase boundary with name, budget, and model."""
        if self._rich_log is None:
            return
        safe_name = sanitize_display_text(name)
        safe_model = sanitize_display_text(model)
        rule = Text()
        rule.append("─" * 40, style="dim")
        self._rich_log.write(rule)
        header = Text()
        header.append(f"  Phase: {safe_name}", style="bold")
        header.append(f"  ${budget:.2f} budget · {safe_model}", style="dim")
        self._rich_log.write(header)
        self._scroll_to_end()

    def append_tool_line(
        self,
        name: str,
        arg: str,
        style: str | None = None,
    ) -> None:
        """Render a single tool-call line with a colored dot."""
        if self._rich_log is None:
            return
        safe_name = sanitize_display_text(name)
        safe_arg = sanitize_display_text(arg) if arg else ""
        color = style or TOOL_COLORS.get(name, DEFAULT_TOOL_COLOR)
        line = Text()
        line.append("  ")
        line.append("● ", style=color)
        label = f"{safe_name} {safe_arg}".rstrip() if safe_arg else safe_name
        line.append(label)
        self._rich_log.write(line)
        self._scroll_to_end()

    def append_text_block(self, text: str) -> None:
        """Render a block of agent text, using Markdown if appropriate."""
        if self._rich_log is None:
            return
        safe = sanitize_display_text(text).strip()
        if not safe:
            return
        if _looks_like_markdown(safe):
            self._rich_log.write(Markdown(safe))
        else:
            for raw_line in safe.splitlines():
                stripped = raw_line.strip()
                if stripped:
                    line = Text()
                    line.append(f"  {stripped}", style=COLOR_DIM)
                    self._rich_log.write(line)
        self._scroll_to_end()

    def append_phase_complete(
        self,
        cost: float,
        turns: int,
        duration: str,
    ) -> None:
        """Render a phase-completion summary."""
        if self._rich_log is None:
            return
        safe_duration = sanitize_display_text(duration)
        line = Text()
        line.append("  ✓ ", style=COLOR_SUCCESS)
        line.append(f"Phase completed  ${cost:.2f} · {turns} turns · {safe_duration}")
        self._rich_log.write(Text())  # blank separator
        self._rich_log.write(line)
        self._rich_log.write(Text())  # blank separator
        self._scroll_to_end()

    def append_phase_error(self, error: str) -> None:
        """Render a phase-failure message."""
        if self._rich_log is None:
            return
        safe = sanitize_display_text(error)
        line = Text()
        line.append("  ✗ ", style=COLOR_ERROR)
        line.append(f"Phase failed: {safe}")
        self._rich_log.write(Text())  # blank separator
        self._rich_log.write(line)
        self._rich_log.write(Text())  # blank separator
        self._scroll_to_end()

    def append_user_message(self, text: str) -> None:
        """Render a user-submitted message in the transcript."""
        if self._rich_log is None:
            return
        safe = sanitize_display_text(text).strip()
        if not safe:
            return
        line = Text()
        line.append("  You: ", style=COLOR_USER_MESSAGE)
        line.append(safe)
        self._rich_log.write(line)
        self._scroll_to_end()

    def clear_transcript(self) -> None:
        """Remove all entries from the transcript."""
        if self._rich_log is not None:
            self._rich_log.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import re  # noqa: E402 — keep at end for readability

_MD_PATTERN = re.compile(
    r"(^#{1,4}\s)|(\*\*.*\*\*)|(\n\d+\.\s)|(\n[-*]\s)|(`[^`]+`)",
    re.MULTILINE,
)


def _looks_like_markdown(text: str) -> bool:
    """Return True if text contains markdown formatting worth rendering."""
    return bool(_MD_PATTERN.search(text))
