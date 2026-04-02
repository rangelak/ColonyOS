# Principal Systems Engineer Review — Task-Level Retry

**Branch**: `colonyos/recovery-b69f562da7`  
**PRD**: `cOS_prds/20260402_022155_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`  
**Round**: 1

## Checklist

### Completeness
- [x] FR-1: `max_task_retries` added to `RecoveryConfig` with default 1
- [x] FR-2: `previous_error` parameter on `_build_single_task_implement_prompt()` with `## Previous Attempt Failed` section, truncated to `incident_char_cap`
- [x] FR-3: `_clean_working_tree()` helper with `git checkout -- .` + `git clean -fd`, defensive error handling
- [x] FR-4: Retry loop wrapping task failure in `_run_sequential_implement()` — clean, retry with error-aware prompt, dependents auto-unblock
- [x] FR-5: `task_retry` recovery events logged via `_record_recovery_event()` with correct fields
- [x] FR-6: `max_task_retries` parsed and validated in `_parse_recovery_config()` with floor check
- [x] All tasks complete, no TODOs or placeholders remain

### Quality
- [x] 218/218 tests pass (22 new + 196 existing, zero regressions)
- [x] No linter errors observed
- [x] Code follows existing patterns faithfully (config field, parse function, save function, validation — all mirror `max_phase_retries`)
- [x] No new dependencies
- [x] No unrelated changes (the fix commit is scoped to exactly the two issues Linus identified)

### Safety
- [x] No secrets or credentials
- [x] No destructive DB operations
- [x] Error handling present at all failure paths: exception path, normal failure path, safety-net fallback
- [x] `_clean_working_tree()` catches OSError/TimeoutExpired, logs warnings, never raises

## Findings

### Positive

- **[src/colonyos/orchestrator.py]**: The retry loop is a plain `for attempt in range(max_attempts)` with `break` on success — no state machine, no abstraction layer. This is the right level of complexity for v1.

- **[src/colonyos/orchestrator.py]**: The `task_results.setdefault()` in the safety-net block (fix commit) correctly avoids overwriting if a result was already populated. Good defensive design.

- **[tests/test_sequential_implement.py]**: Existing tests updated to `max_task_retries=0` to preserve their "fail immediately" semantics. This is the right call — it proves the new code doesn't change behavior when retry is disabled.

- **[src/colonyos/orchestrator.py]**: Both the exception path and the normal failure path share the same retry structure: clean → log event → set `previous_error` → continue. DRY without being over-abstracted.

### Observations (non-blocking)

- **[src/colonyos/orchestrator.py] `_drain_injected_context()` inside retry loop**: On retry, `_drain_injected_context(user_injection_provider)` runs again. If the provider is destructive (drains a queue), the retry gets empty context. This is cosmetic for v1 — the error context injection is the real signal — but worth noting for future iterations.

- **[src/colonyos/orchestrator.py] Recovery event `success: False`**: The `task_retry` event logs `"success": False` for the *trigger* (the failure that caused the retry), not the *outcome* of the retry. This is a naming nuance — the event means "we attempted a retry because of this failure" not "the retry itself failed." Acceptable semantics, but a `"trigger_error"` field name would be clearer.

- **[src/colonyos/orchestrator.py] No `task_retry` event on final success**: When a retry succeeds, there's no corresponding `task_retry` event with `success: True`. The only retry event logged is the one that *triggers* the retry. To fully reconstruct the timeline from recovery events alone, you'd want a completion event. Low priority — the task shows as COMPLETED in `task_results`.

- **[src/colonyos/config.py] No upper bound on `max_task_retries`**: Only validates `>= 0`. A value of 100 would burn budget on a genuinely broken task. Per-task budget caps limit blast radius, but `min(value, 5)` would be a cheap safeguard. Consistent with `max_phase_retries` which also has no ceiling, so this is a systemic choice, not a bug.

- **[src/colonyos/orchestrator.py] `total_duration_ms` accumulation on exception retry**: In the exception path, `total_duration_ms += elapsed_ms` happens before `continue` (retry). The retry's elapsed time is also added. This means `total_duration_ms` correctly reflects wall-clock time for all attempts, which is the right behavior.

## Operability Assessment

**Can I debug a broken retry at 3am from the logs alone?** Mostly yes:
- `_log()` messages clearly indicate retry number and error reason
- `task_retry` recovery events provide structured audit trail
- `task_results` show final status per task
- Gap: no structured log entry for "retry succeeded" — you'd infer it from the task moving to COMPLETED

**What's the blast radius of a misconfigured retry?** Bounded:
- Same `per_task_budget` per attempt — cost is at most `(1 + max_task_retries) * per_task_budget` per task
- `_clean_working_tree()` scoped to `repo_root` via `cwd`, 30s timeout
- No cross-task state leakage — each retry rebuilds prompt from scratch

**Race conditions?** None in sequential mode. The code explicitly skips parallel mode (non-goal).

## Verdict

This is a clean, minimal, well-tested implementation that does exactly what the PRD asks for. The retry loop is straightforward, the error handling is defensive without being paranoid, and the test strategy (mock `run_phase_sync`, test deterministic logic) is correct. The observations above are all follow-up items, not blockers.

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py]: `_drain_injected_context()` runs inside the retry loop — destructive providers lose context on retry. Non-blocking for v1.
- [src/colonyos/orchestrator.py]: Recovery event logs `success: False` for the trigger, not the retry outcome. Naming ambiguity, not a bug.
- [src/colonyos/orchestrator.py]: No `task_retry` event logged when retry succeeds — gap in recovery event timeline reconstruction.
- [src/colonyos/config.py]: No upper bound on `max_task_retries` — consistent with `max_phase_retries` pattern but worth a ceiling in a follow-up.

SYNTHESIS:
From a systems reliability perspective, this implementation is sound. The retry loop is the simplest thing that could work — a plain for-loop with break-on-success, no state machine, no abstraction overhead. The failure modes are well-bounded: same budget per attempt, git cleanup scoped to repo root with timeout, and the safety-net fallback ensures no task silently disappears from results. The test suite correctly validates the deterministic mechanics (git cleanup called, error injected, events logged, dependents unblock) without trying to test stochastic LLM behavior — this is exactly the right testing strategy that the prior two failed attempts got wrong. The code follows existing patterns so faithfully that it's boring, which is the highest compliment for infrastructure code. Ship it.
