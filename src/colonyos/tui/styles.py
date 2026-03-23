"""CSS-in-Python layout strings and color constants for the TUI."""

from __future__ import annotations

# Core palette
COLOR_BG = "#0b0d12"
COLOR_PANEL_BG = "#12161d"
COLOR_TEXT = "#c8d1dc"
COLOR_DIM = "#7c8896"
COLOR_ACCENT = "#f0a030"
COLOR_COLONY = "#f0a030"
COLOR_CYAN = "#55eeff"

# Matches the TOOL_STYLE map from colonyos.ui
TOOL_COLORS: dict[str, str] = {
    "Read": COLOR_CYAN,
    "Write": COLOR_ACCENT,
    "Edit": COLOR_ACCENT,
    "Bash": COLOR_ACCENT,
    "Grep": COLOR_TEXT,
    "Glob": COLOR_TEXT,
    "Agent": COLOR_ACCENT,
    "Dispatch": COLOR_ACCENT,
    "Task": COLOR_ACCENT,
}

DEFAULT_TOOL_COLOR = COLOR_DIM

# Semantic colors
COLOR_SUCCESS = "green"
COLOR_ERROR = "red"
COLOR_WARNING = COLOR_ACCENT
COLOR_USER_MESSAGE = COLOR_TEXT

# Spinner frames for active-phase indicator
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
IDLE_GLYPHS = ("⬡", "◈", "⋯", "⬢")
IDLE_PHRASES = (
    "colony awaiting orders",
    "workers standing by",
    "tunnels quiet",
    "antennae listening",
)

# Main app CSS — transcript ~85%, composer at bottom, status bar between.
APP_CSS = """
Screen {
    layout: vertical;
    background: #0b0d12;
    color: #c8d1dc;
}

StatusBar {
    dock: top;
    height: 1;
    background: #12161d;
    color: #7c8896;
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
    min-height: 6;
    max-height: 9;
    background: #0b0d12;
    border-top: solid #f0a030;
    padding: 0 1;
}

Composer:focus-within {
    border-top: solid #f0a030;
}

Composer TextArea, Composer _ComposerTextArea {
    height: auto;
    min-height: 5;
    max-height: 8;
    background: #12161d;
    color: #c8d1dc;
}

Composer:focus-within _ComposerTextArea {
    border: tall #f0a030;
}

HintBar {
    dock: bottom;
    height: 1;
    background: #12161d;
    color: #7c8896;
    padding: 0 1;
}
"""
