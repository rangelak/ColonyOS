# PRD: Parallel Implement Mode

## Introduction/Overview

ColonyOS currently executes implementation tasks sequentially within a single Claude Code session. For features with multiple independent tasks (e.g., "Add authentication middleware" and "Update API rate limiting"), this means unnecessary wall-clock time — the user waits for Task A to finish before Task B even starts, even when they share no dependencies.

**Parallel Implement Mode** enables the orchestrator to spawn multiple concurrent agent sessions during the Implement phase, executing independent tasks in parallel. This reduces wall-clock time for feature implementation by up to N× (where N is the number of parallel agents), while respecting budget constraints and handling merge conflicts gracefully.

This feature builds on existing ColonyOS patterns:
- **Parallel review execution** (see `run_phases_parallel_sync` in `agent.py` lines 232-240)
- **Task file parsing** (see `_parse_parent_tasks` in `orchestrator.py` lines 799-806)
- **Prefixed UI streaming** (see `make_reviewer_prefix` in `ui.py` lines 225-229)

## Goals

1. **Reduce wall-clock time**: A feature with 4 independent tasks should complete in roughly the time of 2 sequential tasks when using 2+ parallel agents
2. **Maintain correctness**: Conflicts between concurrent agents must be detected and resolved without data loss
3. **Preserve observability**: Per-agent session IDs, costs, and task correlations must appear in run logs
4. **Report efficiency**: `colonyos stats` must show parallel vs sequential time savings
5. **Fail gracefully**: Individual task failures should not block completion of independent tasks

## User Stories

### Story 1: Developer with Independent Tasks
> As a developer running `colonyos run "Add OAuth2 login and API rate limiting"`, I want independent implementation tasks to run concurrently so I can get my PR faster without sacrificing quality.

### Story 2: Cost-Conscious Team Lead
> As a team lead, I want to see how much wall-clock time parallelism saved in each run so I can justify the infrastructure to my manager.

### Story 3: Debugging a Failed Task
> As a developer debugging a failed parallel run, I want to see exactly which task failed and resume from that point without re-running successful tasks.

### Story 4: CI Pipeline Operator
> As a DevOps engineer running ColonyOS in CI (shallow clones), I want parallel mode to gracefully degrade to sequential if git worktrees aren't available, with a clear warning explaining why.

## Functional Requirements

### FR-1: Task Dependency Annotation (Plan Phase)
1. The Plan phase agent MUST annotate each task in the task file with dependencies using the format: `depends_on: [1.0, 2.0]`
2. Tasks with no explicit `depends_on` field are treated as having no dependencies (can run immediately)
3. Example task file format:
   ```markdown
   - [ ] 1.0 Add user model
     depends_on: []
   - [ ] 2.0 Add authentication middleware
     depends_on: [1.0]
   - [ ] 3.0 Add rate limiting
     depends_on: []
   - [ ] 4.0 Integrate auth with rate limiting
     depends_on: [2.0, 3.0]
   ```

### FR-2: DAG Validation
1. The orchestrator MUST parse dependency annotations and build a directed acyclic graph (DAG)
2. If circular dependencies are detected, the run MUST fail immediately with a `PreflightError` showing the cycle path (e.g., "Circular dependency: 3.0 → 4.0 → 3.0")
3. If the task file has no dependencies (all independent), all tasks execute concurrently up to `max_parallel_agents`

### FR-3: Parallel Session Orchestration
1. Launch up to `max_parallel_agents` concurrent Claude Code sessions (default: 3, configurable)
2. Each agent works on a single task in its own git worktree (isolated filesystem)
3. Tasks with unsatisfied dependencies wait in a ready queue until predecessors complete
4. When a task completes, signal dependent tasks and check if they're ready to execute

### FR-4: Git Worktree Isolation
1. Create ephemeral worktrees under `.colonyos/worktrees/<task_id>/`
2. Each worktree is created from the feature branch HEAD
3. Agents commit directly to the feature branch from their worktree
4. Clean up worktrees after merge (success or failure)

### FR-5: Incremental Merge Strategy
1. After each agent completes its task:
   a. Agent commits its changes to a task-specific branch (e.g., `colonyos/<feature>/task-3.0`)
   b. Orchestrator acquires an in-memory asyncio lock (60-second timeout for deadlock prevention)
   c. Orchestrator merges the task branch into the main feature branch
   d. If merge succeeds, signal dependent tasks
   e. If merge conflicts occur, spawn a conflict-resolution agent (see FR-6)
2. Lock acquisition MUST log timestamps for audit trails

### FR-6: Conflict Resolution Agent
1. When merge conflicts occur, spawn a dedicated conflict-resolution agent with:
   - Read access to the PRD and task file (for semantic context)
   - Both conflicting versions (ours/theirs)
   - Full conflict markers in the working tree
2. After resolution, the agent MUST run the test suite (reuse Verify phase pattern)
3. If tests fail after resolution, mark the conflict as unresolvable and fail the run
4. Log conflict resolution as `Phase.CONFLICT_RESOLVE` for observability

### FR-7: Budget Allocation
1. Each parallel agent receives a budget of `budget.per_phase / max_parallel_agents`
2. Enforce budgets strictly per-agent to contain blast radius (one runaway agent cannot starve others)
3. Track actual per-agent costs in `PhaseResult.artifacts` with `task_id` annotation
4. Aggregate all parallel agent costs into the Implement phase total

### FR-8: Failure Handling
1. When one agent fails:
   a. Mark that specific task as FAILED in the run log
   b. Continue executing independent tasks that don't depend on the failed task
   c. Block tasks that depend on the failed task (mark as BLOCKED)
   d. Preserve all partial work on the feature branch
   e. Mark the overall run as FAILED
2. Failed runs can be resumed with `--resume` to retry only failed/blocked tasks

### FR-9: UI Integration
1. Print a task legend before parallel execution starts (similar to reviewer legend in `print_reviewer_legend`)
2. Use task IDs as prefixes: `[3.0]` for parent tasks, `[3.1]` for subtasks
3. Apply color rotation from existing `REVIEWER_COLORS` list
4. Example output:
   ```
   [3.0] Add rate limiting
   [4.0] Add metrics endpoint

   [3.0] ● Read src/middleware.py
   [4.0] ● Write src/metrics.py
   [3.0] ✓ Phase completed  $0.85 · 12 turns · 45s
   ```

### FR-10: Session Logging
1. Add `task_id` field to `PhaseResult.artifacts` for parallel implement phases
2. Keep `RunLog.phases` as a flat list (backward compatible)
3. Example PhaseResult for a parallel task:
   ```json
   {
     "phase": "implement",
     "success": true,
     "cost_usd": 0.85,
     "session_id": "abc123",
     "artifacts": {
       "task_id": "3.0",
       "result": "Completed rate limiting middleware"
     }
   }
   ```

### FR-11: Stats Integration
1. Add three new columns to `colonyos stats` output:
   - `Wall Time`: Actual elapsed time for the implement phase
   - `Agent Time`: Sum of all parallel agent durations
   - `Parallelism`: Ratio of agent time to wall time (e.g., "2.3x")
2. Sequential runs show `1.0x` parallelism
3. Add `parallel_tasks` count to run log metadata

### FR-12: Graceful Degradation
1. During preflight, check for git worktree support: `git worktree list`
2. If worktrees are unsupported (shallow clones, old Git versions):
   a. Log a warning: `[colonyos] Parallel implement disabled: <reason>`
   b. Record reason in `log.preflight.warnings`
   c. Fall back to existing sequential implementation
3. Never fail a run solely because parallelism isn't available

### FR-13: Configuration
```yaml
parallel_implement:
  enabled: true                # Master toggle
  max_parallel_agents: 3       # Concurrent sessions
  conflict_strategy: "auto"    # "auto" | "fail" | "manual"
  merge_timeout_seconds: 60    # Lock acquisition timeout
  worktree_cleanup: true       # Auto-delete worktrees after run
```

## Non-Goals

1. **Cross-run parallelism**: This feature is within a single run; we won't parallelize across multiple `colonyos run` invocations
2. **Distributed execution**: All parallel agents run on the same machine; we won't implement remote agent orchestration
3. **Dynamic rebalancing**: Budget pools are not shared between agents; we won't implement work stealing
4. **Automatic dependency inference**: Dependencies must be explicitly annotated in the task file; we won't infer them from code analysis
5. **Worktree persistence**: Worktrees are ephemeral; we won't support resuming from existing worktrees

## Technical Considerations

### Existing Infrastructure to Leverage
- `run_phases_parallel_sync()` in `agent.py` (lines 232-240): Already supports concurrent agent execution via `asyncio.gather`
- `PhaseUI` prefix system in `ui.py` (lines 225-240): Color-coded prefixes for parallel output streams
- `_parse_parent_tasks()` in `orchestrator.py` (lines 799-806): Existing task file parsing
- `PreflightResult.warnings` in `models.py` (line 108): Infrastructure for degradation warnings

### New Components Required
1. **DAG Parser** (`src/colonyos/dag.py`): Parse `depends_on` annotations, detect cycles, compute execution order
2. **Worktree Manager**: Create/cleanup ephemeral worktrees, handle failures
3. **Merge Lock**: In-memory asyncio lock with timeout and logging
4. **Conflict Resolver Agent**: New instruction template at `src/colonyos/instructions/conflict_resolve.md`

### Backward Compatibility
- The `phases` list in `RunLog` remains flat (no schema change)
- Existing task files without `depends_on` annotations work (treated as fully independent)
- `parallel_implement.enabled: false` preserves current sequential behavior

### Risk: Git Worktree Limitations
Git worktrees fail in:
- Shallow clones (`git clone --depth 1`)
- Some NFS/network filesystems
- Old Git versions (< 2.5)

Mitigation: Detect and degrade gracefully (FR-12).

## Success Metrics

1. **Wall-clock reduction**: Parallel runs with 3+ independent tasks complete in ≤50% of sequential time
2. **Conflict rate**: <10% of parallel runs encounter merge conflicts (indicates good DAG design)
3. **Adoption**: After 1 week, >50% of runs with 3+ tasks use parallel mode
4. **Reliability**: No increase in failed runs attributable to parallel mode bugs

## Open Questions

1. **Worktree vs. Shared Worktree**: The personas were split on this. The PRD assumes worktrees based on security/isolation arguments, but shared worktree with sequential merge is a valid alternative if worktree complexity proves too high. Consider a config flag `parallel_implement.isolation: "worktree" | "shared"`.

2. **Budget Pool vs. Strict Per-Agent**: The PRD specifies strict per-agent budgets for blast radius containment. However, several personas argued for shared pools with per-agent ceilings. Consider revisiting if users complain about budget waste.

3. **Conflict Strategy "manual"**: What does `conflict_strategy: manual` actually do? Pause and wait for user input? Mark as failed and let user resolve? Needs spec before implementation.

## Persona Synthesis

### Areas of Agreement
- **Fail fast on circular dependencies**: All 7 personas agreed — don't silently fall back to sequential
- **Task IDs over generic prefixes**: Use `[3.0]` not `[T1]` for direct correlation with task file
- **Preserve partial work on failure**: Never auto-rollback; keep commits for debugging
- **In-memory asyncio locks**: Simpler than file locks, no stale lock cleanup needed
- **Run tests after conflict resolution**: Non-negotiable for correctness

### Areas of Tension
- **Worktree vs. Shared Worktree**: Security/Linus/Jony favor worktrees for isolation; Michael/Jobs favor shared for simplicity
- **Budget pools**: Michael/Jobs/Andrej favor shared pools for efficiency; Systems Engineer/Security favor strict per-agent for blast radius
- **Graceful degradation**: Security argues for fail-hard; others prefer degrade-with-warning

### Resolution Rationale
- **Worktrees**: Chosen for security isolation and eliminating race condition classes
- **Strict budgets**: Chosen for predictable failure modes and audit trails
- **Graceful degradation**: Chosen because blocking CI runs for parallelism is worse than sequential execution
