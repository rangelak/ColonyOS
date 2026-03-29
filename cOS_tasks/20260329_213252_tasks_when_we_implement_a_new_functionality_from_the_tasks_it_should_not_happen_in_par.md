# Tasks: Sequential Task Implementation as Default

**PRD**: `cOS_prds/20260329_213252_prd_when_we_implement_a_new_functionality_from_the_tasks_it_should_not_happen_in_par.md`

## Relevant Files

- `src/colonyos/config.py` - Contains `ParallelImplementConfig` dataclass and `DEFAULTS` dict; flip `enabled` default
- `src/colonyos/orchestrator.py` - Contains `_execute_implement_phase()` where parallel vs sequential is decided; add sequential task runner
- `src/colonyos/dag.py` - Contains `TaskDAG.topological_sort()` and `get_ready_tasks()`; no changes needed but used by sequential runner
- `src/colonyos/parallel_orchestrator.py` - Contains `should_use_parallel()` gate and `ParallelOrchestrator`; no changes needed, verify still works when opted in
- `src/colonyos/models.py` - Contains `PhaseResult` and task-related data structures; may need minor additions for sequential tracking
- `tests/test_config.py` - Tests for config defaults; update to assert `enabled=False`
- `tests/test_dag.py` - Tests for DAG topological sort; no changes needed
- `tests/test_orchestrator.py` - Tests for orchestrator; add sequential runner tests
- `tests/test_parallel_orchestrator.py` - Tests for parallel orchestrator; verify still pass with new default

## Tasks

- [x] 1.0 Flip parallel_implement default to disabled
  depends_on: []
  - [x] 1.1 Update tests in `tests/test_config.py` to assert `ParallelImplementConfig.enabled` defaults to `False` and `DEFAULTS["parallel_implement"]["enabled"]` is `False`
  - [x] 1.2 Change `enabled: bool = True` to `enabled: bool = False` in `ParallelImplementConfig` dataclass in `src/colonyos/config.py`
  - [x] 1.3 Change `"enabled": True` to `"enabled": False` in `DEFAULTS["parallel_implement"]` dict in `src/colonyos/config.py`
  - [x] 1.4 Add a log warning in `_parse_parallel_implement_config()` or the orchestrator when `parallel_implement.enabled` is explicitly `True`, informing user about merge conflict risk

- [x] 2.0 Implement sequential task runner in orchestrator
  depends_on: [1.0]
  - [x] 2.1 Write tests for the sequential task runner: topological ordering, cumulative commits, per-task budget allocation (`phase_budget / task_count`), PhaseResult artifact generation
  - [x] 2.2 Implement `_run_sequential_implement()` method in `orchestrator.py` that:
    - Parses task file into `TaskDAG` using `dag.py`
    - Iterates tasks in `topological_sort()` order
    - For each task: builds single-task implement prompt, runs agent session with per-task budget, commits on success
    - Returns `PhaseResult` with per-task cost/duration breakdown in artifacts
  - [x] 2.3 Wire `_run_sequential_implement()` into `_execute_implement_phase()` as the default path when `parallel_implement.enabled` is `False`, replacing the current single-prompt fallback

- [x] 3.0 Implement failure handling with DAG-aware skip logic
  depends_on: [2.0]
  - [x] 3.1 Write tests for failure scenarios: failed task blocks dependents, independent tasks continue, BLOCKED status tracking, transitive dependency skip
  - [x] 3.2 Add failure tracking to `_run_sequential_implement()`: maintain `completed` and `failed` sets, check dependencies before each task using DAG adjacency, mark tasks with failed dependencies as BLOCKED and skip them
  - [x] 3.3 Ensure BLOCKED tasks are reported in PhaseResult artifacts with clear error messages indicating which dependency failed

- [x] 4.0 Verify parallel mode still works as opt-in
  depends_on: [1.0]
  - [x] 4.1 Run existing `tests/test_parallel_orchestrator.py` tests and verify they all pass with the new default (they should, since tests set config explicitly)
  - [x] 4.2 Add an integration-style test that sets `parallel_implement.enabled = True` in config and verifies `should_use_parallel()` returns `True` and the parallel path is taken
  - [x] 4.3 Verify `WorktreeManager`, `parallel_preflight`, and conflict resolution logic are not affected by the default change

- [x] 5.0 Update orchestrator prompts for single-task context
  depends_on: [2.0]
  - [x] 5.1 Write tests verifying the implement prompt for sequential mode references only the current task (not all tasks) and includes context about completed prior tasks
  - [x] 5.2 Modify `_build_implement_prompt()` or create a `_build_single_task_implement_prompt()` that scopes the agent to one task at a time, with a summary of what prior tasks accomplished (task IDs and their descriptions)

- [x] 6.0 End-to-end validation and regression testing
  depends_on: [2.0, 3.0, 4.0, 5.0]
  - [x] 6.1 Run the full test suite (`pytest tests/`) and verify no regressions
  - [x] 6.2 Verify the sequential runner produces correct git history (one commit per task on the feature branch)
  - [x] 6.3 Verify budget tracking: total cost across all sequential tasks does not exceed `phase_budget`, and per-task costs are reported in artifacts
