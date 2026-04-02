Now I have a comprehensive understanding of ColonyOS. Let me analyze the project and its development history to propose the most impactful feature.

## Proposal: Multi-Agent Parallel Implementation

### Rationale
ColonyOS already parallelizes code reviews effectively, but the Implement phase remains sequential — a single agent implements all tasks linearly. For large features with multiple independent tasks, parallelizing implementation across multiple agents could reduce wall-clock time by 50-70% while maintaining code coherence through task-level isolation and merge conflict resolution.

### Builds Upon
- "Rich Streaming Terminal UI" — parallel agents need coordinated UI output with prefixes (already built for reviews)
- "Per-Phase Model Override Configuration" — parallel agents can leverage different models per task complexity
- "`colonyos queue` Durable Multi-Item Execution Queue" — task queue semantics and crash recovery patterns

### Feature Request
Add a `parallel_implement` mode that spawns multiple agent sessions to implement independent tasks concurrently. The implementation should:

1. **Task Dependency Analysis**: During the Plan phase, have the planner annotate each task with dependencies (e.g., `depends_on: [1.0, 2.0]`). The orchestrator parses these annotations to build a DAG.

2. **Parallel Session Orchestration**: In the Implement phase, launch N concurrent agent sessions (configurable via `max_parallel_agents: 3` in config.yaml). Each agent works on a single task, checking out the same feature branch. Tasks with unsatisfied dependencies wait in a ready queue.

3. **Incremental Merge Strategy**: After each agent completes its task, atomically merge its changes:
   - Agent commits to an ephemeral worktree or stash
   - Orchestrator acquires a lock, applies the changes to the main feature branch
   - If merge conflicts occur, spawn a conflict-resolution agent to reconcile
   - Signal dependent tasks that their prerequisite is satisfied

4. **UI Integration**: Extend the existing `PhaseUI` prefix system (used for parallel reviewers) to show concurrent task progress: `[Task 3.0] Reading src/...`, `[Task 4.0] Writing tests...`

5. **Budget & Safety**: Each parallel agent respects `budget.per_phase / max_parallel_agents`. If any agent fails, mark only that task as failed; allow completion of independent tasks. Aggregate costs across all parallel agents into the Implement phase total.

6. **Configuration**:
   ```yaml
   parallel_implement:
     enabled: true
     max_parallel_agents: 3
     conflict_strategy: "auto"  # "auto" | "fail" | "manual"
   ```

7. **Fallback**: If `enabled: false` or the task list has no independent tasks (fully sequential dependencies), the orchestrator falls back to the existing single-agent implementation.

Acceptance criteria:
- A feature with 4 independent tasks completes in roughly the time of 2 sequential tasks (assuming 2+ parallel agents)
- Conflicts between concurrent agents are detected and handled without data loss
- The run log captures per-agent session IDs and costs
- `colonyos stats` reports parallel vs sequential implementation time
