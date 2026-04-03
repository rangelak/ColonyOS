"""Multi-line composer widget with auto-grow behavior."""

from __future__ import annotations

from typing import Any

from textual import on
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import TextArea


class _ComposerTextArea(TextArea):
    """TextArea subclass that intercepts Enter for submission."""

    class SubmitRequest(Message):
        """Internal message asking the Composer to submit."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    async def _on_key(self, event: Any) -> None:
        """Intercept Enter to submit instead of inserting newline.

        Shift+Enter and Ctrl+J insert a newline instead.
        """
        # Terminal emulators do not agree on how modified Enter is reported.
        newline_keys = {
            "shift+enter",
            "shift+return",
            "ctrl+j",
            "ctrl+enter",
            "ctrl+return",
        }
        if event.key in newline_keys:
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            text = self.text.strip()
            if text:
                self.post_message(self.SubmitRequest(text))
                self.clear()
            return
        await super()._on_key(event)


class Composer(Vertical):
    """Multi-line input composer that grows with content.

    Wraps a ``TextArea`` with auto-grow from 5 to 8 lines.
    Enter submits, Shift+Enter inserts a newline.
    """

    TEXTAREA_MIN_HEIGHT = 5
    TEXTAREA_MAX_HEIGHT = 8
    CONTAINER_CHROME_HEIGHT = 1

    BINDINGS = [
        Binding("escape", "focus_self", "Focus composer", show=False),
    ]

    # Layout CSS is defined in APP_CSS (styles.py) — no DEFAULT_CSS needed.

    class Submitted(Message):
        """Emitted when the user presses Enter to submit input."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def compose(self):  # noqa: ANN201
        """Mount the inner TextArea."""
        yield _ComposerTextArea(id="composer-input")

    def on_mount(self) -> None:
        """Focus the text area on mount."""
        ta = self.query_one(TextArea)
        ta.focus()
        self._sync_heights(ta.document.line_count)

    @on(TextArea.Changed)
    def _on_text_changed(self, event: TextArea.Changed) -> None:
        """Recalculate height when content changes."""
        ta = event.text_area
        self._sync_heights(ta.document.line_count)

    @on(_ComposerTextArea.SubmitRequest)
    def _on_submit_request(self, event: _ComposerTextArea.SubmitRequest) -> None:
        """Forward the internal submit request as a Composer.Submitted message."""
        self.post_message(self.Submitted(event.text))

    def action_focus_self(self) -> None:
        """Return focus to the composer text area."""
        self.query_one(TextArea).focus()

    def restore_text(self, text: str) -> None:
        """Restore previously submitted text into the composer."""
        ta = self.query_one(TextArea)
        ta.text = text
        self._sync_heights(ta.document.line_count)
        ta.focus()

    def _sync_heights(self, line_count: int) -> None:
        """Keep the container one row taller than the bordered text area."""
        textarea_height = max(
            self.TEXTAREA_MIN_HEIGHT,
            min(line_count + 1, self.TEXTAREA_MAX_HEIGHT),
        )
        self.query_one(TextArea).styles.height = textarea_height
        self.styles.height = textarea_height + self.CONTAINER_CHROME_HEIGHT
