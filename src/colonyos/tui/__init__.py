"""Interactive Terminal UI built on Textual.

This package is optional — install with ``pip install colonyos[tui]``.
"""

from __future__ import annotations


def _check_dependency() -> None:
    """Raise a clear error if Textual is not installed."""
    try:
        import textual  # noqa: F401
    except ImportError:
        raise ImportError(
            "colonyos[tui] extra required — run: pip install colonyos[tui]"
        ) from None


_check_dependency()
