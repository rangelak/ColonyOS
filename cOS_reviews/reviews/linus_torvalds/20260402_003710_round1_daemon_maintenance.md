# Review: Daemon Inter-Queue Maintenance — Self-Update, Branch Sync & CI Fix

**Reviewer**: Linus Torvalds
**Branch**: `colonyos/every_time_the_daemon_detects_changes_when_start_cbbe0ac8d6`
**PRD**: `cOS_prds/20260402_003710_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Date**: 2026-04-02

---

## Summary

The overall structure is clean and the decomposition is sensible: `maintenance.py` as a pure-function library, daemon as the orchestrator. The data structures are honest — `BranchStatus` and `CIFixCandidate` are frozen dataclasses with obvious fields. Good. But there are two bugs that will bite you in production, and one requirement that's implemented as a Potemkin village.

## Critical Findings

### 1. FR-5 Maintenance Budget Is Decorative (Bug)

`_check_maintenance_budget()` checks `daily_maintenance_spend_usd >= budget` — but **nothing in the entire codebase ever increments `daily_maintenance_spend_usd`**. I searched every reference. The field exists in `DaemonState`, it serializes and deserializes correctly, the gate function works, but spend is never tracked. CI-fix items go through the normal queue and their cost is tracked against the daily budget, not the maintenance budget.

This means FR-5 ("Track maintenance spend separately", "Stop enqueuing new CI-fix items when maintenance budget is exhausted") is not implemented. The budget will always read $0.00 and the gate will never close.

### 2. Circuit Breaker Resets Itself (Bug)

The self-update circuit breaker trips after 2 consecutive rollback failures and "disables" self-update by returning early from `_check_startup_rollback()`. But it doesn't actually disable anything persistent. Here's the sequence:

1. Bad update → crash within 60s → rollback, `consecutive_failures = 1`
2. Rolled-back code → crash again → `consecutive_failures = 2` → circuit breaker trips, returns early
3. Daemon now runs old (good) code → survives 60s → `_maybe_record_uptime_good_commit()` **resets `consecutive_failures` to 0**
4. Next maintenance cycle → `_run_maintenance_cycle()` → pulls same bad code → `self_update=True` → installs → exec → crash → back to step 1

Infinite loop. The circuit breaker is a no-op because the uptime recorder unconditionally resets the counter. The fix: when the circuit breaker trips, you need to either (a) set a flag that `_run_maintenance_cycle` checks before attempting self-update, or (b) not reset the failure counter in `_maybe_record_uptime_good_commit` when the daemon is running rolled-back code (i.e., HEAD != last_good_commit means the counter should reset, HEAD == last_good_commit after a rollback means it should not).

### 3. `.colonyos/last_good_commit` Not Gitignored

This file is runtime state (like `daemon_state.json`, `queue.json`, `runtime.lock` — all gitignored). It will show up in `git status`, get accidentally committed, and pollute diffs. Add it to `.gitignore`.

## Minor Findings

### 4. Duplicate `gh pr list` Calls

`_fetch_open_prs_for_prefix()` (branch sync) and `_fetch_open_prs_for_ci()` (CI fix) both call `gh pr list --state open` with nearly identical parameters. In a maintenance cycle that runs both, that's two GitHub API calls when one would do. Share the result.

### 5. `shell=True` in `run_self_update`

The `self_update_command` is passed to `subprocess.run(shell=True)`. The config is operator-controlled so this is acceptable for v1, but document the security implication — anyone who can write `.colonyos/config.yaml` can execute arbitrary commands as the daemon user.

### 6. `_ahead_behind` Semantics Are Swapped

`git rev-list --left-right A...B` outputs `<left>\t<right>` where left = commits in A not in B, right = commits in B not in A. So `remote_ref...origin/main` gives: left = ahead of main, right = behind main. The code assigns `ahead = int(parts[0])` and `behind = int(parts[1])` — this is correct only if "ahead" means "commits the branch has that main doesn't" and "behind" means "commits main has that the branch doesn't". The naming is correct but worth a comment since it's a common source of confusion.

## Checklist Assessment

| Item | Status | Notes |
|------|--------|-------|
| FR-1: Self-update detection | ✅ | Clean pull→compare→install→exec flow |
| FR-2: Self-update rollback | ⚠️ | Circuit breaker resets itself (bug #2) |
| FR-3: Branch sync scan | ✅ | Correct, reports diverged branches |
| FR-4: CI fix enqueueing | ✅ | Deduplication, cap, queue integration |
| FR-5: Maintenance budget | ❌ | Gate exists but spend never tracked (bug #1) |
| FR-6: Configuration | ✅ | All fields parsed, validated, serialized |
| Tests pass | ✅ | 450 pass, good coverage |
| No TODOs/placeholders | ✅ | Clean |
| No secrets committed | ✅ | |
| Error handling | ✅ | Every subprocess call wrapped, non-raising |
| Follows conventions | ✅ | Matches existing daemon patterns |

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/daemon.py]: `_check_maintenance_budget()` gates on `daily_maintenance_spend_usd` but nothing ever increments it — FR-5 budget tracking is unimplemented
- [src/colonyos/daemon.py]: `_maybe_record_uptime_good_commit()` unconditionally resets `self_update_consecutive_failures` to 0, defeating the circuit breaker — creates infinite update-crash-rollback loop
- [.gitignore]: `.colonyos/last_good_commit` is runtime state not in `.gitignore` — will be accidentally committed
- [src/colonyos/maintenance.py]: `_fetch_open_prs_for_prefix()` and `_fetch_open_prs_for_ci()` make duplicate `gh pr list` API calls — should share the result
- [src/colonyos/maintenance.py]: `run_self_update()` uses `shell=True` — acceptable for v1 but document the trust boundary

SYNTHESIS:
The code is well-organized and follows the existing daemon patterns faithfully. The decomposition into `maintenance.py` for pure logic and daemon methods for orchestration is correct. Data structures are simple and honest. Error handling is thorough — every subprocess call is wrapped. But there are two bugs that will cause production problems: the maintenance budget is a gate with no meter behind it (FR-5 is decorative), and the circuit breaker defeats itself by resetting the failure counter on uptime. The `.gitignore` omission is a minor irritant. Fix the budget tracking and the circuit breaker reset logic, add the gitignore entry, and this is ready to ship.
