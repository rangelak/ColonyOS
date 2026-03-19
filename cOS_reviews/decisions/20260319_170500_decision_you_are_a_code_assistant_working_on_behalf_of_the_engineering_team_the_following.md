# Decision Gate: Slack Thread Fix Requests

**Branch**: `colonyos/you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following`
**PRD**: `cOS_prds/20260319_152207_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Date**: 2026-03-19

## Persona Verdicts

| Persona | Round | Verdict |
|---------|-------|---------|
| Andrej Karpathy | 5 | APPROVE |
| Linus Torvalds | 5 | APPROVE |
| Principal Systems Engineer | 3 (final) | APPROVE |
| Principal Systems Engineer (Google/Stripe) | 5 | REQUEST-CHANGES |
| Staff Security Engineer | 5 | APPROVE |

**Tally**: 4 approve, 1 request-changes

## Findings Summary

### CRITICAL
None.

### HIGH
- **HEAD SHA capture bug** (`cli.py:2676-2679`): After `run_thread_fix()` returns, `_get_head_sha()` is called but the `finally` block has already restored the original branch. The SHA returned is from the *original* branch, not the fix branch. This wrong SHA is propagated to `parent_item.head_sha`, causing subsequent fix rounds to fail with a false "force-push detected" error. **Fix**: Use `log.preflight.head_sha` (which was correctly captured by `_save_run_log` before branch restore) instead of calling `_get_head_sha()` post-return. This is a 1-line change.
- **Missing stash before branch restore** (`orchestrator.py:run_thread_fix finally`): If the Implement phase crashes mid-edit leaving uncommitted changes, `git checkout {original_branch}` in the `finally` block will fail, leaving the watch process on the fix branch. The main `run()` function has stash logic; `run_thread_fix()` does not. **Fix**: Add the same stash-before-checkout pattern from `run()`.

### MEDIUM
- `strip_slack_links()` logs per-URL at INFO (noisy at scale) — should be DEBUG with INFO summary
- `extract_raw_from_formatted_prompt()` has fragile string-matching coupling to `format_slack_as_prompt()`
- `run_thread_fix()` has 5 copy-pasted early-return failure blocks — should extract a helper
- `_execute_fix_item()` imports private orchestrator functions (`_load_run_log`, `_get_head_sha`)

### LOW
- `QueueItem` at 17 fields — consider base+subclass in future
- `find_parent_queue_item()` is O(n) linear scan — fine at current scale
- `thread_fix.md` has redundant "checkout branch" instruction
- `fix_rounds` increment-before-enqueue has minor over-counting risk on state save failure

## Completeness

All 21 functional requirements (FR-1 through FR-21) are implemented. All task groups are complete. No placeholder or TODO code. Instruction templates created. Comprehensive test coverage (460-520 tests passing across reviewer runs, zero failures).

## Security Posture

Strong. Defense-in-depth on branch names (validated at triage, enqueue, and execution). HEAD SHA verification for force-push defense. Three-layer sanitization pipeline (Slack link strip -> XML tag strip -> role-anchoring). Re-sanitization of parent prompts at point of use. Thread-fix items go through same semaphore/budget/circuit-breaker as regular runs.

---

VERDICT: NO-GO

### Rationale
The HEAD SHA capture bug (`cli.py:2676-2679`) directly undermines multi-round fix support, which is a core feature of this PR. After a successful first fix round, the wrong SHA is propagated to the parent item, causing all subsequent fix rounds to fail with a false "force-push detected" error. Additionally, the missing stash-before-restore in `run_thread_fix()`'s finally block creates a "3am production hazard" — a mid-edit agent failure would leave the watch process on the wrong branch. Both issues were identified by the Principal Systems Engineer (Google/Stripe caliber) and are straightforward to fix.

### Unresolved Issues
- HEAD SHA captured via `_get_head_sha()` after branch restore returns wrong SHA — use `log.preflight.head_sha` instead
- `run_thread_fix()` finally block needs stash-before-checkout logic matching `run()`'s pattern

### Recommendation
Address the two HIGH findings (estimated <30 minutes of work), re-run tests, and re-submit for decision. The rest of the implementation is production-ready — no rework needed beyond these targeted fixes.
