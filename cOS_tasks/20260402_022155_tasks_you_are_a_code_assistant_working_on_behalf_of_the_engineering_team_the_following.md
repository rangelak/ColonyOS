# Tasks: Task-Level Retry for Auto-Recovery

## Relevant Files

- `src/colonyos/config.py` - RecoveryConfig dataclass (line 250) and `_parse_recovery_config()` validation (line 777). Add `max_task_retries` field.
- `src/colonyos/orchestrator.py` - Main orchestration logic. `_run_sequential_implement()` (line 765), `_build_single_task_implement_prompt()` (line 646), `_record_recovery_event()` (line 2866). All retry loop changes go here.
- `src/colonyos/models.py` - `TaskStatus` enum (line 83), `RunLog` with `recovery_events` (line 264). Read-only reference — no changes needed.
- `src/colonyos/dag.py` - `TaskDAG` and dependency resolution. Read-only reference — no changes needed.
- `src/colonyos/recovery.py` - Git state preservation helpers. Read-only reference for cleanup patterns.
- `tests/test_config.py` - Existing tests for RecoveryConfig parsing. Extend with `max_task_retries` tests.
- `tests/test_sequential_implement.py` - Existing tests for sequential task execution. Extend with retry loop tests.
- `tests/test_orchestrator.py` - Existing recovery cascade tests (lines 3675–3755). Add minimal task retry integration test.

## Tasks

- [x] 1.0 Add `max_task_retries` config field and validation
  depends_on: []
  - [x] 1.1 Write tests in `tests/test_config.py` for `max_task_retries`: default value is 1, YAML parsing works, validation rejects negative values, floor/ceiling enforcement matches `max_phase_retries` pattern.
  - [x] 1.2 Add `max_task_retries: int = 1` to `RecoveryConfig` dataclass in `src/colonyos/config.py` (after line 254, alongside `max_phase_retries`).
  - [x] 1.3 Add parsing and validation for `max_task_retries` in `_parse_recovery_config()` (line 777 of `config.py`), using the same pattern as `max_phase_retries`.

- [x] 2.0 Add `previous_error` parameter to task prompt builder
  depends_on: []
  - [x] 2.1 Write tests verifying `_build_single_task_implement_prompt()` includes a `## Previous Attempt Failed` section when `previous_error` is provided, and omits it when `None`. Test that the error string is truncated to `incident_char_cap`.
  - [x] 2.2 Add optional `previous_error: str | None = None` parameter to `_build_single_task_implement_prompt()` in `src/colonyos/orchestrator.py` (line 646). When provided, append a delimited error section to the user prompt, truncated to `config.recovery.incident_char_cap`.

- [x] 3.0 Add `_clean_working_tree()` helper
  depends_on: []
  - [x] 3.1 Write tests for `_clean_working_tree()`: verify it calls `git checkout -- .` and `git clean -fd`, verify it handles subprocess errors gracefully (logs warning, does not raise), verify it is scoped to the provided `repo_root`.
  - [x] 3.2 Implement `_clean_working_tree(repo_root: Path)` in `src/colonyos/orchestrator.py` as a module-level helper. Use `subprocess.run()` with the same patterns as existing git helpers in the file (e.g., the git operations around lines 918–976). Log a warning on failure but do not raise — the retry should still proceed even if cleanup is imperfect.

- [x] 4.0 Implement task retry loop in `_run_sequential_implement()`
  depends_on: [1.0, 2.0, 3.0]
  - [x] 4.1 Write unit tests in `tests/test_sequential_implement.py` for the retry loop:
    - Task fails once, succeeds on retry → task moves to `completed`, dependents execute normally.
    - Task fails all retry attempts → task marked `FAILED`, dependents `BLOCKED` (existing behavior preserved).
    - `_clean_working_tree()` is called before each retry attempt.
    - `_build_single_task_implement_prompt()` receives `previous_error` on retry.
    - `_record_recovery_event()` is called with `kind="task_retry"` for each retry.
    - `max_task_retries=0` disables retry (immediate failure, existing behavior).
    - Budget: retry uses same `per_task_budget`, not additional.
  - [x] 4.2 Modify the task failure handling in `_run_sequential_implement()` (around lines 885–995 of `src/colonyos/orchestrator.py`):
    - Wrap the task execution in a retry loop: `for attempt in range(1 + config.recovery.max_task_retries)`.
    - On failure (attempt < max): call `_clean_working_tree()`, log `"task_retry"` event, rebuild prompt with `previous_error=result.error`, re-invoke `run_phase_sync()`.
    - On retry success: add task to `completed` set (not `failed`), break out of retry loop, continue DAG execution. Blocked dependents auto-unblock via existing set-membership checks (lines 833–837).
    - On all retries exhausted: existing failure behavior (add to `failed`, compute blocked set).
  - [x] 4.3 Verify the full sequential flow works end-to-end: run existing tests in `tests/test_sequential_implement.py` and `tests/test_orchestrator.py` to confirm no regressions. Fix any test failures.

- [x] 5.0 Final validation and cleanup
  depends_on: [4.0]
  - [x] 5.1 Run the full test suite (`pytest tests/`) and confirm all tests pass (both new and existing).
  - [x] 5.2 Verify no commented-out code, no TODOs, no placeholder implementations in any changed files.
  - [x] 5.3 Verify the recovery cascade still works end-to-end: task retry (new) → phase retry (existing at line 4433) → nuke (existing). The `PhaseResult` returned by `_run_sequential_implement()` with `success=False` should still trigger `_attempt_phase_recovery()` exactly as before when all task retries are exhausted.
