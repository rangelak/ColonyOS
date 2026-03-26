# Review: Principal Systems Engineer (Google/Stripe caliber)

**Branch:** `colonyos/implement_the_latest_prd_tasks_file`
**PRDs Covered:** TUI Interactive Terminal UI, TUI Default Mode / UX Fixes / Smart Routing, `colonyos sweep` Autonomous Quality Agent
**Reviewer Perspective:** Distributed systems, API design, reliability, observability

---

## Checklist Assessment

### Completeness
- [x] TUI entry point (`colonyos tui`, `colonyos run --tui`) — implemented
- [x] TranscriptView with scrollable RichLog, auto-scroll — implemented
- [x] Composer with multi-line input, Enter/Shift+Enter — implemented
- [x] StatusBar with phase/cost/turns/elapsed — implemented
- [x] TextualUI adapter bridging orchestrator to Textual — implemented
- [x] Optional `[tui]` dependency group — implemented
- [x] Output sanitization — implemented and hardened
- [x] TUI as default for interactive TTY — implemented with `_interactive_stdio()` + `_tui_available()` gating
- [x] `--no-tui` escape hatch — implemented
- [x] Ctrl+C cancellation with double-press force-exit — implemented
- [x] Smart routing with complexity classification (trivial/small/large) — implemented
- [x] Skip-planning fast path for small fixes — implemented via `_write_fast_path_artifacts()`
- [x] Mid-run user input injection — implemented via janus queue + `_drain_injected_context()`
- [x] `colonyos sweep` command with dry-run/execute/plan-only — implemented
- [x] Phase.SWEEP enum with read-only tools — implemented
- [x] SweepConfig dataclass — implemented
- [x] Preflight dirty-worktree recovery — implemented (bonus, beyond PRD scope)
- [x] No TODO/FIXME/placeholder code in shipped source

### Quality
- [x] All 1898 tests pass
- [x] Code follows existing project conventions (Click commands, dataclasses, PhaseUI duck-type pattern)
- [x] No unnecessary dependencies (textual, janus are optional; no new required deps)
- [x] No unrelated changes included

### Safety
- [x] No secrets or credentials in committed code
- [x] Secret-like path detection in preflight recovery (`_is_secret_like_path()`) — good safety gate
- [x] Sanitization hardened: ANSI escape regex expanded, control characters stripped, carriage return overwrite attack mitigated
- [x] Sweep analysis phase restricted to read-only tools (Read, Glob, Grep)
- [x] Review phase never skipped regardless of complexity classification

---

## Findings

### Thread Safety (Medium Severity)

- **[src/colonyos/tui/app.py]**: `_run_active` flag is read/written from both the Textual main thread (lines 195, 199, 225, 298) and the worker thread (line 330 via `call_from_thread`). No lock protects it. In practice, `call_from_thread` marshals the write to the main thread, so the race window is narrow — but if `action_cancel_run()` fires between `_start_run()` setting `True` and the worker completing, you could see a stale read. **Low blast radius** (worst case: a notice message appears instead of accepting input), but a `threading.Event` would be cleaner.

- **[src/colonyos/tui/adapter.py]**: `_text_buf`, `_tool_json`, `_in_tool` are mutable state on the adapter, written by orchestrator thread callbacks and read for queue dispatch. This works under CPython's GIL but is technically a data race under free-threaded Python (PEP 703). **Acceptable for now** given the single-writer pattern.

### Error Handling (Low Severity)

- **[src/colonyos/tui/app.py:316-324]**: `_run_with_lifecycle` catches all `Exception` and shows it in the UI, which is correct. However, `call_from_thread()` in the `finally` block (line 326) can itself raise `RuntimeError` if the app is already unmounting. A bare `try/except` around the finally-block `call_from_thread` would prevent a noisy traceback on rapid Ctrl+C → exit.

- **[src/colonyos/tui/app.py:213-228]**: `action_cancel_run()` calls `self.exit()` synchronously. If the worker thread is mid-`call_from_thread`, the app teardown and the worker's `call_from_thread` could race. Textual likely handles this, but it's worth noting.

### Architecture (Observation, Not Blocking)

- **[src/colonyos/router.py]**: Two parallel classification systems now exist — `route_query()` (intent + complexity) and `choose_tui_mode()` (mode selection). Both invoke an LLM. In the TUI flow, `choose_tui_mode()` is the primary dispatcher and `route_query()` is used in the non-TUI REPL path. This duality is fine for now but should be unified if the non-TUI path is deprecated.

- **[src/colonyos/orchestrator.py]**: `run_sweep()` catches `Exception` broadly when calling `scan_directory()` for bootstrap context. The comment says "Non-critical" which is fair — but narrowing to `(ImportError, OSError, ValueError)` would prevent masking unexpected failures.

### Sanitization (Low Severity)

- **[src/colonyos/tui/adapter.py + transcript.py]**: CommandOutputMsg is NOT sanitized at the adapter level — sanitization is deferred to transcript's `append_command_output()`. All other message types are sanitized in the adapter. This split responsibility means if a new consumer of the queue is added without sanitizing CommandOutputMsg, unsanitized terminal output could reach display. Consider sanitizing in the adapter for defense-in-depth.

- **[src/colonyos/tui/widgets/transcript.py]**: Text blocks are pre-sanitized in the adapter, then optionally passed through `Markdown()` for rich rendering. The Markdown parser could theoretically reinterpret sequences that were safe as plain text but meaningful as Markdown. **Very low risk** in practice since `sanitize_display_text()` strips control sequences, not Markdown syntax.

### Test Coverage (Observation)

- **[tests/test_cli.py:2773-2780]**: Two sweep CLI tests are conditionally skipped with `pytest.skip("sweep CLI command not yet registered")`. These should be un-skipped now that the command is registered.

- **[tests/tui/]**: Comprehensive test suite (adapter, app, widgets, CLI integration) with proper skip guards for optional TUI dependencies. Good pattern.

---

## VERDICT: approve

## FINDINGS:
- [src/colonyos/tui/app.py]: `_run_active` flag accessed from multiple threads without synchronization — low blast radius but should use threading.Event for correctness
- [src/colonyos/tui/app.py:326]: `call_from_thread()` in finally block can raise RuntimeError during app teardown — wrap in try/except
- [src/colonyos/tui/adapter.py]: CommandOutputMsg not sanitized at adapter level — split responsibility creates future risk
- [src/colonyos/router.py]: Two parallel LLM classification systems (route_query + choose_tui_mode) — document intended lifecycle
- [tests/test_cli.py:2773-2780]: Two sweep CLI tests still conditionally skipped despite command being registered

## SYNTHESIS:
This is a substantial, well-executed implementation covering three PRDs (TUI, TUI-as-default with smart routing, and sweep). The architecture follows established patterns — the TextualUI adapter cleanly implements the existing PhaseUI duck-type contract, the janus queue provides a correct async-sync bridge, and the sweep command reuses the existing pipeline. All 1898 tests pass. The thread safety concerns around `_run_active` are real but low-impact given the single-writer-via-`call_from_thread` pattern; the worst case is a cosmetic UI glitch, not data corruption or lost work. Sanitization coverage is thorough — the ANSI regex hardening and carriage return attack mitigation show good security awareness. The two skipped sweep CLI tests are a minor loose end. The dual routing system (route_query vs choose_tui_mode) adds conceptual weight but is justified by the different entry points (REPL vs TUI). Overall, this is production-ready code with the right trade-offs for a v1 ship. The findings above are hardening improvements, not blockers.
