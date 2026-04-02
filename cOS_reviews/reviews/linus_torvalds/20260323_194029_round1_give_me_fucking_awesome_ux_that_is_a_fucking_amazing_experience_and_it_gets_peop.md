# Review by Linus Torvalds (Round 1)

Now I have a thorough understanding of the implementation. Let me write the review.

---

## Linus Torvalds Review

All right, I've read every line of this diff. 2,465 lines added, 21 files, and I'll give credit where it's due: the code is mostly straightforward and does what it says on the tin. But let me be Linus about this.

### What's good

The **adapter pattern** is clean. Frozen dataclasses for queue messages — that's the right call. Thread-safe, immutable, simple data structures. You show me the data structures and I understand the code. `TextualUI` implements the duck-type interface, pushes frozen messages onto a janus queue, and the app drains them. That's a clean separation.

The **test suite** is solid — 84 tests, all passing. The adapter tests use a `FakeSyncQueue` instead of requiring an event loop, which means they run fast and test the actual logic. The existing 1,687 tests still pass. Zero regressions.

**Sanitization** is consistently applied — all output goes through `sanitize_display_text()` before hitting the queue. Good.

### What's problematic

**The `_current_instance` class variable pattern is garbage.** In `_launch_tui()`, you set `AssistantApp._current_instance = app_instance` and then the `_run_callback` closure reads it back via `AssistantApp._current_instance`. This is a global mutable singleton — the kind of thing you write when you can't figure out how to pass a reference through a closure properly. The callback is *defined inside the same function* that creates `app_instance` — just close over it directly. You already have `app_instance` in scope. This is a one-line fix that eliminates a class-level `_current_instance: AssistantApp | None = None` that has no business existing.

**The monkey-patching of `on_mount` is ugly.** When a prompt is given, you save `original_on_mount`, define a new async function, and reassign `app_instance.on_mount`. This is fragile — if Textual changes how it resolves lifecycle methods, this breaks silently. The right way is to subclass or pass the initial prompt as a constructor argument and handle it in the real `on_mount`.

**StatusBar has five reactive watchers that all call `_render_bar()`.** Every single `watch_*` method is `self._render_bar()`. That's not "reactive" — that's "call the same function five different ways." The methods `set_phase()`, `set_complete()`, `set_error()`, and `increment_turn()` already call `_render_bar()` directly. So every state change renders *twice*: once from the public method, once from the reactive watcher. This is sloppy. Either use reactives with watchers and remove the manual `_render_bar()` calls, or remove the watchers entirely since the public methods already render. Don't do both.

**The spinner timer runs at 100ms unconditionally**, even when idle. It checks `if not self.is_running: return` on every tick, which means you're doing 10 timer callbacks per second to do nothing. Start the timer when a phase begins, stop it when it ends.

**`TranscriptView` wraps `VerticalScroll` wrapping `RichLog`.** The PRD says "use RichLog" — and RichLog already handles virtual scrolling internally. Why is there a `VerticalScroll` container around it? The `on_scroll_y` tracking logic on the outer container is checking scroll position on the inner `RichLog`. This layering seems unnecessary. Either the `RichLog` handles its own scrolling (it does) or you need the outer container — but then your scroll tracking is on the wrong widget.

### Verdict on completeness

All PRD functional requirements are covered:
- ✅ FR-1: `colonyos tui` command and `--tui` flag
- ✅ FR-2: Transcript pane with RichLog
- ✅ FR-3: Composer with auto-grow, Enter/Shift+Enter
- ✅ FR-4: Status bar with phase/cost/turns/elapsed/spinner
- ✅ FR-5: TextualUI adapter with all 8 callbacks
- ✅ FR-6: Keybindings (Enter, Shift+Enter, Ctrl+C, Ctrl+L, Escape)
- ✅ FR-7: Optional dependency with `tui` extra
- ✅ FR-8: Output sanitization

No TODOs, no placeholder code, no commented-out junk.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/cli.py]: `_current_instance` class-variable singleton pattern is unnecessary — `_run_callback` can close over `app_instance` directly since it's defined in the same scope
- [src/colonyos/cli.py]: Monkey-patching `on_mount` is fragile — pass initial prompt via constructor arg and handle in the real `on_mount` method
- [src/colonyos/tui/widgets/status_bar.py]: Five reactive watchers all calling `_render_bar()` cause double-rendering since every public method also calls `_render_bar()` — pick one approach
- [src/colonyos/tui/widgets/status_bar.py]: Spinner timer runs at 100ms unconditionally even when idle — start/stop it with phase lifecycle
- [src/colonyos/tui/widgets/transcript.py]: `VerticalScroll` wrapping `RichLog` adds unnecessary layering — `RichLog` already handles virtual scrolling
- [src/colonyos/tui/app.py]: `_current_instance` class attribute declared on `AssistantApp` has no business being there — it's an artifact of the cli.py closure bug

SYNTHESIS:
The architecture is sound — frozen dataclasses over a janus queue, adapter pattern matching the existing PhaseUI interface, optional dependency with clean import guards. The test coverage is good, existing tests don't regress, and all PRD requirements are met. But there are real code quality issues: a global mutable singleton where a simple closure suffices, monkey-patching lifecycle methods instead of proper subclassing, double-rendering from conflicting reactive/imperative patterns, and an always-running timer that does nothing 99% of the time. None of these are hard to fix — they're 30-minute cleanup items. Fix the double-rendering and the singleton pattern, and this ships clean. The implementation proves the concept works; now make the code as simple as the architecture.
