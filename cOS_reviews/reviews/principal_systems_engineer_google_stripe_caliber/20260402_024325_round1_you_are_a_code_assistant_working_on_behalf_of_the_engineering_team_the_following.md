# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

Now I'll produce the review output directly as instructed:

---

## Review: Principal Systems Engineer (Google/Stripe caliber)

### Completeness

- [x] **FR-1**: `max_task_retries: int = 1` added to `RecoveryConfig`, defaults dict, parsing, validation, and serialization (`save_config`). Complete.
- [x] **FR-2**: `previous_error` parameter added to `_build_single_task_implement_prompt()`. Appends `## Previous Attempt Failed` section with truncation to `incident_char_cap`. Complete.
- [x] **FR-3**: `_clean_working_tree()` helper implemented with `git checkout -- .` + `git clean -fd`, proper error handling (warns but doesn't raise), 30s timeout. Complete.
- [x] **FR-4**: Retry loop wraps task execution in `_run_sequential_implement()` with correct attempt tracking, clean-tree-before-retry, error-aware prompt rebuild, dependent auto-unblocking. Complete.
- [x] **FR-5**: `_record_recovery_event(log, kind="task_retry", details={...})` called with `task_id`, `attempt`, `error`, `success` fields. Complete.
- [x] **FR-6**: Parsing and validation for `max_task_retries` in `_parse_recovery_config()` with floor enforcement (non-negative). Complete.
- [x] All tasks in task file marked complete.
- [x] No TODO/FIXME/HACK/placeholder code found.

### Quality

- [x] All 218 tests pass (22 new + 196 existing) — zero regressions.
- [x] No linter errors in changed files.
- [x] Code follows existing project conventions (same subprocess patterns, same `_log` style, same recovery event structure).
- [x] No new dependencies added.
- [x] No unrelated changes included.
- [x] Existing failure tests updated to `max_task_retries=0` to preserve their semantics — correct approach.

### Safety

- [x] No secrets or credentials in committed code.
- [x] `_is_secret_like_path` filtering preserved in the retry path.
- [x] Error handling present for all failure cases, including the safety-net catch at line 1090.
- [x] Error strings truncated to `incident_char_cap` before prompt injection — bounds attack surface.

### Detailed Findings

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py:916-918]: Memory injection and external context (`_drain_injected_context`) are called inside the retry loop, meaning on retry they'll re-inject repo map, re-query memory, and drain the context provider again. For `_inject_repo_map` and `_inject_memory_block` this is idempotent (appends to a freshly-built prompt). For `_drain_injected_context`, if the provider has already been drained on attempt 0, it returns empty on attempt 1 — functionally correct but worth documenting as intentional. Not a bug, just a subtlety.
- [src/colonyos/orchestrator.py:1080-1086]: When all retries are exhausted, `task_results[task_id]` records `cost_usd` and `duration_ms` from only the **last** attempt, not the cumulative cost across all attempts. The `total_cost` accumulator correctly sums all attempts (line 983), but the per-task metadata doesn't reflect total spend on that task. This is a minor observability gap — a developer debugging a run might wonder why the task cost looks low despite retries.
- [src/colonyos/orchestrator.py:971-979]: In the exception path with all retries exhausted, `task_results[task_id]` does NOT include `cost_usd` (only `error`, `description`, `duration_ms`). This is consistent with the pre-existing behavior for exceptions (exceptions don't have a cost from `result.cost_usd`), so this is acceptable but worth noting the asymmetry with the non-exception failure path.
- [src/colonyos/orchestrator.py:1090-1093]: The safety-net `if not task_succeeded and task_id not in failed` is good defensive programming. It handles the theoretical case where the loop exits without marking the task. However, it doesn't populate `task_results[task_id]`, which could cause a KeyError downstream if something iterates `task_results` expecting all task IDs. Low probability — existing code iterates `task_order` and checks membership — but worth noting.
- [src/colonyos/config.py:797-801]: No upper-bound ceiling on `max_task_retries`. The PRD's open question #1 asked whether to cap at 2-3. Currently a user could set `max_task_retries=100`. This matches the current `max_phase_retries` pattern (also uncapped), so it's consistent, but a future hardening pass should add a ceiling.
- [tests/test_sequential_implement.py]: Test coverage is comprehensive: happy path (fail-then-succeed), all-retries-exhausted, clean-tree-called, previous-error-passed, recovery-event-logged, zero-retries-disables, same-budget. The `TestCleanWorkingTree` class is thorough with error, timeout, and independence tests. Good.

SYNTHESIS:
This is a clean, well-scoped implementation that does exactly what the PRD specifies — no more, no less. The retry loop is inserted at the right abstraction level (inside the task iteration, wrapping the execute-and-handle block), and the existing recovery cascade is completely untouched. The code follows established patterns throughout: same subprocess invocation style, same recovery event structure, same config parsing/validation pattern. The safety-net at line 1090 shows good defensive thinking. The test suite is solid — 22 new tests covering all the specified scenarios, and all 196 existing tests pass without modification (except the 3 that correctly received `max_task_retries=0` to preserve their original semantics). The per-task cost tracking asymmetry (only last attempt recorded) is a minor observability gap that could be addressed in a follow-up, but it doesn't affect correctness. The implementation is ready to ship.