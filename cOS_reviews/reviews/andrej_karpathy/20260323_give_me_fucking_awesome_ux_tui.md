# Review: Interactive Terminal UI (Textual TUI)

**Reviewer**: Andrej Karpathy
**Branch**: `colonyos/give_me_fucking_awesome_ux_that_is_a_fucking_amazing_experience_and_it_gets_peop`
**PRD**: `cOS_prds/20260323_190105_prd_give_me_fucking_awesome_ux_that_is_a_fucking_amazing_experience_and_it_gets_peop.md`

---

## Checklist Assessment

### Completeness
- [x] FR-1: TUI Entry Point — `colonyos tui` command and `--tui` flag on `run` implemented
- [x] FR-2: Transcript Pane — `TranscriptView` wrapping `RichLog` with phase headers, tool lines, text blocks, auto-scroll
- [x] FR-3: Composer Pane — `Composer` with auto-grow 3→8 lines, Enter submit, Shift+Enter newline
- [x] FR-4: Status Bar — phase name, cost, turns, elapsed, pulsing spinner
- [x] FR-5: TextualUI Adapter — 8-method duck-type, frozen dataclass messages, janus queue bridge
- [x] FR-6: Keybindings — Enter, Shift+Enter, Ctrl+C, Ctrl+L, Escape all wired
- [x] FR-7: Optional Dependency — `tui = ["textual>=0.40", "janus>=1.0"]` in pyproject.toml, lazy import guard
- [x] FR-8: Output Sanitization — all adapter output goes through `sanitize_display_text()`
- [x] All tasks in task file have corresponding implementations
- [x] No TODO/FIXME/placeholder code found

### Quality
- [x] 84 TUI tests pass
- [x] 1687 existing tests pass — zero regressions
- [x] No linter errors in new code
- [x] Code follows existing project conventions (duck-type PhaseUI interface, TOOL_STYLE map reuse, lazy import pattern)
- [x] Only 2 new dependencies (textual, janus) — both well-justified and optional
- [x] No unrelated changes — diff is cleanly scoped

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive database operations
- [x] Error handling present: ImportError fallback with clear install instructions, queue access before mount raises RuntimeError
- [x] Output sanitization prevents terminal escape injection (FR-8)

---

## Findings

- [src/colonyos/cli.py]: The `_launch_tui` function uses `AssistantApp._current_instance` as a class-level mutable singleton to bridge the run callback with the app instance. This works for single-process usage but is a code smell — a closure or passing the queue directly through the callback would be cleaner. Not a blocker for v1.

- [src/colonyos/tui/adapter.py]: Good design decision to use frozen dataclasses as the message protocol. This is the right level of structure — typed enough to catch bugs, simple enough to not over-engineer. The `_try_extract_arg` reuses the existing `TOOL_ARG_KEYS` and `_truncate` from `ui.py` rather than reimplementing, which is correct.

- [src/colonyos/tui/adapter.py]: The `on_text_delta` silently drops text when `_in_tool` is True. This matches `PhaseUI` behavior but means any text the model emits between `on_tool_start` and `on_tool_done` is lost. Worth documenting explicitly even if it's the current contract.

- [src/colonyos/tui/app.py]: The queue consumer loop (`_consume_queue`) is a clean async drain pattern. The `on_unmount` properly cancels the task and closes the queue. The `run_worker(thread=True)` pattern for running the synchronous orchestrator inside Textual's event loop is exactly the right solution — avoids the `asyncio.run()` conflict described in the PRD.

- [src/colonyos/tui/widgets/status_bar.py]: The spinner updates at 100ms intervals via `set_interval(0.1, ...)`. This is fine but means the timer fires even when idle. The `_advance_spinner` early-returns when not running, so cost is negligible, but a more disciplined approach would start/stop the timer with `set_phase`/`set_complete`. Minor.

- [src/colonyos/tui/widgets/status_bar.py]: Reactive watchers (`watch_phase_name`, `watch_is_running`, etc.) each call `_render_bar()`, which means setting multiple reactive attributes in sequence (e.g., in `set_phase`) triggers multiple re-renders. Textual batches these within the same event loop tick, so this is fine in practice, but it's worth knowing if performance debugging is ever needed.

- [src/colonyos/tui/widgets/transcript.py]: The `_looks_like_markdown` heuristic uses a regex to detect headers, bold, lists, and inline code. This is a reasonable 80/20 — renders markdown when it looks like markdown, falls back to plain text otherwise. False positives (e.g., a tool output containing `**`) are harmless since Markdown rendering is still readable.

- [src/colonyos/tui/widgets/composer.py]: The `_ComposerTextArea` subclass intercepts `_on_key` which is an internal Textual method. This is fragile against Textual version upgrades. The alternative (using `on_key` or bindings) may not give enough control, so this is an acceptable tradeoff for v1, but should be watched.

- [tests/tui/]: 84 tests with good coverage: adapter queue contract tests (no Textual needed), Textual pilot tests for widgets, integration tests for the full app, CLI entry point tests, and setup/import guard tests. The `FakeSyncQueue` pattern for testing the adapter without Textual is smart — it means the core logic is testable in CI even if Textual has rendering issues.

- [src/colonyos/tui/adapter.py]: No token-level streaming to the transcript — text accumulates in `_text_buf` and only flushes on `on_turn_complete`. This matches the PRD's explicit decision ("Text appears as buffered blocks on `on_turn_complete`") but means during a long turn, the user sees nothing in the transcript until the turn finishes. The status bar spinner provides the "something is happening" signal, but for v2, streaming partial text (with coalescing/debounce) would significantly improve the feel of liveness.

---

## Synthesis

This is a clean, well-scoped implementation that does exactly what the PRD says and nothing more. The architecture is sound: frozen dataclass messages over a janus queue is the right concurrency bridge — it separates the synchronous orchestrator thread from Textual's async event loop without introducing complex shared state. The adapter reuses existing `TOOL_STYLE` maps and `sanitize_display_text()` rather than reimplementing, which shows good engineering taste.

From an AI engineering perspective, the key question is: are we giving the user enough signal about what the model is doing? v1 answers "yes, minimally" — you see tool calls as they happen, text blocks on turn completion, and cost/turns/elapsed in the status bar. The missing piece is liveness during long turns: if the model is generating a 2000-token response, the user sees a spinner for 10+ seconds with no transcript update. The PRD explicitly defers character streaming to v2, which is the right call for shipping, but it should be the very next iteration.

The test suite is notably strong — 84 tests covering the adapter contract, widget behavior, full app integration, and CLI entry points, all without breaking the existing 1687 tests. The `FakeSyncQueue` pattern for testing the adapter independently of Textual is particularly good practice.

One architectural note: the `_current_instance` singleton pattern in `_launch_tui` is the one piece I'd want cleaned up before v2 adds any complexity. A proper closure or dependency injection would prevent subtle bugs if the app lifecycle gets more complex.

Overall: this ships a real, usable interactive TUI with zero regressions, clean separation from the existing CLI, and a solid test foundation. Approve.

VERDICT: approve

FINDINGS:
- [src/colonyos/cli.py]: `_current_instance` singleton pattern is a code smell — use closure or DI in v2
- [src/colonyos/tui/adapter.py]: Text buffering means no transcript updates during long turns — v2 should add streaming with debounce
- [src/colonyos/tui/adapter.py]: `on_text_delta` drops text inside tool calls — matches existing contract but should be documented
- [src/colonyos/tui/widgets/composer.py]: `_on_key` override is fragile against Textual version changes
- [src/colonyos/tui/widgets/status_bar.py]: Spinner timer runs continuously even when idle (negligible cost, minor inefficiency)

SYNTHESIS:
Clean, minimal, well-tested implementation that correctly bridges the synchronous orchestrator with Textual's async event loop via janus queue and frozen dataclass messages. All 8 PRD functional requirements are met. 84 new tests pass alongside 1687 existing tests with zero regressions. The adapter reuses existing UI infrastructure rather than reimplementing it. The main gap is liveness during long turns (text buffering means no mid-turn transcript updates), which is explicitly deferred to v2 per the PRD. The `_current_instance` singleton in the CLI launcher should be cleaned up before adding complexity. Ship it.
