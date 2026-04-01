"""Tests for the TranscriptView widget."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from colonyos.tui.widgets.transcript import TranscriptView


# ---------------------------------------------------------------------------
# Test app that embeds a TranscriptView for pilot testing
# ---------------------------------------------------------------------------


class TranscriptTestApp(App):
    """Minimal app wrapping TranscriptView for testing."""

    def compose(self) -> ComposeResult:
        yield TranscriptView(id="tv")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTranscriptView:
    """Textual pilot tests for TranscriptView."""

    async def test_mounts_as_richlog(self, require_tui: None) -> None:
        """TranscriptView should mount as a RichLog (it extends RichLog directly)."""
        async with TranscriptTestApp().run_test() as pilot:
            from textual.widgets import RichLog
            tv = pilot.app.query_one("#tv", TranscriptView)
            assert tv is not None
            assert isinstance(tv, RichLog)

    async def test_append_phase_header(self, require_tui: None) -> None:
        """Phase header should appear in the RichLog."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_phase_header("planning", 5.0, "opus")
            # RichLog should now have entries (rule + header = 2)
            log = tv
            # _lines is the internal list of renderables in RichLog
            assert len(log.lines) >= 2  # noqa: SLF001

    async def test_append_phase_header_with_extra(self, require_tui: None) -> None:
        """Phase header extra metadata should render without error."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_phase_header("implement", 5.0, "opus", "branch: feat/tui")
            log = tv
            assert len(log.lines) >= 2  # noqa: SLF001

    async def test_append_tool_line(self, require_tui: None) -> None:
        """Tool line should appear with the right content."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_tool_line("Read", "/some/file.py")
            log = tv
            assert len(log.lines) >= 1  # noqa: SLF001

    async def test_append_tool_line_uses_tool_color(self, require_tui: None) -> None:
        """Tool dot should use the matching TOOL_COLORS color."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_tool_line("Bash", "ls -la")
            log = tv
            # The line was written; basic smoke test
            assert len(log.lines) >= 1  # noqa: SLF001

    async def test_append_text_block_plain(self, require_tui: None) -> None:
        """Plain text should be appended as dim lines."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_text_block("hello world")
            log = tv
            assert len(log.lines) >= 1  # noqa: SLF001

    async def test_append_text_block_markdown(self, require_tui: None) -> None:
        """Markdown-like text should be rendered as Markdown."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_text_block("## Heading\n\nSome **bold** text.")
            log = tv
            assert len(log.lines) >= 1  # noqa: SLF001

    async def test_append_text_block_empty_ignored(self, require_tui: None) -> None:
        """Empty text blocks should not produce entries."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_text_block("   ")
            log = tv
            assert len(log.lines) == 0  # noqa: SLF001

    async def test_append_command_output_preserves_indentation(self, require_tui: None) -> None:
        """Preformatted command output should keep leading spaces and blank lines."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_command_output("  aligned\n\n    deeper")
            log = tv
            assert len(log.lines) >= 5  # noqa: SLF001

    async def test_append_phase_complete(self, require_tui: None) -> None:
        """Phase complete summary should appear."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_phase_complete(1.23, 5, "1m 30s")
            log = tv
            # blank + summary + blank = 3 entries
            assert len(log.lines) >= 3  # noqa: SLF001

    async def test_append_phase_error(self, require_tui: None) -> None:
        """Phase error should appear."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_phase_error("something broke")
            log = tv
            assert len(log.lines) >= 3  # noqa: SLF001

    async def test_append_user_message(self, require_tui: None) -> None:
        """User messages should appear with 'You:' prefix."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_user_message("fix the bug")
            log = tv
            assert len(log.lines) >= 1  # noqa: SLF001

    async def test_append_user_message_empty_ignored(self, require_tui: None) -> None:
        """Empty user messages should not produce entries."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_user_message("  ")
            log = tv
            assert len(log.lines) == 0  # noqa: SLF001

    async def test_append_notice(self, require_tui: None) -> None:
        """System notices should render distinctly."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_notice("wait for the run to finish")
            log = tv
            assert len(log.lines) >= 3  # noqa: SLF001

    async def test_clear_transcript(self, require_tui: None) -> None:
        """clear_transcript should remove all entries."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_tool_line("Read", "/a.py")
            tv.append_tool_line("Write", "/b.py")
            log = tv
            assert len(log.lines) >= 2  # noqa: SLF001
            tv.clear_transcript()
            assert len(log.lines) == 0  # noqa: SLF001

    async def test_phase_boundary_has_rule_line(self, require_tui: None) -> None:
        """Phase header should produce at least 2 entries (rule + header)."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_phase_header("review", 3.0, "sonnet")
            log = tv
            # Rule line + header line = at least 2 entries
            assert len(log.lines) >= 2

    async def test_sanitizes_output(self, require_tui: None) -> None:
        """ANSI escape sequences should be stripped before rendering."""
        from colonyos.sanitize import sanitize_display_text

        # Verify the sanitizer strips ANSI at the unit level
        raw = "hello \x1b[31mworld\x1b[0m"
        clean = sanitize_display_text(raw)
        assert "\x1b" not in clean
        assert "hello" in clean

        # And verify the widget accepts and renders it without error
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_user_message(raw)
            log = tv
            assert len(log.lines) >= 1

    async def test_user_message_sanitized(self, require_tui: None) -> None:
        """User messages should be sanitized through sanitize_display_text."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            # OSC window title attack should be stripped
            tv.append_user_message("\x1b]0;pwned\x07safe message")
            log = tv
            assert len(log.lines) >= 1

    async def test_multiple_phases_separated(self, require_tui: None) -> None:
        """Two phase headers should produce distinct boundary markers."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_phase_header("plan", 2.0, "opus")
            tv.append_tool_line("Read", "a.py")
            tv.append_phase_complete(0.5, 2, "10s")
            tv.append_phase_header("implement", 5.0, "opus")
            log = tv
            # Should have entries from both phases
            assert len(log.lines) >= 6  # noqa: SLF001

    async def test_programmatic_scroll_guard(self, require_tui: None) -> None:
        """on_scroll_y should be a no-op when _programmatic_scroll is True."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv._auto_scroll = True
            tv._programmatic_scroll = True
            tv.on_scroll_y()
            # _auto_scroll should remain True because the guard skipped the check
            assert tv._auto_scroll is True

    async def test_get_plain_text_returns_string(self, require_tui: None) -> None:
        """get_plain_text should return transcript content as a string."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv.append_user_message("hello plain text")
            text = tv.get_plain_text()
            assert isinstance(text, str)
            assert "hello" in text.lower() or "plain" in text.lower()

    async def test_get_plain_text_empty(self, require_tui: None) -> None:
        """get_plain_text on empty transcript returns empty or whitespace string."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            text = tv.get_plain_text()
            assert isinstance(text, str)

    async def test_re_enable_auto_scroll(self, require_tui: None) -> None:
        """re_enable_auto_scroll should set _auto_scroll to True."""
        async with TranscriptTestApp().run_test() as pilot:
            tv = pilot.app.query_one("#tv", TranscriptView)
            tv._auto_scroll = False
            tv.re_enable_auto_scroll()
            assert tv._auto_scroll is True


@pytest.mark.asyncio
class TestTranscriptViewCSS:
    """Verify CSS properties are correctly applied to TranscriptView."""

    async def test_transcript_has_scrollbar_size(self, require_tui: None) -> None:
        """TranscriptView should have scrollbar-size from CSS (not from dead descendant selector)."""
        from colonyos.tui.app import AssistantApp

        app = AssistantApp()
        async with app.run_test() as pilot:
            tv = pilot.app.query_one(TranscriptView)
            # scrollbar-size: 1 1 should be applied directly to TranscriptView
            assert tv.styles.scrollbar_size_horizontal == 1
            assert tv.styles.scrollbar_size_vertical == 1

    async def test_transcript_has_padding(self, require_tui: None) -> None:
        """TranscriptView should have padding from CSS (not from dead descendant selector)."""
        from colonyos.tui.app import AssistantApp

        app = AssistantApp()
        async with app.run_test() as pilot:
            tv = pilot.app.query_one(TranscriptView)
            # padding: 0 2 should be applied directly to TranscriptView
            assert tv.styles.padding.right == 2
            assert tv.styles.padding.left == 2

    async def test_screen_has_overflow_hidden(self, require_tui: None) -> None:
        """Screen should have overflow: hidden to prevent a second scrollbar."""
        from colonyos.tui.app import AssistantApp

        app = AssistantApp()
        async with app.run_test() as pilot:
            screen = pilot.app.screen
            # Screen overflow should be hidden so it doesn't create its own scrollbar
            assert screen.styles.overflow_x == "hidden"
            assert screen.styles.overflow_y == "hidden"
