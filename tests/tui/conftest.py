"""Shared fixtures for TUI tests."""

from __future__ import annotations

import pytest


@pytest.fixture()
def anyio_backend():
    return "asyncio"


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


@pytest.fixture()
def sync_queue():
    """Create a janus queue and return its sync side for adapter tests."""
    import janus
    import asyncio

    loop = asyncio.new_event_loop()
    q = janus.Queue(loop=loop) if hasattr(janus.Queue, "__init__") else None

    # janus >= 1.0 doesn't take a loop param; create in running loop
    import threading

    result = {}

    def _create():
        asyncio.set_event_loop(asyncio.new_event_loop())
        _loop = asyncio.get_event_loop()
        _q = janus.Queue()
        result["queue"] = _q
        result["loop"] = _loop
        _loop.run_forever()

    t = threading.Thread(target=_create, daemon=True)
    t.start()

    # Give the thread a moment to start
    import time
    time.sleep(0.05)

    yield result.get("queue")

    if result.get("loop"):
        result["loop"].call_soon_threadsafe(result["loop"].stop)
