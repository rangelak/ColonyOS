# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

Confirmed: `compute_stats()` does NOT call `compute_delivery_outcomes()` and the `delivery_outcomes` field is never populated. Now I have everything I need for the review.

---

## Review — Principal Systems Engineer

### Artifact Verification

| Artifact | Status |
|----------|--------|
| Branch `colonyos/add_a_pr_outcome_tracking_system_that_monitors_the_fate_of_prs_created_by_colony` | ✅ Exists, 10 commits |
| PRD | ✅ Present at expected path |
| Task file | ✅ Present, all 8 parent tasks / 30 sub-tasks marked complete |
| Code diff | ✅ 1,941 lines added across 15 files |

### Checklist

- [x] **Tests exist** — 654 lines of test code in `test_outcomes.py` plus additions to `test_ceo.py`, `test_config.py`, `test_daemon.py`, `test_stats.py` (334 new tests pass)
- [ ] **All tests pass** — ❌ `test_registry_sync.py::test_all_commands_in_readme` FAILS (see below)
- [ ] **All functional requirements implemented** — ❌ Two gaps (see below)
- [x] **No TODO/FIXME/placeholder code** — Clean
- [x] **No secrets or credentials** — Clean
- [x] **No unnecessary dependencies** — Uses only `gh` CLI, SQLite, existing project modules
- [x] **Error handling present** — Consistent try/except-log-continue pattern throughout
- [ ] **No unrelated changes** — ⚠️ Minor TUI scrollbar fix included

---

VERDICT: request-changes

FINDINGS:
- [README.md]: **Regression — test failure.** The new `outcomes` CLI command is registered in `cli.py` but not documented in the README CLI Reference section. This causes `test_registry_sync.py::test_all_commands_in_readme` to fail: `assert re.search('colonyos outcomes', cli_section)` returns None. 1 of 1785 tests fails. This is a gating issue.
- [src/colonyos/stats.py]: **Dead code path — FR-6.3 not wired up.** `compute_delivery_outcomes()` is defined (line 449) but never called. `compute_stats()` (line 478) does not invoke it, so `StatsResult.delivery_outcomes` is always the zero-valued default. The `render_dashboard()` guard (`if total_tracked > 0`) means the Delivery Outcomes panel will **never** render. The function, the dataclass, and the renderer exist, but the call chain is broken. This means `colonyos stats` will never show delivery outcomes — FR-6.3 is unimplemented in practice.
- [src/colonyos/orchestrator.py]: **FR-3.2 not implemented.** The PRD requires: "Also register PRs created via `run_thread_fix()` when a new PR is created." The `run_thread_fix()` function (line 3267) has no call to `_register_pr_outcome()`. PRs created through the thread-fix recovery path will not be tracked.
- [src/colonyos/outcomes.py]: **No UNIQUE constraint on `pr_number`.** If `track_pr()` is called twice for the same PR number (possible in recovery paths, daemon restarts, or retries), duplicate rows are inserted. Subsequently, `update_outcome()` uses `WHERE pr_number = ?` which updates ALL matching rows — silently corrupting data. The schema should have `UNIQUE(pr_number)` or use `INSERT OR IGNORE` / `INSERT ... ON CONFLICT`.
- [src/colonyos/outcomes.py]: **SQLite concurrency without WAL.** `OutcomeStore` opens its own `sqlite3.connect()` without enabling WAL journal mode. The daemon's `_poll_pr_outcomes()` and the orchestrator's `_register_pr_outcome()` can execute concurrently (daemon tick vs. pipeline thread). Without WAL, concurrent writes will trigger `SQLITE_BUSY`. The existing `MemoryStore` (if it also lacks WAL) may have the same latent issue, but adding a new writer increases the probability of contention. At minimum, set a `timeout` on the connection (e.g., `sqlite3.connect(..., timeout=10)`).
- [src/colonyos/tui/styles.py]: **Unrelated change.** A TUI scrollbar CSS fix (commit `9bb0114`) is bundled into this feature branch. While harmless, it should be on a separate branch to keep the PR reviewable.

SYNTHESIS:
The implementation demonstrates solid engineering in its core module design — the `OutcomeStore` class, the polling logic, the CEO prompt injection, and the daemon integration all follow existing codebase patterns faithfully. The error-handling strategy (try/except → log → continue) is applied consistently and correctly — I'd be confident this won't crash the daemon at 3am. The test coverage is thorough with 334 new tests covering happy paths, edge cases, and failure modes.

However, there are three issues that need fixing before merge: (1) the README regression causes a real test failure, (2) `compute_delivery_outcomes()` is dead code — the stats dashboard integration is wired at the rendering layer but never at the computation layer, so the feature literally doesn't work end-to-end, and (3) FR-3.2 (`run_thread_fix` integration) is missing. The SQLite concerns (no UNIQUE constraint, no WAL/timeout) are lower severity but represent data integrity risks that will bite at scale — a duplicate row from a retry will cause `update_outcome` to silently apply updates to the wrong record. I'd strongly recommend fixing the UNIQUE constraint now and adding `timeout=10` to the connection, both of which are one-line changes.