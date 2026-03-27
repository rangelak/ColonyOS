# Review: Principal Systems Engineer (Round 2) — TUI-Native Auto Mode

**Branch**: `colonyos/add_support_for_auto_inside_the_tui_the_tui_should_be_the_default_colonyos_exper`
**Commit**: `ccc812b` — 1,269 lines across 21 files
**Reviewer**: Principal Systems Engineer (Google/Stripe caliber)
**Date**: 2026-03-27

---

## State Assessment

The branch now has a real implementation commit with substantive code across all five functional requirement areas. The overall architecture is sound — CEO profiles, log writer, scroll fix, transcript export, and the auto-in-TUI loop skeleton are all present. Tests pass (29/29 for the new test files). However, there are several **critical integration gaps** where the building blocks exist but aren't wired together, and the two-tier cancellation behavior has a correctness bug that would cause data loss in production.

---

## Findings

### Critical (blocks ship)

1. **[src/colonyos/tui/app.py:261] Two-tier Ctrl+C is broken — first Ctrl+C exits the TUI immediately**
   FR-1.5 requires: "single Ctrl+C stops the loop after the current iteration completes." The current `action_cancel_run` sets `_stop_event` (correct) but then unconditionally calls `self.exit()` on the *first* press. This means the user never gets graceful between-iteration cancellation — the TUI dies immediately, potentially mid-API-call. The `self.exit()` should only fire on the second press (the `raise SystemExit(1)` path already handles that). For the first press during an auto loop, the method should set the stop event, show the "stopping after current iteration" notice, and return without exiting.

2. **[src/colonyos/cli.py] TranscriptLogWriter is never instantiated — FR-3 integration missing**
   `TranscriptLogWriter` is fully implemented and tested in `log_writer.py`, but it is **never imported or used** in `cli.py`, `app.py`, or anywhere else in the runtime path. Tasks 7.2 ("Instantiate TranscriptLogWriter in _launch_tui and hook it into _consume_queue") and 7.3 ("Ensure properly closed on TUI exit") are marked complete but have zero implementation. Every TUI session should be logging, but no log files are ever created during normal operation.

3. **[src/colonyos/cli.py:5252-5375] No budget or time cap enforcement in TUI auto loop**
   The CLI `auto` command (line ~1870) enforces `effective_max_hours` and `effective_max_budget` with pre- and post-iteration checks. `_run_auto_in_tui` parses only `--loop` and enforces neither. FR-1.2 explicitly requires `--max-hours` and `--max-budget` flags. A user running `auto --loop 50` in the TUI has no budget guardrail — this is a cost-safety issue. The existing patterns from the CLI auto function should be replicated.

### High (should fix before merge)

4. **[src/colonyos/cli.py:5267-5273] `--persona` flag not parsed**
   FR-2.4 requires `auto --persona <name>` to pin a specific CEO profile. `_run_auto_in_tui` only parses `--loop`. The `get_ceo_profile(name=...)` path exists and is tested but is unreachable from the TUI.

5. **[src/colonyos/cli.py:5277] No guard against concurrent auto loops**
   FR-1.7 requires `_run_active` to prevent starting a second auto loop. `_run_auto_in_tui` sets `_auto_loop_active = True` but never checks it (or `_run_active`) before starting. If the user somehow submits "auto" twice before the first iteration begins, two loops run concurrently sharing `current_adapter` — a race condition that would corrupt transcript output and cost tracking.

6. **[src/colonyos/config.py:701] Custom CEO profiles not sanitized on config load**
   Config loading calls `_parse_personas(raw.get("ceo_profiles", []))` which does **not** call `sanitize_display_text`. The dedicated `parse_custom_ceo_profiles()` in `ceo_profiles.py` does sanitize, but it's never called. FR-2.7 requires user-defined profiles to be sanitized against prompt injection. Either `load_config` should call `parse_custom_ceo_profiles` instead of `_parse_personas`, or `_parse_personas` should gain sanitization.

7. **[.gitignore] `.colonyos/logs/` not gitignored**
   FR-3.2 requires `.colonyos/logs/` to be added to `.gitignore` by `colonyos init`. Neither the project `.gitignore` nor the `init` command was updated in this diff. Task 3.4 is marked complete but has no implementation. Users could accidentally commit transcript logs containing secrets.

### Medium (should address)

8. **[src/colonyos/tui/app.py:280-286] Transcript export doesn't set 0o600 permissions**
   `action_export_transcript` uses `Path.write_text()` which inherits the process umask (typically 0o644). This is inconsistent with the log writer's security model where logs are 0o600. On shared machines, exported transcripts could be world-readable. Should use `os.open()` with explicit permissions like `TranscriptLogWriter` does.

9. **[src/colonyos/cli.py:5259] Thread safety on `current_adapter`**
   `current_adapter` is a nonlocal variable written by the worker thread (in both `_run_callback` and `_run_auto_in_tui`) and read by the main thread (in `_inject_callback`). No lock or atomic operation protects it. While the janus queue provides thread-safe message passing, the `current_adapter` assignment itself is a potential data race. In practice CPython's GIL makes simple reference assignments atomic, but this is an implementation detail, not a language guarantee. A `threading.Lock` around `current_adapter` access would be defensive.

10. **[src/colonyos/cli.py:5344-5345] Closure captures loop variable `adapter2`**
    `_ui_factory` is defined inside the loop body and captures `adapter2` by reference. While this works correctly because `run_orchestrator` consumes `_ui_factory` synchronously before the next iteration, it's a fragile pattern. If orchestrator execution ever became async or deferred, this would silently use the wrong adapter. Consider using a default argument (`def _ui_factory(prefix: str = "", _a=adapter2): return _a`) to capture by value.

### Low (nice to have)

11. **[tests/] No integration tests for TUI auto mode**
    Tasks 5.1 and 7.1 reference `tests/tui/test_cli_integration.py` but this file doesn't exist in the diff. The tests that exist cover the building blocks (CEO profiles, log writer, transcript widget) but not the `_run_auto_in_tui` function itself — which is the highest-risk code path in this PR. Even a mock-based test that verifies the iteration loop, stop event handling, and message emission would catch regressions.

12. **[src/colonyos/tui/widgets/transcript.py] `get_plain_text` performance concern**
    `get_plain_text()` creates a new `Console(width=200)` for every line in `self.lines`. For a long auto session (thousands of transcript lines), this could be slow. Consider a single `Console` instance reused across lines.

---

## Checklist Assessment

| Item | Status | Notes |
|------|--------|-------|
| All PRD functional requirements implemented | **Partial** | FR-1.2 (budget/time caps), FR-1.5 (graceful cancel), FR-1.7 (concurrent guard), FR-2.4 (--persona), FR-3.2 (gitignore), FR-3 integration (log writer wiring) are incomplete |
| All tasks marked complete | **Misleading** | Tasks 3.4, 5.5 (partial), 5.7 (buggy), 7.2, 7.3 are marked [x] but not fully implemented |
| No placeholder/TODO code | Pass | No TODOs found |
| Tests pass | **Pass** | 29/29 new tests pass |
| No linter errors introduced | Pass | |
| Follows project conventions | Pass | Code style matches existing patterns |
| No unnecessary dependencies | Pass | No new deps |
| No unrelated changes | Pass | All changes are scoped to the PRD |
| No secrets in committed code | Pass | |
| Error handling present | **Partial** | CEO and orchestrator failures are caught; budget overflow is not |

---

## Synthesis

The implementation demonstrates solid architectural judgment — the CEO profile abstraction is clean, the log writer has the right security properties (0o600, secret redaction, rotation), and the scroll fix correctly addresses the root cause with the `_programmatic_scroll` guard. The code quality of individual components is high.

However, **the integration layer is incomplete**. The log writer was built but never plugged in. The TUI auto loop works for the happy path but lacks the safety rails (budget caps, concurrent-run guards, graceful cancellation) that distinguish a prototype from production code. When I ask "what happens when this fails at 3am?" — a runaway `auto --loop 50` with no budget cap will drain API credits; a first Ctrl+C kills the TUI mid-API-call instead of gracefully stopping; and there's no log file to debug what happened because the writer was never wired in.

The fix list is well-scoped: wire in the log writer, replicate budget/time enforcement from CLI auto, fix Ctrl+C to not exit on first press during auto loops, add the `--persona` flag parsing, use `parse_custom_ceo_profiles` in config loading, and update `.gitignore`. These are integration tasks, not redesigns — the building blocks are all there.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/tui/app.py:261]: Two-tier Ctrl+C broken — first press exits TUI instead of gracefully stopping auto loop between iterations
- [src/colonyos/cli.py]: TranscriptLogWriter never instantiated — FR-3 log persistence integration is completely missing
- [src/colonyos/cli.py:5252-5375]: No budget or time cap enforcement in TUI auto loop — cost safety gap
- [src/colonyos/cli.py:5267-5273]: `--persona` flag not parsed — FR-2.4 unreachable from TUI
- [src/colonyos/cli.py:5277]: No concurrent auto loop guard — FR-1.7 race condition
- [src/colonyos/config.py:701]: Custom CEO profiles loaded without sanitize_display_text — prompt injection risk (FR-2.7)
- [.gitignore]: `.colonyos/logs/` not added to gitignore or `colonyos init` — FR-3.2 missing
- [src/colonyos/tui/app.py:280-286]: Transcript export uses default umask instead of 0o600 permissions
- [src/colonyos/cli.py:5259]: `current_adapter` accessed cross-thread without lock
- [tests/]: No integration tests for `_run_auto_in_tui` despite being highest-risk code path

SYNTHESIS:
The building blocks are well-crafted — CEO profiles, log writer, scroll fix, and transcript export are individually sound with good test coverage. But the integration layer that makes these a cohesive feature has critical gaps: the log writer is built but never plugged in, the auto loop lacks budget enforcement (a cost-safety issue), and the two-tier Ctrl+C exits immediately instead of gracefully stopping. These are wiring problems, not design problems — the architecture is right, the last mile of integration needs completion. I'd estimate 2-3 hours of focused work to close all findings.
