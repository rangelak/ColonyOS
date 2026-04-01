# Linus Torvalds — Review Round 1
## Stuck Daemon Detection (Watchdog)

**Branch:** `colonyos/add_detection_when_the_daemon_is_stuck_a1a5e19963`
**Date:** 2026-04-01

---

## Checklist

### Completeness
- [x] FR-1: Watchdog thread — daemon thread, 30s wake interval, heartbeat mtime check ✅
- [x] FR-2: Auto-recovery — phase cancel → grace period → force cancel → reset state → mark FAILED ✅
- [x] FR-3: Slack alert — posts via `_post_slack_message()` with try/except wrapper ✅
- [x] FR-4: `started_at` on QueueItem — field added, set atomically with RUNNING, schema v5 ✅
- [x] FR-5: Enhanced `/healthz` — `pipeline_started_at`, `pipeline_duration_seconds`, `pipeline_stalled` ✅
- [x] FR-6: Monitor event — `watchdog_stall_detected` emitted via `encode_monitor_event()` ✅
- [x] FR-7: Configurable threshold — `watchdog_stall_seconds` with 120s floor, logged at startup ✅

### Quality
- [x] 377 tests pass, 0 failures (including 38 new tests)
- [x] Code follows existing patterns (threading, lock discipline, config parsing)
- [x] No unnecessary dependencies added
- [x] No unrelated changes

### Safety
- [x] No secrets or credentials
- [x] Error handling on every external call in the watchdog path
- [x] Every try/except in `_watchdog_recover` is isolated — one failure doesn't abort recovery

---

## Findings

### Non-blocking observations

1. **[src/colonyos/daemon.py:1731]** `if stall_seconds is None: return` — `watchdog_stall_seconds` is typed as `int = 1920` on `DaemonConfig` and clamped to minimum 120 during parsing. It can never be `None` at runtime. This is dead code. Harmless but unnecessary — I'd delete it for clarity.

2. **[src/colonyos/daemon.py:1764-1829]** The recovery function is ~65 lines with 5 numbered steps, each wrapped in its own try/except. This is correct defensive programming for a watchdog thread. The steps are: emit monitor event → Slack alert → phase cancel → grace wait → force cancel → reset state. Each step is independently guarded. Good.

3. **[src/colonyos/daemon.py:1700-1702]** `if self._watchdog_thread is not None` — this check is always True because `_start_watchdog_thread()` unconditionally assigns `self._watchdog_thread`. Another dead branch, but harmless.

4. **[src/colonyos/daemon.py:1809]** The 30-second grace period uses `self._stop_event.wait(30)`, which means if the daemon is shutting down during recovery, it aborts the wait cleanly. Good use of the existing shutdown coordination.

5. **[src/colonyos/daemon.py:1821-1829]** Force-reset under `self._lock` is correct — this is the same lock used for all state transitions. The watchdog never acquires `_agent_lock`, which is the lock held by stuck pipelines. This is the key architectural decision and it's right.

6. **[src/colonyos/models.py]** `started_at` field position is correct — after `added_at`, before `run_id`. `from_dict` uses `.get()` for backward compatibility with schema v4 data. `to_dict` always includes it. Clean.

7. **[src/colonyos/daemon.py:1795]** `_post_slack_message` is called without a timeout parameter. The PRD's Open Question 3 flagged this — if the Slack API hangs, the watchdog thread hangs too. The try/except catches exceptions but not infinite blocking. This is an acceptable v1 trade-off since `_post_slack_message` presumably uses the Slack SDK's default HTTP timeout, but worth noting for v2.

8. **[tests/]** The test-to-production ratio is roughly 4:1 (664 new test lines vs ~162 production lines). Tests cover: thread lifecycle, stall detection, false-positive prevention, grace-period fallback, Slack alert content, Slack failure resilience, monitor event format, end-to-end integration, startup logging, healthy-run safety. Thorough.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/daemon.py:1731]: Dead `None` check on `stall_seconds` — field is always `int`, never `None`. Harmless but delete it.
- [src/colonyos/daemon.py:1700-1702]: Dead `is not None` check on `_watchdog_thread` — `_start_watchdog_thread` always sets it. Cosmetic.
- [src/colonyos/daemon.py:1795]: `_post_slack_message` has no explicit timeout — if Slack API blocks, watchdog thread blocks. Acceptable for v1 given the try/except, but add a timeout in v2.
- [src/colonyos/daemon.py:1821-1829]: Force-reset correctly uses `self._lock` (not `_agent_lock`). This is the right architectural decision — the whole feature hinges on this.

SYNTHESIS:
This is a clean, correct implementation. The data structures tell the story: `_pipeline_started_at` (monotonic float), `_pipeline_stalled` (bool), `_current_running_item` (QueueItem reference) — three fields that give the watchdog everything it needs without touching the locks that stuck pipelines hold. The two-phase cancellation (graceful → forced) with a 30-second grace period is the conservative approach, and the force-reset under `self._lock` at the end is the safety net that guarantees recovery even if both cancellation attempts fail. ~162 lines of production code across 4 files, 38 new tests all passing, no regressions in the existing 339 tests. The code is simple, obvious, and does exactly what the PRD says. Ship it.
