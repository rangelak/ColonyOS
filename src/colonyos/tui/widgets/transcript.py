"""TranscriptView widget — scrollable event display for the TUI.

Wraps Textual's built-in ``RichLog`` widget with methods for appending
phase headers, tool calls, text blocks, and status messages.  Uses Rich
renderables for color-coded, structured output.
"""

from __future__ import annotations

import re
from io import StringIO

from rich import box
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from textual.widgets import RichLog

from colonyos.sanitize import sanitize_display_text
from colonyos.tui.styles import (
    COLOR_ACCENT,
    COLOR_COLONY,
    COLOR_DIM,
    COLOR_ERROR,
    COLOR_SUCCESS,
    COLOR_USER_MESSAGE,
    DEFAULT_TOOL_COLOR,
    TOOL_COLORS,
)


class TranscriptView(RichLog):
    """Scrollable transcript of agent activity.

    Extends ``RichLog`` directly — RichLog already handles virtual scrolling,
    so no extra container is needed.  Auto-scrolls to the bottom when the user
    is near the end; stops auto-scrolling when the user has scrolled up.
    """

    # Layout CSS is defined in APP_CSS (styles.py) — no DEFAULT_CSS needed.

    def __init__(self, **kwargs: object) -> None:
        # RichLog constructor args
        super().__init__(highlight=False, markup=True, wrap=True, **kwargs)
        self._auto_scroll = True
        self._programmatic_scroll: bool = False

    # -- scroll tracking -----------------------------------------------------

    def on_scroll_y(self) -> None:
        """Track whether the user has scrolled away from the bottom."""
        if self._programmatic_scroll:
            return
        max_scroll = self.virtual_size.height - self.size.height
        if max_scroll <= 0:
            self._auto_scroll = True
        else:
            self._auto_scroll = self.scroll_y >= max_scroll

    def _scroll_to_end(self) -> None:
        """Scroll to the bottom if auto-scroll is active."""
        if self._auto_scroll:
            self._programmatic_scroll = True
            self.scroll_end(animate=False)
            self._programmatic_scroll = False

    # -- public API ----------------------------------------------------------

    def append_phase_header(
        self,
        name: str,
        budget: float,
        model: str,
        extra: str = "",
    ) -> None:
        """Render a phase boundary with name, budget, and model."""
        rule = Text()
        rule.append("─" * 40, style=COLOR_DIM)
        self.write(rule)
        header = Text()
        header.append("  Phase: ", style=COLOR_COLONY)
        header.append(name, style="bold")
        header.append(f"  ·  ${budget:.2f} budget · {model}", style=COLOR_DIM)
        if extra:
            header.append(f" · {extra}", style=COLOR_DIM)
        self.write(header)
        self._scroll_to_end()

    def append_tool_line(
        self,
        name: str,
        arg: str,
        style: str | None = None,
    ) -> None:
        """Render a single tool-call line with a colored dot."""
        color = style or TOOL_COLORS.get(name, DEFAULT_TOOL_COLOR)
        line = Text()
        line.append("  ")
        line.append("● ", style=color)
        line.append(name, style=f"bold {color}")
        if arg:
            line.append(f" {arg}", style=COLOR_DIM)
        self.write(line)
        self._scroll_to_end()

    def append_text_block(self, text: str) -> None:
        """Render a block of agent text, using Markdown if appropriate."""
        text = text.strip()
        if not text:
            return
        if _looks_like_markdown(text):
            self.write(Markdown(text))
        else:
            for raw_line in text.splitlines():
                stripped = raw_line.strip()
                if stripped:
                    line = Text()
                    line.append(f"  {stripped}", style=COLOR_DIM)
                    self.write(line)
        self._scroll_to_end()

    def append_command_output(self, text: str) -> None:
        """Render captured CLI output as a preformatted block."""
        text = sanitize_display_text(text).rstrip("\n")
        if not text.strip():
            return
        self.write(Text())
        for raw_line in text.splitlines():
            self.write(Text(raw_line, style=COLOR_DIM, no_wrap=True, overflow="ignore"))
        self.write(Text())
        self._scroll_to_end()

    def append_phase_complete(
        self,
        cost: float,
        turns: int,
        duration: str,
    ) -> None:
        """Render a phase-completion summary."""
        line = Text()
        line.append("  ✓ ", style=COLOR_SUCCESS)
        line.append(f"Phase completed  ${cost:.2f} · {turns} turns · {duration}")
        self.write(Text())  # blank separator
        self.write(line)
        self.write(Text())  # blank separator
        self._scroll_to_end()

    def append_phase_error(self, error: str) -> None:
        """Render a phase-failure message."""
        line = Text()
        line.append("  ✗ ", style=COLOR_ERROR)
        line.append(f"Phase failed: {error}")
        self.write(Text())  # blank separator
        self.write(line)
        self.write(Text())  # blank separator
        self._scroll_to_end()

    def append_user_message(self, text: str) -> None:
        """Render a user-submitted message in the transcript."""
        text = sanitize_display_text(text)
        if not text:
            return
        line = Text()
        line.append("  You: ", style=COLOR_USER_MESSAGE)
        line.append(text)
        self.write(line)
        self._scroll_to_end()

    def append_injected_message(self, text: str) -> None:
        """Render a mid-run user message distinctly from a new run."""
        text = sanitize_display_text(text)
        if not text:
            return
        line = Text()
        line.append("  You (mid-run): ", style=f"bold {COLOR_ACCENT}")
        line.append(text, style=COLOR_USER_MESSAGE)
        self.write(line)
        self._scroll_to_end()

    def append_notice(self, text: str) -> None:
        """Render a neutral system notice for non-error feedback."""
        text = sanitize_display_text(text)
        if not text:
            return
        line = Text()
        line.append("  ! ", style=f"bold {COLOR_ACCENT}")
        line.append(text, style=COLOR_DIM)
        self.write(Text())
        self.write(line)
        self.write(Text())
        self._scroll_to_end()

    def append_welcome_banner(self) -> None:
        """Render the initial welcome card on first launch."""
        self.write(Text())
        logo_lines_raw = [
            " ██████╗  ██████╗  ██╗      ██████╗  ███╗   ██╗ ██╗   ██╗  ██████╗  ███████╗",
            "██╔════╝ ██╔═══██╗ ██║     ██╔═══██╗ ████╗  ██║ ╚██╗ ██╔╝ ██╔═══██╗ ██╔════╝",
            "██║      ██║   ██║ ██║     ██║   ██║ ██╔██╗ ██║  ╚████╔╝  ██║   ██║ ███████╗",
            "██║      ██║   ██║ ██║     ██║   ██║ ██║╚██╗██║   ╚██╔╝   ██║   ██║ ╚════██║",
            "╚██████╗ ╚██████╔╝ ███████╗╚██████╔╝ ██║ ╚████║    ██║    ╚██████╔╝ ███████║",
            " ╚═════╝  ╚═════╝  ╚══════╝ ╚═════╝  ╚═╝  ╚═══╝    ╚═╝     ╚═════╝  ╚══════╝",
        ]
        logo_lines: list[Text] = []
        split_at = 58
        for raw_line in logo_lines_raw:
            line = Text(justify="center")
            for index, char in enumerate(raw_line):
                if char == " ":
                    line.append(char)
                elif index < split_at:
                    line.append(char, style="bold #c8d1dc")
                else:
                    line.append(char, style="bold #f0a030")
            logo_lines.append(line)

        logo_group = Group(*logo_lines, Text(""))
        prompt = Text(
            "Enter a prompt below to dispatch work",
            style=COLOR_DIM,
            justify="center",
        )
        shortcuts = Text(
            "Shift+Enter / Ctrl+J newline   Ctrl+C cancel   Ctrl+L clear",
            style=COLOR_DIM,
            justify="center",
        )
        panel = Panel(
            Group(logo_group, prompt, shortcuts),
            border_style=COLOR_COLONY,
            box=box.ROUNDED,
            padding=(1, 2),
            title="Ready",
            subtitle="workers standing by",
            expand=True,
        )
        self.write(panel, expand=True)
        self.write(Text())
        self._scroll_to_end()

    def get_plain_text(self) -> str:
        """Return all transcript content as plain text (for transcript export).

        Uses Rich's Console to render each line without markup.
        """
        parts: list[str] = []
        for line_entry in self.lines:
            buf = StringIO()
            console = Console(file=buf, width=200, no_color=True, highlight=False)
            console.print(line_entry, end="")
            parts.append(buf.getvalue())
        return "\n".join(parts)

    def re_enable_auto_scroll(self) -> None:
        """Re-enable auto-scroll and jump to the bottom."""
        self._auto_scroll = True
        self._scroll_to_end()

    def clear_transcript(self) -> None:
        """Remove all entries from the transcript."""
        self.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MD_PATTERN = re.compile(
    r"(^#{1,4}\s)|(\*\*.*\*\*)|(\n\d+\.\s)|(\n[-*]\s)|(`[^`]+`)",
    re.MULTILINE,
)


def _looks_like_markdown(text: str) -> bool:
    """Return True if text contains markdown formatting worth rendering."""
    return bool(_MD_PATTERN.search(text))
