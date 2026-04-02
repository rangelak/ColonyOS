# Review — Principal Systems Engineer, Round 1

**Branch**: `colonyos/when_you_should_run_the_cli_tests_before_deliver_4c1d93388a`
**PRD**: `cOS_prds/20260401_224904_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## FR Coverage

| Requirement | Status | Evidence |
|------------|--------|---------|
| FR-1: Verify phase in main pipeline | ✅ | Inserted between Learn and Deliver in `_run_pipeline()`. Read-only tools `["Read", "Bash", "Glob", "Grep"]` enforced at runtime. |
| FR-2: Verify-fix loop | ✅ | Loop runs `max_fix_attempts + 1` iterations (initial verify + N fix-then-reverify cycles). Fix agent uses `Phase.FIX` with full tool access. |
| FR-3: Hard-block delivery | ✅ | `_fail_run_log()` + `return log` when `verify_passed is False`. 3 integration tests confirm `Phase.DELIVER not in phase_types`. |
| FR-4: Budget guard | ✅ | Dual budget checks: before verify AND before fix. Pattern matches review loop exactly. |
| FR-5: Config integration | ✅ | `PhasesConfig.verify: bool = True`, `VerifyConfig(max_fix_attempts=2)`, DEFAULTS updated, `_parse_verify_config()` validates `>= 1`. |
| FR-6: Instruction templates | ✅ | `verify.md` (read-only, sentinel contract) and `verify_fix.md` (write-enabled, receives `{test_failure_output}`). |
| FR-7: Resume support | ✅ | `_compute_next_phase()` updated: `decision → verify`, `learn → verify`, `verify → deliver`. `_SKIP_MAP` updated. Integration test covers resume from failed verify. |
| FR-8: Heartbeat + UI | ✅ | `_touch_heartbeat()` called before verify. `phase_header()` / `_log()` fallback. Test confirms heartbeat file exists. |
| FR-9: Thread-fix unchanged | ✅ | No diff touches thread-fix code paths. |

## Reliability & Failure Mode Analysis

### What happens at 3am?

1. **Verify agent hangs or exceeds timeout**: `timeout_seconds=config.budget.phase_timeout_seconds` is passed to `run_phase_sync`, consistent with all other phases. The watchdog heartbeat is touched before entry. ✅

2. **Verify agent produces garbage output (no sentinel)**: `_verify_detected_failures()` falls through all regex checks and returns `False` (fail-open). This is the correct default — better to ship a PR that might fail CI than to block delivery on a malformed agent response. The sentinel makes the ambiguous case narrow in practice. ✅

3. **Fix agent crashes mid-loop**: `fix_result.success` check exits the loop gracefully → `verify_passed` remains `False` → delivery blocked. ✅

4. **Budget exhaustion mid-loop**: Dual guards catch this before both verify and fix iterations. Cost accumulation uses the same `sum(p.cost_usd)` pattern as the review loop. ✅

5. **Resume after verify failure**: `_compute_next_phase("learn") → "verify"` correctly routes resumed runs. The `_SKIP_MAP["learn"]` skips `{plan, implement, review}` so the pipeline doesn't re-run expensive phases. ✅

### Race conditions?

None introduced. The verify loop is single-threaded within `_run_pipeline()`, same as the review-fix loop. No shared mutable state between verify and fix agents.

### Blast radius of a bad agent session?

Limited to the verify-fix loop. If verify produces a false negative (claims tests pass when they fail), the existing CI Fix phase catches environment-specific failures post-delivery. If verify produces a false positive (claims tests fail when they pass), the loop either self-corrects on re-verify or blocks delivery after exhausting retries — annoying but safe.

## API Surface

- **Config**: `VerifyConfig` is minimal (single field), `PhasesConfig.verify` is a boolean toggle. Clean, composable. No unnecessary knobs.
- **`_verify_detected_failures()`**: Well-designed decision function. Primary sentinel parsing, regex fallback, fail-open default. 16 unit tests cover edge cases including the critical "0 failed" false-positive scenario.
- **`_build_verify_prompt()` / `_build_verify_fix_prompt()`**: Follow the exact same signature pattern as `_build_fix_prompt()` and `_build_ci_fix_prompt()`. No API surface bloat.

## Observability / Debuggability

- Each verify and fix iteration produces a separate `PhaseResult` appended to the run log. You can reconstruct the full timeline: observe → fix → re-observe.
- `_log()` calls at each decision point (pass, fail with attempt count, budget exhaustion) provide sufficient breadcrumbs.
- `Phase.FIX` reuse means verify-fix and review-fix appear as the same phase type in logs. This limits audit granularity but is acceptable for v1 — the ordering in the phase list is sufficient to distinguish them.

## Test Quality

- **55 verify-specific tests** across 3 test files
- **16 unit tests** for `_verify_detected_failures()` covering sentinel, regex fallback, edge cases
- **4 pipeline integration tests** (pass, fail-then-fix, exhausted retries, budget guard)
- **Resume test** validates `_compute_next_phase` + `_SKIP_MAP` integration
- **Config round-trip test** validates save/load
- All existing tests updated to include the new verify phase in mock sequences — no regressions

## Non-Blocking Notes

1. **`Phase.FIX` reuse**: Verify-fix uses `Phase.FIX` rather than a dedicated `Phase.VERIFY_FIX`. This means verify-fix inherits `_SAFETY_CRITICAL_PHASES` membership automatically (net positive for security), but log entries can't distinguish review-fix from verify-fix by phase type alone. Acceptable for v1 — the phase ordering in the log disambiguates.

2. **No haiku default for `Phase.VERIFY`**: The PRD suggests haiku for cost savings. The implementation correctly excludes `Phase.VERIFY` from `_SAFETY_CRITICAL_PHASES` (allowing haiku assignment without warning), but doesn't default to it. Users can override via `phase_models.verify: haiku`. Non-blocking.

3. **Raw `{test_failure_output}` in system prompt**: The verify-fix template interpolates raw test output into the system prompt without sanitization. This is consistent with the existing threat model (user's own repo content) and acceptable.

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py]: Phase.FIX reuse for verify-fix limits audit granularity in logs — acceptable for v1, phase ordering disambiguates
- [src/colonyos/orchestrator.py]: `_verify_detected_failures()` fail-open on ambiguous output is correct design — structured sentinel makes the ambiguous case narrow
- [src/colonyos/orchestrator.py]: Dual budget guards (before verify AND before fix) follow review-loop pattern exactly — no resource leak path
- [src/colonyos/orchestrator.py]: Verify agent `allowed_tools` correctly restricted to `["Read", "Bash", "Glob", "Grep"]` at runtime — defense-in-depth
- [src/colonyos/orchestrator.py]: Hard-block delivery via `_fail_run_log()` + `return log` enforces core invariant "never open a broken PR"
- [src/colonyos/config.py]: `_parse_verify_config()` validates `max_fix_attempts >= 1` preventing misconfiguration
- [src/colonyos/config.py]: No haiku default for Phase.VERIFY — users can override, non-blocking for v1
- [src/colonyos/instructions/verify_fix.md]: Raw `{test_failure_output}` interpolated without sanitization — accepted risk, consistent with existing threat model

SYNTHESIS:
This is a well-engineered implementation that follows existing patterns precisely. Every critical failure mode is handled: budget exhaustion, agent crashes, ambiguous output, resume after failure. The core invariant — never open a PR you know is broken — is enforced through multiple layers: runtime tool restriction, structured sentinel parsing with robust fallback, dual budget guards, and hard-block delivery. The two-agent separation (read-only verify, write-enabled fix) preserves clean audit boundaries. 55 tests cover the decision boundary, pipeline integration, config, and resume paths. No regressions in the existing 3110 tests. Ship it.
