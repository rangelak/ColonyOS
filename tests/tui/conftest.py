"""Shared fixtures for TUI tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def tui_available() -> bool:
    """Return True if the tui extras are installed."""
    try:
        import textual  # noqa: F401
        import janus  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.fixture
def require_tui(tui_available: bool) -> None:
    """Skip the test if tui extras are not installed."""
    if not tui_available:
        pytest.skip("TUI extras not installed (pip install colonyos[tui])")
