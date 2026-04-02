# PRD: Task-Level Retry for Auto-Recovery

## Introduction / Overview

When any single task fails during the `implement` phase, ColonyOS currently retries the **entire phase** from scratch — re-executing all tasks (including already-committed successes) via `_attempt_phase_recovery()`. This wastes time, money, and throws away valid work. Users have reported this as "really annoying."

This feature adds a **task-level retry loop** inside `_run_sequential_implement()` that retries individual failed tasks (with error context injected into the prompt) before falling through to the existing phase-level and nuke recovery cascade. The new 3-tier cascade becomes:

```
Task fails → Retry task (1x, error-aware, clean git state) → Phase recovery (existing) → Nuke (existing)
```

## Goals

1. **Reduce wasted work**: Successful tasks should never be re-executed when only one task fails.
2. **Improve recovery success rate**: Error context in the retry prompt gives the agent a targeted second chance.
3. **Preserve existing recovery cascade**: Task-level retry is a new first tier; phase retry and nuke remain unchanged as fallbacks.
4. **Maintain cost predictability**: Task retries use the same per-task budget slice — no surprise cost overruns.
5. **Full observability**: Task retries are logged as `"task_retry"` events in `RunLog.recovery_events`.

## User Stories

1. **As a developer using ColonyOS**, I want a failed task to be retried individually before the whole phase is re-run, so I don't waste time and budget re-executing tasks that already succeeded.
2. **As a developer debugging a failed run**, I want to see in the recovery event log which tasks were retried, what error triggered the retry, and whether the retry succeeded — so I can understand what happened.
3. **As a team lead configuring ColonyOS**, I want to control the number of task-level retries via `max_task_retries` in `RecoveryConfig`, so I can tune the recovery behavior for my team's needs.

## Functional Requirements

- **FR-1**: Add `max_task_retries: int = 1` field to `RecoveryConfig` dataclass in `src/colonyos/config.py` (line 250).
- **FR-2**: Add an optional `previous_error: str | None = None` parameter to `_build_single_task_implement_prompt()` in `src/colonyos/orchestrator.py` (line 646). When provided, append a clearly delimited `## Previous Attempt Failed` section to the user prompt with the error string (truncated to `config.recovery.incident_char_cap`).
- **FR-3**: Add a `_clean_working_tree(repo_root: Path)` helper in `src/colonyos/orchestrator.py` that runs `git checkout -- .` and `git clean -fd` to discard uncommitted changes from a failed task attempt. This is lightweight — prior successful tasks are already committed individually (lines 965–976).
- **FR-4**: Wrap the task failure handling in `_run_sequential_implement()` (lines 885–995) with a retry loop:
  - On task failure, if `attempt < config.recovery.max_task_retries`:
    1. Call `_clean_working_tree()` to reset uncommitted changes.
    2. Log a `"task_retry"` recovery event via `_record_recovery_event()`.
    3. Rebuild the task prompt with `previous_error=result.error`.
    4. Re-invoke `run_phase_sync()` with the error-aware prompt and same `per_task_budget`.
  - If retry succeeds: move task from `failed` to `completed`, continue DAG execution (dependents auto-unblock via existing set-membership checks at lines 833–837).
  - If all retries exhausted: mark task as `FAILED`, block dependents (existing behavior), proceed to phase-level result.
- **FR-5**: Log task retry events using the existing `_record_recovery_event(log, kind="task_retry", details={...})` pattern (line 2866) with fields: `task_id`, `attempt`, `error` (from prior attempt), `success` (of retry).
- **FR-6**: Parse and validate `max_task_retries` in `_parse_recovery_config()` (config.py line 777) with the same floor/ceiling pattern used for `max_phase_retries`.

## Non-Goals

- **Parallel mode retry**: The parallel orchestrator (`_run_parallel_implement`, line 1019) has fundamentally different execution mechanics (branch-per-task, concurrent git writes). Task retry in parallel mode is out of scope for this change. All 7 expert reviewers agreed: ship sequential first, extend later.
- **Additional budget for retries**: Retries use the same `per_task_budget` slice. Granting extra budget rewards failure and breaks cost predictability.
- **Retry prompt with full stack traces**: Error messages are truncated to `incident_char_cap` (4000 chars). Raw stack traces could leak sensitive information.
- **Automatic retry count tuning**: `max_task_retries` is a static config value, not adaptive.
- **Changes to phase-level or nuke recovery**: Those remain untouched.

## Technical Considerations

### Existing Code Architecture

The retry loop inserts into a well-defined location in `_run_sequential_implement()` (orchestrator.py, lines 765–995):

```
For each task in topological order:
  1. Check if blocked by failed dependency (lines 833–837) → skip if blocked
  2. Build prompt via _build_single_task_implement_prompt() (line 646)
  3. Execute via run_phase_sync() (line 870)
  4. On success: selective git add + commit (lines 918–976)
  5. On failure: add to `failed` set, compute transitive blocked set (lines 886–909)
```

The retry wraps step 5: before adding to `failed`, attempt up to `max_task_retries` retries with git cleanup + error-aware prompt.

### Key Design Decisions (7/7 Persona Consensus)

| Decision | Agreement | Rationale |
|----------|-----------|-----------|
| Task-level retry is the right granularity | 7/7 | Cheapest intervention before expensive phase retry |
| Sequential mode only for v1 | 7/7 | Parallel has fundamentally different isolation concerns |
| Default `max_task_retries = 1` | 7/7 | Mirrors `max_phase_retries` convention |
| Clean git state before retry (`git checkout -- . && git clean -fd`) | 7/7 | Failed attempt's partial changes poison the retry |
| Auto-resume blocked dependents | 7/7 | Existing set-membership checks handle this for free |
| Include error context in retry prompt | 7/7 | The single highest-leverage thing for retry success |
| Same per-task budget for retry | 7/7 | Preserves cost predictability |
| Track `task_retry` events in recovery log | 7/7 | Critical for observability and tuning |

### Notable Tension

- **Security engineer** recommends using `preserve_and_reset_worktree` (heavier, creates forensic snapshot) instead of lightweight `git checkout/clean`. For v1, we use the lighter approach since each successful task is already committed — there's nothing to lose. The forensic value is low for a task-level retry vs. a nuke.
- **Security engineer** recommends sanitizing error messages as untrusted input before injecting into prompts. We truncate to `incident_char_cap` which bounds the attack surface.

### Dependencies

- No new external dependencies required.
- Changes are isolated to 3 files: `config.py`, `orchestrator.py`, and test files.

### Risk: Prior Implementation Failures

This feature has failed implementation **twice** (branches `652b8f1f4c` and `12f12712df`), both times at the integration testing stage. The root cause both times: writing complex integration tests that mock the full recovery cascade (task retry → phase retry → nuke) is extremely difficult.

**Mitigation**: All 7 personas agree — write **unit tests** that mock `run_phase_sync` to test retry loop mechanics. Do NOT write end-to-end integration tests for the full cascade. Test the deterministic logic (git cleanup called, error injected, recovery event logged, dependents unblock), not the stochastic LLM behavior.

## Success Metrics

1. **Task retry resolves failures without phase retry** — measurable via `recovery_events` containing `task_retry` with `success=true` and NO subsequent `auto_recovery` or `nuke` events.
2. **Reduced time/cost for recoverable failures** — comparing run duration and cost for runs with task-level retries vs. phase retries.
3. **Zero regressions** — all existing tests pass, existing recovery cascade behavior unchanged when task retry is exhausted.

## Open Questions

1. Should `max_task_retries` have a hard ceiling (e.g., max 3) to prevent misconfiguration? Security engineer suggests capping at 2.
2. Should we add a `task_retry_enabled` boolean separate from `max_task_retries`? (Likely overkill — `max_task_retries=0` effectively disables it.)
3. Future: Should parallel mode get task-level retry, and if so, what isolation model (worktree per retry attempt)?
