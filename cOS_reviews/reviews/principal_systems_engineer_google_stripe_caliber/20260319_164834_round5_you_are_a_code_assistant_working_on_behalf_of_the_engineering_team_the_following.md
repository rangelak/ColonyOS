# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 5)

Now I have a comprehensive view. Let me write the review.

---

## Review: Principal Systems Engineer Perspective

### Completeness Assessment

**FR-1 (should_process_thread_fix)**: ✅ Implemented in `slack.py:158-231`. Correctly checks threaded reply, bot mention, completed parent QueueItem, bot self-message guard, allowlist, channel check.

**FR-2 (should_process_message unchanged)**: ✅ The original function is preserved; thread-fix is a separate code path.

**FR-3 (allowed_user_ids)**: ✅ Enforced in `should_process_thread_fix`.

**FR-4 (thread-to-run mapping)**: ✅ `find_parent_queue_item()` scans for `slack_ts == thread_ts` with `status == completed`.

**FR-5 (branch_name on QueueItem)**: ✅ Added to `models.py:246`.

**FR-6 (fix_rounds counter)**: ✅ Added to `models.py:247`, incremented under `state_lock` in `_handle_thread_fix`.

**FR-7 (run_thread_fix)**: ✅ Full implementation in `orchestrator.py`. Branch checkout, HEAD SHA verification, Implement→Verify→Deliver pipeline, branch restore in `finally`.

**FR-8 (skip Plan)**: ✅ No Plan phase in `run_thread_fix`.

**FR-9 (skip triage)**: ✅ No triage call in the thread-fix path.

**FR-10 (eyes + acknowledgment)**: ✅ In `_handle_thread_fix`, lines 2042-2054.

**FR-11 (SlackUI for phases)**: ✅ `_fix_ui_factory` creates `SlackUI` for thread updates.

**FR-12 (fix summary)**: ✅ `post_run_summary` called at line 2719.

**FR-13 (error messages)**: ✅ `format_fix_error`, `format_fix_round_limit` used for branch-deleted, max-rounds scenarios.

**FR-14 (max_fix_rounds_per_thread)**: ✅ In `SlackConfig`.

**FR-15 (budget enforcement)**: ✅ Fix costs count against `daily_cost_usd`, `aggregate_cost_usd`, circuit breaker.

**FR-16 (per_phase budget)**: ✅ `config.budget.per_phase` used in each phase call.

**FR-17 (max rounds message)**: ✅ Cumulative cost calculation and message posted.

**FR-18 (sanitize_slack_content)**: ✅ Called via `format_slack_as_prompt` which sanitizes.

**FR-19 (format_slack_as_prompt)**: ✅ Used in fix item creation.

**FR-20 (Slack link sanitizer)**: ✅ `strip_slack_links` in `sanitize.py`, integrated into `sanitize_slack_content`.

**FR-21 (thread_ts validation)**: ✅ `find_parent_queue_item` checks for completed parent before any work.

**parent_item_id**: ✅ Added to `QueueItem` for audit trail.

**head_sha propagation**: ✅ After fix completes, new HEAD SHA propagated to parent for multi-round support.

**Instruction templates**: ✅ `thread_fix.md` and `thread_fix_verify.md` created.

### Quality & Safety Findings

All 517 tests pass. No linter errors observed. Code follows existing patterns.

**[src/colonyos/cli.py:2051]**: `parent_item.branch_name` accessed outside `state_lock` for the acknowledgment message. This is technically a data race, but `branch_name` is a string that was set before the fix item was enqueued, and only the executor thread would modify the parent item later. The field is read-only at this point, so this is benign — but it's worth noting as a pattern to avoid going forward.

**[src/colonyos/cli.py:2676-2679]**: `_get_head_sha` is called after `run_thread_fix` returns but *before* acquiring `state_lock`. The `run_thread_fix` `finally` block restores the original branch, so `_get_head_sha` would return the HEAD of the *original* branch, not the fix branch. This is a bug — the SHA captured will be wrong for subsequent fix rounds. The function would need to either: (a) capture the SHA inside `run_thread_fix` before branch restore and return it on the RunLog, or (b) explicitly `git rev-parse origin/{branch_name}` instead of just HEAD.

**[src/colonyos/orchestrator.py:run_thread_fix]**: The `finally` block restores `original_branch`, which is the branch checked out *before* the fix started. However, if another queue item runs concurrently (shouldn't happen due to semaphore, but defense-in-depth), the original branch could have changed. The semaphore serialization makes this safe in practice.

**[src/colonyos/orchestrator.py:run_thread_fix]**: No stash-before-checkout logic, unlike the main `run()` function which stashes dirty working tree. If the implement phase leaves uncommitted changes (agent failure mid-edit), the checkout back to the original branch will fail. The error is logged but the working tree is left on the fix branch.

**[src/colonyos/sanitize.py:67]**: Slack link URLs are logged at `INFO` level. In a high-traffic Slack workspace, this could be noisy. Should be `DEBUG` with audit-specific events at `INFO`.

**[src/colonyos/slack.py:extract_raw_from_formatted_prompt]**: This reverse-engineering of `format_slack_as_prompt` output is fragile — if the format changes, this breaks silently (falls back to full string). A cleaner approach would be to store the raw prompt separately on the QueueItem. Acceptable for MVP but should be tracked.

**[src/colonyos/cli.py:2697]**: `log.phases[-1].error[:200]` — if `log.phases` is empty (possible if branch validation fails before any phase runs), the list access is guarded by `if log.phases`, so this is safe.

**No secrets in committed code**: ✅ Verified.

**Error handling**: ✅ Comprehensive — branch validation, PR state check, SHA mismatch, config load failure, all have explicit error paths.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/cli.py:2676-2679]: HEAD SHA captured after `run_thread_fix` returns, but the finally block already restored the original branch — so `_get_head_sha` returns the wrong SHA. Subsequent fix rounds will have a stale/incorrect `expected_head_sha`, causing false "force-push detected" failures. Fix: capture the post-fix HEAD SHA inside `run_thread_fix` (before branch restore) and return it on the `RunLog`, or use `git rev-parse {branch_name}` explicitly.
- [src/colonyos/orchestrator.py:run_thread_fix finally block]: No stash logic before restoring original branch. If the implement phase fails mid-edit leaving uncommitted changes, `git checkout {original_branch}` will fail and the repo is left on the fix branch. This is a 3am production hazard for the watch process — the next queue item runs on the wrong branch.
- [src/colonyos/sanitize.py:67]: Slack link audit logging at INFO level will be noisy in production. Should be DEBUG for individual URLs, with a single INFO-level summary.
- [src/colonyos/slack.py:extract_raw_from_formatted_prompt]: Fragile coupling to `format_slack_as_prompt` output format. Silent fallback means format drift won't be caught until context is polluted. Consider storing raw prompt separately on QueueItem.

SYNTHESIS:
This is a solid, well-structured implementation that covers all 21 functional requirements with defense-in-depth security measures (branch name validation at multiple layers, sanitization, SHA verification). The test suite is comprehensive (517 tests passing) and the code follows existing conventions. The two blocking issues are the HEAD SHA capture bug (which will cause false failures on multi-round fixes — the exact "3am scenario" I worry about) and the missing stash-before-restore in the thread-fix finally block (which can leave the watch process on the wrong branch after a mid-edit failure). Both are straightforward fixes: capture SHA before branch restore and add stash logic matching the main `run()` function. After those fixes, this is ready to ship.