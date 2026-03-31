# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

Here's my review as **Principal Systems Engineer**:

---

## Review Complete — Request Changes

All 15 functional requirements are implemented and 47 new tests pass. The architecture is sound: disabled by default, write-gated, worktree isolation, 1-PR-per-tick, exception isolation from the daemon loop. However, I'm requesting changes on **3 must-fix items**:

### Must-fix

1. **Duplicated `OutcomeStore` connections** — `sync_stale_prs()` opens one, `_sync_single_pr()` opens another. Two SQLite connections per tick for the same DB is wasteful and fragile. Pass the instance from caller to callee.

2. **`_get_current_failures()` full-table scan** — Calls `get_sync_candidates(999999)` then linear-scans for the PR. This should be a direct `SELECT sync_failures FROM pr_outcomes WHERE pr_number = ?`.

3. **Not using `WorktreeManager` (FR-4 violation)** — The PRD specifies using the existing `WorktreeManager` class, but the implementation manually shells out to `git worktree add/remove`, duplicating lifecycle logic and missing safety checks (task-ID validation, path traversal protection).

### Should-fix (non-blocking)

4. No timeout on the `git merge` subprocess — could hang indefinitely
5. `_last_pr_sync_time` updated even on failure — persistent failures won't retry until next interval
6. Makes separate `gh pr view` API calls instead of reading from already-polled outcome data

---

VERDICT: **request-changes**

Review saved to `cOS_reviews/reviews/principal_systems_engineer_google_stripe_caliber/20260331_131622_round1_daemon_pr_sync.md`.