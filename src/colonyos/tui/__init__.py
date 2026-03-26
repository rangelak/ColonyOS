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
        import textual  # noqa: F401
    except ImportError:
        missing.append("textual")
    try:
        import janus  # noqa: F401
    except ImportError:
        missing.append("janus")

    if missing:
        pkgs = ", ".join(missing)
        raise ImportError(
            f"Missing TUI dependencies: {pkgs}. "
            "Install the tui extra: pip install colonyos[tui]"
        )


_check_dependencies()
