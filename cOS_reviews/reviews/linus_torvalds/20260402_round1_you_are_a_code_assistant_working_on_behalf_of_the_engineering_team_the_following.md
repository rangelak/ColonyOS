# Review: Task-Level Retry for Auto-Recovery

**Reviewer**: Linus Torvalds
**Branch**: `colonyos/recovery-b69f562da7`
**PRD**: `cOS_prds/20260402_022155_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Round**: 1

## Checklist

### Completeness
- [x] FR-1: `max_task_retries: int = 1` added to `RecoveryConfig` — correct
- [x] FR-2: `previous_error` param added to `_build_single_task_implement_prompt()` with truncation — correct
- [x] FR-3: `_clean_working_tree()` helper — correct, with proper error handling
- [x] FR-4: Retry loop wrapping task failure handling — correct
- [x] FR-5: `task_retry` recovery events logged — correct
- [x] FR-6: Parsing/validation in `_parse_recovery_config()` — correct
- [x] All tasks in task file marked complete
- [x] No placeholder or TODO code remains

### Quality
- [x] All tests pass (218/218, 0 failures)
- [ ] No linter errors introduced (not verified, but code looks clean)
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies added
- [x] No unrelated changes included

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive database operations
- [x] Error handling is present for failure cases

## Findings

### Minor Issues

- [tests/test_sequential_implement.py]: **Duplicate class definition** — `TestCleanWorkingTree` is defined twice: once as an empty stub at line 992 ("Tests moved below; see TestTaskRetryLoop") and again with actual tests at line 1319. Python silently uses the second definition so tests pass, but this is dead code. Delete the empty class at line 992.

- [src/colonyos/orchestrator.py]: **Safety net lacks task_results entry** — The safety net at line 1090 (`if not task_succeeded and task_id not in failed`) adds to `failed` but doesn't populate `task_results[task_id]`. Every other failure path writes a `task_results` entry. If this safety net ever fires, downstream code iterating `task_results` could KeyError or silently miss the task. This should be unreachable if the loop logic is correct, but if you're going to write defensive code, make it actually defensive.

- [tests/test_sequential_implement.py]: **Existing tests silently changed** — Three existing tests (`test_first_task_fails_blocks_chain`, `test_independent_tasks_continue_on_failure`, `test_agent_exception_marks_task_failed`) had their configs changed from `ColonyConfig()` to `ColonyConfig(recovery=RecoveryConfig(max_task_retries=0))`. This is correct — without it, the default retry=1 would break these tests — but it's worth noting this is exactly the kind of subtle behavioral change that proves the feature works. The existing tests validated "fail immediately" behavior; they now need explicit opt-out. Good.

### Observations (Not Blocking)

- The retry loop structure is clean. `for attempt in range(max_attempts)` with `break` on success is the obvious pattern. No overengineering, no abstract retry decorator, no callback hell. Just a for loop. That's exactly right.

- Error truncation uses simple string slicing (`previous_error[:config.recovery.incident_char_cap]`). This could slice in the middle of a multi-byte character, but for error messages going into an LLM prompt, nobody cares. Simple is correct here.

- The `_clean_working_tree()` helper is appropriately paranoid — catches both OSError and TimeoutExpired, logs warnings, never raises. This means a retry proceeds even if git is in a weird state, which is the right call. The retry itself will fail if the working tree is poisoned, and that failure gets handled by the exhaustion path.

- No hard ceiling on `max_task_retries` (PRD Open Question #1). The validation rejects negative values but allows arbitrarily large ones. For v1 this is fine — if someone sets it to 100, they deserve what they get.

## Assessment

VERDICT: request-changes

FINDINGS:
- [tests/test_sequential_implement.py]: Dead code — empty duplicate `TestCleanWorkingTree` class at line 992 should be deleted
- [src/colonyos/orchestrator.py]: Safety net at line 1090 doesn't populate `task_results[task_id]`, creating a potential KeyError for downstream consumers

SYNTHESIS:
This is a well-executed, minimal change that does exactly one thing and does it correctly. The retry loop is a plain for-loop — no abstractions, no frameworks, no cleverness. The data structures are obvious: `failed` set, `completed` set, `task_results` dict. The test coverage is thorough and tests the right things (deterministic logic, not LLM behavior). The two issues I found are minor: one is dead code from a sloppy refactor, the other is an incomplete safety net that's theoretically unreachable but should still be correct. Fix those and this ships. Third time's the charm.
