# PRD: Sequential Task Implementation as Default

**Date**: 2026-03-29
**Status**: Draft
**Author**: ColonyOS Plan Agent

---

## 1. Introduction / Overview

ColonyOS currently defaults to **parallel task implementation** using git worktrees (`parallel_implement.enabled = True`). Each task gets an isolated filesystem copy via `WorktreeManager`, tasks run concurrently via asyncio in `ParallelOrchestrator`, and results are merged back with conflict resolution.

In practice, most task graphs are **linear dependency chains** (task 2 depends on 1, task 3 depends on 2). Parallel execution of dependent tasks creates merge conflicts that require manual intervention or an expensive auto-resolution agent (10% of budget). The user's feedback is clear: **merge conflicts from parallel execution cost more time than parallelism saves**.

This PRD proposes making **sequential implementation the default**, where tasks execute one-at-a-time on a single branch in topological order, with each task seeing the committed output of all prior tasks. Parallel mode remains available as an explicit opt-in for power users with truly independent tasks.

## 2. Goals

| # | Goal | Measure |
|---|------|---------|
| G1 | Eliminate merge conflicts in the default implement flow | Zero merge conflict errors in sequential mode |
| G2 | Tasks with dependencies see prior task output | Each task agent starts with all prior commits on the branch |
| G3 | Preserve parallel mode as opt-in | `parallel_implement.enabled: true` in config still works |
| G4 | Respect existing DAG dependency annotations | Tasks execute in topological order from `dag.py` |
| G5 | Maximize useful output on partial failure | Independent tasks continue even if a dependency chain fails |

## 3. User Stories

**US-1**: As a ColonyOS user, I want tasks to execute sequentially by default so that task 2.0 can use the code written by task 1.0 without merge conflicts.

**US-2**: As a ColonyOS user, I want failed tasks to only block their dependents, not the entire run, so I get maximum useful output.

**US-3**: As a power user with independent microservice tasks, I want to opt into parallel worktree mode via config so I can still benefit from concurrent execution when appropriate.

**US-4**: As a daemon operator, I want the implement phase behavior to be consistent whether triggered by Slack, GitHub issues, or CLI so there are no surprises.

## 4. Functional Requirements

| # | Requirement |
|---|-------------|
| FR-1 | Change `ParallelImplementConfig.enabled` default from `True` to `False` in `config.py` |
| FR-2 | Change `DEFAULTS["parallel_implement"]["enabled"]` from `True` to `False` in `config.py` |
| FR-3 | Implement a sequential task runner in the orchestrator that processes tasks one-at-a-time on the current branch |
| FR-4 | Sequential runner must use `TaskDAG.topological_sort()` from `dag.py` for task ordering |
| FR-5 | Each task must be committed to the branch before the next task starts, so later tasks see prior changes |
| FR-6 | On task failure, mark the task as failed, skip all transitive dependents (mark as BLOCKED), but continue with independent tasks using `get_ready_tasks()` DAG logic |
| FR-7 | Sequential mode budget: divide `phase_budget` by `task_count` to give each task a fair share |
| FR-8 | Log a warning when `parallel_implement.enabled` is explicitly set to `True`, informing the user about merge conflict risk |
| FR-9 | The sequential runner must produce `PhaseResult` artifacts consistent with the parallel runner (per-task cost, duration, status) |
| FR-10 | All existing parallel orchestrator code (`parallel_orchestrator.py`, `worktree.py`, `parallel_preflight.py`) remains intact and functional when opted into |

## 5. Non-Goals

| # | Non-Goal |
|---|----------|
| NG-1 | Removing or deprecating the parallel orchestrator code |
| NG-2 | Building a "smart hybrid" mode that auto-detects which tasks can be parallelized |
| NG-3 | Changing the review phase parallelism (multi-persona reviews are read-only and correctly parallel) |
| NG-4 | Modifying the daemon's queue-level sequential execution (already sequential) |
| NG-5 | Adding a CLI flag to toggle parallel/sequential per-run (config-only for now) |

## 6. Technical Considerations

### 6.1 Key Files to Modify

| File | Change |
|------|--------|
| `src/colonyos/config.py` | Flip `enabled` default to `False` in both `ParallelImplementConfig` dataclass (line ~146) and `DEFAULTS` dict (line ~53) |
| `src/colonyos/orchestrator.py` | Add sequential task runner in `_execute_implement_phase()` (line ~3673); currently falls back to single-prompt sequential when parallel returns `None` — replace with per-task sequential loop |
| `src/colonyos/dag.py` | No changes needed — `topological_sort()` and `get_ready_tasks()` already provide the required ordering and failure-skip logic |
| `src/colonyos/parallel_orchestrator.py` | No changes needed — `should_use_parallel()` already gates on `config.enabled` |

### 6.2 Sequential Execution Flow

```
1. Parse task file → TaskDAG
2. topo_order = dag.topological_sort()
3. completed = set(), failed = set()
4. For each task_id in topo_order:
   a. If task_id depends on any failed task → mark BLOCKED, skip
   b. Build implement prompt for this single task
   c. Run agent session (budget = phase_budget / task_count)
   d. If success → git commit, add to completed
   e. If failure → add to failed
5. Return PhaseResult with per-task breakdown
```

### 6.3 Existing Sequential Fallback

The orchestrator already has a sequential fallback at line ~3689 that runs ALL tasks in a single agent prompt. The new sequential runner differs: it runs **one task per agent session** with a commit between each, preserving the per-task tracking and failure isolation that the parallel runner provides.

### 6.4 Budget Strategy

Divide phase budget evenly across tasks (`phase_budget / task_count`). This is consistent with the parallel runner's approach but uses actual task count instead of `max_parallel_agents`. The run-level budget cap in config acts as the overall ceiling.

### 6.5 Persona Consensus & Tensions

**Full agreement (7/7 personas)**:
- Flip default, don't delete parallel code
- Use topological order from existing DAG
- Cumulative access is the whole point
- Skip dependents, continue independents on failure
- Implement phase only — no other phases affected
- Sequential default, hybrid is V2 at best
- Keep parallel config as opt-in

**Tension: Budget allocation**:
- Seibel, Jobs, Security: divide evenly by task count (predictable cost)
- Ive, Linus, Systems Engineer: full phase budget per task (don't starve complex tasks)
- **Resolution**: Divide by task count. Predictable cost is more important for an autonomous system. Users can increase `per_phase` budget if tasks are underfunded.

## 7. Success Metrics

| # | Metric | Target |
|---|--------|--------|
| SM-1 | Merge conflict errors in default mode | 0 |
| SM-2 | Task dependency visibility (later tasks see prior code) | 100% |
| SM-3 | Parallel mode still functional when opted in | All existing parallel tests pass |
| SM-4 | Partial failure recovery (independent tasks complete) | Independent tasks complete despite sibling failures |

## 8. Open Questions

| # | Question | Status |
|---|----------|--------|
| OQ-1 | Should we add a `--parallel` CLI flag for per-run override, or keep it config-only? | Deferred to V2 (NG-5) |
| OQ-2 | Should the sequential runner reuse the same agent session across tasks (context accumulation) or start fresh per task? | Fresh per task recommended — prevents context window overflow on large task lists |
| OQ-3 | Should we add a budget reserve (5-10%) for retries on failed tasks? | Nice-to-have, not in initial scope |
