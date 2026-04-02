"""Interactive Terminal UI for ColonyOS (Textual TUI).

This package requires the ``tui`` extra::

    pip install colonyos[tui]

If Textual is not installed, importing this package raises a clear error.
"""

from __future__ import annotations


def _check_dependencies() -> None:
    """Verify that required TUI dependencies are installed."""
    missing: list[str] = []
    try:
        import textual as _textual
    except ImportError:
        missing.append("textual")
    else:
        _ = _textual.__name__
    try:
        import janus as _janus
    except ImportError:
        missing.append("janus")
    else:
        _ = _janus.__name__

    if missing:
        pkgs = ", ".join(missing)
        raise ImportError(
            f"Missing TUI dependencies: {pkgs}. "
            "Install the tui extra: pip install colonyos[tui]"
        )


_check_dependencies()
