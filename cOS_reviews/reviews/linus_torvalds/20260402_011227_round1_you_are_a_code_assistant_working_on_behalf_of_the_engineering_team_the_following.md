# Review by Linus Torvalds (Round 1)

---

**VERDICT: request-changes**

Here's my review as Linus Torvalds. Three issues need fixing before this ships:

### Critical Bugs

1. **FR-5 Maintenance Budget is a Potemkin Village** — `_check_maintenance_budget()` gates CI-fix enqueueing on `daily_maintenance_spend_usd >= budget`, but **nothing in the entire codebase ever increments that counter**. CI-fix items flow through the normal queue with normal budget tracking. The maintenance budget will always read $0.00 and the gate will never close. FR-5 is unimplemented.

2. **Circuit Breaker Resets Itself** — After 2 rollback failures, the circuit breaker trips and prevents rollback. But after 60s uptime, `_maybe_record_uptime_good_commit()` unconditionally resets `self_update_consecutive_failures` to 0. Next maintenance cycle → pulls same bad code → installs → exec → crash → repeat forever. The circuit breaker is a no-op.

3. **`.colonyos/last_good_commit` not gitignored** — Runtime state file will show up in `git status` and get accidentally committed.

### Minor Issues

4. Duplicate `gh pr list` API calls between branch sync and CI fix scanning — should share the result.

### What's Good

The decomposition is clean — `maintenance.py` as pure functions, daemon as orchestrator. Data structures (`BranchStatus`, `CIFixCandidate`) are frozen dataclasses with obvious fields. Error handling is thorough. 450 tests pass. The self-update pull→compare→install→exec flow is correct. Config parsing with validation is solid.

Full review written to `cOS_reviews/reviews/linus_torvalds/20260402_003710_round1_daemon_maintenance.md`.