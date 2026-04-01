# Principal Systems Engineer Review — Stuck Daemon Detection (Round 1)

**Branch:** `colonyos/add_detection_when_the_daemon_is_stuck_a1a5e19963`
**PRD:** `cOS_prds/20260401_135527_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Tests:** 377 passed, 0 failed

## Checklist

### Completeness
- [x] FR-1: Watchdog Thread — `daemon=True` thread, 30s wake via `_stop_event.wait(30)`, independent of `_agent_lock`
- [x] FR-2: Auto-Recovery — Graceful cancel → 30s grace → force cancel → reset state → mark FAILED
- [x] FR-3: Slack Alert — Posts via `_post_slack_message()`, wrapped in try/except for failure isolation
- [x] FR-4: `started_at` on QueueItem — Field added, schema v4→v5, set atomically under `_lock` with RUNNING transition
- [x] FR-5: Enhanced `/healthz` — `pipeline_started_at`, `pipeline_duration_seconds`, `pipeline_stalled`
- [x] FR-6: Monitor Event — `watchdog_stall_detected` with `item_id`, `stall_duration_seconds`, `action_taken`
- [x] FR-7: Configurable Threshold — `watchdog_stall_seconds` with 120s floor, logged at startup
- [x] All tasks complete, no placeholder/TODO code

### Quality
- [x] All 377 tests pass
- [x] Code follows existing project conventions (thread naming, lock discipline, error handling patterns)
- [x] No unnecessary dependencies added (uses existing `request_active_phase_cancel`, `request_cancel`, `_post_slack_message`)
- [x] No unrelated changes included — 7 clean commits, scoped to the feature
- [x] ~4:1 test-to-production ratio (664 test lines vs 162 production lines)

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive operations without safeguards
- [x] Error handling present for all failure cases in recovery path

## Analysis

### What's Right

**Lock independence is correctly architected.** The watchdog reads `_pipeline_running` (a bool, GIL-safe), `_pipeline_started_at` (a float, set atomically), and heartbeat file mtime (filesystem stat). None of these require `_agent_lock`, which is precisely the lock held by the stuck pipeline. This is the critical design decision and it's correct.

**Dual-condition detection prevents false positives.** Both elapsed time AND heartbeat staleness must exceed the threshold. A long-running but progressing pipeline (heartbeat refreshed between phases) won't trigger the watchdog. This is the right conservative approach — Goal 5 ("zero disruption to healthy runs") is satisfied.

**Recovery escalation ladder is sound.** `request_active_phase_cancel()` → 30s grace → `request_cancel()` → force-reset under `_lock`. The grace period uses `_stop_event.wait(30)`, which is interruptible during daemon shutdown — good detail.

**Three exit paths all reset state.** Success (line ~747), KeyboardInterrupt (line ~770), and exception/failure (line ~848) all clear `_pipeline_started_at` and `_current_running_item`. No state leak.

### Non-blocking Observations (v2)

1. **Slack timeout in watchdog recovery:** `_post_slack_message()` has no explicit socket timeout. If the Slack API hangs, the watchdog thread blocks during recovery. The try/except prevents a crash, and the Slack SDK has internal timeouts (~30s), but an explicit `timeout=10` on the HTTP call would be more defensive. Low risk for v1.

2. **Benign race condition on state reset:** The watchdog's force-reset (Step 4, under `_lock`) and the main thread's finally block can both set the item to FAILED and reset `_pipeline_running`. Both converge on the same terminal state, so this is cosmetically redundant but not incorrect. The `_lock` serializes the mutations.

3. **`_pipeline_stalled` flag persistence:** The flag stays `True` after recovery until the next pipeline sets it to `False`. This is arguably correct — `/healthz` should reflect "last known stall" until the next healthy run clears it. But it means a recovered daemon that's idle will report `pipeline_stalled: True` indefinitely. Consider clearing it on the next successful pipeline completion.

4. **`stall_seconds is None` guard is unreachable:** `watchdog_stall_seconds` is typed `int = 1920` with a 120 floor clamp — it can never be `None`. The guard is harmless defensive coding.

VERDICT: approve

FINDINGS:
- [src/colonyos/daemon.py]: Watchdog thread correctly avoids `_agent_lock` by reading only GIL-safe primitives and filesystem stats — architecturally sound
- [src/colonyos/daemon.py]: Dual-condition check (elapsed AND heartbeat age) prevents false positives on long-running but progressing pipelines
- [src/colonyos/daemon.py]: All three pipeline exit paths (success, interrupt, exception) correctly clear `_pipeline_started_at` and `_current_running_item`
- [src/colonyos/daemon.py]: `_post_slack_message()` in `_watchdog_recover` lacks explicit socket timeout — Slack SDK internal timeout (~30s) is the de facto ceiling; non-blocking for v1
- [src/colonyos/daemon.py]: `_pipeline_stalled` flag persists `True` after recovery until next pipeline starts — acceptable but consider clearing on successful completion in v2
- [src/colonyos/daemon.py]: `stall_seconds is None` guard on line ~169 is unreachable (typed int with floor clamp) — harmless defensive code
- [src/colonyos/models.py]: Schema v4→v5 migration is backward-compatible via `None` default on `started_at` — correct
- [tests/test_daemon.py]: 664 lines of thorough tests including failure isolation (Slack errors don't break recovery) and false-positive prevention

SYNTHESIS:
From a systems reliability perspective, this implementation is correct and well-scoped. The fundamental architectural decision — a watchdog thread that's independent of the lock held by the stuck pipeline — is the only design that can work here, and it's executed properly. The dual-condition stall detection (elapsed time AND heartbeat staleness) is the right conservative approach for an auto-recovery system where false positives would be catastrophic. The recovery escalation ladder (graceful → grace period → force → state reset) follows the standard pattern for cooperative cancellation with a hard fallback. The 162 lines of production code are appropriately minimal — no over-engineering, no unnecessary abstractions. The test coverage at ~4:1 ratio with proper emphasis on failure isolation gives me confidence this won't break at 3am. The non-blocking observations (Slack timeout, stale flag persistence, unreachable guard) are all v2 polish items. Ship it.
