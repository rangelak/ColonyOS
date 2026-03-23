"""Multi-line composer widget with auto-grow behavior."""

from __future__ import annotations

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

    async def _on_key(self, event) -> None:  # noqa: ANN001
        """Intercept Enter to submit instead of inserting newline.

        Shift+Enter and Ctrl+J insert a newline instead.
        """
        if event.key == "shift+enter" or event.key == "ctrl+j":
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

    Wraps a ``TextArea`` with auto-grow from 3 to 8 lines.
    Enter submits, Shift+Enter inserts a newline.
    """

    MIN_HEIGHT = 3
    MAX_HEIGHT = 8

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

    @on(TextArea.Changed)
    def _on_text_changed(self, event: TextArea.Changed) -> None:
        """Recalculate height when content changes."""
        ta = event.text_area
        line_count = ta.document.line_count
        desired = max(self.MIN_HEIGHT, min(line_count + 1, self.MAX_HEIGHT))
        ta.styles.height = desired
        self.styles.height = desired

    @on(_ComposerTextArea.SubmitRequest)
    def _on_submit_request(self, event: _ComposerTextArea.SubmitRequest) -> None:
        """Forward the internal submit request as a Composer.Submitted message."""
        self.post_message(self.Submitted(event.text))

    def action_focus_self(self) -> None:
        """Return focus to the composer text area."""
        self.query_one(TextArea).focus()
