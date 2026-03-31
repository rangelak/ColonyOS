# Review: Daemon PR Sync — Principal Systems Engineer (Round 1)

**Branch**: `colonyos/add_some_step_to_the_daemon_that_looks_for_prs_t_39931c28b1`
**PRD**: `cOS_prds/20260331_131622_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Date**: 2026-03-31

---

## Checklist

### Completeness
- [x] FR-1: Fetches open PRs from OutcomeStore — `get_sync_candidates()` queries `status = 'open'`
- [x] FR-2: Uses `mergeStateStatus` via `gh pr view` — `_check_merge_state()` checks BEHIND/DIRTY
- [x] FR-3: Only `colonyos/` prefix branches — `branch_name.startswith(branch_prefix)` filter
- [x] FR-4: Ephemeral worktree — creates in `.colonyos/worktrees/task-pr-sync-{N}`
- [x] FR-5: `git merge origin/main --no-edit` — clean merge pushes, conflict aborts
- [x] FR-6: 1 PR per tick — returns after first sync attempt
- [x] FR-7: Skips RUNNING queue items — checks `running_branches` set
- [x] FR-8: Conflict handling — `git merge --abort`, worktree teardown
- [x] FR-9: Slack + PR comment on conflict — with conflicting file list
- [x] FR-10: Tracks `last_sync_at`/`sync_failures` in SQLite, retry cap via `max_sync_failures`
- [x] FR-11: Does NOT touch `consecutive_failures` counter — isolated in its own try/except
- [x] FR-12: `PRSyncConfig` with `enabled=False`, `interval_minutes=60`, `max_sync_failures=3`
- [x] FR-13: Gated on `write_enabled` — checked in both `sync_stale_prs()` and daemon passes `dashboard_write_enabled`
- [x] FR-14: Structured logging with branch, PR#, pre/post SHA, outcome
- [x] FR-15: `last_sync_at` column added to `pr_outcomes`

### Quality
- [x] All 47 new tests pass
- [x] Code follows existing patterns (subprocess wrapping, OutcomeStore, dataclass config)
- [x] No unnecessary dependencies
- [x] No unrelated changes

### Safety
- [x] No secrets in code
- [x] Disabled by default (`enabled: False`)
- [x] Write-enabled gate
- [x] Never force-pushes
- [x] Worktree teardown in `finally` block

---

## Findings

### Must-fix (request-changes)

1. **[src/colonyos/pr_sync.py:78-82] OutcomeStore opened per-call without connection pooling or reuse**
   `sync_stale_prs()` creates a new `OutcomeStore(repo_root)` (SQLite connection) on every invocation, and `_sync_single_pr()` creates *another* one. That's 2 SQLite connections per tick for the same database. The store opened in `sync_stale_prs` is closed in a `finally` block, but the one in `_sync_single_pr` is closed in its own `finally`. This works but is wasteful and fragile — if the module is ever called from a context where `repo_root` resolves differently, you get two connections to different DBs. **Fix**: Pass the `OutcomeStore` instance from `sync_stale_prs` into `_sync_single_pr` instead of constructing a second one.

2. **[src/colonyos/pr_sync.py:332-341] `_get_current_failures()` is an O(N) full-table scan**
   This function calls `get_sync_candidates(999999)` to fetch *all* open PRs, then linear-scans for the matching `pr_number`. It's called on every failure path. This should be a direct SQL query: `SELECT sync_failures FROM pr_outcomes WHERE pr_number = ?`. At scale (dozens of open PRs), this is unnecessary work during an already-failing code path.

3. **[src/colonyos/pr_sync.py:193-203] Not using `WorktreeManager` despite PRD requirement (FR-4)**
   The PRD explicitly states: *"perform the merge in an isolated ephemeral worktree (via `WorktreeManager`)"*. The implementation manually shells out to `git worktree add/remove` instead of using the existing `WorktreeManager` class in `src/colonyos/worktree.py`. This duplicates worktree lifecycle logic (path calculation, cleanup, error handling, task-ID validation against path traversal) and misses `WorktreeManager`'s safety checks. **Fix**: Use `WorktreeManager.create_worktree()` and `WorktreeManager.remove_worktree()`.

### Should-fix (non-blocking but important)

4. **[src/colonyos/pr_sync.py:205-210] No timeout on the merge subprocess**
   The merge `subprocess.run()` call on line 205 has no `timeout` parameter. A merge on a very large repo could hang indefinitely (e.g., if origin/main has thousands of commits ahead). Every other subprocess call in the module has an explicit timeout. **Fix**: Add `timeout=120` (or configurable) to the merge call.

5. **[src/colonyos/daemon.py:597] `_last_pr_sync_time` updated unconditionally**
   The timer is updated even if `_sync_stale_prs()` raises an exception (caught by the inner try/except). This means a persistent failure (e.g., SQLite locked) will only be retried after the full interval. Consider only updating the timestamp on successful completion, so transient failures retry on the next tick.

6. **[src/colonyos/pr_sync.py:107] `_check_merge_state` makes a separate `gh pr view` call**
   FR-2 notes that `mergeStateStatus` is "already called during outcome polling" and the `_call_gh_pr_view` diff confirms it was added to the outcome polling JSON fields. But `_check_merge_state()` makes its own independent `gh pr view` call. For N candidate PRs, that's N additional GitHub API calls per sync cycle. **Consider**: Read `mergeStateStatus` from the outcome data stored during polling instead of re-querying GitHub. This reduces API calls and avoids rate-limit risk.

### Observations (no fix needed)

7. **[src/colonyos/pr_sync.py:68] Lazy import of `QueueItemStatus`** — The `from colonyos.models import QueueItemStatus` inside the function body avoids a circular import. This is fine but should be documented with a comment explaining why.

8. **[tests/test_pr_sync.py] Test coverage is thorough** — Good coverage of gate conditions, success path, conflict path, worktree lifecycle, and integration flow. The side_effect pattern for subprocess mocking is well-structured.

9. **[src/colonyos/outcomes.py] Schema migration is idempotent** — `_migrate_sync_columns()` uses `PRAGMA table_info` to check before ALTERing. Correct approach for SQLite migrations.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/pr_sync.py:78-82]: Two separate OutcomeStore instances created per sync cycle — pass instance from caller to `_sync_single_pr` instead of constructing a second one
- [src/colonyos/pr_sync.py:332-341]: `_get_current_failures()` does a full-table scan via `get_sync_candidates(999999)` instead of a direct SQL lookup by pr_number
- [src/colonyos/pr_sync.py:193-203]: Does not use `WorktreeManager` class as specified by FR-4 — manually shells out to `git worktree add/remove`, duplicating lifecycle logic and missing safety checks
- [src/colonyos/pr_sync.py:205-210]: No timeout on `git merge` subprocess call — could hang indefinitely on large repos
- [src/colonyos/daemon.py:597]: `_last_pr_sync_time` updated even when sync throws — persistent failures won't retry until next interval
- [src/colonyos/pr_sync.py:107]: Makes separate `gh pr view` API call per candidate instead of reading `mergeStateStatus` from already-polled outcome data

SYNTHESIS:
This is a well-structured implementation that correctly addresses all 15 functional requirements with good test coverage (47 tests, all passing). The architecture decisions — disabled by default, write-gated, worktree isolation, 1-PR-per-tick, exception isolation from the daemon loop — are all sound. The code follows existing project patterns and the daemon integration is clean. However, there are three issues I'd want fixed before approving: (1) the duplicated OutcomeStore connections are a resource leak pattern that will bite you in production; (2) the full-table scan in `_get_current_failures` is unnecessarily expensive on the failure path; and (3) most critically, the PRD specifies using `WorktreeManager` for worktree operations and the implementation bypasses it entirely, duplicating logic and missing safety features like task-ID validation. These are straightforward fixes that don't require architectural changes. The non-blocking findings (merge timeout, timer update semantics, redundant API calls) are worth addressing but shouldn't block the merge.
