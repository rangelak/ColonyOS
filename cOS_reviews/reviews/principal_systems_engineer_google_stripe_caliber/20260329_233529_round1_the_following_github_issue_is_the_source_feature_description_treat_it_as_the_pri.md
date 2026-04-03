# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

Now I have everything I need. Here is my review:

---

## Review — Principal Systems Engineer (Google/Stripe caliber)

### Completeness Assessment

| FR | Status | Notes |
|----|--------|-------|
| FR-1 | ✅ | `_friendly_error()` updated with `"overloaded"` and `"529"` pattern matching |
| FR-2 | ✅ | `_is_transient_error()` checks `status_code` first (429/503/529), falls back to string matching on `str(exc)`, `exc.stderr`, `exc.result` |
| FR-3 | ✅ | Retry loop wraps `query()` in `run_phase()` with restart-from-scratch semantics |
| FR-4 | ✅ | Defaults: `max_attempts=3`, `base_delay_seconds=10.0`, `max_delay_seconds=120.0`, full jitter via `random.uniform(0, computed_delay)` |
| FR-5 | ✅ | `RetryConfig` dataclass in `config.py`, nested under `ColonyConfig.retry`, parsed via `_parse_retry_config()`, added to `DEFAULTS` |
| FR-6 | ✅ | `fallback_model: str | None` on `RetryConfig`, two-pass loop architecture (primary → fallback) |
| FR-7 | ✅ | Fallback hard-blocked for `_SAFETY_CRITICAL_PHASES` (`review`, `decision`, `fix`) — tested for all three |
| FR-8 | ✅ | Retry messages via `ui.on_text_delta()` or `_log()`, with clear format: `"API overloaded, retrying in {delay:.0f}s (attempt {n}/{max})..."` |
| FR-9 | ✅ | `retry_info: dict[str, Any] | None` on `PhaseResult`, serialized/deserialized in `_save_run_log`/`_load_run_log` |
| FR-10 | ✅ | Each parallel phase retries independently via its own `run_phase()` call — no cross-phase coordination |

### Quality Assessment

**All 434 tests pass.** The test suite adds ~1,150 lines covering:
- `_is_transient_error()`: 12 tests (structured attrs, string fallback, negative cases)
- `_friendly_error()` 529 handling: 6 tests (new patterns + regression checks for existing patterns)
- Retry loop: 9 tests (success-after-retry, exhaustion, permanent-no-retry, backoff range validation, UI/log messaging, max_attempts=1 disables)
- Fallback: 8 tests (success after primary exhaustion, blocked on all 3 safety-critical phases, None fallback, double exhaustion, logging)
- Config parsing: 10 tests (defaults, YAML override, partial override, validation errors, all valid models)
- Models: 7 tests (retry_info serialization round-trips, backward compat)
- Orchestrator wiring: 4 integration tests (config flows to all call sites, retry_info in RunLog, recovery not triggered on internal retry success)

**Config validation is thorough.** `_parse_retry_config()` validates: `max_attempts >= 1`, delays non-negative, `fallback_model` in `VALID_MODELS`. Good — bad config fails fast at load time, not at 3am mid-run.

**Orchestrator wiring is comprehensive.** 23 `retry_config=config.retry` additions across all `run_phase_sync` call sites. The integration test explicitly asserts every `run_phase_sync` call receives the config.

### Findings

VERDICT: approve

FINDINGS:
- [.colonyos/daemon_state.json]: **Unrelated file committed.** This is runtime daemon state (daily spend tracking, heartbeat timestamps) that should never be in version control. It's not in `.gitignore` and belongs there. Remove from this branch before merge.
- [src/colonyos/agent.py]: **`_TRANSIENT_PATTERNS` allocated inside hot path.** The tuple `("overloaded", "529", "503")` is re-created on every call to `_is_transient_error()`. Move to module-level constant. Cosmetic — no functional impact.
- [src/colonyos/agent.py]: **`for/else` control flow is subtle.** The two-pass retry loop uses `for/else` with `continue` on both the inner `else` and post-inner-loop `continue` (lines ~310-315). The trailing `# Inner loop was broken out of` comments help, but this is the most complex control flow in the file. A `_retry_with_backoff()` extraction would improve readability but is not a blocker.
- [src/colonyos/agent.py]: **String "503" in `_is_transient_error` may false-positive.** An error message containing "503" as part of a port number or unrelated text would match. Low risk in practice since these are API errors, but worth noting.
- [src/colonyos/agent.py]: **No test for mid-stream 529.** All tests simulate 529 before `query()` yields any messages. A 529 that kills the generator *after* partial streaming (some `StreamEvent`s yielded, then exception) is not tested. The code handles it correctly (the try/except wraps the entire `async for`), but an explicit test would document this contract.
- [src/colonyos/models.py]: **`retry_info` typed as `dict[str, Any]` rather than a dataclass.** The schema is well-defined (attempts, transient_errors, fallback_model_used, total_retry_delay_seconds) and would benefit from a typed structure. Acceptable for v1 given it flows cleanly through JSON serialization.

SYNTHESIS:
This is a clean, well-scoped implementation that does exactly what the PRD specifies — no more, no less. The architecture decision to place retry inside `run_phase()` below the orchestrator's recovery system is correct: transient transport errors are resolved transparently, and the heavyweight diagnostic/nuke recovery is never triggered for API hiccups. The two-pass (primary → fallback) loop is the most complex piece, and while the nested `for/else` is harder to read than I'd like, it's functionally correct and thoroughly tested. Config validation fails fast with clear messages. The 23 orchestrator wiring points are all covered by integration tests that assert the config actually flows through. The only actionable issue is the `daemon_state.json` file that shouldn't be in the diff — remove it (and add `.colonyos/daemon_state.json` to `.gitignore`). Everything else is polish-level. Ship it.
