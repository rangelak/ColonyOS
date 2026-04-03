# Task Review: - [x] 6.0 Implement budget guard for fix iterations

## Review Complete: Task 6.0 — Budget Guard for Fix Iterations

### Consolidated Verdict: **request-changes** (unanimous, 7/7 reviewers)

All seven persona reviewers independently arrived at the same verdict. Here are the key findings:

### Critical Issues

1. **Budget threshold is wrong (F1)** — The guard checks `remaining < per_phase` but a fix cycle runs 3 phases (fix + review + decision), each costing up to `per_phase`. Should be `remaining < 3 * per_phase`. This means the guard can approve iterations that overshoot the budget.

2. **Duplicated cost computation (F2)** — The PRD specifies `log.total_cost_so_far` but no such property exists. The budget guard inlines the sum, duplicating `RunLog.mark_finished()` logic. Should be a `@property` on `RunLog`.

### High-Priority Issues

3. **Per-task review costs not tracked (F5)** — Successful per-task review results are never appended to `log.phases`, so the budget guard systematically undercounts actual spend.

4. **Double failure message (F3)** — Budget exhaustion logs "budget exhausted" then falls through to also log "all iterations exhausted," which is misleading.

5. **Test only covers trivial case (F4)** — The test has budget already negative; no boundary test where remaining is positive but insufficient for a full cycle.

### Medium Issues

6. **No config validation (F6)** — Negative `per_phase` disables the guard entirely.
7. **No structured observability (F7)** — Budget exhaustion is indistinguishable from other failures in the run log JSON.

The full review is at `cOS_reviews/20260317_review_task6_budget_guard.md`.
