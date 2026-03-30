"""Structural tests for the cli/ package foundation.

Validates that the package is importable, key symbols are re-exported,
and no single module exceeds the 800-line limit (FR-1 / G1).
"""

from __future__ import annotations

from pathlib import Path

import click
import pytest


def test_app_is_importable_from_colonyos_cli():
    """colonyos.cli:app must remain the public entry point."""
    from colonyos.cli import app

    assert isinstance(app, click.Group)


def test_find_repo_root_importable():
    """_find_repo_root must be importable from the top-level cli package."""
    from colonyos.cli import _find_repo_root

    assert callable(_find_repo_root)


def test_find_repo_root_returns_path():
    from colonyos.cli._helpers import _find_repo_root

    result = _find_repo_root()
    assert isinstance(result, Path)


def test_helpers_importable_from_package():
    """Key helpers must be re-exported from colonyos.cli."""
    from colonyos.cli import (
        _find_repo_root,
        _tui_available,
        _interactive_stdio,
        _load_dotenv,
        _current_branch_name,
        _announce_mode_cli,
        _dirty_recovery_help,
    )

    assert callable(_find_repo_root)
    assert callable(_tui_available)
    assert callable(_interactive_stdio)
    assert callable(_load_dotenv)
    assert callable(_current_branch_name)
    assert callable(_announce_mode_cli)
    assert callable(_dirty_recovery_help)


def test_app_defined_in_app_module():
    """The Click group must be defined in _app.py (FR-3, FR-6)."""
    from colonyos.cli._app import app

    assert isinstance(app, click.Group)


def test_no_cli_module_exceeds_800_lines():
    """No file in cli/ should exceed 800 lines (G1).

    ``_legacy.py`` is excluded — it is a temporary migration artifact
    containing the original monolith and will be deleted in task 6.
    """
    cli_dir = Path(__file__).resolve().parent.parent / "src" / "colonyos" / "cli"
    assert cli_dir.is_dir(), f"cli/ package not found at {cli_dir}"

    # _legacy.py is the original cli.py being incrementally decomposed
    skip = {"_legacy.py"}

    violations: list[str] = []
    for py_file in sorted(cli_dir.glob("*.py")):
        if py_file.name in skip:
            continue
        line_count = len(py_file.read_text().splitlines())
        if line_count > 800:
            violations.append(f"{py_file.name}: {line_count} lines")

    assert not violations, (
        f"Files exceeding 800 lines:\n" + "\n".join(violations)
    )
