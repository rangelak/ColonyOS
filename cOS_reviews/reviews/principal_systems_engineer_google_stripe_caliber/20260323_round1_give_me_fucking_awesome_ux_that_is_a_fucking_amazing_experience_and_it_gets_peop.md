# Review: Interactive Terminal UI (Textual TUI)

**Reviewer**: Principal Systems Engineer (Google/Stripe caliber)
**Branch**: `colonyos/give_me_fucking_awesome_ux_that_is_a_fucking_amazing_experience_and_it_gets_peop`
**PRD**: `cOS_prds/20260323_190105_prd_give_me_fucking_awesome_ux_that_is_a_fucking_amazing_experience_and_it_gets_peop.md`

---

## Checklist

### Completeness
- [x] FR-1: TUI entry point (`colonyos tui` command + `--tui` flag on `run`)
- [x] FR-2: Transcript pane with RichLog, auto-scroll, phase headers, tool lines, text blocks
- [x] FR-3: Composer with auto-grow (3-8 lines), Enter submit, Shift+Enter newline
- [x] FR-4: Status bar with phase name, cost, turns, elapsed time, spinner
- [x] FR-5: TextualUI adapter implementing 8-method PhaseUI interface
- [x] FR-6: Keybindings (Enter, Shift+Enter, Ctrl+C, Ctrl+L, Escape)
- [x] FR-7: Optional dependency (`tui = ["textual>=0.40", "janus>=1.0"]`)
- [x] FR-8: Output sanitization via `sanitize_display_text()`
- [x] All tasks complete (8 task merges visible in commit history)
- [x] No TODO/FIXME/placeholder code

### Quality
- [x] All 84 TUI tests pass
- [x] All 1687 existing tests pass — zero regressions
- [x] No linter errors (clean imports, no unused code post-polish commit)
- [x] Follows existing conventions (duck-type PhaseUI interface, optional dependency pattern, ui_factory injection)
- [x] Only 2 new dependencies added (textual, janus) — both well-scoped and optional
- [x] No unrelated changes — diff is tightly scoped to TUI feature + README docs

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive database operations
- [x] Error handling present: ImportError fallback, graceful None guards on `_rich_log`, queue lifecycle cleanup

---

## Findings

- [src/colonyos/cli.py `_launch_tui`]: **Race condition on `_current_instance` class variable**. The `_run_callback` closure captures `AssistantApp._current_instance` at call time (line 4238), but this is set two lines before `app_instance.run()` (line 4256). If `_run_callback` fires before `on_mount` completes, `event_queue` will raise `RuntimeError`. In practice this is safe because the worker thread is only spawned from `on_mount` or `on_composer_submitted`, both of which happen after the app is running. However, the mutable class-level singleton pattern (`_current_instance`) is fragile — it prevents running two TUI instances in the same process and makes testing harder. **Severity: Low.** Acceptable for v1 but should be refactored to pass the queue directly into the callback closure.

- [src/colonyos/cli.py `_on_mount_with_prompt`]: **Monkey-patching `on_mount`** by reassigning the method on the instance is brittle. If `AssistantApp.on_mount` is ever decorated or if Textual changes its method resolution, this breaks silently. A cleaner pattern would be to pass the initial prompt into `AssistantApp.__init__` and handle it in the real `on_mount`. **Severity: Low.** Works today, but a maintenance risk.

- [src/colonyos/tui/app.py `_consume_queue`]: **No backpressure or error handling in the consumer loop**. If a widget method (e.g., `append_tool_line`) raises an exception, the entire consumer task dies and subsequent events are silently dropped. The user sees a frozen transcript with no indication of what happened. Should wrap the dispatch body in try/except with at least a log or status bar error notification. **Severity: Medium.** At 3am, a frozen TUI with no error is the worst debugging experience.

- [src/colonyos/tui/app.py `on_unmount`]: Good cleanup of the consumer task and queue. However, the worker thread running the orchestrator is not cancelled on unmount — if the user quits the TUI while a phase is running, the orchestrator thread continues running in the background until it finishes or the process exits. This is acceptable for v1 (the process exits anyway), but worth noting for future REPL-mode work.

- [src/colonyos/tui/widgets/status_bar.py]: **Timer fires every 100ms unconditionally**, even when idle. This is fine for a terminal app (no battery concerns), but the `_render_bar()` call on every spinner advance triggers a full Rich Text rebuild + widget update. The `_last_rendered` field exists but is never used to skip no-op updates. Adding a guard (`if text.plain == self._last_rendered: return`) would reduce unnecessary redraws. **Severity: Low.**

- [src/colonyos/tui/widgets/status_bar.py]: The reactive watchers (`watch_phase_name`, `watch_is_running`, etc.) each call `_render_bar()`, and `set_phase()` sets multiple reactive attributes in sequence, potentially causing 3-4 redundant renders in a single call. Not a correctness issue but suboptimal. **Severity: Low.**

- [src/colonyos/tui/adapter.py]: **Solid implementation.** The frozen dataclasses for queue messages are a good pattern — immutable, thread-safe, clearly typed. The `_flush_text()` / `_try_extract_arg()` logic correctly mirrors `PhaseUI` behavior. Sanitization is applied at the adapter boundary before queueing, which is the right place.

- [src/colonyos/tui/widgets/transcript.py `on_scroll_y`]: Auto-scroll threshold is 3 *lines*, but `scroll_y` and `virtual_size.height` are in CSS pixels/units, not lines. This threshold may need tuning based on actual line heights. **Severity: Low.** Functional, just may need empirical adjustment.

- [tests/tui/]: **Comprehensive test coverage.** 84 tests covering the adapter queue contract, widget rendering, CLI integration, and app lifecycle. The `FakeSyncQueue` pattern avoids needing a running event loop for adapter tests, which is a good testing strategy. Tests correctly skip when TUI extras aren't installed.

---

## Synthesis

This is a clean, well-structured v1 implementation that hits every functional requirement in the PRD with minimal footprint (2,465 lines added across 21 files, zero lines changed in existing source outside `cli.py` and `pyproject.toml`). The architecture is sound: frozen dataclasses over a janus queue for thread-safe event passing, the existing `ui_factory` injection point for zero-refactor integration, and RichLog for efficient append-only rendering.

The main operational concern is the missing error handling in the queue consumer loop — if any widget render throws, the TUI silently freezes. This is the kind of thing that bites you at 3am when some unexpected Rich renderable triggers an edge case. The `_current_instance` singleton and `on_mount` monkey-patch are code smells but not blocking for a v1 that's explicitly scoped to "ship and validate."

From a systems perspective: the concurrency model is correct (sync producer thread → janus queue → async consumer), the dependency isolation is proper (optional extras, import guards, graceful fallback), and the blast radius is zero (no changes to the orchestrator, agent, or existing UI paths). All 1687 existing tests pass unchanged.

I'd want the consumer loop error handling added before this goes to users who aren't developers (silent freezes are unacceptable UX), but for an internal/developer-facing v1, this is ready to ship.

VERDICT: approve

FINDINGS:
- [src/colonyos/tui/app.py]: Queue consumer loop has no error handling — widget render exceptions silently kill the consumer, freezing the TUI with no indication
- [src/colonyos/cli.py]: `_current_instance` class-level singleton is fragile; prefer passing queue into callback closure directly
- [src/colonyos/cli.py]: Monkey-patching `on_mount` for initial prompt is brittle; should be constructor parameter
- [src/colonyos/tui/widgets/status_bar.py]: `_last_rendered` exists but is never used to skip no-op redraws; spinner timer causes redundant renders when idle
- [src/colonyos/tui/widgets/status_bar.py]: Multiple reactive attribute sets in `set_phase()` cause redundant render cascades
- [src/colonyos/tui/widgets/transcript.py]: Auto-scroll threshold units may not match actual scroll units; needs empirical tuning

SYNTHESIS:
Solid v1 that delivers all PRD requirements with zero regression risk. The janus queue bridge, frozen message dataclasses, and ui_factory injection are architecturally clean. The main operational gap is the unguarded consumer loop — a single widget render exception silently freezes the entire TUI. For a developer-facing v1, this is shippable. Before broader rollout, add try/except in the consumer loop and eliminate the singleton pattern. The implementation demonstrates good engineering discipline: 84 new tests, no existing code broken, proper optional dependency isolation, and output sanitization at the adapter boundary.
