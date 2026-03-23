"""Keybinding hints bar displayed below the composer."""

from __future__ import annotations

from textual.widgets import Static


class HintBar(Static):
    """Single-line bar showing keyboard shortcut hints.

    Renders dim text so it stays out of the way while remaining
    discoverable for new users.
    """

    DEFAULT_CSS = """
    HintBar {
        height: 1;
        dock: bottom;
        background: $surface;
        color: $text-muted;
        padding: 0 2;
    }
    """

    HINT_TEXT = (
        "Enter send · Shift+Enter newline · Ctrl+C stop run · Ctrl+L clear"
    )

    def on_mount(self) -> None:
        """Render the hint text."""
        self.update(self.HINT_TEXT)
