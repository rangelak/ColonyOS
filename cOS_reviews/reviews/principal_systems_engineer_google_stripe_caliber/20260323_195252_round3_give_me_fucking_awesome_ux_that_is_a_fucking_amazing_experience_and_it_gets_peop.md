# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 3)

I now have a thorough picture. Let me write the review.

---

## Review: Principal Systems Engineer Perspective

### Completeness Assessment

**FR-1 (TUI Entry Point)**: ✅ `colonyos tui` command and `--tui` flag both implemented. Graceful `ImportError` fallback with clear install instructions.

**FR-2 (Transcript Pane)**: ✅ `TranscriptView` wraps `RichLog` with all 8 callback types rendered. Auto-scroll with threshold-based tracking works correctly.

**FR-3 (Composer Pane)**: ✅ Multi-line `TextArea` with auto-grow 3→8 lines. Enter submits, Shift+Enter inserts newline. Clears after submit.

**FR-4 (Status Bar)**: ✅ Phase name, cost, turns, elapsed time. Spinner animation via 100ms timer during active phases.

**FR-5 (TextualUI Adapter)**: ✅ All 8 methods implemented. Frozen dataclasses for thread-safe queue messages. Text buffering with flush-on-turn-complete.

**FR-6 (Keybindings)**: ✅ Enter, Shift+Enter, Ctrl+C, Ctrl+L, Escape all bound.

**FR-7 (Optional Dependency)**: ✅ `tui = ["textual>=0.40", "janus>=1.0"]` in pyproject.toml. Import guarded with `_check_dependencies()`.

**FR-8 (Output Sanitization)**: ✅ All adapter output runs through `sanitize_display_text()`.

### Test Results

- **1775 tests pass** (0 failures, 0 regressions)
- **86 new TUI tests** covering adapter, app, composer, transcript, status bar, CLI integration, and setup
- No TODOs, FIXMEs, or placeholder code

---

VERDICT: approve

FINDINGS:
- [src/colonyos/tui/app.py:172]: Lambda closure `lambda: self._run_callback(text)` is safe here (text is a local), but the `exclusive=True` flag means a second submission cancels the running orchestrator mid-flight. This is intentional (per FR-6 Ctrl+C cancel), but there's no user confirmation before killing an in-progress run. Acceptable for v1, should add a "run in progress, cancel?" guard in v2.
- [src/colonyos/tui/app.py:98-102]: The initial prompt auto-submission creates a `TextualUI` adapter inside the `_run_callback` closure (defined in cli.py:4238-4252), meaning a new adapter instance is created per submission rather than being reused. This is fine — the adapter is stateless between runs — but it means turn_count resets between submissions. This is correct behavior.
- [src/colonyos/cli.py:4254]: `app_instance._run_callback = _run_callback` mutates a private attribute after construction. While it works (because `.run()` hasn't started), it would be cleaner as a setter method. Minor style nit.
- [src/colonyos/tui/adapter.py:101-108]: The adapter holds mutable state (`_text_buf`, `_tool_json`, `_turn_count`) and is accessed from a worker thread with no synchronization. This is safe *only because* Textual's `exclusive=True` guarantees one worker at a time. If someone later changes to `exclusive=False` or adds parallel workers, this becomes a race condition. A docstring comment noting this invariant would be prudent.
- [src/colonyos/tui/widgets/status_bar.py:77]: Spinner timer at 100ms (10fps) is reasonable. The `_render_bar()` call from `_advance_spinner` triggers `self.update()` which is a Textual main-thread operation, correctly called from a timer callback (which runs on the main loop). No threading issue here.
- [src/colonyos/sanitize.py:124]: The `sanitize_display_text()` strips leading/trailing whitespace via `.strip()`, which also strips `\n` and `\t`. The adapter's `_flush_text` calls `.strip()` before sanitize, so multi-paragraph agent text blocks lose internal structure. The commit message says this was addressed ("Fix sanitizer stripping newlines"), but `_CONTROL_CHARS_RE` preserves `\n/\t/\r` while `.strip()` at the end removes trailing ones. This is the correct behavior — trailing whitespace is noise, internal newlines are preserved via `sanitize_display_text` because `.strip()` only affects edges.

SYNTHESIS:
This is a clean, well-scoped v1 implementation. The architecture is sound: frozen dataclasses for the thread boundary, janus queue for async↔sync bridging, and the existing PhaseUI duck-type contract preserved without modification. The 86 new tests cover all widget methods, adapter state transitions, CLI fallback paths, and message dispatch. The concurrency model is simple and correct — one worker thread, one consumer task, exclusive scheduling — which is exactly the right call for v1. The main operational concern is the lack of a guard against accidentally canceling a running orchestrator via double-submission, and the implicit single-thread invariant in the adapter that should be documented. No secrets, no destructive operations, no regression. Ship it.
