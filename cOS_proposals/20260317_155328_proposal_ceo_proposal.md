Now I have a comprehensive understanding of the project. Let me analyze what's been built and identify the biggest gap.

## Proposal: Resume Failed Runs from Last Checkpoint

### Rationale
ColonyOS runs a multi-phase pipeline (plan → implement → review/fix → decision → deliver) where each phase costs real money and time. When a phase fails — due to budget exhaustion, network errors, or a NO-GO verdict — the entire run is marked FAILED and the user must start from scratch, re-spending on phases that already succeeded. This is the single biggest UX and cost pain point for an autonomous pipeline tool: there is no ability to pick up where you left off. Adding run resumption would make ColonyOS dramatically more cost-efficient and resilient to transient failures.

### Feature Request
Add a `--resume <run-id>` flag to `colonyos run` that resumes a previously failed run from the last successfully completed phase, skipping phases that already succeeded.

**Specific requirements:**

1. **RunLog enhancement**: Extend the `RunLog` JSON serialization (in `_save_run_log`) to persist enough state for resumption: the `branch_name`, `prd_rel` path, `task_rel` path, and the last successfully completed phase. This information is already computed in `run()` but not saved — it needs to be added to the run log JSON.

2. **`--resume` CLI flag**: Add a `--resume` option to the `run` command that accepts a run ID (e.g., `run-20260317133813-abc1234567`). When provided, load the run log JSON, extract the saved state, and determine which phase to start from.

3. **Phase resumption logic in orchestrator**: Add a `resume_from` parameter to the `run()` function. When set, skip all phases up to and including the last successful phase. For example, if plan and implement succeeded but review failed, resume from the review phase using the saved `branch_name` and `prd_rel`. The orchestrator should log `"Resuming from phase: review"` so the user knows what's happening.

4. **Run log continuity**: When resuming, append new `PhaseResult` entries to the existing run log rather than creating a new one. Update the run ID's JSON file in-place so the full history (original + resumed phases) is preserved in a single log. Set `status` back to `RUNNING` at resume start.

5. **Validate resumable state**: Before resuming, verify that: (a) the branch still exists locally, (b) the PRD file still exists, (c) the task file still exists. If any precondition fails, print a clear error and exit.

6. **`colonyos status` enhancement**: In the `status` command output, show a `[resumable]` tag next to failed runs that have enough saved state to be resumed. This helps users discover the feature.

7. **Tests**: Add unit tests for: run log state persistence (branch_name, prd_rel, task_rel saved), phase skip logic (mock phases and verify only the right ones run), precondition validation (missing branch/files), and run log continuity (resumed phases appended correctly).

**Acceptance criteria:**
- `colonyos run --resume <run-id>` resumes a failed run from the next phase after the last success
- Phases that already succeeded are not re-run (saving time and money)
- The run log JSON contains all state needed for resumption (`branch_name`, `prd_rel`, `task_rel`)
- Preconditions (branch exists, PRD exists, task file exists) are validated before resuming
- `colonyos status` shows `[resumable]` for eligible failed runs
- A resumed run's phases are appended to the original run log (single run ID, unified history)
- All existing tests continue to pass
- New tests cover state persistence, skip logic, validation, and log continuity
