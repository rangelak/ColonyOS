"""CSS-in-Python layout strings and color constants for the TUI."""

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

# Semantic colors
COLOR_SUCCESS = "green"
COLOR_ERROR = "red"
COLOR_WARNING = "yellow"
COLOR_ACCENT = "bright_cyan"
COLOR_DIM = "dim"
COLOR_USER_MESSAGE = "bright_white"

# Spinner frames for active-phase indicator
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Main app CSS — transcript ~85%, composer at bottom, status bar between.
APP_CSS = """
Screen {
    layout: vertical;
}

StatusBar {
    dock: top;
    height: 1;
    background: $surface;
    color: $text-muted;
    padding: 0 1;
}

TranscriptView {
    height: 1fr;
    min-height: 10;
}

TranscriptView RichLog {
    padding: 0 2;
    scrollbar-size: 1 1;
}

Composer {
    height: auto;
    min-height: 3;
    max-height: 8;
    border-top: solid $accent;
    padding: 0 1;
}

Composer:focus-within {
    border-top: solid $accent;
}

Composer TextArea {
    height: auto;
    min-height: 3;
    max-height: 8;
}

HintBar {
    dock: bottom;
    height: 1;
    background: $surface;
    color: $text-muted;
    padding: 0 1;
}
"""
