# Tasks: Git State Pre-flight Check

## Relevant Files

- `src/colonyos/models.py` - Add `PreflightResult` dataclass alongside existing `ResumeState` and `RunLog`; add `preflight` field to `RunLog`
- `src/colonyos/orchestrator.py` - Add `_preflight_check()` and `_resume_preflight()` functions; integrate into `run()` between branch name computation and Plan phase
- `src/colonyos/cli.py` - Add `--offline` and `--force` flags to `run` and `auto` commands; pass through to orchestrator
- `src/colonyos/github.py` - Add `check_open_pr()` function using `gh pr list --head <branch>`
- `tests/test_preflight.py` - **New file** — comprehensive tests for pre-flight logic
- `tests/test_orchestrator.py` - Update existing orchestrator tests to account for pre-flight integration
- `tests/test_cli.py` - Add tests for new `--offline` and `--force` CLI flags
- `tests/test_github.py` - Add tests for `check_open_pr()` function

## Tasks

- [x] 1.0 Add `PreflightResult` data model
  - [x] 1.1 Write tests for `PreflightResult` dataclass serialization in `tests/test_preflight.py` (construct instances, verify `to_dict()` / `from_dict()` round-trip, verify defaults)
  - [x] 1.2 Add `PreflightResult` dataclass to `src/colonyos/models.py` with fields: `current_branch: str`, `is_clean: bool`, `branch_exists: bool`, `open_pr_number: int | None`, `open_pr_url: str | None`, `main_behind_count: int | None`, `action_taken: str`, `warnings: list[str]`
  - [x] 1.3 Add optional `preflight: PreflightResult | None` field to `RunLog` dataclass; update `to_dict()` and `from_dict()` methods

- [x] 2.0 Add `check_open_pr()` to GitHub module
  - [x] 2.1 Write tests for `check_open_pr()` in `tests/test_github.py` — mock `subprocess.run` for `gh pr list` calls, test: PR found, no PR found, network timeout, `gh` not installed
  - [x] 2.2 Implement `check_open_pr(branch: str, repo_root: Path, timeout: int = 5) -> tuple[int | None, str | None]` in `src/colonyos/github.py` — returns `(pr_number, pr_url)` or `(None, None)`

- [x] 3.0 Implement core pre-flight check function
  - [x] 3.1 Write tests for `_preflight_check()` in `tests/test_preflight.py` — use `tmp_path` fixtures with real `git init` repos to test all states:
    - Clean repo on main → proceed
    - Dirty working tree → raise `click.ClickException`
    - Existing branch with no PR → warn and refuse
    - Existing branch with open PR → refuse with PR URL
    - Main behind origin/main → warn
    - `--offline` mode → skip network checks
    - `--force` mode → bypass all checks
    - Network timeout on `git fetch` → graceful degradation
  - [x] 3.2 Implement `_preflight_check(repo_root: Path, branch_name: str, config: ColonyConfig, *, offline: bool = False, force: bool = False) -> PreflightResult` in `src/colonyos/orchestrator.py`:
    - Check `git status --porcelain` for uncommitted changes
    - Check `git branch --list` for existing branch (reuse `validate_branch_exists`)
    - If branch exists, call `check_open_pr()` from `github.py`
    - Run `git fetch origin main` with 5s timeout (skip if offline)
    - Check `git rev-list --count main..origin/main` for staleness
    - Return `PreflightResult` with all findings
  - [x] 3.3 Implement `_resume_preflight(repo_root: Path, branch_name: str) -> PreflightResult` — lightweight check for resume mode: verify clean working tree only

- [x] 4.0 Integrate pre-flight into `run()` orchestrator function
  - [x] 4.1 Write integration tests in `tests/test_orchestrator.py` verifying that `run()` calls pre-flight before Plan phase and stores result on `RunLog`
  - [x] 4.2 In `run()`, insert `_preflight_check()` call between branch name computation (line ~1419) and Plan phase (line ~1428); store result on `log.preflight`
  - [x] 4.3 In `run()`, for resume path (`resume_from is not None`), call `_resume_preflight()` instead
  - [x] 4.4 Add UI output for pre-flight results — log warnings via `_log()`, show branch state in phase header

- [x] 5.0 Handle autonomous mode pre-flight
  - [x] 5.1 Write tests for autonomous mode git state handling in `tests/test_preflight.py` — verify that bad git state marks iteration as failed and continues
  - [x] 5.2 In `_run_single_iteration()` in `cli.py` (or equivalent autonomous loop), wrap `run()` call to catch pre-flight `click.ClickException`, log the error, mark iteration as failed, and continue to next iteration
  - [x] 5.3 In autonomous mode, ensure the pipeline always starts from main by adding a `git checkout main && git pull --ff-only` sequence before calling `run()` (only in auto mode, with error handling)

- [x] 6.0 Add CLI flags
  - [x] 6.1 Write tests for `--offline` and `--force` flags in `tests/test_cli.py` — verify flags are parsed and passed through to `run_orchestrator()`
  - [x] 6.2 Add `--offline` flag to `run` command in `cli.py` — passes `offline=True` to `run()` in orchestrator
  - [x] 6.3 Add `--force` flag to `run` command in `cli.py` — passes `force=True` to `run()` in orchestrator
  - [x] 6.4 Add `--offline` flag to `auto` command in `cli.py`
  - [x] 6.5 Update `run()` signature in `orchestrator.py` to accept `offline: bool = False` and `force: bool = False` parameters

- [x] 7.0 End-to-end validation
  - [x] 7.1 Run full test suite to verify no regressions
  - [x] 7.2 Verify pre-flight results appear in saved RunLog JSON files
  - [ ] 7.3 Test the happy path manually: `colonyos run "test feature"` on clean main
