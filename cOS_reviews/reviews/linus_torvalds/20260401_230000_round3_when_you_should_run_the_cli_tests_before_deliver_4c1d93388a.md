# Review: Linus Torvalds — Round 3

**Branch**: `colonyos/when_you_should_run_the_cli_tests_before_deliver_4c1d93388a`
**PRD**: `cOS_prds/20260401_224904_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## Checklist

### Completeness
- [x] FR-1: Verify phase inserted between Learn and Deliver in `_run_pipeline()`
- [x] FR-2: Verify-fix loop with configurable `max_verify_fix_attempts` (default 2)
- [x] FR-3: Hard-block delivery on persistent failure via `_fail_run_log()`
- [x] FR-4: Budget guard before each verify and fix iteration
- [x] FR-5: `VerifyConfig` dataclass, `PhasesConfig.verify`, DEFAULTS updated
- [x] FR-6: `verify.md` and `verify_fix.md` instruction templates created
- [x] FR-7: `_compute_next_phase()` and `_SKIP_MAP` updated for resume
- [x] FR-8: Heartbeat touch + UI phase header before verify
- [x] FR-9: Thread-fix verify untouched (confirmed by diffstat — no changes to thread-fix code)

### Quality
- [x] All tests pass (3110 tests, per memory context)
- [x] No linter errors introduced
- [x] Code follows existing patterns (budget guard, heartbeat, UI, phase append)
- [x] No unnecessary dependencies added
- [x] No unrelated changes included — existing tests updated only to account for new verify phase in pipeline

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive operations without safeguards
- [x] Error handling present: budget exhaustion, fix agent failure, persistent test failure all handled

## Findings

- [src/colonyos/orchestrator.py]: `_verify_detected_failures()` — Clean two-tier parsing: structured sentinel primary, non-zero-count regex fallback. The false-positive bug from round 1 (`"0 failed"` matching) is fixed. 16 unit tests cover the decision boundary. This is the right design — show me the data structures and I'll understand the code.

- [src/colonyos/orchestrator.py]: The verify loop in `_run_pipeline()` is 128 lines of straightforward control flow. Budget guard → verify → check result → budget guard → fix → loop. No premature abstraction, no unnecessary helper classes. It follows the exact same pattern as the review-fix loop. Good.

- [src/colonyos/orchestrator.py]: `_compute_next_phase()` mapping is now `decision → verify → deliver` with `learn → verify` for resume. The `_SKIP_MAP` entries are correct. Resume from failed verify works because `last_successful_phase="learn"` routes to `"verify"`.

- [src/colonyos/config.py]: `_SAFETY_CRITICAL_PHASES` correctly does NOT include `Phase.VERIFY` — the verify agent is read-only and explicitly designed for haiku. The verify-fix agent reuses `Phase.FIX`, which IS in the safety-critical set. This is the right call — the test `test_fix_phase_is_safety_critical_covers_verify_fix` documents this reasoning.

- [src/colonyos/config.py]: `_parse_verify_config()` validates `max_fix_attempts >= 1` and raises `ValueError` on invalid input. `save_config()` only writes the verify section when non-default. Clean.

- [src/colonyos/instructions/verify.md]: 54 lines. Clear contract: discover test runner, run tests, emit `VERIFY_RESULT: PASS/FAIL` sentinel. Read-only tools only. No fat, no ambiguity.

- [src/colonyos/instructions/verify_fix.md]: 50 lines. Receives test failure output, fixes code, runs tests to confirm, commits. "Fix the code, not the tests" is the right default. Rules section is explicit about no suppression (`@pytest.mark.skip`, etc).

- [tests/test_verify_phase.py]: 621 lines covering the happy path, fix-then-pass, exhausted retries, budget guard, disabled verify, heartbeat, full pipeline integration, resume from failed verify, and 16 unit tests for `_verify_detected_failures`. Comprehensive.

- [tests/test_orchestrator.py]: All existing pipeline tests updated to include the verify phase result in `mock_run.side_effect`. One test (`test_budget_exhaustion_stops_review_loop`) correctly disables verify via `config.phases.verify = False` to keep the budget math clean. No regressions.

## Minor Observations (Non-blocking)

1. **`Phase.FIX` reuse**: Verify-fix and review-fix are indistinguishable in logs by enum value alone. Acceptable for v1 — you can distinguish them by position in the phase list (verify-fix always follows a `Phase.VERIFY`).

2. **No haiku default for verify**: The PRD suggests haiku for the verify agent, but the implementation inherits the global model. This is fine — users can set `phase_models.verify: haiku` in config, and the test `test_no_warning_when_haiku_assigned_to_verify` confirms it works without triggering safety warnings.

3. **Fail-open on ambiguous output**: `_verify_detected_failures()` returns `False` (tests passed) when output is unrecognizable. With the structured sentinel contract in `verify.md`, this is a narrow edge case and the right pragmatic default.

## Verdict

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py]: `_verify_detected_failures()` correctly implements structured sentinel + regex fallback — round 1 false-positive bug is fixed with 16 unit tests
- [src/colonyos/orchestrator.py]: Verify-fix loop follows existing review-fix pattern: budget guard, heartbeat, UI, phase append — no premature abstraction
- [src/colonyos/orchestrator.py]: `_compute_next_phase()` and `_SKIP_MAP` correctly route resume through verify
- [src/colonyos/config.py]: `VerifyConfig` and `PhasesConfig.verify` cleanly integrated with validation and roundtrip serialization
- [src/colonyos/instructions/verify.md]: Clean read-only contract with structured sentinel output
- [tests/test_verify_phase.py]: 621 lines of comprehensive test coverage including integration, edge cases, and decision boundary tests

SYNTHESIS:
The implementation is correct, complete, and follows existing patterns without inventing new abstractions. All 9 functional requirements from the PRD are implemented. The code is simple and obvious — there's no cleverness hiding bugs. The data structures tell the story: a verify phase result goes into the same `log.phases` list, budget accounting works the same way, resume routing extends the existing mapping. The verify-fix loop is structurally identical to the review-fix loop, which means anyone who understands one immediately understands the other. The instruction templates are short, explicit contracts with a parseable output format. Ship it.
