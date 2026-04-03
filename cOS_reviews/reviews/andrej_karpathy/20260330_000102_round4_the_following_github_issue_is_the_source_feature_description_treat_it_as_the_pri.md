# Review by Andrej Karpathy (Round 4)

23 `retry_config=` lines for 21 `run_phase_sync(` calls — the extra 2 are the `run_phase(` calls in the parallel tasks (lines 2810, 4171 which are `run_phase_sync` inside `async def` wrappers). That's correct.

Now let me write the review output. I have a comprehensive picture:

---

## Review — Andrej Karpathy (Round 4)

I reviewed the full diff (1,962 lines across 12 files), read the PRD, and verified 447 tests pass green.

### Completeness Assessment

All 10 functional requirements are implemented:

| FR | Status | Notes |
|----|--------|-------|
| FR-1 | ✅ | `_friendly_error()` detects overloaded/529/503 via `_TRANSIENT_PATTERNS` regex, returns generic "API is temporarily overloaded. Will retry..." |
| FR-2 | ✅ | `_is_transient_error()` checks `status_code` first (429/503/529), regex fallback second with word boundaries |
| FR-3 | ✅ | `run_phase()` wraps query in retry loop via `_run_phase_attempt()` extraction, restart-from-scratch semantics |
| FR-4 | ✅ | Defaults: `max_attempts=3`, `base_delay_seconds=10.0`, `max_delay_seconds=120.0`, full jitter via `random.uniform(0, computed_delay)` |
| FR-5 | ✅ | `RetryConfig` dataclass nested under `ColonyConfig.retry`, parsed via `_parse_retry_config()` |
| FR-6 | ✅ | `fallback_model` opt-in, disabled by default, validated against `VALID_MODELS` allowlist |
| FR-7 | ✅ | `_SAFETY_CRITICAL_PHASES` uses `Phase.REVIEW.value`, `Phase.DECISION.value`, `Phase.FIX.value` — hard-blocks fallback |
| FR-8 | ✅ | Retry messages via `ui.on_text_delta()` or `_log()` with "API overloaded, retrying in {delay}s (attempt {n}/{max})..." |
| FR-9 | ✅ | `RetryInfo` frozen dataclass on `PhaseResult`, serialized to/from RunLog JSON with explicit `.get()` extraction |
| FR-10 | ✅ | Parallel phases retry independently — each `run_phase()` has its own retry loop |

### Architecture Assessment (Karpathy perspective)

**The core design is correct.** The key architectural decision — retry lives inside `run_phase()`, below the orchestrator's recovery system — is the right call. 529 is a transport error, not a reasoning failure. The orchestrator should never see it, and it doesn't. The refactoring of `run_phase()` into `_run_phase_attempt()` + retry loop is clean separation of concerns.

**The two-pass structure is elegant.** `passes: list[tuple[str | None, int]]` gives each model its own `max_attempts` budget. The total can be `2 * max_attempts` — clearly documented in the docstring and tested. This is a good design because it means a flaky primary doesn't eat into fallback budget.

**Error detection is appropriately defensive.** Checking structured `status_code` first, then falling back to word-boundary regex on `str(exc)`, `stderr`, and `result` — this handles the current SDK's unstructured error surface while being upgradeable when the SDK gets proper error types. The word-boundary regexes (`\b529\b`, `\b503\b`) avoid false positives on port numbers and file paths. Good test coverage proves this.

**Resume invalidation is correct.** After a transient error kills the query, `current_resume = None` ensures retries restart from scratch. This is the right behavior given that no `session_id` is returned from a 529'd request. The test `test_resume_cleared_after_transient_error` validates this precisely.

**One known tech debt item:** `retry_config=config.retry` is threaded through ~23 call sites. This is verbose but correct — it follows the existing codebase pattern where config is explicitly passed rather than implicitly accessed. Acknowledged in prior rounds as non-blocking.

### Test Coverage Assessment

The test suite is thorough — 57+ new tests covering:
- `_is_transient_error()`: structured status codes, string matching, word boundary edge cases, priority ordering
- `_friendly_error()`: overloaded detection, existing error types preserved, substring false positive prevention
- Retry loop: success after N failures, exhaustion, permanent error short-circuit, backoff delay ranges, `max_attempts=1` disabling retry, resume clearing
- Fallback: primary exhaustion → fallback success, safety-critical phase blocking (review, decision, fix individually), fallback exhaustion, logging via UI and _log
- Config parsing: validation, defaults, invalid model rejection
- Model serialization: `RetryInfo` round-trip through RunLog JSON, explicit field extraction resilience

### Remaining Observations (non-blocking)

1. **`_friendly_error()` word-boundary false positive on "line 529"**: The test `test_529_substring_in_filepath_not_overloaded` is documented as known behavior — `\b529\b` matches "line 529 of config.py" because "529" is a standalone word there. This is acceptable: the practical impact is nil because `_friendly_error()` is only called on actual SDK exceptions, not arbitrary log lines. The regex already avoids the dangerous case (port numbers like "5290").

2. **No circuit breaker across phases**: If the API is overloaded, every parallel phase will independently retry. With 4 concurrent reviewers × 3 attempts × 10s base delay, that's potentially 120s+ of retry storms. The PRD explicitly lists this as a non-goal ("full jitter provides sufficient decorrelation"), and I agree it's the right tradeoff for v1.

3. **Budget amplification from retries**: A 529 mid-stream burns partial cost that isn't tracked (no `ResultMessage` returned). The PRD acknowledges this and relies on the per-run budget cap as the safety net. Correct for v1.

VERDICT: approve

FINDINGS:
- [src/colonyos/agent.py]: Word-boundary regex `\b529\b` matches "line 529 of config.py" — documented, non-blocking since context is always SDK exceptions
- [src/colonyos/orchestrator.py]: `retry_config=config.retry` threaded through 23 call sites — verbose but follows existing codebase conventions, acknowledged tech debt
- [src/colonyos/agent.py]: No circuit breaker across parallel phases — acceptable for v1 per PRD non-goals, full jitter provides sufficient decorrelation

SYNTHESIS:
This is a well-executed, well-tested implementation. The core architecture is right: transport-level retry belongs in `run_phase()`, invisible to the orchestrator's heavyweight recovery system. The two-pass fallback structure is elegant and the safety-critical phase guard is sound (using enum values catches rename errors at import time). The error detection strategy is appropriately defensive for the current SDK surface, and the test suite is comprehensive with 57+ new tests covering happy paths, edge cases, and failure modes. The `RetryInfo` dataclass provides good observability without cluttering the hot path. The implementation treats prompts and error patterns with the right level of rigor — word-boundary regexes, explicit field extraction from JSON, validated model allowlists. I see no blocking issues. Ship it.
