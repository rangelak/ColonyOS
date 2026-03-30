"""Click group definition, root command, version option, and welcome banner.

This module is imported first by ``__init__.py`` — it must have zero imports
from other ``cli/`` sub-modules to prevent circular dependencies.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from colonyos import __version__
from colonyos.config import load_config


def _show_welcome() -> None:
    """Render the ColonyOS welcome banner (shown when no subcommand is given).

    The command list is generated dynamically from the Click ``app.commands``
    registry so that the banner never drifts from actually registered commands.
    """
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    from colonyos.cli._helpers import _find_repo_root

    console = Console()

    repo_root = _find_repo_root()
    config_path = repo_root / ".colonyos" / "config.yaml"
    initialized = config_path.exists()

    model = "unknown"
    if initialized:
        try:
            config = load_config(repo_root)
            model = config.model or "unknown"
        except Exception:
            pass

    home = Path.home()
    try:
        display_path = "~/" + str(repo_root.relative_to(home))
    except ValueError:
        display_path = str(repo_root)

    # Left column: ant icon, branding, context
    left = Text(justify="center")
    left.append("\n")
    left.append("    \u2591\u2592\u2593\u2588\u2588\u2593\u2592\u2591\n", style="yellow")
    left.append("   \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\n", style="yellow")
    left.append("  \u2588\u2588\u25cf\u2588\u2588\u2588\u25cf\u2588\u2588\n", style="yellow")
    left.append("   \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\n", style="yellow")
    left.append("    \u2588\u2588\u2588\u2588\u2588\u2588\n", style="yellow")
    left.append("   \u2588\u2588 \u2588\u2588 \u2588\u2588\n", style="yellow")
    left.append("  \u2588\u2588  \u2588\u2588  \u2588\u2588\n", style="yellow")
    left.append("\n")
    left.append(f"  {model} \u00b7 v{__version__}\n", style="dim")
    left.append(f"  {display_path}\n", style="dim")

    # Right column: commands generated from Click registry + flags
    right = Text()
    right.append("Commands\n", style="bold")

    # Dynamically iterate over registered commands
    max_name_len = max((len(name) for name in app.commands), default=0)
    for name in sorted(app.commands):
        cmd = app.commands[name]
        summary = (cmd.get_short_help_str(limit=60) or "").strip()
        padding = " " * (max_name_len - len(name) + 2)
        right.append(f"  {name}", style="green")
        right.append(f"{padding}{summary}\n")
    right.append("\u2500" * 34 + "\n", style="bright_black")
    right.append("Flags\n", style="bold")
    right.append("  -v, --verbose", style="green")
    right.append("   Stream text\n")
    right.append("  -q, --quiet", style="green")
    right.append("     Minimal output\n")
    right.append("  --version", style="green")
    right.append("       Show version\n")

    if not initialized:
        right.append("\u2500" * 34 + "\n", style="bright_black")
        right.append("  Run ")
        right.append("colonyos init", style="green bold")
        right.append(" to get started\n")

    grid = Table.grid(padding=(0, 2))
    grid.add_column(width=34, justify="center")
    grid.add_column(justify="left", no_wrap=True)
    grid.add_row(left, right)

    console.print()
    console.print(
        Panel(
            grid,
            title=f"[bold]ColonyOS[/bold] [dim]v{__version__}[/dim]",
            title_align="left",
            border_style="bright_black",
            padding=(1, 2),
            expand=True,
        )
    )
    console.print()


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="colonyos")
@click.pass_context
def app(ctx: click.Context) -> None:
    """ColonyOS — autonomous agent loop that turns prompts into shipped PRs."""
    from colonyos.cli._helpers import (
        _find_repo_root,
        _interactive_stdio,
        _load_dotenv,
        _tui_available,
    )

    _load_dotenv()
    if ctx.invoked_subcommand is None:
        repo_root = _find_repo_root()
        config = load_config(repo_root)
        if (
            _interactive_stdio()
            and _tui_available()
            and config.project is not None
        ):
            # Lazy import to avoid pulling in the full TUI launcher at startup
            from colonyos.cli._tui_launcher import _launch_tui

            _launch_tui(repo_root, config)
            return
        _show_welcome()
        if sys.stdin.isatty():
            # Lazy import to avoid pulling in REPL machinery at startup
            from colonyos.cli._repl import _run_repl

            _run_repl()
