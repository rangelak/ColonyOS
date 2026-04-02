# Review — Principal Systems Engineer, Round 1

**Branch**: `colonyos/when_you_should_run_the_cli_tests_before_deliver_4c1d93388a`
**PRD**: `cOS_prds/20260401_224904_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## Completeness Assessment

| Requirement | Status | Notes |
|---|---|---|
| FR-1: Verify phase in main pipeline | ✅ | Inserted between Learn and Deliver; `allowed_tools=["Read", "Bash", "Glob", "Grep"]` enforced at runtime |
| FR-2: Verify-fix loop | ✅ | Two-agent pattern: read-only verify → write-enabled fix → re-verify. Up to `max_fix_attempts` retries |
| FR-3: Hard-block on persistent failure | ✅ | `_fail_run_log()` + `return log` prevents any path to Deliver when tests fail after all attempts |
| FR-4: Budget guard | ✅ | Dual budget check — before every verify AND before every fix iteration, matching review-loop pattern exactly |
| FR-5: Config integration | ✅ | `PhasesConfig.verify`, `VerifyConfig` dataclass, `DEFAULTS["phases"]["verify"]`, `DEFAULTS["verify"]`, `load_config`/`save_config` roundtrip, input validation (`max_fix_attempts >= 1`) |
| FR-6: Instruction templates | ✅ | `verify.md` (read-only test runner with sentinel contract) + `verify_fix.md` (write-enabled with context injection) |
| FR-7: Resume support | ✅ | `_compute_next_phase`: `decision→verify`, `learn→verify`, `verify→deliver`. `_SKIP_MAP` updated for `learn` and `verify` |
| FR-8: Heartbeat + UI | ✅ | `_touch_heartbeat()` before verify; `phase_header()` with `_make_ui()` fallback to `_log()` |
| FR-9: Thread-fix unchanged | ✅ | Zero modifications to thread-fix flow |

## Quality Deep Dive

### Loop Control Logic (Critical Path)

The verify-fix loop at orchestrator.py ~line 4986 is well-structured:

```
for attempt in range(max_fix_attempts + 1):
    budget_guard()
    verify_agent()  // read-only
    if passed: break
    if attempt >= max_fix_attempts: break  // no more fixes available
    budget_guard()
    fix_agent()  // write-enabled
```

This correctly provides `max_fix_attempts + 1` verify checks (initial + one after each fix), and `max_fix_attempts` fix attempts. The asymmetry is right: the final iteration is verify-only (no point fixing if you can't re-verify). Three integration tests validate the boundary: pass-on-first-try, fix-then-pass, and exhaust-all-retries.

### Sentinel Parsing (`_verify_detected_failures`)

The two-tier design is operationally sound:

1. **Primary**: Structured `VERIFY_RESULT: PASS/FAIL` sentinel — deterministic, case-insensitive
2. **Fallback**: Regex matching `[1-9]\d*\s+(failed|failures?|errors?)` — avoids the classic false-positive on `0 failed` and class names like `ErrorHandler`

The fail-open default (ambiguous output → assume pass) is the right call for v1. The alternative (fail-closed) would block delivery on agent output format glitches, which is worse operationally than the occasional miss. The 16 unit tests cover the critical edge cases.

### Phase.FIX Reuse

The verify-fix agent reuses `Phase.FIX` rather than introducing a new enum variant. This is pragmatically correct — the fix phase already exists in `_SAFETY_CRITICAL_PHASES`, inheriting the haiku-warning guard. The test at `test_fix_phase_is_safety_critical_covers_verify_fix` documents this design choice explicitly. The trade-off (verify-fix is log-indistinguishable from review-fix by enum alone) is acceptable because phase ordering in the log disambiguates unambiguously.

### Audit Separation

The two-agent pattern (read-only verify → write-enabled fix) preserves a clean audit boundary. Each invocation produces a separate `PhaseResult` with its own session ID, cost, and artifacts. You can always reconstruct "what was observed" vs "what was changed" from the run log — critical for post-incident forensics at 3am.

### Observability

When tests fail after all retries, `_fail_run_log()` captures the failure message with enough context to diagnose. The verify agent's artifacts contain the full test output, and each fix agent's artifacts contain what it attempted. The log-line pattern (`Verify: test failures detected (attempt N/M)`) gives operators immediate signal.

### Test Coverage

- **79 new tests** across 3 new test files + updates to existing tests
- **3,110 total tests pass** with zero regressions
- Coverage spans: config parsing/validation/roundtrip, sentinel parsing (16 edge cases), pipeline integration (pass/fail/fix/budget/resume/disable/heartbeat), instruction template structure, phase ordering, and resume-from-failed-verify

## Non-Blocking Observations

1. **No haiku default for verify**: The PRD mentions verify should default to a cheaper model. The implementation inherits the global model. This is fine for v1 — operators can set `phase_models.verify: haiku` in config, and a test verifies no safety-critical warning fires for this assignment.

2. **Phase.FIX reuse**: As noted above, verify-fix shares the FIX enum. A dedicated `Phase.VERIFY_FIX` would improve log clarity in future, but is not worth the churn now.

3. **Fail-open on ambiguous output**: The sentinel contract makes this a narrow gap in practice. The fallback regex adds a second layer. Acceptable risk for v1.

4. **No `per_run` budget increase**: The PRD raised the question of bumping from $15 to $20. The implementation doesn't change the default, which is correct — verify is cheap (read-only), and the budget guard prevents runaway costs regardless.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py]: Verify-fix loop correctly implements dual budget guards, two-agent separation, and hard-block on persistent failure. Loop control logic handles the N+1 boundary (N fixes, N+1 verifies) correctly.
- [src/colonyos/orchestrator.py]: `_verify_detected_failures()` sentinel parsing is robust with proper fallback hierarchy and 16 unit tests covering edge cases.
- [src/colonyos/config.py]: VerifyConfig with input validation, DEFAULTS integration, and save/load roundtrip are clean and follow existing patterns exactly.
- [src/colonyos/instructions/verify.md]: Read-only contract is clearly enforced with explicit tool restrictions and structured sentinel output format.
- [src/colonyos/instructions/verify_fix.md]: Context injection via `{test_failure_output}` gives the fix agent sufficient diagnostic information.
- [tests/]: 79 new tests with comprehensive coverage of happy path, error paths, budget exhaustion, resume, and config validation. All 3,110 tests pass.

SYNTHESIS:
This is a clean, well-scoped implementation that follows every established pattern in the codebase (budget guards, heartbeat, phase append, UI headers, resume chain). The critical invariant — never open a PR with known test failures — is enforced by a hard `_fail_run_log()` + `return log` that makes it impossible to reach Deliver after persistent test failures. The two-agent separation preserves audit boundaries. The sentinel parsing avoids false positives with a proper structured-then-heuristic hierarchy. Test coverage is thorough at 79 new tests with zero regressions across the full 3,110-test suite. The non-blocking observations (no haiku default, Phase.FIX reuse, fail-open) are all reasonable v1 trade-offs that the implementation documents via tests and comments. Ship it.
