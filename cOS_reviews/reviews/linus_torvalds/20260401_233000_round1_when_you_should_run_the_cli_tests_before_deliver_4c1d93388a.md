# Review — Linus Torvalds, Round 1

**Branch**: `colonyos/when_you_should_run_the_cli_tests_before_deliver_4c1d93388a`
**PRD**: `cOS_prds/20260401_224904_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## Completeness

| Requirement | Status | Notes |
|---|---|---|
| FR-1: Verify phase in main pipeline | ✅ | Between Learn and Deliver, read-only tools enforced |
| FR-2: Verify-fix loop | ✅ | Two-agent pattern, up to `max_fix_attempts` retries |
| FR-3: Hard-block on persistent failure | ✅ | `_fail_run_log()` prevents delivery |
| FR-4: Budget guard | ✅ | Before verify AND before fix, matching review loop |
| FR-5: Config integration | ✅ | `PhasesConfig.verify`, `VerifyConfig`, DEFAULTS, load/save roundtrip |
| FR-6: Instruction templates | ✅ | `verify.md` + `verify_fix.md` with structured sentinel |
| FR-7: Resume support | ✅ | `_compute_next_phase` and `_SKIP_MAP` updated |
| FR-8: Heartbeat + UI | ✅ | `_touch_heartbeat()` + phase header |
| FR-9: Thread-fix unchanged | ✅ | No modifications to thread-fix flow |
| PRD: Safety-critical phases | ❌ | `Phase.VERIFY` NOT added to `_SAFETY_CRITICAL_PHASES` (PRD line 79 explicitly requires this) |

## Quality

- All 222 verify-related tests pass (0 failures)
- Full test suite: 3110 tests pass
- No linter errors observed
- Code follows existing patterns (budget guard, heartbeat, phase append, UI header)
- No unnecessary dependencies
- No unrelated changes

## Safety

- No secrets or credentials
- `_fail_run_log()` hard-blocks delivery on persistent failure
- Error handling present for fix agent failure (`fix_result.success` check)
- Budget guards prevent runaway costs

## Findings

### Missing: `_SAFETY_CRITICAL_PHASES` update (non-blocking)

The PRD section "Safety-Critical Phase" (line 79) explicitly states:

> The verify-fix agent should be added to `_SAFETY_CRITICAL_PHASES` (config.py line 25) to prevent model fallback during fix iterations, consistent with the review/fix phases.

The current `_SAFETY_CRITICAL_PHASES` is:
```python
_SAFETY_CRITICAL_PHASES: frozenset[str] = frozenset(
    {Phase.REVIEW.value, Phase.DECISION.value, Phase.FIX.value}
)
```

`Phase.VERIFY` is **not** added. This means if someone configures `phase_models.verify: haiku`, the safety warning won't fire. However, the verify agent is read-only (just runs tests), so the actual risk is minimal — the dangerous phase is FIX, which is already covered. I'll note this as a gap but won't block on it.

### `Phase.FIX` reuse (accepted trade-off)

The verify-fix agent reuses `Phase.FIX` rather than introducing a new `Phase.VERIFY_FIX`. This means you can't distinguish review-fix from verify-fix by enum alone in the run log. However, phase ordering disambiguates, and introducing a new enum would ripple across the codebase for zero functional benefit. This is the right call.

### Fail-open on ambiguous output (accepted trade-off)

`_verify_detected_failures()` returns `False` (tests passed) when output is unrecognizable. The structured sentinel makes this window narrow, and the alternative (fail-closed blocking delivery on every ambiguous output) would be far worse in practice.

### No haiku default for verify (noted, non-blocking)

PRD section "Model Selection" suggests verify should default to haiku since it's read-only. The implementation inherits the global model. This is fine for v1 — correctness over cost optimization.

## Assessment

The implementation is correct, complete where it matters, and follows the existing codebase patterns without inventing new abstractions. The data structures are simple — `VerifyConfig` is a single-field dataclass, the loop is a straightforward `for` with two break conditions, and the sentinel parsing has a clean fallback chain. The test coverage is thorough: 16 unit tests for the parsing boundary, 6 pipeline tests for the verify loop, 4 integration tests for end-to-end behavior, plus config roundtrip tests.

The one explicit PRD requirement that's missing (`_SAFETY_CRITICAL_PHASES`) is genuinely low-risk since VERIFY is read-only and FIX (the dangerous phase) is already in the set. I won't block on it, but it should be noted.

Ship it.

VERDICT: approve

FINDINGS:
- [src/colonyos/config.py]: `Phase.VERIFY` not added to `_SAFETY_CRITICAL_PHASES` — PRD line 79 explicitly requires this. Low-risk since verify is read-only, but it's a stated requirement gap.
- [src/colonyos/orchestrator.py]: `Phase.FIX` reused for verify-fix agent — acceptable trade-off, phase ordering disambiguates.
- [src/colonyos/orchestrator.py]: `_verify_detected_failures()` fail-open on ambiguous output — correct design choice; sentinel narrows the window.

SYNTHESIS:
The implementation is correct, complete, and follows existing patterns without inventing new abstractions. The verify-fix loop is a clean copy of the review-fix loop pattern with proper budget guards, heartbeat touches, and hard-block on exhausted retries. The sentinel-based parsing of test output is the right approach — treat the prompt as a typed function with a parseable return value, then fall back to heuristics. Test coverage is excellent at 64+ tests covering the parsing boundary, pipeline integration, and config roundtrip. The single gap (`_SAFETY_CRITICAL_PHASES`) is low-risk and non-blocking. Ship it.
