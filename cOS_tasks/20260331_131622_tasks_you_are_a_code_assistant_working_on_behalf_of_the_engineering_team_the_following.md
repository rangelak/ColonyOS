# Tasks: Daemon PR Sync — Keep ColonyOS PRs Up-to-Date with Main

**PRD**: `cOS_prds/20260331_131622_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## Relevant Files

- `src/colonyos/config.py` - Add `PRSyncConfig` dataclass and wire into `DaemonConfig`; update DEFAULTS, parser, and serializer
- `src/colonyos/pr_sync.py` - **New file** — core sync logic: detect stale PRs, perform merge in worktree, push, handle failures
- `src/colonyos/daemon.py` - Add `_sync_stale_prs()` as tick concern #7, add timer state, wire to config
- `src/colonyos/outcomes.py` - Add `mergeStateStatus` to `_call_gh_pr_view` JSON fields; add `last_sync_at`/`sync_failures` columns to `pr_outcomes` table; add update/query methods
- `src/colonyos/github.py` - Add `post_pr_comment()` helper function for PR comments via `gh pr comment`
- `tests/test_config.py` - Tests for PRSyncConfig parsing, defaults, validation, and serialization
- `tests/test_pr_sync.py` - **New file** — tests for all sync logic: detection, clean merge, conflict handling, failure tracking, worktree lifecycle
- `tests/test_daemon.py` - Tests for the new `_sync_stale_prs` tick concern integration
- `tests/test_outcomes.py` - Tests for new schema columns and query methods
- `tests/test_github.py` - Tests for `post_pr_comment()` helper

## Tasks

- [x] 1.0 Configuration: Add PRSyncConfig to the config system
  depends_on: []
  - [x] 1.1 Write tests in `tests/test_config.py`: add `TestPRSyncConfig` class testing default values (`enabled=False`, `interval_minutes=60`, `max_sync_failures=3`), parsing from YAML dict, validation (interval must be >= 1, max_sync_failures must be >= 1), serialization roundtrip, and that non-default values are included in `save_config` output
  - [x] 1.2 Add `PRSyncConfig` dataclass to `src/colonyos/config.py` with fields: `enabled: bool = False`, `interval_minutes: int = 60`, `max_sync_failures: int = 3`
  - [x] 1.3 Add `pr_sync` entry to `DaemonConfig` dataclass as `pr_sync: PRSyncConfig = field(default_factory=PRSyncConfig)`
  - [x] 1.4 Add `pr_sync` defaults to the `DEFAULTS["daemon"]` dict
  - [x] 1.5 Add `_parse_pr_sync_config()` function following the pattern of `_parse_ci_fix_config()`: extract values, validate types and ranges, return `PRSyncConfig`
  - [x] 1.6 Wire `_parse_pr_sync_config()` into `_parse_daemon_config()` and add serialization in `save_config()`

- [ ] 2.0 Schema: Extend OutcomeStore with sync tracking columns
  depends_on: []
  - [ ] 2.1 Write tests in `tests/test_outcomes.py`: add `TestSyncColumns` class testing that new columns exist after init, that `update_sync_status()` correctly sets `last_sync_at`/`sync_failures`, that `get_sync_candidates()` returns only open PRs with `sync_failures < max`, and that the schema migration handles existing databases gracefully
  - [ ] 2.2 Add `last_sync_at TEXT` and `sync_failures INTEGER DEFAULT 0` columns to the `pr_outcomes` CREATE TABLE in `OutcomeStore._init_db()`. Add an ALTER TABLE migration path for existing databases (try ALTER, catch if column exists)
  - [ ] 2.3 Add `update_sync_status(pr_number, last_sync_at, sync_failures)` method to `OutcomeStore`
  - [ ] 2.4 Add `get_sync_candidates(max_failures)` method that returns open PRs where `sync_failures < max_failures`, ordered by `last_sync_at ASC NULLS FIRST` (oldest-synced first)
  - [ ] 2.5 Add `mergeStateStatus` to the `--json` field list in `_call_gh_pr_view()` and surface it in the returned dict

- [ ] 3.0 GitHub helper: Add PR comment posting function
  depends_on: []
  - [ ] 3.1 Write tests in `tests/test_github.py`: add `TestPostPRComment` class testing successful comment posting (mock subprocess), handling of `gh` CLI failure (returns False, logs warning), and timeout handling
  - [ ] 3.2 Add `post_pr_comment(repo_root: Path, pr_number: int, body: str) -> bool` function to `src/colonyos/github.py` that calls `gh pr comment {pr_number} --body {body}` via subprocess. Return True on success, False on failure. Follow the same error-handling pattern as `fetch_open_prs()` (catch FileNotFoundError, TimeoutExpired, log warnings)

- [ ] 4.0 Core sync logic: Implement pr_sync module
  depends_on: [1.0, 2.0, 3.0]
  - [ ] 4.1 Write tests in `tests/test_pr_sync.py`: comprehensive test class `TestPRSync` covering:
    - `test_skip_when_disabled` — returns early if `config.daemon.pr_sync.enabled` is False
    - `test_skip_non_colonyos_branches` — filters out PRs not matching `branch_prefix`
    - `test_skip_already_uptodate` — skips PRs where `mergeStateStatus` is not BEHIND/DIRTY
    - `test_clean_merge_success` — mocks git/gh subprocess calls for a clean merge, verifies push and `update_sync_status` called
    - `test_conflict_aborts_cleanly` — mocks merge failure, verifies `git merge --abort`, no push, Slack notification, PR comment, `sync_failures` incremented
    - `test_max_failures_skips_pr` — PR with `sync_failures >= max` is not attempted
    - `test_worktree_lifecycle` — verifies worktree is created before merge and torn down after (both success and failure paths)
    - `test_skip_branch_with_running_item` — skips PR whose branch matches a RUNNING queue item
    - `test_write_enabled_gate` — sync does nothing if write is not enabled
  - [ ] 4.2 Create `src/colonyos/pr_sync.py` with the main `sync_stale_prs()` function:
    - Accept `repo_root`, `config`, `queue_state`, `post_slack_fn` (callback), `write_enabled` flag
    - Gate on `config.daemon.pr_sync.enabled` and `write_enabled`
    - Call `OutcomeStore.get_sync_candidates(max_failures)` to get candidate PRs
    - For each candidate: check `mergeStateStatus` from latest outcome poll data, filter by `branch_prefix`, skip if branch has a RUNNING queue item
    - Process at most 1 PR per invocation (return after first sync attempt)
  - [ ] 4.3 Implement `_sync_single_pr()` helper in `pr_sync.py`:
    - `git fetch origin main` + `git fetch origin {branch}`
    - Create ephemeral worktree via `WorktreeManager` on the PR branch
    - Attempt `git merge origin/main --no-edit` in the worktree
    - On success: `git push origin {branch}`, update `OutcomeStore` with `last_sync_at=now`, `sync_failures=0`
    - On conflict: `git merge --abort`, post Slack notification, post PR comment via `post_pr_comment()`, increment `sync_failures` in OutcomeStore
    - Always: tear down worktree in a `finally` block
  - [ ] 4.4 Add structured logging for each sync operation: branch name, PR number, pre/post HEAD SHA, outcome

- [ ] 5.0 Daemon integration: Wire sync into the tick loop
  depends_on: [4.0]
  - [ ] 5.1 Write tests in `tests/test_daemon.py`: add `TestPRSync` class testing:
    - `test_sync_called_on_interval` — sync function is called when interval elapses
    - `test_sync_not_called_when_disabled` — sync function is not called when `pr_sync.enabled` is False
    - `test_sync_not_called_when_paused` — sync is skipped when daemon is paused
    - `test_sync_not_called_during_pipeline` — sync is skipped when `_pipeline_running` is True
    - `test_sync_exception_caught` — exceptions in sync do not crash the daemon
  - [ ] 5.2 Add `_last_pr_sync_time: float` instance variable to `Daemon.__init__()`, initialized to `0.0`
  - [ ] 5.3 Add `_sync_stale_prs()` method to `Daemon` class that wraps `pr_sync.sync_stale_prs()` in try/except (matching the `_poll_pr_outcomes` pattern at line 1060)
  - [ ] 5.4 Add concern #7 to `_tick()` after PR outcome polling (line 586): check interval elapsed, not paused, not pipeline running, then call `_sync_stale_prs()`
  - [ ] 5.5 Gate the sync call on `write_enabled` (the `dashboard_write_enabled` config field or `COLONYOS_WRITE_ENABLED` env var)

- [ ] 6.0 End-to-end verification and documentation
  depends_on: [5.0]
  - [ ] 6.1 Write an integration-style test in `tests/test_pr_sync.py` (`TestPRSyncIntegration`) that exercises the full flow: create OutcomeStore with a tracked PR, mock `gh pr view` returning `mergeStateStatus: "BEHIND"`, mock git subprocess calls for fetch/merge/push, verify the sync completes successfully and updates the database
  - [ ] 6.2 Add a `## PR Sync` section to `README.md` under the Daemon section documenting the feature: what it does, how to enable it, config options, and behavior on conflicts
  - [ ] 6.3 Run the full test suite (`pytest tests/`) and verify all existing tests still pass plus all new tests pass
