# Review: Interactive Terminal UI (Textual TUI) — Round 2

**Reviewer**: Linus Torvalds
**Branch**: `colonyos/give_me_fucking_awesome_ux_that_is_a_fucking_amazing_experience_and_it_gets_peop`
**PRD**: `cOS_prds/20260323_190105_prd_give_me_fucking_awesome_ux_that_is_a_fucking_amazing_experience_and_it_gets_peop.md`

## Checklist Assessment

### Completeness
- [x] FR-1 (TUI entry point): `colonyos tui` command and `--tui` flag on `colonyos run` — both implemented in `cli.py`
- [x] FR-2 (Transcript pane): `TranscriptView` extends `RichLog` directly with phase headers, tool lines, text blocks, user messages, auto-scroll tracking
- [x] FR-3 (Composer pane): `Composer` wraps `TextArea` with auto-grow 3→8 lines, Enter submits, Shift+Enter/Ctrl+J for newline
- [x] FR-4 (Status bar): `StatusBar` shows phase name, cumulative cost, turns, elapsed time, cycling spinner during active phases
- [x] FR-5 (TextualUI adapter): All 8 methods implemented, frozen dataclass messages, janus queue bridge, sanitization on all output
- [x] FR-6 (Keybindings): Enter, Shift+Enter, Ctrl+C, Ctrl+L, Escape all wired
- [x] FR-7 (Optional dependency): `tui = ["textual>=0.40", "janus>=1.0"]` in pyproject.toml, lazy import guard
- [x] FR-8 (Output sanitization): All text goes through `sanitize_display_text()` before queuing

### Quality
- [x] All 86 TUI tests pass
- [x] All 1687 existing tests pass — zero regressions
- [x] Code follows existing project conventions (file structure, naming, docstrings)
- [x] Only two new dependencies (textual, janus), both optional and well-motivated
- [x] No unrelated changes — the diff is clean and focused

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive operations
- [x] Error handling: graceful ImportError for missing deps, queue cleanup on unmount, CancelledError handling in consumer loop

## Detailed Findings

### What's Done Right

**Data structures are correct.** The frozen dataclasses for queue messages (`PhaseHeaderMsg`, `ToolLineMsg`, etc.) are exactly the right abstraction. Immutable, typed, thread-safe by construction. No fancy event bus, no inheritance hierarchy, no visitor pattern — just data. This is how you do it.

**The adapter is clean.** `TextualUI` is 220 lines, implements the existing 8-method duck interface, buffers text properly, extracts tool args using the same logic as `PhaseUI`, and sanitizes everything. It doesn't try to be clever. It doesn't introduce new abstractions. It just translates callbacks into queue messages.

**The threading model is simple and correct.** Orchestrator runs in a `Worker(thread=True)`. Adapter pushes to `janus.SyncQueue`. App drains `async_q`. No shared mutable state. No locks. No condition variables. The janus queue is the only coordination point. This is the right way to bridge sync and async code.

**Widget count is minimal.** Four widgets total: `TranscriptView`, `Composer`, `StatusBar`, `HintBar`. `TranscriptView` extends `RichLog` directly instead of wrapping it in a container — correct choice, avoids an unnecessary layer.

**Tests are thorough and well-structured.** The adapter tests use a `FakeSyncQueue` based on stdlib `queue.Queue` — no Textual dependency needed for the core contract tests. The widget tests use Textual's pilot. 86 tests covering the full lifecycle.

### Minor Issues (Not Blocking)

**`_launch_tui` creates the app then monkey-patches `_run_callback` on line 4254.** This is because the callback needs a reference to the app's queue, which doesn't exist until mount. It works, but it's mildly ugly. A factory function or passing a queue-factory callable would be cleaner. Not worth blocking on.

**`Composer` has duplicate CSS.** `DEFAULT_CSS` in `composer.py` (lines 57-74) overlaps with `APP_CSS` in `styles.py` (lines 55-71). The `Composer` CSS will win due to specificity, but the duplication is unnecessary. Pick one source of truth.

**`_looks_like_markdown` regex (transcript.py line 161-163) is a heuristic.** It'll false-positive on things like backtick-quoted variable names in plain text. For v1 this is fine — worst case you get slightly fancier rendering. Just noting it.

**`StatusBar._last_rendered` (line 59) is tracked but never read externally.** It's useful for testing but it's a testing-only attribute leaking into production code. Could be removed or gated behind a test flag. Minor.

**`on_composer_submitted` lambda closure (app.py line 172):** `lambda: self._run_callback(text)` captures `self._run_callback` late. If `_run_callback` were ever reassigned between submission and worker execution, you'd get the wrong callback. Given the current code this can't happen, but the pattern is fragile. Store the callback in a local variable first, like the `on_mount` method already does on line 97-98.

## Test Results

```
tests/tui/ — 86 passed in 2.08s
tests/ (excluding tui) — 1687 passed in 2.47s
Total: 1773 passed, 0 failed, 0 regressions
```

---

VERDICT: approve

FINDINGS:
- [src/colonyos/cli.py:4254]: Monkey-patching `_run_callback` after construction is mildly ugly but functional
- [src/colonyos/tui/widgets/composer.py:57-74]: Duplicate CSS with `styles.py` APP_CSS — pick one source of truth
- [src/colonyos/tui/widgets/transcript.py:161-163]: `_looks_like_markdown` is a heuristic that will false-positive on backtick-quoted names — acceptable for v1
- [src/colonyos/tui/widgets/status_bar.py:59]: `_last_rendered` is a test-only attribute in production code
- [src/colonyos/tui/app.py:172]: Lambda captures `self._run_callback` late — fragile if callback were ever reassigned

SYNTHESIS:
This is a clean, minimal implementation that does exactly what the PRD says and nothing more. The data structures are right — frozen dataclasses for thread-safe queue messages, no over-abstracted event bus. The threading model is correct — one janus queue, one coordination point, no shared mutable state. The widget hierarchy is flat — four widgets, no unnecessary containers or wrapper layers. 86 new tests pass, 1687 existing tests are untouched. The code reuses existing patterns (TOOL_STYLE map, sanitize_display_text, PhaseUI duck interface) instead of inventing new ones. The PRD said "ship in one week" — this implementation looks like it took about a day, which is exactly how it should be when the scope is properly constrained. The minor issues (duplicate CSS, monkey-patched callback, test-only attribute) are all v2 cleanup items, not blockers. Ship it.
