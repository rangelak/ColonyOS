"""Textual pilot tests for Composer and HintBar widgets."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import TextArea

from colonyos.tui.widgets.composer import Composer
from colonyos.tui.widgets.hint_bar import HintBar


class ComposerApp(App):
    """Minimal app that mounts a Composer for testing."""

    submitted_texts: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.submitted_texts = []

    def compose(self) -> ComposeResult:
        yield Composer()
        yield HintBar()

    def on_composer_submitted(self, event: Composer.Submitted) -> None:
        self.submitted_texts.append(event.text)


@pytest.mark.asyncio
async def test_composer_mounts_with_text_area():
    """Composer should contain a TextArea widget."""
    async with ComposerApp().run_test() as pilot:
        app = pilot.app
        composer = app.query_one(Composer)
        ta = composer.query_one(TextArea)
        assert ta is not None


@pytest.mark.asyncio
async def test_composer_enter_submits_and_clears():
    """Enter key should submit text and clear the TextArea."""
    async with ComposerApp().run_test() as pilot:
        app = pilot.app
        ta = app.query_one(TextArea)
        # Type some text
        ta.insert("hello world")
        await pilot.pause()

        assert ta.text == "hello world"

        # Press Enter to submit
        await pilot.press("enter")
        await pilot.pause()

        assert app.submitted_texts == ["hello world"]
        assert ta.text == ""


@pytest.mark.asyncio
async def test_composer_empty_submit_does_nothing():
    """Enter on empty composer should not emit a Submitted message."""
    async with ComposerApp().run_test() as pilot:
        app = pilot.app
        await pilot.press("enter")
        await pilot.pause()
        assert app.submitted_texts == []


@pytest.mark.asyncio
async def test_composer_shift_enter_inserts_newline():
    """Shift+Enter should insert a newline instead of submitting."""
    async with ComposerApp().run_test() as pilot:
        app = pilot.app
        ta = app.query_one(TextArea)
        ta.insert("line1")
        await pilot.pause()

        await pilot.press("shift+enter")
        await pilot.pause()

        # Should not have submitted
        assert app.submitted_texts == []
        # Should contain a newline
        assert "\n" in ta.text


@pytest.mark.asyncio
async def test_composer_submitted_message_carries_text():
    """Submitted message should carry the stripped text."""
    async with ComposerApp().run_test() as pilot:
        app = pilot.app
        ta = app.query_one(TextArea)
        ta.insert("  spaced text  ")
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert app.submitted_texts == ["spaced text"]


@pytest.mark.asyncio
async def test_composer_restore_text_restores_draft():
    """Composer should be able to restore a cleared draft."""
    async with ComposerApp().run_test() as pilot:
        app = pilot.app
        composer = app.query_one(Composer)
        composer.restore_text("retry this prompt")
        await pilot.pause()

        ta = app.query_one(TextArea)
        assert ta.text == "retry this prompt"
        assert ta.has_focus


@pytest.mark.asyncio
async def test_hint_bar_renders_keybinding_text():
    """HintBar should display the keybinding hints."""
    async with ComposerApp().run_test() as pilot:
        app = pilot.app
        hint = app.query_one(HintBar)
        # In Textual 8.x, use render() to get the renderable
        rendered = str(hint.render())
        assert "Ask for a change or explain what you need" in rendered
        assert "Enter send" in rendered
        assert "Ctrl+C cancel" in rendered
        assert "Ctrl+J newline" in rendered
        assert "Ctrl+L clear" in rendered
        assert "Shift+drag" in rendered
        assert "select" in rendered


@pytest.mark.asyncio
async def test_composer_ctrl_j_inserts_newline():
    """Ctrl+J should always insert a newline fallback."""
    async with ComposerApp().run_test() as pilot:
        app = pilot.app
        ta = app.query_one(TextArea)
        ta.insert("line1")
        await pilot.pause()

        await pilot.press("ctrl+j")
        await pilot.pause()

        assert app.submitted_texts == []
        assert "\n" in ta.text


@pytest.mark.asyncio
async def test_composer_height_grows_with_content():
    """Composer height should increase as lines are added."""
    async with ComposerApp().run_test() as pilot:
        app = pilot.app
        ta = app.query_one(TextArea)

        # Insert multiple lines
        ta.insert("line1\nline2\nline3\nline4\nline5")
        await pilot.pause()

        composer = app.query_one(Composer)
        # Container should reserve an extra row for its own border chrome.
        height = composer.styles.height
        assert height is not None
        assert height.value >= Composer.TEXTAREA_MIN_HEIGHT + Composer.CONTAINER_CHROME_HEIGHT
        assert ta.styles.height is not None
        assert height.value == ta.styles.height.value + Composer.CONTAINER_CHROME_HEIGHT


@pytest.mark.asyncio
async def test_composer_height_caps_at_max():
    """Composer height should not exceed MAX_HEIGHT."""
    async with ComposerApp().run_test() as pilot:
        app = pilot.app
        ta = app.query_one(TextArea)

        # Insert many lines
        lines = "\n".join(f"line{i}" for i in range(20))
        ta.insert(lines)
        await pilot.pause()

        composer = app.query_one(Composer)
        height = composer.styles.height
        assert height is not None
        assert height.value <= (
            Composer.TEXTAREA_MAX_HEIGHT + Composer.CONTAINER_CHROME_HEIGHT
        )


@pytest.mark.asyncio
async def test_composer_initial_height_reserves_border_row():
    """Composer should start one row taller than the inner TextArea."""
    async with ComposerApp().run_test() as pilot:
        app = pilot.app
        composer = app.query_one(Composer)
        ta = app.query_one(TextArea)
        await pilot.pause()

        assert composer.styles.height is not None
        assert ta.styles.height is not None
        assert (
            composer.styles.height.value
            == ta.styles.height.value + Composer.CONTAINER_CHROME_HEIGHT
        )
