# Review — Linus Torvalds, Round 1

## Summary

I read the PRD, reviewed the full git diff (1793 lines across 19 files), and ran the 55 verify-specific tests (all pass). Here's my assessment.

### Completeness

All 9 functional requirements from the PRD are implemented:

| Requirement | Status | Evidence |
|-------------|--------|----------|
| FR-1: Verify phase in main pipeline | Done | `_run_pipeline()` inserts verify between Learn and Deliver with read-only tools |
| FR-2: Verify-fix loop | Done | Loop in orchestrator runs up to `max_fix_attempts + 1` iterations |
| FR-3: Hard-block delivery | Done | `_fail_run_log()` + `return log` when `verify_passed` is False |
| FR-4: Budget guard | Done | Dual budget checks — before verify AND before fix |
| FR-5: Config integration | Done | `PhasesConfig.verify`, `VerifyConfig`, `_parse_verify_config()`, validation |
| FR-6: Instruction templates | Done | `verify.md` (read-only) and `verify_fix.md` (write-enabled) |
| FR-7: Resume support | Done | `_compute_next_phase()` updated: decision→verify, learn→verify, verify→deliver |
| FR-8: Heartbeat + UI | Done | `_touch_heartbeat()` before verify, `phase_header()` display |
| FR-9: Thread-fix unchanged | Done | No modifications to existing thread-fix flow |

### Code Quality

The implementation is straightforward and follows existing patterns. No clever tricks, no premature abstractions. Let me go through what matters:

**`_verify_detected_failures()`** — This is the critical decision function. The data structure is right: primary sentinel parsing (`VERIFY_RESULT: PASS/FAIL`) with regex fallback for non-zero failure counts. The `\b[1-9]\d*\s+(?:failed|failures?|errors?)\b` regex correctly avoids the `0 failed` false-positive trap. 16 unit tests cover the edge cases. The fail-open default (ambiguous → assume pass) is the correct choice — you don't block delivery on parser bugs.

**The verify loop** — Clean control flow. `for attempt in range(max_fix_attempts + 1)` gives you initial verify + N fix-then-reverify iterations. Budget guard at the top of each iteration AND before each fix. Early break on success. The fix agent reuses `Phase.FIX` which inherits safety-critical status automatically — this is pragmatic, not a hack.

**Config** — `VerifyConfig` is a simple dataclass with validation (`max_fix_attempts >= 1`). `_parse_verify_config()` follows the identical pattern as every other config parser in the file. `save_config()` only writes non-default values. No surprises.

**Resume chain** — The `_SKIP_MAP` and `_compute_next_phase()` updates are correct. `learn → verify → deliver` is the right insertion point. The `verify` skip set includes itself (preventing infinite loops on resume).

**Templates** — `verify.md` is a well-structured prompt: discover → run → emit sentinel. Explicitly forbids modification. `verify_fix.md` receives `{test_failure_output}` as structured context and includes clear rules (fix code not tests, no skipping, no suppression). Both are separate from the thread-fix template, which is the right call.

### What I'd nitpick

1. **`Phase.FIX` reuse for verify-fix**: The audit trail shows `Phase.FIX` for both review-fix and verify-fix. If you're debugging a run log, you can't immediately tell which fix is which without looking at ordering. A `Phase.VERIFY_FIX` enum value would be cleaner — but that's a v2 concern, not a blocker for shipping.

2. **No haiku default for `Phase.VERIFY`**: The PRD explicitly says "The verify agent (read-only test execution) should default to a cheaper model (haiku)." The implementation lets users configure it via `phase_models.verify: haiku` but doesn't set it by default. This is the right call for correctness — you don't want to ship a degraded default and discover haiku can't find `pyproject.toml` — but it's worth noting the deviation from the PRD.

3. **`verify_fix.md` receives raw test output without sanitization**: The `{test_failure_output}` placeholder gets whatever the verify agent spit out, interpolated directly into the system prompt. This is fine because it's the user's own repo content and follows the existing threat model, but it's worth calling out.

None of these are blocking.

### Tests

55 tests pass. The test suite is thorough:
- 16 unit tests for `_verify_detected_failures()` covering sentinels, fallback regexes, false positives, edge cases
- 6 pipeline integration tests (pass, fix-then-pass, exhaust-retries, budget-guard, disabled, heartbeat)
- 4 end-to-end integration tests (full pipeline variations including resume)
- 13 instruction template validation tests
- 12 config tests (defaults, parsing, validation, roundtrip)
- Updates to all existing tests that mock the pipeline sequence

The existing 3110 tests also pass with zero regressions.

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py]: `_verify_detected_failures()` implements correct sentinel → regex fallback parsing with fail-open default; 16 unit tests cover the decision boundary
- [src/colonyos/orchestrator.py]: Verify loop control flow is clean — dual budget guards, early break on success, `Phase.FIX` reuse inherits safety-critical status automatically
- [src/colonyos/orchestrator.py]: `Phase.FIX` reuse for verify-fix limits audit granularity (can't distinguish review-fix from verify-fix in logs without checking order) — acceptable for v1
- [src/colonyos/config.py]: `_parse_verify_config()` validates `max_fix_attempts >= 1` and follows existing parser patterns exactly
- [src/colonyos/config.py]: No haiku default for `Phase.VERIFY` despite PRD suggestion — correct design choice for reliability
- [src/colonyos/instructions/verify.md]: Clean separation of concerns — discover, run, emit sentinel; explicitly forbids code modification
- [src/colonyos/instructions/verify_fix.md]: Raw `{test_failure_output}` interpolated without sanitization — accepted risk per existing threat model
- [src/colonyos/orchestrator.py]: Resume chain correctly updated: `learn → verify → deliver` with proper `_SKIP_MAP` entries
- [tests/test_verify_phase.py]: 621 lines of comprehensive tests covering all critical paths including budget exhaustion and resume scenarios

SYNTHESIS:
This is a clean, well-structured implementation that does exactly what it says on the tin. The data structures are right — sentinel-based output parsing with regex fallback, a simple loop with budget guards at both entry points, and config that validates its invariants. No unnecessary abstractions, no clever hacks, no commented-out code. The two-agent separation (read-only verify, write-enabled fix) preserves audit boundaries. The 55 new tests cover all the critical paths including the tricky ones (budget exhaustion mid-loop, resume from failed verify, `0 failed` false-positive avoidance). Ship it.
