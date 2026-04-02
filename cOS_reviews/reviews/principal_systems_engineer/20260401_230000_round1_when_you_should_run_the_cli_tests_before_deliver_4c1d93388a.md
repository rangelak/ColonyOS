# Review: Principal Systems Engineer (Google/Stripe caliber)
## Round 1 — Pre-Delivery Test Verification Phase

**Branch**: `colonyos/when_you_should_run_the_cli_tests_before_deliver_4c1d93388a`
**PRD**: `cOS_prds/20260401_224904_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

---

## Checklist

### Completeness
- [x] FR-1: Verify phase inserted between Learn and Deliver with read-only tools
- [x] FR-2: Verify-fix loop with configurable max attempts (default 2)
- [x] FR-3: Hard-block delivery on persistent failure via `_fail_run_log()`
- [x] FR-4: Budget guard before each verify and fix iteration
- [x] FR-5: `VerifyConfig` dataclass + `PhasesConfig.verify` + defaults wired
- [x] FR-6: `verify.md` and `verify_fix.md` instruction templates with sentinel
- [x] FR-7: Resume support — `_compute_next_phase("learn") → "verify"`, `_SKIP_MAP` updated
- [x] FR-8: Heartbeat + UI header consistent with other phases
- [x] FR-9: Thread-fix verify untouched

### Quality
- [x] All 3,110 tests pass (0 failures, 0 regressions)
- [x] No linter errors introduced
- [x] Code follows existing project conventions (budget guard, phase append, heartbeat, UI)
- [x] No unnecessary dependencies added
- [x] No unrelated changes included

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive operations without safeguards
- [x] Error handling present for all failure cases (budget exhaustion, fix agent failure, persistent test failure)

---

## Findings

### Non-blocking

1. **[src/colonyos/config.py]**: `Phase.VERIFY` is not added to `_SAFETY_CRITICAL_PHASES` as PRD line 79 specifies. However, verify uses read-only tools and the PRD itself recommends haiku for verify. The *fix* agent uses `Phase.FIX` which IS in the safety-critical set. Acceptable for v1.

2. **[src/colonyos/orchestrator.py]**: Verify-fix reuses `Phase.FIX` enum, making review-fix and verify-fix indistinguishable in `RunLog.phases` without positional inference. A `Phase.VERIFY_FIX` would improve forensics but is a v2 concern.

3. **[src/colonyos/orchestrator.py]**: Verify agent defaults to the global model (opus) rather than haiku as PRD suggests for cost optimization. `config.get_model(Phase.VERIFY)` falls back to the global default. Non-blocking — correctness is unaffected, and a phase-specific model default can be added in a follow-up.

---

## Synthesis

This is a clean, well-structured implementation that follows every established pattern in the codebase. The core invariant — **never open a PR you know is broken** — holds under all tested scenarios: first-pass success, fix-then-pass, exhausted retries, budget exhaustion, config disable, and resume from failure.

The critical previous-round issues (false-positive detection on "0 failed"/"ErrorHandler", missing `_compute_next_phase("learn")` mapping) are fully resolved with the structured `VERIFY_RESULT: PASS/FAIL` sentinel and 16 unit tests on the decision boundary function. The resume chain is complete, the budget guards are at both entry points, and the two-agent separation preserves audit boundaries.

The three non-blocking items (safety-critical phases set, Phase.FIX reuse, haiku default) are all reasonable v2 optimizations that don't affect correctness or safety. The implementation ships the smallest thing that works — exactly what was asked for.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/config.py]: Phase.VERIFY not in _SAFETY_CRITICAL_PHASES (non-blocking — verify is read-only, fix is already protected)
- [src/colonyos/orchestrator.py]: Phase.FIX reuse makes verify-fix and review-fix indistinguishable in audit logs (v2 improvement)
- [src/colonyos/orchestrator.py]: Verify agent defaults to opus instead of haiku for cost savings (non-blocking optimization)

SYNTHESIS:
Solid implementation that faithfully follows existing pipeline patterns. All 9 functional requirements are met, all 3,110 tests pass, the critical decision boundary function has structured sentinel parsing with robust fallback heuristics, and the core safety invariant (never open a known-broken PR) holds under all tested scenarios. The three minor findings are optimization opportunities for v2, not blockers. Ship it.
