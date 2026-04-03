# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 2)

## Principal Systems Engineer Review — Complete

**VERDICT: request-changes**

### Critical Findings

1. **`head_sha` staleness bug** — After a successful fix run, the parent `QueueItem.head_sha` is never updated with the new HEAD. This means the second fix round will **always** fail the force-push detection check (SHA mismatch), making `max_fix_rounds_per_thread > 1` effectively broken.

2. **Lock-free iteration of shared mutable state** — `should_process_thread_fix` reads `queue_state.items` without holding `state_lock` while the `QueueExecutor` thread mutates the list concurrently. Pass `list(queue_state.items)` as a snapshot or acquire the lock.

### Minor Findings

3. **No early branch/PR validation at enqueue time** — User gets `:eyes:` acknowledgment, then a delayed failure minutes later when the executor discovers the branch is deleted or PR is merged. A fast `git ls-remote` check before enqueuing would improve UX.

4. **`_DualUI` duck-typing fragility** — Every method call is `type: ignore`. A `Protocol` would catch interface drift at type-check time.

### What's Good

- **Defense-in-depth**: Branch name validated in 3 layers (enqueue → execute → orchestrator), sanitization pipeline runs on all thread replies, HEAD SHA verification defends against force-push tampering.
- **Backwards compatibility**: `QueueItem` new fields have sensible defaults, deserialization is tolerant of missing keys, tested.
- **`should_process_message()` untouched**: Separate code paths as required by FR-2.
- **504 tests pass** with solid coverage of the new feature.
- **Clean architecture**: The fix pipeline correctly reuses existing infrastructure (`SlackUI`, `validate_branch_exists`, `check_open_pr`, `sanitize_slack_content`) rather than reimplementing.

### Synthesis

The implementation is well-structured and covers all 21 functional requirements. The security posture is strong. The two blocking issues are the `head_sha` propagation bug (which makes multi-round fixes reliably fail) and the unlocked shared state access. Fix those two, and this ships.

Full review written to `cOS_reviews/reviews/principal-systems-engineer/review_round_1.md`.
