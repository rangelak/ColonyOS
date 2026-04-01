# Tasks: Daemon Inter-Queue Maintenance — Self-Update, Branch Sync & CI Fix

## Relevant Files

- `src/colonyos/config.py` - Add `self_update`, `self_update_command`, `maintenance_budget_usd`, `max_ci_fix_items`, `branch_sync_enabled` fields to `DaemonConfig`
- `src/colonyos/daemon.py` - Add maintenance cycle orchestration: self-update check, branch scan, CI-fix enqueueing
- `src/colonyos/daemon_state.py` - Add self-update tracking fields (`last_good_commit`, `self_update_failures`, `maintenance_spend_usd`)
- `src/colonyos/recovery.py` - Add `pull_and_check_update()` helper for git pull + SHA comparison
- `src/colonyos/maintenance.py` - **New file**: Branch sync scan logic, CI status checking, self-update execution
- `src/colonyos/ci.py` - Existing CI infrastructure reused (no changes expected, but may need minor adaption for maintenance context)
- `src/colonyos/cleanup.py` - Reference for `list_merged_branches()` pattern (no changes)
- `.colonyos/config.yaml` - Add `self_update: true` and maintenance config for the ColonyOS repo itself
- `tests/test_maintenance.py` - **New file**: Tests for all maintenance logic
- `tests/test_daemon.py` or `tests/test_cli.py` - Integration tests for daemon maintenance cycle
- `tests/test_config.py` - Tests for new config fields

## Tasks

- [x] 1.0 Add maintenance configuration fields to `DaemonConfig`
  depends_on: []
  - [x] 1.1 Write tests for new config fields: `self_update`, `self_update_command`, `maintenance_budget_usd`, `max_ci_fix_items`, `branch_sync_enabled` — verify defaults, YAML parsing, and validation
  - [x] 1.2 Add fields to `DaemonConfig` dataclass in `config.py:300`: `self_update: bool = False`, `self_update_command: str = "uv pip install ."`, `maintenance_budget_usd: float = 20.0`, `max_ci_fix_items: int = 2`, `branch_sync_enabled: bool = True`
  - [x] 1.3 Update `_parse_daemon_config()` in `config.py` to read the new fields from YAML
  - [x] 1.4 Add self-update tracking fields to `DaemonState` in `daemon_state.py`: `last_good_commit: str | None`, `self_update_consecutive_failures: int`, `daily_maintenance_spend_usd: float`, `maintenance_reset_date: str | None`

- [ ] 2.0 Implement self-update detection and installation (`maintenance.py`)
  depends_on: [1.0]
  - [ ] 2.1 Write tests for `pull_and_check_update(repo_root) -> tuple[bool, str | None, str | None]` — returns `(changed, old_sha, new_sha)`. Test cases: no changes, fast-forward success, pull failure (returns `(False, ...)` without raising), no tracking branch
  - [ ] 2.2 Write tests for `run_self_update(repo_root, command) -> bool` — runs `uv pip install .` via subprocess, returns success/failure. Test cases: success, non-zero exit code, timeout
  - [ ] 2.3 Write tests for `record_last_good_commit(repo_root, sha)` and `read_last_good_commit(repo_root) -> str | None` — file I/O to `.colonyos/last_good_commit`
  - [ ] 2.4 Write tests for `should_rollback(repo_root, startup_time) -> bool` — checks if last_good_commit differs from HEAD and process started < 60 seconds ago
  - [ ] 2.5 Implement `pull_and_check_update()` in `maintenance.py`: `git rev-parse HEAD` → `git pull --ff-only` → `git rev-parse HEAD` → compare SHAs
  - [ ] 2.6 Implement `run_self_update()` in `maintenance.py`: `subprocess.run(command, shell=True, cwd=repo_root, timeout=120)`
  - [ ] 2.7 Implement `record_last_good_commit()` and `read_last_good_commit()` in `maintenance.py`
  - [ ] 2.8 Implement `should_rollback()` in `maintenance.py`

- [ ] 3.0 Implement branch sync scan (`maintenance.py`)
  depends_on: [1.0]
  - [ ] 3.1 Write tests for `scan_diverged_branches(repo_root, prefix) -> list[BranchStatus]` where `BranchStatus` has fields: `name`, `ahead`, `behind`, `has_open_pr`, `pr_number`. Test cases: no branches, all up-to-date, some diverged, branches without PRs
  - [ ] 3.2 Write tests for `format_branch_sync_report(branches: list[BranchStatus]) -> str` — Slack-formatted summary. Test: empty list returns None, multiple branches produce readable output
  - [ ] 3.3 Implement `scan_diverged_branches()`: enumerate `colonyos/`-prefixed branches via `git branch -r --list 'origin/colonyos/*'`, compute ahead/behind with `git rev-list --count --left-right`, check open PRs via `gh pr list --head <branch>`
  - [ ] 3.4 Implement `format_branch_sync_report()`: Slack mrkdwn format with branch names, ahead/behind counts, PR links

- [ ] 4.0 Implement CI fix enqueueing (`maintenance.py`)
  depends_on: [1.0]
  - [ ] 4.1 Write tests for `find_branches_with_failing_ci(repo_root, prefix) -> list[CIFixCandidate]` where `CIFixCandidate` has: `branch`, `pr_number`, `failed_checks: list[str]`. Test cases: no PRs, all passing, some failing, draft PRs excluded
  - [ ] 4.2 Write tests for `build_ci_fix_queue_items(candidates, max_items, existing_queue) -> list[QueueItem]` — deduplication against existing queue, respects max_items cap
  - [ ] 4.3 Implement `find_branches_with_failing_ci()`: use `gh pr list --state open --json number,headRefName` then `gh pr checks <number>` for each, filter to failing
  - [ ] 4.4 Implement `build_ci_fix_queue_items()`: create `QueueItem` with `source_type="ci-fix"`, `source_value=<pr_number>`, standard priority via `compute_priority("ci-fix")`, dedup against existing items

- [ ] 5.0 Integrate maintenance cycle into daemon
  depends_on: [2.0, 3.0, 4.0]
  - [ ] 5.1 Write tests for `Daemon._run_maintenance_cycle()` — verify it calls self-update check, branch scan, CI-fix enqueue in order; verify it skips when `self_update` is False; verify it respects maintenance budget; verify exec is called after successful self-update
  - [ ] 5.2 Write tests for startup rollback: daemon detects `last_good_commit` mismatch + recent start → rolls back
  - [ ] 5.3 Write tests for self-update circuit breaker: after 2 consecutive rollbacks, self-update disabled and Slack alert sent
  - [ ] 5.4 Implement `_run_maintenance_cycle()` method in `Daemon` class: called from `_run_pipeline_for_item()` finally block (after `restore_to_branch()` at line 1681). Sequence: (1) `pull_and_check_update()`, (2) if changed and `self_update` enabled → `run_self_update()` → persist state → `os.execv()`, (3) `scan_diverged_branches()` → post to Slack, (4) `find_branches_with_failing_ci()` → `build_ci_fix_queue_items()` → enqueue
  - [ ] 5.5 Implement startup rollback check in `Daemon.start()`: before entering main loop, check `should_rollback()`. If true, checkout last good commit, reinstall, exec. If 2+ consecutive failures, disable self-update and alert.
  - [ ] 5.6 Add maintenance budget tracking: tag CI-fix queue items with `source_type="ci-fix"`, track spend in `DaemonState.daily_maintenance_spend_usd`, check against `daemon.maintenance_budget_usd` before enqueueing new items
  - [ ] 5.7 Update `last_good_commit` on successful startup (after 60 seconds of uptime, write current SHA)

- [ ] 6.0 Update ColonyOS repo config and documentation
  depends_on: [1.0]
  - [ ] 6.1 Add `self_update: true`, `maintenance_budget_usd: 20.0`, and `branch_sync_enabled: true` to `.colonyos/config.yaml` under the `daemon:` section
  - [ ] 6.2 Verify all existing tests pass with the new config fields (no regressions)
