# Tasks: Fix TUI Scrolling, Double Scrollbar, and Text Selection

## Relevant Files

- `src/colonyos/tui/styles.py` - CSS layout with dead `TranscriptView RichLog` selector (line 67-70) and Screen rule (line 50-52)
- `src/colonyos/tui/widgets/transcript.py` - TranscriptView widget with scroll tracking, auto_scroll logic, and all append methods
- `src/colonyos/tui/widgets/hint_bar.py` - Keybinding hints footer; needs Shift+drag hint
- `src/colonyos/tui/app.py` - AssistantApp with keybindings, monitor_mode, and action_scroll_to_end
- `tests/tui/test_transcript.py` - Existing TranscriptView tests; add scroll behavior tests
- `tests/tui/test_app.py` - Existing app integration tests; add Screen overflow tests

## Tasks

- [x] 1.0 Fix CSS: double scrollbar and dead selector
  depends_on: []
  - [x] 1.1 Write tests verifying TranscriptView CSS properties are applied (scrollbar-size, padding) and Screen has overflow hidden
  - [x] 1.2 In `src/colonyos/tui/styles.py`: change `TranscriptView RichLog` selector to `TranscriptView` so padding and scrollbar-size are applied to the widget itself (it IS a RichLog, not a parent of one)
  - [x] 1.3 In `src/colonyos/tui/styles.py`: add `overflow: hidden;` to the `Screen` CSS rule to prevent the Screen from creating a second scrollbar

- [x] 2.0 Fix auto-scroll behavior: disable RichLog built-in auto_scroll
  depends_on: []
  - [x] 2.1 Write tests in `tests/tui/test_transcript.py`: verify `TranscriptView` initializes with `RichLog.auto_scroll == False`; verify custom `_auto_scroll` starts as `True`; verify writing content does not force scroll when `_auto_scroll` is `False`
  - [x] 2.2 In `src/colonyos/tui/widgets/transcript.py` `__init__`: pass `auto_scroll=False` to `super().__init__()` so the base class's built-in auto-scroll is disabled
  - [x] 2.3 In `src/colonyos/tui/widgets/transcript.py` `on_scroll_y`: add a 3-line tolerance threshold so auto-scroll re-engages when user scrolls near the bottom (`self.scroll_y >= max_scroll - 3` instead of `self.scroll_y >= max_scroll`)
  - [x] 2.4 Fix `_programmatic_scroll` flag timing: instead of clearing the flag synchronously after `scroll_end()`, set a `_pending_programmatic_clear` flag and clear `_programmatic_scroll` at the start of the next `on_scroll_y` call, ensuring the guard works correctly with async scroll events

- [x] 3.0 Add "new content below" indicator
  depends_on: [2.0]
  - [x] 3.1 Write tests: verify `_unread_lines` counter increments when content is written while `_auto_scroll` is `False`; verify counter resets when auto-scroll re-engages; verify indicator text appears/disappears correctly
  - [x] 3.2 In `src/colonyos/tui/widgets/transcript.py`: add `_unread_lines: int = 0` counter; increment in `_scroll_to_end` when `_auto_scroll` is `False`; reset to 0 when `_auto_scroll` becomes `True`
  - [x] 3.3 In `src/colonyos/tui/widgets/transcript.py`: add a method to render a subtle notification (e.g., `self.notify("↓ N new lines — press End to resume", severity="information")` using Textual's built-in notification system, or a reactive label) when `_unread_lines` transitions from 0 to >0
  - [x] 3.4 In `src/colonyos/tui/app.py` `action_scroll_to_end`: ensure unread counter is cleared when user presses End

- [x] 4.0 Add text selection hints and improve copy discoverability
  depends_on: []
  - [x] 4.1 Write tests: verify HintBar rendered text includes "Shift+drag" hint; verify welcome banner mentions selection
  - [x] 4.2 In `src/colonyos/tui/widgets/hint_bar.py` `_render_hints`: add "Shift+drag" and "select" to the keybinding hints line
  - [x] 4.3 In `src/colonyos/tui/widgets/transcript.py` `append_welcome_banner` and `append_daemon_monitor_banner`: add "Shift+drag to select" to the shortcuts text

- [x] 5.0 Integration testing and regression check
  depends_on: [1.0, 2.0, 3.0, 4.0]
  - [x] 5.1 Run the full existing test suite (`pytest tests/tui/`) to verify no regressions
  - [x] 5.2 Add an integration test in `tests/tui/test_app.py` that mounts `AssistantApp`, pushes multiple messages via the queue, and verifies that scroll position is preserved when `_auto_scroll` is `False`
  - [x] 5.3 Add an integration test for monitor mode (`monitor_mode=True`) verifying single scrollbar behavior and no Composer/HintBar widgets
  - [x] 5.4 Run the full project test suite to verify no regressions outside the TUI
