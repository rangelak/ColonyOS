# Review: Task-Level Retry for Auto-Recovery (Round 2)

**Reviewer**: Linus Torvalds
**Branch**: `colonyos/recovery-b69f562da7`
**PRD**: `cOS_prds/20260402_022155_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Date**: 2026-04-02

## Checklist

### Completeness
- [x] FR-1: `max_task_retries` field added to `RecoveryConfig` with default 1
- [x] FR-2: `previous_error` parameter added to `_build_single_task_implement_prompt()` with truncation
- [x] FR-3: `_clean_working_tree()` helper implemented (checkout + clean, warns on failure, never raises)
- [x] FR-4: Retry loop wraps task failure handling in `_run_sequential_implement()`
- [x] FR-5: `task_retry` recovery events logged with correct fields
- [x] FR-6: `max_task_retries` parsed and validated in `_parse_recovery_config()`
- [x] All tasks complete, no TODOs or placeholders

### Quality
- [x] 218/218 tests pass (22 new + 196 existing, zero regressions)
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies added
- [x] No unrelated changes included

### Safety
- [x] No secrets or credentials in committed code
- [x] `_clean_working_tree()` handles failures gracefully (logs, never raises)
- [x] Error handling present for all failure cases
- [x] Safety-net block now populates `task_results` via `setdefault` (fix from round 1)

## Assessment

The two issues from round 1 are fixed:

1. **Dead code removed** — the empty `TestCleanWorkingTree` stub is gone.
2. **Safety net populates `task_results`** — uses `setdefault` to avoid clobbering, which is the right call.

The implementation is clean. Let me summarize what's actually good here, because I was focused on the bugs last time:

**Data structures are correct.** The retry loop is a plain `for attempt in range(max_attempts)` with `break` on success and `continue` on retry. No state machines, no callback hell, no clever abstractions. You can read it top to bottom and understand what happens. That's how code should be.

**`_clean_working_tree()` is properly paranoid.** It catches `OSError` and `TimeoutExpired`, logs warnings, and never raises. The second git command runs even if the first fails. This is correct defensive programming — you don't abort a retry because cleanup was imperfect.

**Error injection into the prompt is simple string slicing.** `previous_error[:config.recovery.incident_char_cap]` — no regex, no parsing, no sanitization framework. It's a bound on input size and that's sufficient for v1.

**Existing tests were updated correctly.** The tests that expect "fail immediately" behavior now explicitly pass `max_task_retries=0`. This is the right way to handle a default change — make the old tests explicitly opt into the old behavior rather than relying on implicit defaults.

**Test philosophy is correct.** Unit tests mock `run_phase_sync` and test deterministic logic. They verify: git cleanup called, error injected into retry prompt, recovery events logged, dependents unblock on retry success, dependents stay blocked on retry exhaustion, same budget used. This is testing the contract, not the LLM.

No remaining issues. Ship it.

## Verdict

**VERDICT: approve**

FINDINGS:
- [src/colonyos/orchestrator.py]: Round 1 safety-net fix correctly uses `setdefault` — avoids clobbering if result already exists
- [tests/test_sequential_implement.py]: Round 1 dead code stub removed cleanly

SYNTHESIS:
Both round 1 issues are fixed. The implementation is minimal, correct, and well-tested. The retry loop is a plain for-loop with no unnecessary abstractions. `_clean_working_tree()` is appropriately defensive. Error injection is simple truncation. Test coverage is thorough and tests deterministic behavior. 218/218 tests pass with zero regressions. This is ready to merge.
