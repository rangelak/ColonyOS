# Review: Daemon PR Sync — Linus Torvalds (Round 5)

**Branch**: `colonyos/add_some_step_to_the_daemon_that_looks_for_prs_t_39931c28b1`
**PRD**: `cOS_prds/20260331_131622_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Test results**: 2683/2683 passed (47 new)

---

## Assessment

### Completeness

- [x] FR-1 through FR-3 (Detection): `get_sync_candidates()` + `_check_merge_state()` + branch prefix filter
- [x] FR-4 through FR-7 (Sync Execution): Worktree isolation, merge + push, 1 PR per tick, running queue skip
- [x] FR-8 through FR-11 (Failure Handling): Abort on conflict, Slack + PR comment, failure tracking, isolated from circuit breaker
- [x] FR-12 through FR-13 (Configuration): `PRSyncConfig` dataclass, opt-in, write-enabled gate
- [x] FR-14 through FR-15 (Observability): Structured logging, `last_sync_at`/`sync_failures` columns

### What's Good

The data structures are right, which means the code is right. `OutcomeStore` with `get_sync_candidates(max_failures)` ordering by `last_sync_at IS NOT NULL, last_sync_at ASC` — that's the correct way to round-robin. NULLs first for never-synced PRs. Simple SQL, no ORM garbage.

`_sync_single_pr` follows the obvious structure: fetch, worktree, merge, push, cleanup in finally. No clever abstractions. The function does one thing and you can read it top to bottom. Good.

The config parsing follows the existing pattern (`_parse_pr_sync_config` mirrors `_parse_ci_fix_config`). That's how you maintain a codebase — do the same thing the same way everywhere.

The daemon integration is 11 lines in `_tick()` and 15 lines in `_sync_stale_prs()`. That's appropriate — a new concern should be minimal glue.

### What's Wrong

1. **`_get_current_failures` is embarrassingly stupid.** It calls `get_sync_candidates(999999)` and then does a linear scan through ALL open PRs to find one by number. That's O(n) when you could just write a `SELECT sync_failures FROM pr_outcomes WHERE pr_number = ?` query. The magic number 999999 is the kind of thing that makes me lose faith in a developer. It works, but it's lazy thinking.

2. **Two `OutcomeStore` instances in the same logical operation.** `sync_stale_prs()` opens a store, gets candidates, closes it. Then `_sync_single_pr()` opens ANOTHER store to do the update. That's two separate database connections for what should be one. Pass the store through, or better yet, have the caller manage the lifecycle. The `finally: store.close()` in `_sync_single_pr` is doing resource management that belongs to the caller.

3. **`_check_merge_state` duplicates `_call_gh_pr_view`.** The PRD explicitly says to piggyback on the `mergeStateStatus` field already being fetched in outcome polling. Instead, this code makes a SEPARATE `gh pr view` call for every candidate PR. That's unnecessary GitHub API calls. The data is already in the outcome poll results — use it. At minimum, the `_call_gh_pr_view` in outcomes.py now fetches `mergeStateStatus` but `_check_merge_state` in pr_sync.py ignores that and calls `gh` again independently.

4. **No escalation notification on max failures.** FR-10 says "After a configurable number of consecutive failures (default 3), stop retrying and **post a final escalation notification**." The code stops retrying (filtered out by `get_sync_candidates`), but never sends the escalation message. The Slack message says "manual resolution required" on every failure, but there's no distinct "I'm giving up on this PR" notification.

5. **Worktree path is hardcoded, not using `WorktreeManager`.** FR-4 and the PRD architecture section explicitly call for using `WorktreeManager`. Instead, the code manually constructs `repo_root / ".colonyos" / "worktrees" / f"task-{task_id}"` and calls raw `git worktree add/remove`. This duplicates the worktree lifecycle management that `WorktreeManager` already handles and bypasses whatever safety checks it provides.

### Non-blocking Observations

- The `except Exception: pass` in `_get_current_failures` silently swallows errors. At least log it.
- The lazy import `from colonyos.pr_sync import sync_stale_prs` inside `_sync_stale_prs` is fine for avoiding circular imports but add a comment saying why.
- The `from colonyos.models import QueueItemStatus` inside `sync_stale_prs` body is also a lazy import — same comment applies.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/pr_sync.py]: `_get_current_failures` does a linear scan with magic number 999999 instead of a direct SQL query
- [src/colonyos/pr_sync.py]: Two separate `OutcomeStore` instances opened for one logical operation — pass the store through instead of creating a new one in `_sync_single_pr`
- [src/colonyos/pr_sync.py]: `_check_merge_state` makes redundant `gh pr view` calls when `mergeStateStatus` is already fetched by outcome polling — use the cached data
- [src/colonyos/pr_sync.py]: Missing escalation notification when a PR reaches max_sync_failures (FR-10)
- [src/colonyos/pr_sync.py]: Manually constructs worktree paths instead of using `WorktreeManager` as specified by the PRD (FR-4)

SYNTHESIS:
The overall architecture is sound — the right decisions were made at the design level (merge not rebase, worktree isolation, opt-in, 1-per-tick). The code reads cleanly top to bottom, the test coverage is thorough (47 tests covering every requirement), and nothing will crash the daemon. But there are five concrete issues that need fixing. Three are about unnecessary duplication and waste (`_get_current_failures` linear scan, duplicate store instances, redundant API calls), one is a missing requirement (escalation notification), and one is ignoring the existing `WorktreeManager` abstraction that the PRD explicitly calls for. None of these are hard to fix — they're the kind of thing you get when someone writes the code in one pass without going back to read what already exists. Fix these five things and this is a clean approve.
