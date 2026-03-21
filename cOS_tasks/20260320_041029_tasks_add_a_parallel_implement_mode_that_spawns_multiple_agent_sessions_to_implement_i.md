# Tasks: Parallel Implement Mode

## Relevant Files

### Core Implementation
- `src/colonyos/dag.py` - **NEW FILE** - DAG parser for task dependencies, cycle detection, topological sort
- `src/colonyos/worktree.py` - **NEW FILE** - Git worktree manager (create, cleanup, isolation)
- `src/colonyos/orchestrator.py` - Main pipeline logic; add parallel implement orchestration
- `src/colonyos/agent.py` - Agent execution; extend for task-aware parallel execution
- `src/colonyos/config.py` - Configuration; add `ParallelImplementConfig` dataclass
- `src/colonyos/models.py` - Data models; extend `PhaseResult` for task tracking

### Instruction Templates
- `src/colonyos/instructions/plan.md` - Modify to instruct planner to annotate `depends_on`
- `src/colonyos/instructions/implement_parallel.md` - **NEW FILE** - Per-task implement instructions
- `src/colonyos/instructions/conflict_resolve.md` - **NEW FILE** - Merge conflict resolution instructions

### UI & Stats
- `src/colonyos/ui.py` - Extend prefix system for task IDs
- `src/colonyos/stats.py` - Add parallelism efficiency columns

### Tests
- `tests/test_dag.py` - **NEW FILE** - DAG parser and cycle detection tests
- `tests/test_worktree.py` - **NEW FILE** - Worktree manager tests
- `tests/test_orchestrator.py` - Add parallel implement integration tests
- `tests/test_config.py` - Add parallel_implement config validation tests
- `tests/test_stats.py` - Add parallelism stats tests

---

## Tasks

- [x] 1.0 Add configuration schema for parallel implement mode
  depends_on: []
  - [ ] 1.1 Write tests for `ParallelImplementConfig` validation (enabled, max_parallel_agents, conflict_strategy, merge_timeout_seconds)
  - [ ] 1.2 Add `ParallelImplementConfig` dataclass to `config.py` with validation
  - [ ] 1.3 Add `parallel_implement` section parser to `load_config()`
  - [ ] 1.4 Add `parallel_implement` section serializer to `save_config()`
  - [ ] 1.5 Update `.colonyos/config.yaml` schema documentation in README

- [x] 2.0 Implement DAG parser for task dependencies
  depends_on: []
  - [ ] 2.1 Write tests for `parse_task_dependencies()` with valid task files
  - [ ] 2.2 Write tests for cycle detection (circular dependency error messages)
  - [ ] 2.3 Write tests for topological sort producing valid execution order
  - [ ] 2.4 Implement `TaskDAG` class in `dag.py` with:
    - `parse_task_file(content: str) -> dict[str, list[str]]`
    - `detect_cycle() -> list[str] | None` (returns cycle path or None)
    - `topological_sort() -> list[str]` (execution order)
    - `get_ready_tasks(completed: set[str]) -> list[str]`
  - [ ] 2.5 Add regex parser for `depends_on: [...]` annotations in task file

- [x] 3.0 Implement git worktree manager
  depends_on: []
  - [ ] 3.1 Write tests for worktree creation (happy path)
  - [ ] 3.2 Write tests for worktree cleanup (success and failure cases)
  - [ ] 3.3 Write tests for shallow clone detection (graceful degradation)
  - [ ] 3.4 Implement `WorktreeManager` class in `worktree.py` with:
    - `create_worktree(task_id: str, base_branch: str) -> Path`
    - `cleanup_worktree(task_id: str) -> None`
    - `cleanup_all_worktrees() -> None`
    - `check_worktree_support() -> tuple[bool, str]` (supported, reason)
  - [ ] 3.5 Add worktree path validation (prevent path traversal)

- [x] 4.0 Extend PhaseResult model for task tracking
  depends_on: []
  - [ ] 4.1 Write tests for PhaseResult with task_id in artifacts
  - [ ] 4.2 Add `task_id` to PhaseResult.artifacts pattern (no schema change, convention)
  - [ ] 4.3 Add helper method `RunLog.get_task_results(task_id: str) -> list[PhaseResult]`
  - [ ] 4.4 Update `_save_run_log()` to include parallel metadata (parallel_tasks count, wall_time_ms, agent_time_ms)

- [x] 5.0 Update Plan phase to annotate task dependencies
  depends_on: [2.0]
  - [ ] 5.1 Write tests for plan output with `depends_on` annotations
  - [ ] 5.2 Update `plan.md` instruction template with dependency annotation format
  - [ ] 5.3 Add example dependency patterns to instruction (independent, sequential, diamond)
  - [ ] 5.4 Add validation that generated task file parses without cycles

- [x] 6.0 Implement parallel implement orchestration
  depends_on: [1.0, 2.0, 3.0, 4.0]
  - [ ] 6.1 Write tests for parallel implement with 2 independent tasks
  - [ ] 6.2 Write tests for parallel implement with DAG (some dependent, some independent)
  - [ ] 6.3 Write tests for graceful degradation when worktrees unavailable
  - [ ] 6.4 Add `_run_parallel_implement()` function to `orchestrator.py`:
    - Parse task file and build DAG
    - Validate no cycles (raise PreflightError if cycles found)
    - Check worktree support; degrade if unavailable
    - Create worktrees for ready tasks
    - Launch parallel agents with task-specific prompts
    - Track completion and signal dependent tasks
    - Merge completed task branches sequentially
  - [ ] 6.5 Add merge lock using `asyncio.Lock()` with 60-second timeout via `asyncio.wait_for()`
  - [ ] 6.6 Integrate `_run_parallel_implement()` into main `_run_pipeline()` flow
  - [ ] 6.7 Add fallback to sequential `_run_pipeline()` when parallel is disabled or unavailable

- [x] 7.0 Implement conflict resolution agent
  depends_on: [6.0]
  - [ ] 7.1 Write tests for conflict resolution with PRD context
  - [ ] 7.2 Write tests for conflict resolution running test suite after merge
  - [ ] 7.3 Write tests for unresolvable conflicts (fail run cleanly)
  - [ ] 7.4 Create `conflict_resolve.md` instruction template with:
    - Read access to PRD and task file
    - Instructions to analyze both versions
    - Requirement to preserve intent from both sides
    - Requirement to run test suite after resolution
  - [ ] 7.5 Add `Phase.CONFLICT_RESOLVE` to Phase enum
  - [ ] 7.6 Implement `_spawn_conflict_resolver()` in `orchestrator.py`
  - [ ] 7.7 Add conflict resolution budget (separate from per-task budget)

- [x] 8.0 Extend UI for parallel task streaming
  depends_on: [4.0]
  - [ ] 8.1 Write tests for task prefix generation (`[3.0]`, `[3.1]` format)
  - [ ] 8.2 Write tests for task legend printing
  - [ ] 8.3 Add `make_task_prefix(task_id: str) -> str` to `ui.py`
  - [ ] 8.4 Add `print_task_legend(tasks: list[tuple[str, str]])` to `ui.py`
  - [ ] 8.5 Update `PhaseUI` to accept optional `task_id` parameter

- [x] 9.0 Extend stats for parallelism reporting
  depends_on: [4.0]
  - [ ] 9.1 Write tests for parallelism stats computation (wall_time, agent_time, ratio)
  - [ ] 9.2 Write tests for stats output with parallelism columns
  - [ ] 9.3 Add `wall_time_ms` and `agent_time_ms` fields to run log metadata
  - [ ] 9.4 Add `compute_parallelism_stats()` function to `stats.py`
  - [ ] 9.5 Add `Parallelism` column to stats table (show "2.3x" or "1.0x" for sequential)
  - [ ] 9.6 Add `parallel_tasks` column showing count of concurrent tasks

- [x] 10.0 Implement failure handling and resume
  depends_on: [6.0]
  - [ ] 10.1 Write tests for partial failure (one task fails, others continue)
  - [ ] 10.2 Write tests for resume with `--resume` flag skipping completed tasks
  - [ ] 10.3 Write tests for BLOCKED task status when dependency fails
  - [ ] 10.4 Add `TaskStatus` enum: PENDING, RUNNING, COMPLETED, FAILED, BLOCKED
  - [ ] 10.5 Track per-task status in run log artifacts
  - [ ] 10.6 Update `prepare_resume()` to identify failed/blocked tasks
  - [ ] 10.7 Update `_run_parallel_implement()` to skip already-completed tasks on resume

- [x] 11.0 Add preflight checks for parallel mode
  depends_on: [3.0, 6.0]
  - [ ] 11.1 Write tests for preflight detecting shallow clone
  - [ ] 11.2 Write tests for preflight detecting old Git version
  - [ ] 11.3 Add `_check_parallel_prerequisites()` to `orchestrator.py`
  - [ ] 11.4 Check git version (require >= 2.5 for worktrees)
  - [ ] 11.5 Check for shallow clone via `git rev-parse --is-shallow-repository`
  - [ ] 11.6 Add degradation warning to `PreflightResult.warnings`

- [x] 12.0 Create implement_parallel instruction template
  depends_on: []
  - [ ] 12.1 Create `implement_parallel.md` with task-specific context injection
  - [ ] 12.2 Include task ID, task description, and dependency context
  - [ ] 12.3 Emphasize committing atomically for clean merges
  - [ ] 12.4 Reference PRD and full task file for broader context

- [x] 13.0 Integration testing and documentation
  depends_on: [6.0, 7.0, 8.0, 9.0, 10.0, 11.0]
  - [ ] 13.1 Write end-to-end test: 4 independent tasks complete in ~2x time (mocked agents)
  - [ ] 13.2 Write end-to-end test: conflict detected and resolved
  - [ ] 13.3 Write end-to-end test: graceful degradation in shallow clone
  - [ ] 13.4 Update README.md with parallel_implement configuration section
  - [ ] 13.5 Add architecture diagram showing DAG → parallel agents → merge flow
  - [ ] 13.6 Document conflict_strategy options (auto, fail, manual)

---

## Dependency Graph Visualization

```
          ┌─────────────────────────────────────────────────────────┐
          │                        Phase 1                          │
          │  (Independent - can run in parallel)                    │
          └─────────────────────────────────────────────────────────┘
                │              │              │              │
           ┌────┴────┐    ┌────┴────┐    ┌────┴────┐    ┌────┴────┐
           │  1.0    │    │  2.0    │    │  3.0    │    │  4.0    │
           │ Config  │    │  DAG    │    │Worktree │    │ Models  │
           └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘
                │              │              │              │
                │         ┌────┴────┐         │              │
                │         │  5.0    │         │              │
                │         │  Plan   │         │              │
                │         └────┬────┘         │              │
                │              │              │              │
          ┌─────┴──────────────┴──────────────┴──────────────┴─────┐
          │                        Phase 2                          │
          │  (All depend on multiple Phase 1 tasks)                 │
          └─────────────────────────────────────────────────────────┘
                                    │
                              ┌─────┴─────┐
                              │    6.0    │
                              │Orchestrate│
                              └─────┬─────┘
                                    │
     ┌──────────────┬───────────────┼───────────────┬──────────────┐
     │              │               │               │              │
┌────┴────┐   ┌─────┴────┐    ┌─────┴────┐    ┌─────┴────┐   ┌─────┴────┐
│  7.0    │   │   8.0    │    │   9.0    │    │  10.0    │   │  11.0    │
│Conflict │   │   UI     │    │  Stats   │    │ Failure  │   │Preflight │
└────┬────┘   └─────┬────┘    └─────┬────┘    └─────┬────┘   └─────┬────┘
     │              │               │               │              │
     └──────────────┴───────────────┴───────────────┴──────────────┘
                                    │
                              ┌─────┴─────┐
                              │   13.0    │
                              │Integration│
                              └───────────┘

Task 12.0 (implement_parallel.md) has no dependencies and can run any time.
```

## Estimated Effort

| Task | Complexity | Estimated Turns |
|------|------------|-----------------|
| 1.0 Config | Low | 5-8 |
| 2.0 DAG Parser | Medium | 10-15 |
| 3.0 Worktree Manager | Medium | 10-15 |
| 4.0 Model Extensions | Low | 3-5 |
| 5.0 Plan Update | Low | 3-5 |
| 6.0 Orchestration | High | 25-35 |
| 7.0 Conflict Resolution | Medium | 10-15 |
| 8.0 UI Extensions | Low | 5-8 |
| 9.0 Stats Extensions | Low | 5-8 |
| 10.0 Failure Handling | Medium | 10-15 |
| 11.0 Preflight Checks | Low | 5-8 |
| 12.0 Instruction Template | Low | 3-5 |
| 13.0 Integration Tests | Medium | 10-15 |

**Total estimated: 100-150 turns** (can be reduced with parallelism!)
