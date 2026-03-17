# Tasks: Developer Onboarding, README Overhaul & Long-Running Autonomous Loops

**PRD**: `cOS_prds/20260317_163656_prd_i_want_this_to_be_super_easy_to_set_up_if_you_re_a_dev_you_should_be_able_to_be.md`
**Date**: 2026-03-17

## Relevant Files

- `src/colonyos/cli.py` - Add `doctor` command, modify `auto` command (remove hard cap, add `--max-hours`/`--max-budget`/`--resume-loop`), add loop state persistence
- `src/colonyos/config.py` - Add `max_duration_hours` and `max_total_usd` to `BudgetConfig`, update `DEFAULTS` and parsing
- `src/colonyos/init.py` - Add `--quick` flag, add doctor pre-check, add post-init next-step suggestion
- `src/colonyos/models.py` - Add `LoopState` dataclass for loop persistence
- `src/colonyos/orchestrator.py` - Add heartbeat file touch during phase execution
- `README.md` - Full overhaul with badges, hero section, wall of PRs, philosophy, doctor reference
- `tests/test_cli.py` - Tests for `doctor`, loop cap removal, `--max-hours`, `--max-budget`, `--resume-loop`, loop state
- `tests/test_config.py` - Tests for new `BudgetConfig` fields and backward compatibility
- `tests/test_init.py` - Tests for `--quick` flag and doctor pre-check
- `tests/test_models.py` - Tests for `LoopState` dataclass (new file)

## Tasks

- [x] 1.0 Add `colonyos doctor` command
  - [x] 1.1 Write tests in `tests/test_cli.py` for the `doctor` command: test all 5 checks pass, test each check failing individually with correct exit code, test output formatting (checkmarks/X marks), test with and without `.colonyos/config.yaml` present
  - [x] 1.2 Implement the `doctor` Click command in `src/colonyos/cli.py`: subprocess calls to check `python --version`, `claude --version`, `git --version`, `gh auth status`, and YAML parsing of config file. Print formatted pass/fail results with install instructions. Exit code 0 on all pass, 1 on any fail.
  - [x] 1.3 Extract doctor checks into a reusable `run_doctor_checks()` function (returns list of check results) so `init` can call it too

- [x] 2.0 Add `colonyos init --quick` flag
  - [x] 2.1 Write tests in `tests/test_init.py` for `--quick` flag: test it skips interactive prompts, test it uses first persona pack, test it creates valid config with defaults, test post-init next-step message is printed
  - [x] 2.2 Implement `--quick` flag in `src/colonyos/init.py`: when set, skip persona workshop, use first persona pack from `persona_packs.py`, use `DEFAULTS` from `config.py`, still prompt for project name/description/stack (or accept via `--name`/`--description`/`--stack` flags)
  - [x] 2.3 Add doctor pre-check to `colonyos init`: call `run_doctor_checks()` at the start, refuse to proceed if hard prerequisites (python, claude, git) are missing, warn (but continue) if `gh` is not authenticated
  - [x] 2.4 Add post-init next-step: after config is saved, print a copy-pasteable command like `Next: colonyos run "Add a health check endpoint"`

- [x] 3.0 Extend `BudgetConfig` for long-running loops
  - [x] 3.1 Write tests in `tests/test_config.py` for new `BudgetConfig` fields: test `max_duration_hours` and `max_total_usd` are parsed from YAML, test defaults when fields are missing (backward compat), test round-trip save/load with new fields
  - [x] 3.2 Add `max_duration_hours: float = 8.0` and `max_total_usd: float = 500.0` to `BudgetConfig` in `src/colonyos/config.py`. Update `DEFAULTS` dict. Update `_parse_budget()` to handle new fields gracefully when missing from YAML.

- [x] 4.0 Add `LoopState` model and persistence
  - [x] 4.1 Write tests in `tests/test_models.py` (new file) for `LoopState` dataclass: test serialization to/from JSON, test updating iteration count and aggregate cost, test loading from file, test file not found returns None
  - [x] 4.2 Implement `LoopState` dataclass in `src/colonyos/models.py` with fields: `loop_id`, `current_iteration`, `total_iterations`, `aggregate_cost_usd`, `start_time_iso`, `completed_run_ids`, `failed_run_ids`, `status` (running/completed/interrupted)
  - [x] 4.3 Add `save_loop_state()` and `load_loop_state()` functions in `src/colonyos/models.py` or `src/colonyos/orchestrator.py` that persist to `.colonyos/runs/loop_state_{loop_id}.json`

- [x] 5.0 Overhaul `auto` command for long-running loops
  - [x] 5.1 Write tests in `tests/test_cli.py` for: `--loop` with values > 10, `--max-hours` flag, `--max-budget` flag, `--resume-loop` flag, loop state file creation after each iteration, graceful exit on time cap hit, graceful exit on budget cap hit, continue-on-failure behavior (failed iteration doesn't kill the loop)
  - [x] 5.2 Remove `MAX_LOOP_ITERATIONS = 10` hard cap in `src/colonyos/cli.py`. Replace the validation with a configurable default from config (or 100 as fallback).
  - [x] 5.3 Add `--max-hours` and `--max-budget` CLI flags to the `auto` command. These override `budget.max_duration_hours` and `budget.max_total_usd` from config for the current session.
  - [x] 5.4 Implement time-based and aggregate budget guards in the auto loop: at the top of each iteration, check elapsed wall-clock time against `max_duration_hours` and aggregate cost against `max_total_usd`. Exit gracefully with a summary if either cap is hit.
  - [x] 5.5 Implement loop state persistence: create a `LoopState` at loop start, update and save after each iteration completes or fails.
  - [x] 5.6 Implement continue-on-failure: when a single iteration fails, log the failure, save loop state, and continue to the next iteration instead of `sys.exit(1)`. Mark the failed run as resumable.
  - [x] 5.7 Implement `--resume-loop` flag: load the latest loop state file, validate it, and continue from the last completed iteration with the same aggregate cost and run history.

- [x] 6.0 Add heartbeat file for external monitoring
  - [x] 6.1 Write tests in `tests/test_orchestrator.py` for heartbeat file: test file is created at phase start, test file is touched periodically, test file path is in `.colonyos/runs/heartbeat`
  - [x] 6.2 Implement heartbeat touch in `src/colonyos/orchestrator.py`: at the start of each phase and after each phase completes, touch `.colonyos/runs/heartbeat`. (Note: touching during a phase requires a background thread or callback, but touching between phases is simpler and sufficient for MVP.)

- [x] 7.0 Enhance `colonyos status` for loop awareness
  - [x] 7.1 Write tests in `tests/test_cli.py` for enhanced status: test it shows loop summary when loop state file exists, test it shows individual run details, test heartbeat staleness warning
  - [x] 7.2 Extend the `status` command in `src/colonyos/cli.py` to read loop state files and display: iterations completed/total, aggregate cost, elapsed time, list of PRs opened. Show a warning if the heartbeat file exists and is more than 5 minutes old.

- [x] 8.0 README overhaul
  - [x] 8.1 Add badge bar below logo: PyPI version badge, MIT license badge, Python 3.11+ badge, build status badge (placeholder)
  - [x] 8.2 Add "Zero to PR" hero section after the tagline: 3 commands, expected timeline, emphasis on sub-2-minute human effort
  - [x] 8.3 Add "Built by ColonyOS" section: list actual PRDs and PRs from `cOS_prds/` that the pipeline built on itself, linking to GitHub PRs where available
  - [x] 8.4 Update prerequisites section: add `colonyos doctor` as the recommended first step, recommend `pipx install colonyos` alongside `pip install`
  - [x] 8.5 Update CLI Reference table: add `doctor`, `init --quick`, `auto --max-hours`, `auto --max-budget`, `auto --resume-loop`
  - [x] 8.6 Add "Why ColonyOS?" philosophy section explaining the self-improvement loop thesis
  - [x] 8.7 Add collapsible "New to Claude Code?" section at the bottom with step-by-step Claude Code installation and authentication guide
  - [x] 8.8 Add a note about the `bypassPermissions` trust model in the prerequisites or a dedicated "Security Model" section so developers give informed consent
  - [x] 8.9 Add terminal recording placeholder (reference to future asciinema/VHS recording) in the hero section
