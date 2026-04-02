# Review: Daemon Inter-Queue Maintenance — Self-Update, Branch Sync & CI Fix

**Reviewer**: Principal Systems Engineer (Google/Stripe caliber)
**Branch**: `colonyos/every_time_the_daemon_detects_changes_when_start_cbbe0ac8d6`
**PRD**: `cOS_prds/20260402_003710_prd_...`
**Date**: 2026-04-02

## Checklist Assessment

### Completeness
- [x] FR-1 (Self-Update Detection & Installation): `pull_and_check_update()` + `run_self_update()` + `os.execv()` — implemented
- [x] FR-2 (Self-Update Rollback): `should_rollback()` + `_check_startup_rollback()` + circuit breaker at 2 failures — implemented
- [x] FR-3 (Branch Sync Scan): `scan_diverged_branches()` + `format_branch_sync_report()` + Slack post — implemented
- [x] FR-4 (CI Fix Enqueueing): `find_branches_with_failing_ci()` + `build_ci_fix_queue_items()` + dedup + max cap — implemented
- [x] FR-5 (Maintenance Budget Cap): `_check_maintenance_budget()` with daily reset — partially implemented (see finding below)
- [x] FR-6 (Configuration): All 5 new fields on `DaemonConfig` with defaults, parsing, validation, save/load — implemented
- [x] All task file items marked complete
- [x] No placeholder or TODO code

### Quality
- [x] All 132 new tests pass (97 maintenance + 23 daemon + 12 config)
- [x] Code follows existing project conventions (dataclass patterns, `_git()` helper mirrors `recovery._git`, error handling style)
- [x] No unnecessary dependencies added
- [x] No unrelated changes included
- [x] No linter errors introduced

### Safety
- [x] No secrets or credentials in committed code
- [x] `self_update` defaults to `False` (opt-in)
- [x] Error handling present on all subprocess calls
- [x] Circuit breaker prevents infinite rollback loops
- [x] `shell=True` on configurable command is acceptable (config file is in trusted `.colonyos/` directory)

## Findings

### P1 — Maintenance budget is never incremented

- **[src/colonyos/daemon.py:2555-2568]**: `_check_maintenance_budget()` checks `daily_maintenance_spend_usd >= budget` but **nothing in the codebase ever increments `daily_maintenance_spend_usd`**. The budget gate will always pass (spend stays at 0.0). This means the budget cap is non-functional — CI-fix items will be enqueued without limit.

  The PRD (FR-5) says: "Track maintenance spend (CI-fix items tagged with `source_type="ci-fix"`) separately." This requires hooking into the cost tracking after CI-fix queue items complete, incrementing the maintenance counter.

  **Severity**: Medium. Not a crash bug, but the budget safety mechanism is a no-op. A CI-fix loop could consume the entire daily budget.

### P2 — Branch sync report spams Slack every maintenance cycle

- **[src/colonyos/daemon.py:2430-2436]**: `scan_diverged_branches()` runs after every queue item. If branches remain diverged (which they will — we explicitly don't rebase), the same report is posted to Slack repeatedly. Over a busy day with 20+ queue items, this produces 20+ identical Slack messages.

  **Suggestion**: Add a cooldown (e.g., post at most once per hour or once per day) or deduplicate against the last-posted report. A simple approach: store the last branch sync timestamp in `DaemonState` and skip if < N hours have elapsed.

  **Severity**: Low-medium. Annoying but not dangerous.

### P3 — Maintenance cycle runs regardless of branch state

- **[src/colonyos/daemon.py:1713-1720]**: The maintenance cycle runs in the `finally` block unconditionally — even if `restore_to_branch()` threw an exception and the daemon is on a feature branch instead of `main`. In that case, `git pull --ff-only` would pull into the feature branch, which is almost certainly wrong.

  **Suggestion**: Guard the maintenance cycle on `restore_to_branch` having succeeded, or have `pull_and_check_update()` verify it's on the expected branch (main) before pulling.

  **Severity**: Medium. If `restore_to_branch` fails, the daemon is already in a degraded state, but pulling into the wrong branch makes recovery harder.

### P4 — Duplicate `gh pr list` calls

- **[src/colonyos/maintenance.py]**: `_fetch_open_prs_for_prefix()` (branch sync) and `_fetch_open_prs_for_ci()` (CI fix) both call `gh pr list --state open` with slightly different `--json` fields. In a single maintenance cycle, this makes two identical GitHub API calls. Minor inefficiency but worth noting for rate-limit-sensitive environments.

  **Severity**: Low.

### P5 — `_GH_TIMEOUT = 10` seconds may be too tight

- **[src/colonyos/maintenance.py:223]**: 10 seconds for `gh pr list --limit 100` and `gh pr checks` can be tight on repos with many PRs or slow GitHub API responses. This could cause the branch sync and CI-fix features to silently produce empty results, giving false confidence that everything is clean.

  **Severity**: Low. The error paths are handled gracefully (empty lists returned).

### Positive Observations

- **Error isolation is excellent**: Every subprocess call has timeout + exception handling. The maintenance cycle itself is wrapped in a try/except in the daemon. No single failure can take down the daemon.
- **The `should_rollback()` time-window approach is clever**: Using wall-clock uptime as a health signal is simple, deterministic, and avoids the complexity of active health checks.
- **Deduplication logic in `build_ci_fix_queue_items` is correct**: Checks against PENDING and RUNNING items, allows re-enqueue after COMPLETED items. The set-based lookup is efficient.
- **Test coverage is thorough**: Edge cases like git timeout, JSON parse failure, draft PR exclusion, and circuit breaker tripping are all tested.

## Synthesis

This is a solid, well-structured implementation that delivers the core maintenance cycle with good error isolation and sensible safety defaults. The code follows established project patterns, the test coverage is comprehensive (132 new tests, all passing), and the architecture is clean — `maintenance.py` as a pure-function module with the daemon as the orchestrator.

The two substantive issues are: (1) the maintenance budget counter is never incremented, rendering FR-5's budget cap non-functional, and (2) the maintenance cycle doesn't verify it's on `main` before pulling, which could corrupt branch state if `restore_to_branch` fails. Both are fixable with small, localized changes. The Slack spam issue (P2) is a quality-of-life concern that could be deferred to a follow-up.

Given that the budget tracking gap is a safety mechanism that doesn't actually work, I'm requesting changes to fix P1 before merge. P3 should also be addressed as it has data corruption potential.
