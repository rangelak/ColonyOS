"""CSS-in-Python layout strings and color constants for the TUI."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Color constants — match TOOL_STYLE from ui.py
# ---------------------------------------------------------------------------

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

# Named palette constants used by widgets
COLOR_COLONY = "bright_cyan"
COLOR_TEXT = "bright_white"

# Semantic colors
COLOR_SUCCESS = "green"
COLOR_ERROR = "red"
COLOR_WARNING = "yellow"
COLOR_ACCENT = "bright_cyan"
COLOR_DIM = "dim"
COLOR_USER_MESSAGE = "bright_white"

# Spinner frames for active-phase indicator
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
IDLE_GLYPHS = ("⬡", "◈", "⋯", "⬢")
IDLE_PHRASES = (
    "colony awaiting orders",
    "workers standing by",
    "tunnels quiet",
    "antennae listening",
)

# ---------------------------------------------------------------------------
# Textual CSS for the app layout
# ---------------------------------------------------------------------------

APP_CSS = """
Screen {
    layout: vertical;
    overflow-x: hidden;
    overflow-y: hidden;
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
