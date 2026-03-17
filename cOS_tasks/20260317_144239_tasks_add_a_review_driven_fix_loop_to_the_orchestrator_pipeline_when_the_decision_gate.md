# Tasks: Review-Driven Fix Loop for Orchestrator Pipeline

## Relevant Files

- `src/colonyos/models.py` - Add `FIX` phase enum value
- `src/colonyos/config.py` - Add `max_fix_iterations` config field, update parsing and serialization
- `src/colonyos/instructions/fix.md` - New fix instruction template (to be created)
- `src/colonyos/orchestrator.py` - Add `_build_fix_prompt()`, implement fix loop in `run()`, add CLI feedback logging
- `tests/test_orchestrator.py` - Update existing NO-GO test, add new tests for fix loop, prompt construction, iteration cap, budget guard
- `tests/test_config.py` - Add tests for `max_fix_iterations` config parsing and serialization
- `src/colonyos/naming.py` - May need helper for fix-iteration review artifact filenames

## Tasks

- [x] 1.0 Add `Phase.FIX` enum value to models
  - [x] 1.1 Write test in `tests/test_orchestrator.py` asserting `Phase.FIX == "fix"` and that the Phase enum ordering includes FIX between DECISION and DELIVER
  - [x] 1.2 Add `FIX = "fix"` to the `Phase` enum in `src/colonyos/models.py`
  - [x] 1.3 Run existing tests to verify no regressions (especially `TestPhaseReviewEnum.test_phase_ordering`)

- [x] 2.0 Add `max_fix_iterations` config field
  - [x] 2.1 Write tests in `tests/test_config.py` for: (a) default value is 2, (b) parsing from YAML, (c) serialization via `save_config`, (d) value of 0 disables fix loop
  - [x] 2.2 Add `max_fix_iterations: int = 2` field to `ColonyConfig` in `src/colonyos/config.py`
  - [x] 2.3 Update `load_config()` to parse `max_fix_iterations` from YAML (with default fallback)
  - [x] 2.4 Update `save_config()` to serialize `max_fix_iterations`
  - [x] 2.5 Add `"max_fix_iterations": 2` to the `DEFAULTS` dict

- [x] 3.0 Create fix instruction template
  - [x] 3.1 Create `src/colonyos/instructions/fix.md` with template variables: `{prd_path}`, `{task_path}`, `{branch_name}`, `{reviews_dir}`, `{decision_text}`, `{fix_iteration}`, `{max_fix_iterations}`
  - [x] 3.2 Template should instruct the agent to: read review artifacts, understand findings, make targeted fixes on the existing branch, run tests, update the task file

- [x] 4.0 Implement `_build_fix_prompt()` function
  - [x] 4.1 Write tests in `tests/test_orchestrator.py` for `_build_fix_prompt`: (a) returns tuple of (system, user) strings, (b) system prompt contains base instructions + fix template, (c) user prompt embeds the decision text inline, (d) includes reviews_dir path, (e) includes fix iteration number
  - [x] 4.2 Implement `_build_fix_prompt(config, prd_path, task_path, branch_name, decision_text, fix_iteration)` in `src/colonyos/orchestrator.py` that loads `fix.md`, formats it with the provided arguments, and returns (system, user) tuple

- [x] 5.0 Implement fix loop in orchestrator `run()`
  - [x] 5.1 Write tests for the fix loop in `tests/test_orchestrator.py`:
    - Test: NO-GO → fix → holistic review → GO → deliver (success path)
    - Test: NO-GO → fix → NO-GO → fix → NO-GO → fail (max iterations exhausted)
    - Test: `max_fix_iterations=0` preserves current fail-fast behavior (NO-GO → fail immediately)
    - Test: Fix iterations appear as `Phase.FIX` in the run log
    - Test: UNKNOWN verdict does NOT trigger fix loop (proceeds to deliver as before)
    - Test: Phase failure during fix iteration fails the run
  - [x] 5.2 Refactor the NO-GO handling block (lines 608-613) in `run()` to enter a fix loop:
    - After NO-GO, check `config.max_fix_iterations > 0`
    - Loop up to `max_fix_iterations` times
    - Each iteration: run fix phase → holistic review → decision gate
    - Append all PhaseResults to RunLog
    - Break on GO, fail on max iterations or phase failure
  - [x] 5.3 Update the existing `test_decision_nogo_stops_pipeline` test to set `max_fix_iterations=0` on its config fixture so it continues to pass
  - [x] 5.4 Save fix-iteration review artifacts with iteration-tagged filenames (e.g., `review_final_fix1.md`, `decision_fix1.md`)

- [x] 6.0 Implement budget guard for fix iterations
  - [x] 6.1 Write tests for budget exhaustion:
    - Test: Fix loop stops when remaining per-run budget is insufficient for another iteration
    - Test: Aggregate cost across fix iterations is tracked correctly in RunLog
  - [x] 6.2 Before each fix iteration, compute `remaining = config.budget.per_run - sum(phase costs so far)`. If remaining < `config.budget.per_phase`, log a budget-exhaustion message and break the loop with `RunStatus.FAILED`
  - [x] 6.3 Ensure `RunLog.total_cost_usd` reflects all fix iteration costs via the existing `mark_finished()` method

- [x] 7.0 Add CLI feedback logging for fix loop
  - [x] 7.1 Add `_log()` calls at key points in the fix loop:
    - `"=== Fix Iteration {i}/{max} ==="` at iteration start
    - `"  Re-running holistic review..."` before review
    - `"  Decision: {verdict}"` after decision
    - `"Fix loop: all {max} iterations exhausted. Pipeline failed."` on max iterations
    - `"Fix loop: budget exhausted ({remaining:.2f} remaining). Pipeline failed."` on budget limit
    - `"Fix iteration {i}: resolved NO-GO. Proceeding to deliver."` on success

- [x] 8.0 Final integration testing and cleanup
  - [x] 8.1 Run the full test suite (`pytest tests/`) and verify all tests pass
  - [x] 8.2 Verify the full happy path with mocks: plan → implement → review → NO-GO → fix → review → GO → deliver
  - [x] 8.3 Verify backward compatibility: config with no `max_fix_iterations` field defaults to 2
