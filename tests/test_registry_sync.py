"""Tests that CLI commands stay in sync with the welcome banner and README.

When this test fails, it means a new command was registered in the Click CLI
group but is missing from either the welcome banner or the README CLI
Reference table. To fix:

1. The banner is now auto-generated from ``app.commands``, so it stays in
   sync automatically. If you see a banner failure, check that the new
   command has a Click ``help`` docstring.
2. Add the missing command to the **CLI Reference** table in ``README.md``.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from colonyos.cli import app


# Commands that are internal / hidden and not expected in docs.
_HIDDEN_COMMANDS: frozenset[str] = frozenset()

README_PATH = Path(__file__).resolve().parent.parent / "README.md"


class TestBannerSync:
    """Every registered CLI command appears in the welcome banner output."""

    def test_all_commands_in_banner(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with patch("colonyos.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, [])
        banner = result.output

        for name in app.commands:
            if name in _HIDDEN_COMMANDS:
                continue
            assert name in banner, (
                f"Command '{name}' is registered in the CLI but missing from "
                f"the welcome banner. Ensure the command has a help docstring."
            )


class TestReadmeSync:
    """Every registered CLI command appears in the README CLI Reference table."""

    def test_all_commands_in_readme(self) -> None:
        readme_text = README_PATH.read_text(encoding="utf-8")

        # Extract the CLI Reference section
        match = re.search(
            r"## CLI Reference\s*\n\s*\n?\|.*?\n\|[-| ]+\n((?:\|.*\n)+)",
            readme_text,
        )
        assert match, "Could not find CLI Reference table in README.md"
        table_body = match.group(1)

        for name in app.commands:
            if name in _HIDDEN_COMMANDS:
                continue
            # Look for `colonyos <name>` in the table
            pattern = rf"`colonyos {re.escape(name)}"
            assert re.search(pattern, table_body), (
                f"Command '{name}' is registered in the CLI but missing from "
                f"the README CLI Reference table. Add a row for "
                f"`colonyos {name}` to the table in README.md."
            )
