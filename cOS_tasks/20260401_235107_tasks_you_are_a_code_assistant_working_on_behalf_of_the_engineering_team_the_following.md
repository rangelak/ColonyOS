# Tasks: Auto-Pull Latest on Branch Switch

## Relevant Files

- `src/colonyos/recovery.py` - Add `pull_branch()` helper; modify `restore_to_branch()` to pull after checkout
- `tests/test_recovery.py` - Tests for new pull logic in recovery module
- `src/colonyos/orchestrator.py` - Add pull to base-branch checkout and preflight; ensure thread-fix does NOT pull
- `tests/test_orchestrator.py` - Tests for orchestrator pull behavior
- `src/colonyos/cli.py` - Refactor `_ensure_on_main()` to use shared `pull_branch()` helper
- `tests/test_cli.py` - Tests for refactored `_ensure_on_main()`

## Tasks

- [x] 1.0 Add `pull_branch()` helper to `recovery.py` (foundation — shared pull logic)
  depends_on: []
  - [x] 1.1 Write tests for `pull_branch()` in `tests/test_recovery.py`:
    - Success case: branch has upstream, pull --ff-only succeeds
    - No upstream: `git rev-parse --abbrev-ref @{upstream}` fails → skip silently, return False
    - Pull failure (non-zero exit): returns False with error message
    - Timeout: subprocess.TimeoutExpired → returns False
    - Verify it uses `_git()` helper, not raw subprocess
  - [x] 1.2 Implement `pull_branch(repo_root: Path, timeout: int = 30) -> tuple[bool, str | None]` in `recovery.py`:
    - Check for remote tracking branch via `git rev-parse --abbrev-ref @{upstream}`
    - If no upstream, return `(False, None)` silently
    - Run `git pull --ff-only` using `_git()` helper
    - Return `(True, None)` on success, `(False, error_message)` on failure
    - Log success/failure with branch name via `_LOGGER`

- [x] 2.0 Add pull to `restore_to_branch()` in `recovery.py` (daemon entry point)
  depends_on: [1.0]
  - [x] 2.1 Write tests for `restore_to_branch()` pull behavior in `tests/test_recovery.py`:
    - After checkout, pull is attempted when `pull=True` (default)
    - Pull failure is logged as warning, does not raise, function still returns success description
    - Pull is skipped when `pull=False`
    - Pull is skipped when already on target branch (no checkout needed)
    - Never-raises contract is preserved even if pull throws unexpected exception
  - [x] 2.2 Modify `restore_to_branch()` to accept optional `pull: bool = True` parameter:
    - After successful checkout (line 325), call `pull_branch()` if `pull=True`
    - On pull failure, log warning via `_LOGGER.warning()`
    - Include pull status in return description (e.g., "Restored to main (was on feature-x), pulled latest" or "Restored to main (was on feature-x), pull failed: ...")

- [x] 3.0 Add pull to orchestrator base-branch checkout and preflight (orchestrator entry points)
  depends_on: [1.0]
  - [x] 3.1 Write tests for orchestrator pull behavior in `tests/test_orchestrator.py`:
    - Base-branch checkout: pull succeeds → pipeline continues
    - Base-branch checkout: pull fails → `PreflightError` raised
    - Base-branch checkout: `offline=True` → pull skipped
    - Preflight: pull replaces fetch+warn for main; failure adds warning (not error)
    - Preflight: `offline=True` → pull skipped entirely
    - Thread-fix checkout: verify NO pull is added (regression test)
  - [x] 3.2 Modify base-branch checkout in `run()` (~line 4210-4222):
    - After successful `git checkout base_branch`, add `pull_branch()` call gated by `if not offline`
    - On pull failure, raise `PreflightError` with clear message
  - [x] 3.3 Modify `_preflight_check()` (~line 396-428):
    - Replace the fetch + count-behind + warn pattern with: `pull_branch()` call
    - On pull failure, append warning to `warnings` list (preserve existing behavior)
    - On pull success, skip the behind-count check (pull already resolved it)
    - Gate behind `if not offline` (already in an offline guard)

- [ ] 4.0 Refactor `_ensure_on_main()` in `cli.py` to use shared helper (consistency)
  depends_on: [1.0]
  - [ ] 4.1 Write tests for refactored `_ensure_on_main()` in `tests/test_cli.py`:
    - Verify it calls `pull_branch()` from recovery module
    - Verify offline mode skips the pull (new behavior — currently missing)
    - Verify existing warn-on-failure behavior is preserved
  - [ ] 4.2 Refactor `_ensure_on_main()` to:
    - Import and call `pull_branch()` instead of raw `subprocess.run(["git", "pull", "--ff-only"])`
    - Accept optional `offline: bool = False` parameter; skip pull when True
    - Thread `offline` flag from daemon loop config into `_run_single_iteration()` → `_ensure_on_main()`

- [ ] 5.0 Integration verification and edge case testing
  depends_on: [2.0, 3.0, 4.0]
  - [ ] 5.1 Write integration-style tests verifying end-to-end pull behavior:
    - Daemon queue item: `restore_to_branch()` pulls before next item starts
    - Orchestrator `run()`: main is pulled in preflight, base branch is pulled at checkout
    - Thread-fix path: confirm no pull occurs (SHA check remains intact)
    - Offline mode: confirm zero network calls across all paths
  - [ ] 5.2 Run full test suite (`pytest`) to verify no regressions
  - [ ] 5.3 Manual smoke test: run daemon with a stale local main, verify it auto-pulls before starting next queue item
