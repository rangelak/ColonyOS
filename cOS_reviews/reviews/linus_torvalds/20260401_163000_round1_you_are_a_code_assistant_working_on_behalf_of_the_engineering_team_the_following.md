# Review: Linus Torvalds — Stuck Daemon Detection (Round 1)

**Branch:** `colonyos/add_detection_when_the_daemon_is_stuck_a1a5e19963`
**PRD:** `cOS_prds/20260401_135527_prd_...`
**Tests:** 377 passed, 0 failures

## Checklist

### Completeness
- [x] FR-1: Watchdog thread — daemon thread, 30s wake, independent of `_agent_lock`
- [x] FR-2: Auto-recovery — graceful cancel → 30s grace → force cancel → reset state → FAILED
- [x] FR-3: Slack alert — posts via `_post_slack_message()`, wrapped in try/except
- [x] FR-4: `started_at` on QueueItem — field added, schema v5, set atomically under `_lock`
- [x] FR-5: Enhanced `/healthz` — `pipeline_started_at`, `pipeline_duration_seconds`, `pipeline_stalled`
- [x] FR-6: Monitor event — `watchdog_stall_detected` with correct fields
- [x] FR-7: Configurable threshold — `watchdog_stall_seconds` with 120s floor, logged at startup
- [x] All tasks complete, no TODOs or placeholders

### Quality
- [x] 377 tests pass
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies
- [x] No unrelated changes
- [x] 7 clean commits, one per task

### Safety
- [x] No secrets or credentials
- [x] Error handling present for all failure cases in watchdog
- [x] State mutations under `_lock`

## Detailed Findings

**The data structures are right, so the code is right.** The key design decision — a watchdog thread that reads only GIL-safe primitives (`_pipeline_running`, `_pipeline_started_at`) and filesystem stats (`heartbeat` mtime), completely independent of `_agent_lock` — is correct. You cannot deadlock the watchdog against the thing it's watching. That's the whole point, and they got it right.

**Dual-condition gate is conservative and correct.** Both elapsed time AND heartbeat staleness must exceed the threshold. This means a long-running phase that's still making progress (touching the heartbeat file) won't trigger false positives. The 1920s default exceeds the 1800s phase timeout, so the phase-level cancellation gets first crack. The watchdog is genuinely a second layer of defense, not competing with the first.

**162 lines of production code across 4 files.** That's the right size for this feature. No over-engineering, no abstraction astronautics. `_watchdog_check()` is 25 lines. `_watchdog_recover()` is 50 lines. Both fit on a screen. The recovery is a straight-line sequence: emit event → slack → cancel → wait → force-cancel → reset state. No state machine, no callback hell, no clever indirection.

**Minor nits (non-blocking):**

1. `_watchdog_check` has a `if stall_seconds is None: return` guard, but `stall_seconds` comes from `self.daemon_config.watchdog_stall_seconds` which is typed `int` with a default of 1920 and a floor of 120. It can never be `None`. Dead code, but harmless — the type checker should catch it eventually.

2. `_post_slack_message()` in `_watchdog_recover` has no explicit socket timeout. If the Slack API itself hangs, the watchdog thread blocks on that call. The try/except catches exceptions but doesn't prevent hanging. This is mitigated by the Slack SDK having its own internal timeouts, and the recovery continues regardless. Acceptable for v1, but worth adding an explicit timeout in v2.

3. The `_pipeline_stalled` flag stays `True` after recovery until the next pipeline starts (where it's reset to `False`). This is arguably correct behavior — it tells you "yes, the last thing that happened was a stall" — but it means `/healthz` will show `pipeline_stalled: true` with `pipeline_running: false` until the next item runs. That's fine for observability.

4. Race between watchdog force-reset and the main thread's `finally` block: if the stuck pipeline finally wakes up after the watchdog has already reset state, both paths set the item to FAILED and clear `_pipeline_running`. They converge on the same state, so this is a cosmetic race, not a correctness bug.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/daemon.py]: `stall_seconds is None` check in `_watchdog_check` is dead code — the field is typed `int` with enforced minimum, can never be None
- [src/colonyos/daemon.py]: `_post_slack_message()` in `_watchdog_recover` has no explicit socket timeout; if Slack API hangs, watchdog thread blocks until SDK internal timeout fires. Non-blocking for v1.
- [src/colonyos/daemon.py]: `_pipeline_stalled` stays True after recovery until next pipeline start — correct but worth documenting
- [src/colonyos/daemon.py]: Benign race between watchdog force-reset and main thread finally block — both converge on FAILED state

SYNTHESIS:
This is clean, minimal, correct code. The architecture is right: an independent watchdog thread that cannot deadlock against the stuck pipeline it's monitoring, reading only GIL-safe primitives and filesystem stats. The dual-condition detection gate (elapsed time AND heartbeat staleness) is conservative — false positives are the enemy here, and this design eliminates them. 162 lines of production code, 664 lines of tests, ~4:1 test-to-production ratio. The recovery sequence is a straight-line escalation (graceful → grace period → force → reset) with every step wrapped in try/except so a failure at any point doesn't abort the recovery. The code does the simple, obvious thing at every turn. Ship it.
