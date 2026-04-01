# Linus Torvalds Review — Stuck Daemon Detection (Round 1)

**Branch:** `colonyos/add_detection_when_the_daemon_is_stuck_a1a5e19963`
**Tests:** 377 passed, 0 failures

## Checklist

### Completeness
- [x] FR-1: Watchdog Thread — daemon thread, 30s wake, independent of `_agent_lock`
- [x] FR-2: Auto-Recovery — graceful cancel → 30s grace → force cancel → reset → FAILED
- [x] FR-3: Slack Alert — posts via `_post_slack_message()`, wrapped in try/except
- [x] FR-4: `started_at` on QueueItem — field added, schema v5, set atomically under `_lock`
- [x] FR-5: Enhanced `/healthz` — `pipeline_started_at`, `pipeline_duration_seconds`, `pipeline_stalled`
- [x] FR-6: Monitor Event — `watchdog_stall_detected` with correct fields
- [x] FR-7: Configurable Threshold — `watchdog_stall_seconds` with 120s floor, logged at startup

### Quality
- [x] All tests pass (377/377)
- [x] No linter errors
- [x] Follows existing project conventions
- [x] No unnecessary dependencies
- [x] No unrelated changes

### Safety
- [x] No secrets or credentials
- [x] No destructive operations without safeguards
- [x] Error handling present for all failure cases

## Findings

The implementation is 162 lines of production code across 4 files, with 664 lines of tests. The data structures are right, which means the code is right.

**What's good:**

1. The watchdog thread reads only GIL-safe primitives (`bool`, `float | None`, filesystem `stat()`) — it cannot deadlock with the stuck pipeline holding `_agent_lock`. This is the single most important architectural decision and it's correct.

2. The dual-gate detection (elapsed time AND heartbeat staleness) is conservative in the right way. False positives on an auto-recovery system are worse than false negatives.

3. Every pipeline exit path (success, exception, KeyboardInterrupt) clears `_pipeline_started_at` and `_current_running_item`. I checked all three finally blocks — they're consistent.

4. The recovery function is structured as a linear sequence with each step wrapped in try/except. No step's failure prevents subsequent steps from executing. This is the correct pattern for cleanup code.

5. Config validation clamps below-minimum values with a warning instead of raising — the right call for a long-running daemon where hard failures at startup are more disruptive than clamping.

**Observations (non-blocking):**

1. `_post_slack_message()` has no explicit socket timeout — if the Slack SDK's internal timeout is long, the watchdog thread blocks for that duration during recovery. For v1 this is wrapped in try/except so it can't prevent recovery, but a 10s timeout would be better.

2. There's a benign race between the watchdog's Step 4 (force-reset under `_lock`) and the main thread's finally block doing the same thing when the cancel eventually propagates. Both converge on the same state (FAILED, `_pipeline_running = False`), so the worst case is a redundant persist. Not worth adding complexity to eliminate.

VERDICT: approve

FINDINGS:
- [src/colonyos/daemon.py]: Watchdog thread architecture is correct — reads only GIL-safe primitives, cannot deadlock with `_agent_lock`
- [src/colonyos/daemon.py]: All three pipeline exit paths consistently clear `_pipeline_started_at` and `_current_running_item`
- [src/colonyos/daemon.py]: `_post_slack_message()` lacks explicit socket timeout (non-blocking for v1, SDK has internal timeouts)
- [src/colonyos/daemon.py]: Benign race between watchdog recovery and main thread finally block — both converge on FAILED state, cosmetic only
- [src/colonyos/models.py]: Schema v4→v5 migration is backward-compatible via `None` default on `started_at`
- [src/colonyos/config.py]: Minimum floor clamp with warning is the right pattern for daemon config
- [tests/test_daemon.py]: 664 lines of tests at ~4:1 test-to-production ratio with proper failure isolation

SYNTHESIS:
This is clean, minimal, correct code. 162 lines to add a watchdog thread that detects stuck pipelines and recovers — that's the right size for this feature. The key architectural insight is that the watchdog must be independent of the lock held by the thing it's watching, and the implementation gets this right by reading only GIL-safe primitives and filesystem stats. The dual-gate detection is appropriately conservative. The recovery sequence is a linear cleanup chain where each step is isolated from the others' failures. The test coverage is thorough without being bloated. Ship it.
