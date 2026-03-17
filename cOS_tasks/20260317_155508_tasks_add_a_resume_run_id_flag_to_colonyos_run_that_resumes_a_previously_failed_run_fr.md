# Tasks: Resume Failed Runs via `--resume <run-id>`

## Relevant Files

- `src/colonyos/models.py` - Add `branch_name`, `prd_rel`, `task_rel` optional fields to `RunLog`
- `src/colonyos/orchestrator.py` - Extend `_save_run_log()` to persist new fields, add `resume_from` param to `run()`, add `_load_run_log()` and `_validate_resume_preconditions()` helpers
- `src/colonyos/cli.py` - Add `--resume` option to `run` command, add `[resumable]` tag to `status` command
- `tests/test_orchestrator.py` - Tests for run log persistence, phase skip logic, validation, log continuity
- `tests/test_cli.py` - Tests for `--resume` CLI flag, mutual exclusivity, `[resumable]` status display

## Tasks

- [x]1.0 Extend RunLog model with resume state fields
  - [x]1.1 Write tests in `tests/test_orchestrator.py` asserting that `RunLog` can hold `branch_name`, `prd_rel`, `task_rel` as optional `str | None` fields (default `None`)
  - [x]1.2 Add `branch_name: str | None = None`, `prd_rel: str | None = None`, `task_rel: str | None = None` fields to the `RunLog` dataclass in `src/colonyos/models.py`

- [x]2.0 Persist resume state in run log JSON
  - [x]2.1 Write tests in `tests/test_orchestrator.py` that call `_save_run_log()` with a `RunLog` containing `branch_name`, `prd_rel`, `task_rel` and assert these fields appear in the written JSON file
  - [x]2.2 Write a test that verifies `_save_run_log()` also persists a `last_successful_phase` field derived from the last successful `PhaseResult` in `log.phases`
  - [x]2.3 Update `_save_run_log()` in `src/colonyos/orchestrator.py` (lines 397-426) to include `branch_name`, `prd_rel`, `task_rel`, and `last_successful_phase` in the JSON output
  - [x]2.4 Set `log.branch_name`, `log.prd_rel`, `log.task_rel` in `run()` (after lines 443-446) so they are available when `_save_run_log()` is called at each exit point

- [x]3.0 Add run log loading and resume precondition validation
  - [x]3.1 Write tests for `_load_run_log(repo_root, run_id)`: valid JSON loads correctly, missing file raises error, corrupted JSON raises error, old log without resume fields loads with `None` values
  - [x]3.2 Write tests for `_validate_resume_preconditions()`: fails on `RUNNING` status, fails on `COMPLETED` status, fails on missing branch (mock `git branch --list`), fails on missing PRD file, fails on missing task file, succeeds when all preconditions met
  - [x]3.3 Implement `_load_run_log(repo_root: Path, run_id: str) -> RunLog` in `src/colonyos/orchestrator.py` — reads JSON from `.colonyos/runs/{run_id}.json`, reconstructs `RunLog` with `PhaseResult` entries and resume fields
  - [x]3.4 Implement `_validate_resume_preconditions(repo_root: Path, log: RunLog) -> None` in `src/colonyos/orchestrator.py` — checks status is FAILED, branch exists, PRD exists, task file exists; raises `click.ClickException` on failure

- [x]4.0 Implement phase resumption logic in orchestrator
  - [x]4.1 Write tests for `run()` with `resume_from` parameter: verify that when last_successful_phase is `plan`, only implement/review/deliver phases run (check mock call counts); when last_successful_phase is `implement`, only review/deliver run; when a review/fix phase failed, the review/fix loop re-enters from the top
  - [x]4.2 Write test for run log continuity: pass an existing `RunLog` with prior phases via `resume_from`, verify the returned log has both original and new `PhaseResult` entries, and the JSON file contains all phases
  - [x]4.3 Add `resume_from: dict | None = None` parameter to `run()` in `src/colonyos/orchestrator.py` (line 429). When set, extract `branch_name`, `prd_rel`, `task_rel`, and `log` from the dict instead of computing them fresh. Set `log.status = RunStatus.RUNNING`. Log `"Resuming from phase: {next_phase}"`.
  - [x]4.4 Add phase-skip guards to each phase block in `run()`: compute `phases_to_skip` from `last_successful_phase` mapping, and wrap each phase block (plan, implement, review/fix loop, deliver) with a skip check. The mapping is: `plan` → skip plan, `implement` → skip plan+implement, `review`/`fix`/`decision` → skip plan+implement (re-enter review loop), `deliver` → skip all (nothing to resume).

- [x]5.0 Add `--resume` CLI flag
  - [x]5.1 Write tests in `tests/test_cli.py` for: `--resume` with valid run ID invokes `run()` with correct `resume_from`; `--resume` combined with `--plan-only` or `--from-prd` or a prompt argument prints an error; `--resume` with nonexistent run ID prints an error
  - [x]5.2 Add `--resume` option to the `run` command in `src/colonyos/cli.py` (line 57-60): `@click.option("--resume", "resume_run_id", default=None, help="Resume a failed run from its last successful phase.")`
  - [x]5.3 Add mutual exclusivity check at the top of the `run` function in `cli.py`: if `resume_run_id` is set alongside `prompt`, `plan_only`, or `from_prd`, print error and exit
  - [x]5.4 When `resume_run_id` is provided: call `_load_run_log()`, call `_validate_resume_preconditions()`, build the `resume_from` dict, and pass it to `run_orchestrator()`

- [x]6.0 Enhance `colonyos status` with `[resumable]` tag
  - [x]6.1 Write tests in `tests/test_cli.py` for: failed run with `branch_name`/`prd_rel`/`task_rel` and at least one successful phase shows `[resumable]`; failed run without resume fields does not show `[resumable]`; completed/running runs do not show `[resumable]`
  - [x]6.2 Update the `status` command in `src/colonyos/cli.py` (lines 206-217): after parsing each log JSON, check if `status == "failed"` and `branch_name` key exists and at least one phase has `success == true`; if so, append ` [resumable]` to the status display

- [x]7.0 Integration testing and cleanup
  - [x]7.1 Run the full existing test suite (`pytest tests/`) and verify all tests pass
  - [x]7.2 Write an end-to-end test that simulates: create a run that fails at review, then resume it, and verify the final log has plan+implement from the original run and review+deliver from the resumed run
  - [x]7.3 Verify no commented-out code, no TODOs, no placeholder implementations in shipped code
