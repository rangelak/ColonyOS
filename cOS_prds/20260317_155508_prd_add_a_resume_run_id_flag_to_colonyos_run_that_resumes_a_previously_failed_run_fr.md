# PRD: Resume Failed Runs via `--resume <run-id>`

## 1. Introduction / Overview

ColonyOS orchestrates Claude Code agents through a multi-phase pipeline (plan → implement → review/fix → decision → deliver). When a run fails mid-pipeline — e.g., the review phase errors out after a successful plan and implement — users must re-run the entire pipeline from scratch, wasting both time and money on phases that already succeeded.

This feature adds a `--resume <run-id>` flag to `colonyos run` that resumes a previously failed run from the next phase after the last successfully completed one. The run log JSON is extended to persist resumption state, and `colonyos status` is enhanced to show which failed runs are resumable.

## 2. Goals

1. **Save cost and time**: Skip phases that already succeeded when resuming a failed run.
2. **Preserve run continuity**: A resumed run appends new phase results to the original run log, maintaining a single unified history per run ID.
3. **Fail-safe resumption**: Validate all preconditions (branch exists, PRD/task files exist) before resuming to prevent incoherent state.
4. **Discoverability**: Users can see which failed runs are resumable via `colonyos status`.

## 3. User Stories

- **As a developer**, I want to resume a failed run so I don't re-pay for the plan and implement phases that already succeeded.
- **As a developer**, I want to see `[resumable]` next to failed runs in `colonyos status` so I know which runs I can resume.
- **As a developer**, I want clear error messages when a run can't be resumed (e.g., branch deleted) so I know what to fix.
- **As a developer**, I want a single run log with the full history (original + resumed phases) so I can audit cost and progress.

## 4. Functional Requirements

### FR-1: Extend RunLog serialization with resume state
- In `_save_run_log()` (`orchestrator.py:397-426`), add `branch_name`, `prd_rel`, and `task_rel` fields to the JSON output.
- These values are already computed in `run()` at lines 443-446 but not persisted.
- Add a `last_successful_phase` derived field (the `phase` value of the last `PhaseResult` with `success=True`).

### FR-2: Add `--resume` CLI option
- Add `--resume` option to the `run` command (`cli.py:57-91`) accepting a run ID string.
- `--resume` is mutually exclusive with `--plan-only`, `--from-prd`, and the `prompt` argument.
- When `--resume` is provided, load the run log JSON from `.colonyos/runs/{run_id}.json`, extract saved state, and call `run()` with a new `resume_from` parameter.

### FR-3: Phase resumption logic in orchestrator
- Add a `resume_from` parameter to `run()` (`orchestrator.py:429`).
- When `resume_from` is set (a dict with `branch_name`, `prd_rel`, `task_rel`, `last_successful_phase`, and the existing `RunLog`):
  - Use the provided `branch_name`, `prd_rel`, `task_rel` instead of recomputing them.
  - Load the existing `RunLog` (with its `phases` list) instead of creating a new one.
  - Set `log.status` back to `RunStatus.RUNNING`.
  - Skip all phases up to and including `last_successful_phase`.
  - Log `"Resuming from phase: {next_phase}"` so the user knows what's happening.
- The review/fix loop is treated as a single resumable unit. If any phase in the review/fix/decision group failed, the entire review/fix loop is re-entered from the top.

### FR-4: Run log continuity
- When resuming, reuse the original `RunLog` object (loaded from JSON) rather than creating a new one.
- Append new `PhaseResult` entries to the existing `log.phases` list.
- Write back to the same `{run_id}.json` file, preserving a single unified log.
- Update `status` to `RUNNING` at resume start and `COMPLETED`/`FAILED` at finish.

### FR-5: Validate resumable state
- Before resuming, verify:
  - (a) The run log file exists and is parseable.
  - (b) `status` is `FAILED` (block resume of `RUNNING` or `COMPLETED` runs).
  - (c) The branch (`branch_name`) still exists locally (via `git branch --list`).
  - (d) The PRD file (`prd_rel`) still exists on disk.
  - (e) The task file (`task_rel`) still exists on disk.
- If any precondition fails, print a clear error and exit with code 1.

### FR-6: `colonyos status` enhancement
- In the `status` command (`cli.py:189-220`), show a `[resumable]` tag next to failed runs that have `branch_name`, `prd_rel`, and `task_rel` in their JSON and at least one successful phase.
- Old run logs without these fields are shown without the tag (backward-compatible, no migration).

### FR-7: Tests
- Unit tests for:
  - Run log state persistence (`branch_name`, `prd_rel`, `task_rel` saved in JSON).
  - Phase skip logic (mock phases, verify only the right ones execute on resume).
  - Precondition validation (missing branch, missing PRD, missing task file, non-FAILED status).
  - Run log continuity (resumed phases appended to original, single file).
  - `[resumable]` tag logic in status output.
  - Mutual exclusivity of `--resume` with `--plan-only`/`--from-prd`/`prompt`.

## 5. Non-Goals

- **Mid-phase resumption**: We do not resume inside a phase (e.g., mid-implementation). Failed phases are re-run from scratch; the agent sees existing branch state and adapts.
- **Granular review/fix loop resumption**: The review/fix loop is one resumable unit. We do not checkpoint between review rounds or fix iterations.
- **Auto-checkout**: We validate the branch exists but do not auto-checkout. The user must be on the correct branch (or the implement agent handles checkout). If the branch doesn't exist, we fail with a clear message.
- **Migration of old run logs**: Old logs without `branch_name`/`prd_rel`/`task_rel` are simply non-resumable. No migration is performed.
- **`--force` for RUNNING runs**: Overriding a RUNNING status is out of scope for v1. Users must manually edit the JSON if a process crashed without updating status.

## 6. Technical Considerations

### Existing Architecture Fit
- The `run()` function (`orchestrator.py:429-661`) already has a linear phase structure with early-exit on failure and `_save_run_log()` calls at each exit point. Adding `resume_from` requires injecting a "skip to phase X" guard at the start of each phase block.
- The `RunLog` dataclass (`models.py:60-77`) currently has no fields for branch/artifact paths. Three new optional fields are needed: `branch_name`, `prd_rel`, `task_rel`.
- `_save_run_log()` (`orchestrator.py:397-426`) serializes a fixed JSON schema. Adding three new keys is backward-compatible (old consumers ignore unknown keys).

### Phase Mapping for Resume
The resume logic maps `last_successful_phase` to the next phase to run:
- `plan` → resume from `implement`
- `implement` → resume from `review` (or `deliver` if review disabled)
- `review`/`fix` → resume from `review` (re-enter the review/fix loop from the top)
- `decision` → resume from `deliver`

### Backward Compatibility
- New JSON fields are additive. Old logs parse fine; they just won't have resume data.
- The `run()` function signature gains an optional `resume_from` parameter with `None` default — no breaking change.
- The `status` command reads JSON with `.get()` calls — missing keys default gracefully.

### Dependencies
- No new external dependencies. Uses only `json`, `pathlib`, `subprocess` (for `git branch --list`), and existing project modules.

## 7. Success Metrics

1. `colonyos run --resume <run-id>` successfully resumes a failed run from the correct phase.
2. Skipped phases are not re-executed (verified by mock call counts in tests).
3. The run log JSON file contains `branch_name`, `prd_rel`, `task_rel` for all new runs.
4. `colonyos status` displays `[resumable]` for eligible failed runs and omits it for old/non-resumable runs.
5. All existing tests pass without modification.
6. New tests achieve full coverage of resume logic, validation, and log continuity.

## 8. Open Questions

1. **Cost accounting on resume**: All personas agreed cumulative `total_cost_usd` (original + resumed) is correct. The `mark_finished()` method already sums all phases, so appending new phases and calling `mark_finished()` naturally produces the cumulative total. No changes needed to cost logic.
2. **Review/fix loop granularity**: Strong consensus across all personas to treat review/fix as a single resumable unit. The loop's in-memory state (`last_findings`, iteration counter) is too complex to serialize reliably.
3. **Auto-checkout vs validate-only**: Consensus is validate-only. Auto-checkout risks nuking uncommitted work. The implement agent already handles branch checkout as part of its instructions.

---

### Persona Synthesis

**Areas of unanimous agreement:**
- Review/fix loop = single resumable unit (all 7 personas)
- `--resume`/`--from-prd`/`--plan-only` must be mutually exclusive (all 7)
- Failed IMPLEMENT should re-run from scratch (all 7)
- Old logs should be non-resumable, no migration (all 7)
- Block `--resume` on RUNNING runs (all 7)
- Show `[resumable]` for all eligible failed runs, not just recent (all 7)

**Areas of tension:**
- **Auto-checkout**: YC Partner (Seibel) argued for auto-checkout to reduce friction. All other personas argued for validate-only to avoid silent side effects. **Decision**: Validate-only — safety over convenience.
- **Cost display**: Systems Engineer and Steve Jobs argued for separate `prior_cost_usd` field. Others said `mark_finished()` naturally sums all appended phases. **Decision**: No separate field needed — the phases list already provides granular per-phase cost breakdown, and `mark_finished()` computes the correct cumulative total.
- **Schema versioning**: Jony Ive suggested adding `schema_version` to run logs. **Decision**: Defer — checking for presence of `branch_name` key is sufficient for v1.
