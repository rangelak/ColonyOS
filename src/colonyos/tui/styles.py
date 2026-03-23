"""CSS-in-Python layout and color constants for the TUI."""

from __future__ import annotations

# Matches the TOOL_STYLE map from colonyos.ui
TOOL_COLORS: dict[str, str] = {
    "Read": "cyan",
    "Write": "green",
    "Edit": "green",
    "Bash": "yellow",
    "Grep": "magenta",
    "Glob": "magenta",
    "Agent": "blue",
    "Dispatch": "blue",
    "Task": "blue",
}

DEFAULT_TOOL_COLOR = "dim"

# Main app CSS — transcript ~85%, composer at bottom, status bar between.
APP_CSS = """
Screen {
    layout: vertical;
}

StatusBar {
    height: 1;
    dock: top;
    background: $surface;
    color: $text;
}

TranscriptView {
    height: 1fr;
    min-height: 10;
}

Composer {
    height: auto;
    min-height: 3;
    max-height: 8;
}

HintBar {
    height: 1;
    dock: bottom;
    background: $surface;
    color: $text-muted;
}
"""
