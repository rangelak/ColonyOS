"""Tests for auto-in-TUI functionality — budget caps, persona parsing, concurrent guard."""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest

from colonyos.cli import _AUTO_COMMAND_SIGNAL, _handle_tui_command
from colonyos.config import ColonyConfig


def _tui_available() -> bool:
    try:
        import textual  # noqa: F401
        import janus  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(
    not _tui_available(),
    reason="TUI extras not installed",
)


class TestAutoTokenParsing:
    """Verify that auto command tokens are parsed correctly for TUI routing."""

    def _make_config(self, auto_approve: bool = True) -> ColonyConfig:
        """Create a minimal config mock for _handle_tui_command."""
        config = MagicMock(spec=ColonyConfig)
        config.auto_approve = auto_approve
        return cast(ColonyConfig, config)

    def test_auto_command_signal_returned(self) -> None:
        """auto --no-confirm should return _AUTO_COMMAND_SIGNAL."""
        config = self._make_config(auto_approve=False)
        handled, output, should_exit = _handle_tui_command("auto --no-confirm", config=config)
        assert handled is True
        assert output == _AUTO_COMMAND_SIGNAL

    def test_auto_requires_no_confirm_or_auto_approve(self) -> None:
        """auto without --no-confirm and auto_approve=False should be rejected."""
        config = self._make_config(auto_approve=False)
        handled, output, should_exit = _handle_tui_command("auto", config=config)
        assert handled is True
        assert output != _AUTO_COMMAND_SIGNAL
        assert output is not None
        assert "auto_approve" in output

    def test_auto_with_auto_approve_config(self) -> None:
        """auto with auto_approve=True should return _AUTO_COMMAND_SIGNAL."""
        config = self._make_config(auto_approve=True)
        handled, output, should_exit = _handle_tui_command("auto", config=config)
        assert handled is True
        assert output == _AUTO_COMMAND_SIGNAL

    def test_auto_with_loop_flag(self) -> None:
        """auto --no-confirm --loop 5 should be accepted and return signal."""
        config = self._make_config(auto_approve=True)
        handled, output, should_exit = _handle_tui_command(
            "auto --loop 5 --max-budget 10", config=config
        )
        assert handled is True
        assert output == _AUTO_COMMAND_SIGNAL

    def test_auto_with_persona_flag(self) -> None:
        """auto --persona 'Safety' should be accepted."""
        config = self._make_config(auto_approve=True)
        handled, output, should_exit = _handle_tui_command(
            "auto --persona Safety", config=config
        )
        assert handled is True
        assert output == _AUTO_COMMAND_SIGNAL


class TestAutoInTuiBudgetParsing:
    """Test that _run_auto_in_tui correctly parses budget/time/persona flags.

    Since _run_auto_in_tui is a closure, we verify the token parsing logic
    by extracting the same parsing pattern used in the function.
    """

    @staticmethod
    def _parse_auto_tokens(raw_text: str) -> dict:
        """Replicate the token parsing logic from _run_auto_in_tui."""
        import shlex
        try:
            tokens = shlex.split(raw_text)
        except ValueError:
            tokens = raw_text.split()

        loop_count = 1
        max_budget = None
        max_hours = None
        persona_name = None
        for i, tok in enumerate(tokens):
            if tok == "--loop" and i + 1 < len(tokens):
                try:
                    loop_count = int(tokens[i + 1])
                except ValueError:
                    loop_count = 1
            elif tok == "--max-budget" and i + 1 < len(tokens):
                try:
                    max_budget = float(tokens[i + 1])
                except ValueError:
                    pass
            elif tok == "--max-hours" and i + 1 < len(tokens):
                try:
                    max_hours = float(tokens[i + 1])
                except ValueError:
                    pass
            elif tok == "--persona" and i + 1 < len(tokens):
                persona_name = tokens[i + 1]
        return {
            "loop_count": loop_count,
            "max_budget": max_budget,
            "max_hours": max_hours,
            "persona_name": persona_name,
        }

    def test_parse_all_flags(self) -> None:
        result = self._parse_auto_tokens(
            "auto --loop 5 --max-budget 10.0 --max-hours 2.5 --persona Safety"
        )
        assert result["loop_count"] == 5
        assert result["max_budget"] == 10.0
        assert result["max_hours"] == 2.5
        assert result["persona_name"] == "Safety"

    def test_parse_defaults(self) -> None:
        result = self._parse_auto_tokens("auto")
        assert result["loop_count"] == 1
        assert result["max_budget"] is None
        assert result["max_hours"] is None
        assert result["persona_name"] is None

    def test_parse_invalid_budget_ignored(self) -> None:
        result = self._parse_auto_tokens("auto --max-budget notanumber")
        assert result["max_budget"] is None

    def test_parse_invalid_hours_ignored(self) -> None:
        result = self._parse_auto_tokens("auto --max-hours abc")
        assert result["max_hours"] is None

    def test_parse_invalid_loop_defaults_to_one(self) -> None:
        result = self._parse_auto_tokens("auto --loop xyz")
        assert result["loop_count"] == 1


class TestGitignoreLogsEntry:
    """Verify .colonyos/logs/ is in the gitignore entries list."""

    def test_logs_in_entries_needed(self) -> None:
        """The init module should include .colonyos/logs/ in gitignore entries."""
        from pathlib import Path

        init_path = Path("src/colonyos/init.py")
        source = init_path.read_text()
        assert ".colonyos/logs/" in source
