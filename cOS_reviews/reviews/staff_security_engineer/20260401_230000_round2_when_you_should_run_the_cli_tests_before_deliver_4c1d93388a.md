# Staff Security Engineer — Round 2 Review

**Branch**: `colonyos/when_you_should_run_the_cli_tests_before_deliver_4c1d93388a`
**PRD**: `cOS_prds/20260401_224904_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## Review Checklist

### Completeness
- [x] FR-1: Verify phase inserted between Learn and Deliver in `_run_pipeline()` (orchestrator.py ~line 4986)
- [x] FR-2: Verify-fix loop with configurable `max_fix_attempts` (default 2), matching review-fix pattern
- [x] FR-3: Hard-block delivery on persistent failure via `_fail_run_log()`
- [x] FR-4: Budget guard before each verify and fix iteration
- [x] FR-5: `VerifyConfig` dataclass, `PhasesConfig.verify`, `DEFAULTS["verify"]` all wired
- [x] FR-6: `verify.md` and `verify_fix.md` instruction templates created
- [x] FR-7: Resume support — `_compute_next_phase()` includes `"learn": "verify"` and `"verify": "deliver"`; `_SKIP_MAP` updated
- [x] FR-8: Heartbeat + UI headers present before verify phase
- [x] FR-9: Thread-fix verify unchanged (confirmed no modifications to existing thread-fix flow)
- [x] All tasks complete, no TODO/placeholder code

### Quality
- [x] All 3110 tests pass (0 failures, 0 regressions)
- [x] 64 new verify-specific tests covering: pipeline happy path, fix loop, exhausted retries, budget guard, config disable, resume, heartbeat, sentinel parsing (16 edge cases), instruction template content
- [x] Code follows existing patterns (budget guard, heartbeat, UI header, phase append/capture)
- [x] No unnecessary dependencies added
- [x] No unrelated changes (only verify-related code + test fixture updates for new phase in pipeline)

### Safety & Security Assessment

**Tool restriction enforced at runtime** — The verify agent is restricted to `["Read", "Bash", "Glob", "Grep"]` via the `allowed_tools` parameter passed to `run_phase_sync()` (orchestrator.py line 5034). This is **defense-in-depth**: the restriction is enforced by the runtime, not just by instruction text. The instruction template also explicitly forbids Write/Edit/Agent. Both layers must be bypassed to violate read-only semantics.

**Two-agent audit separation preserved** — Verify (observe-only) and fix (modify) are distinct `Phase.VERIFY` / `Phase.FIX` invocations with separate `PhaseResult` entries in the run log. This enables clean post-incident forensics: you can always distinguish what was observed vs. what was changed.

**Fix agent gets default (unrestricted) tools** — The `run_phase_sync()` call for the fix agent does not pass `allowed_tools`, meaning it gets the full default tool set. This is consistent with the PRD requirement ("Full tool access") and matches the existing review-fix pattern. The fix agent needs write access to repair code.

**Budget guards prevent runaway costs** — Two budget checks per iteration (before verify, before fix), matching the review-fix loop pattern. No unbounded loops possible — `max_fix_attempts` is validated ≥1 at config parse time.

**Hard-block on persistent failure** — Core security invariant holds: the pipeline will NEVER open a PR with known test failures. `_fail_run_log()` terminates the run before reaching Deliver.

**Structured sentinel parsing** — `_verify_detected_failures()` uses a structured `VERIFY_RESULT: PASS/FAIL` sentinel as the primary signal, with regex fallback. This addresses the Round 1 false-positive concern (e.g., "ErrorHandler", "0 failed"). 16 unit tests cover edge cases including case sensitivity, ambiguous output, and class-name false positives.

**No secrets in committed code** — No API keys, tokens, passwords, or `.env` references in any changed files.

**Unsanitized test output passed to fix prompt** — The full verify output (including test names, tracebacks, file paths) is interpolated into `verify_fix.md` via `{test_failure_output}`. A malicious test name could theoretically inject instructions into the fix agent's prompt. However: (a) this is consistent with the existing threat model (review output is similarly passed to fix agents), (b) the test output originates from the user's own repo running locally, and (c) the fix agent is already operating with full write access in that repo. This is an **accepted risk** — the attack surface is the user's own codebase.

**`_SAFETY_CRITICAL_PHASES` correctly excludes VERIFY** — `Phase.VERIFY` is intentionally NOT in the safety-critical set, allowing haiku model assignment without triggering the safety warning. This is correct: verify is a read-only test runner that doesn't need frontier reasoning. `Phase.FIX` IS in the set, so verify-fix inherits the haiku-warning guard.

## Minor Observations (non-blocking)

1. **`_verify_detected_failures()` defaults to False (tests passed) on empty/ambiguous output** — This is fail-open rather than fail-closed. The rationale is pragmatic: blocking delivery on unrecognizable output would create false blocks. However, from a pure security perspective, fail-closed (assume failure on ambiguity) would be safer. The structured sentinel mitigates this: if the verify agent follows instructions, the sentinel will always be present.

2. **Verify-fix reuses `Phase.FIX`** — Review-fix and verify-fix are indistinguishable in the phase log by enum alone. You'd need to inspect the surrounding phases (did a VERIFY precede this FIX, or a REVIEW?) to determine context. Acceptable for v1; a dedicated `Phase.VERIFY_FIX` enum would improve auditability in v2.

3. **No haiku default for verify model** — PRD suggests haiku for cost savings since verify is read-only. The code inherits the global model setting. Non-blocking (operational, not security).

---

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py]: Verify agent tool restriction properly enforced via `allowed_tools` parameter (line 5034), not just instruction text — defense-in-depth implemented correctly
- [src/colonyos/orchestrator.py]: `_verify_detected_failures()` defaults to False (fail-open) on ambiguous output — accepted risk given structured sentinel is the primary signal path
- [src/colonyos/orchestrator.py]: Fix agent does not pass `allowed_tools`, getting unrestricted access — correct per PRD, consistent with existing review-fix pattern
- [src/colonyos/orchestrator.py]: Unsanitized test output in fix prompt (`{test_failure_output}`) — accepted risk, consistent with existing threat model
- [src/colonyos/instructions/verify.md]: No secrets, credentials, or sensitive data in instruction templates
- [src/colonyos/instructions/verify_fix.md]: Commit instruction present — fix agent will commit changes, creating audit trail in git history

SYNTHESIS:
From a security perspective, this implementation is solid. The critical invariant — never open a PR with known test failures — is correctly enforced via `_fail_run_log()`. The verify agent's read-only constraint is enforced at two layers (runtime `allowed_tools` and instruction text), providing genuine defense-in-depth. The two-agent separation (observe vs. modify) preserves audit boundaries. Budget guards prevent cost runaway. The structured sentinel parsing eliminates the Round 1 false-positive vulnerability. The only design choice I'd push back on in a more adversarial environment is the fail-open default on ambiguous output, but the structured sentinel makes this a narrow edge case. All 3110 tests pass with zero regressions. This is ready to ship.
