"""Shared CLI utilities used across multiple command modules.

Contains: _find_repo_root, _tui_available, _interactive_stdio, _load_dotenv,
_current_branch_name, _announce_mode_cli, _dirty_recovery_help.

This module imports only from ``colonyos.config`` / ``colonyos.models`` and
the stdlib — never from other ``cli/`` sub-modules — to stay at the bottom
of the import DAG and prevent circular dependencies.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click

# ---------------------------------------------------------------------------
# Dotenv prefix filter
# Only keys starting with this prefix are loaded from .env files.
# ---------------------------------------------------------------------------
_DOTENV_ALLOWLIST_PREFIX = "COLONYOS_"


def _find_repo_root() -> Path:
    """Walk up from cwd to find a .git directory, or use cwd."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            return parent
    return cwd


def _tui_available() -> bool:
    """Return True when the optional TUI dependencies are importable."""
    try:
        import colonyos.tui  # noqa: F401
        import janus  # noqa: F401
        import textual  # noqa: F401
        return True
    except ImportError:
        return False


def _interactive_stdio() -> bool:
    """Return True when both stdin and stdout are interactive terminals."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _load_dotenv() -> None:
    """Load COLONYOS_* vars from .env; ignore everything else.

    Other keys (e.g. ANTHROPIC_API_KEY) are left alone so they don't
    override the Claude CLI's own auth.
    """
    try:
        from dotenv import dotenv_values
    except ImportError:
        return
    repo_root = _find_repo_root()
    env_path = repo_root / ".env"
    if not env_path.is_file():
        return
    for key, value in dotenv_values(env_path).items():
        if key.startswith(_DOTENV_ALLOWLIST_PREFIX) and value is not None:
            os.environ.setdefault(key, value)


def _current_branch_name(repo_root: Path) -> str:
    """Return the current git branch, or ``main`` on lookup failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return "main"
    branch = result.stdout.strip()
    return branch or "main"


def _announce_mode_cli(message: str | None, *, quiet: bool = False) -> None:
    """Print a short mode announcement for non-TUI flows."""
    if message and not quiet:
        click.echo(click.style(message, dim=True))


def _dirty_recovery_help() -> str:
    """Return the in-TUI help text for dirty-worktree recovery mode."""
    return (
        "Dirty-worktree recovery is pending.\n"
        "Submit `commit` to let ColonyOS prepare a recovery commit and retry the saved prompt,\n"
        "or submit `cancel` to restore the saved prompt to the composer."
    )
