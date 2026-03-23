"""Keybinding hints bar displayed below the composer."""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text
from textual.widgets import Static

from colonyos.tui.styles import COLOR_ACCENT, COLOR_DIM


class HintBar(Static):
    """Single-line bar showing keyboard shortcut hints.

    Renders dim text so it stays out of the way while remaining
    discoverable for new users.
    """

    DEFAULT_CSS = """
    HintBar {
        height: 2;
        dock: bottom;
        background: #12161d;
        color: #7c8896;
        padding: 0 2;
    }
    """

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        super().__init__(**kwargs)
        self._command_hints: list[str] = []

    def on_mount(self) -> None:
        """Render the hint text."""
        self._render_hints()

    def set_command_hints(self, hints: Sequence[str]) -> None:
        """Set the command examples shown in the footer."""
        self._command_hints = list(hints)
        self._render_hints()

    def _render_hints(self) -> None:
        """Render command examples and keybinding hints."""
        text = Text()
        if self._command_hints:
            text.append("Commands", style=f"bold {COLOR_ACCENT}")
            text.append(": ", style=COLOR_DIM)
            text.append("  ·  ".join(self._command_hints), style=COLOR_DIM)
        else:
            text.append("Type a command or prompt", style=COLOR_DIM)
        text.append("\n")
        text.append("Enter", style=f"bold {COLOR_ACCENT}")
        text.append(" send", style=COLOR_DIM)
        text.append("  ·  ", style=COLOR_DIM)
        text.append("Shift+Enter", style=f"bold {COLOR_ACCENT}")
        text.append(" newline", style=COLOR_DIM)
        text.append("  ·  ", style=COLOR_DIM)
        text.append("Ctrl+J", style=f"bold {COLOR_ACCENT}")
        text.append(" newline", style=COLOR_DIM)
        text.append("  ·  ", style=COLOR_DIM)
        text.append("Ctrl+C", style=f"bold {COLOR_ACCENT}")
        text.append(" cancel", style=COLOR_DIM)
        text.append("  ·  ", style=COLOR_DIM)
        text.append("Ctrl+L", style=f"bold {COLOR_ACCENT}")
        text.append(" clear", style=COLOR_DIM)
        self.update(text)
