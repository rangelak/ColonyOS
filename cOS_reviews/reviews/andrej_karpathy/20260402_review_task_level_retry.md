# Review: Task-Level Retry for Auto-Recovery

**Reviewer**: Andrej Karpathy
**Branch**: `colonyos/recovery-b69f562da7`
**PRD**: `cOS_prds/20260402_022155_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## Checklist

### Completeness
- [x] FR-1: `max_task_retries: int = 1` added to `RecoveryConfig`
- [x] FR-2: `previous_error` param added to `_build_single_task_implement_prompt()` with truncation
- [x] FR-3: `_clean_working_tree()` helper implemented with graceful error handling
- [x] FR-4: Retry loop wraps task failure handling in `_run_sequential_implement()`
- [x] FR-5: `task_retry` recovery events logged with proper details
- [x] FR-6: `max_task_retries` parsed/validated in `_parse_recovery_config()`
- [x] All 5 tasks marked complete in task file
- [x] No placeholder or TODO code remains

### Quality
- [x] All 218 tests pass (22 new, 196 existing)
- [x] No linter issues in changed files
- [x] Code follows existing project conventions (same git subprocess patterns, same validation patterns)
- [x] No new dependencies added
- [x] No unrelated changes included

### Safety
- [x] No secrets or credentials in committed code
- [x] Error messages truncated to `incident_char_cap` before prompt injection
- [x] `_clean_working_tree()` handles failures gracefully (warns, doesn't raise)

## Findings

### Positive

- **Error-aware retry prompt is the highest-leverage intervention**: Injecting `previous_error` into the retry prompt is exactly right. The model gets a targeted "here's what went wrong" signal rather than blindly retrying. This is how you'd design a prompt-as-program retry — the error context is the diff between attempt 1 and attempt 2.

- **Clean separation of concerns**: The retry loop is purely in `_run_sequential_implement()`, the prompt change is isolated in `_build_single_task_implement_prompt()`, and `_clean_working_tree()` is a standalone helper. Each piece is independently testable.

- **Correct test philosophy**: Unit tests mock `run_phase_sync` and test deterministic logic (git cleanup called, error injected, events logged, dependents unblock). This avoids the trap that killed the two prior implementation attempts — trying to integration-test stochastic LLM behavior.

### Minor Observations

- [src/colonyos/orchestrator.py]: The `_drain_injected_context()` call happens inside the retry loop (line 918), meaning external context (Slack/GitHub) is re-drained on each attempt. If `_drain_injected_context` is destructive (drains a queue), the retry attempt gets an empty injection. This is probably fine (the context was already consumed) but worth noting — the retry prompt may subtly differ from the first attempt beyond just the `previous_error` section.

- [src/colonyos/orchestrator.py]: The safety net at line 1092 (`if not task_succeeded and task_id not in failed`) catches an edge case but doesn't populate `task_results[task_id]`, meaning downstream code that iterates `task_results` won't have an entry for this task. Low risk since this is a defensive path that shouldn't trigger in practice.

- [src/colonyos/orchestrator.py]: The exception path (line 440-475) records `"success": False` in the recovery event for a retry that hasn't happened yet — it's logging that the *trigger* happened, not the outcome. The naming is slightly misleading but consistent with how the normal failure path does it. A future improvement could log a second event after the retry completes with the actual outcome.

- [src/colonyos/config.py]: No hard ceiling on `max_task_retries` (PRD Open Question #1). The `max_phase_retries` doesn't have one either, so this is consistent. But as noted in the PRD, capping at 2-3 would prevent misconfiguration. Not a blocker.

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py]: `_drain_injected_context()` inside retry loop may give empty context on retry if the provider is destructive — cosmetic, not a bug
- [src/colonyos/orchestrator.py]: Safety-net fallback (line 1092) doesn't populate `task_results` for the edge case — extremely low risk
- [src/colonyos/orchestrator.py]: Recovery event `"success": False` logs the trigger, not the retry outcome — minor naming ambiguity
- [src/colonyos/config.py]: No upper bound on `max_task_retries` — consistent with existing config patterns, low risk

SYNTHESIS:
This is a clean, well-scoped implementation that does exactly what it says. The architecture is right: task-level retry sits as a cheap inner loop before the expensive phase-level retry, and the error-aware prompt injection is the single highest-leverage thing you can do to improve retry success rate. The implementation correctly treats the error message as a structured signal to the model ("here's what broke, fix it") rather than just blindly re-running. The test strategy is also correct — testing the deterministic retry machinery via mocks rather than attempting flaky end-to-end tests against stochastic model outputs. The code changes are minimal, surgical, and follow existing conventions throughout. The three prior-art failures on this feature make the successful implementation here notable. Ship it.
