# Review by Linus Torvalds (Round 2)

All right. I've read the full PRD, reviewed every file in the diff (2,441 lines across 21 files), and run the test suite (57/57 passing). Here's my review as Linus Torvalds.

---

## Review — Linus Torvalds

### Overall

This is a **competent first implementation**. The code is straightforward, the data structures are clear, and the author resisted the urge to over-abstract. The `Daemon` class is basically a scheduling loop with a priority queue and some state persistence — which is exactly what it should be. No framework wankery, no dependency injection theater. The `atomic_write_json` using write-to-temp-then-rename is correct. The PID lock using `fcntl.flock` is correct. The priority queue is a simple sort rather than a heap, which is fine at this scale.

That said, there are real issues.

### Checklist Assessment

| Item | Status | Notes |
|------|--------|-------|
| **FR-1**: `colonyos daemon` command | ✅ | CLI added, all flags present |
| **FR-2**: GitHub Issue Polling | ✅ | `_poll_github_issues()` + `poll_new_issues()` helper in `github.py` |
| **FR-3**: Priority Queue | ✅ | `priority` field on `QueueItem`, schema v4, `compute_priority()`, starvation promotion |
| **FR-4**: CEO Idle-Fill | ✅ | Idle-based with configurable cooldown |
| **FR-5**: Cleanup Scheduling | ✅ | Periodic scan + branch cleanup, `max_cleanup_items` cap |
| **FR-6**: Daily Budget Enforcement | ✅ | Daily reset at UTC midnight, hard stop when exhausted |
| **FR-7**: Circuit Breaker | ✅ | Consecutive failure tracking, cooldown, auto-resume |
| **FR-8**: Crash Recovery | ✅ | Orphaned RUNNING → FAILED, git state preservation |
| **FR-9**: Atomic State Persistence | ✅ | `atomic_write_json()` with fsync + rename |
| **FR-10**: Health & Observability | ⚠️ Partial | `/healthz` endpoint works. Slack heartbeat posts and daily digest are **not implemented** — `_post_heartbeat()` only updates state and logs, never calls Slack. |
| **FR-11**: Slack Kill Switch | ❌ | Not implemented. No "pause"/"stop"/"resume"/"status" command handling in Slack listener. `DaemonState.paused` exists but nothing sets it from Slack. |
| **FR-12**: DaemonConfig | ✅ | All 11 fields, validation, wired into load/save |
| Tests pass | ✅ | 57/57 passing |
| No secrets | ✅ | Clean |
| No TODOs/placeholders | ⚠️ | `_slack_listener_thread` just calls existing `start_socket_mode` without daemon-aware message routing |
| Code conventions | ✅ | Follows existing patterns |

### Specific Findings

**1. FR-11 (Slack Kill Switch) is completely missing.** The PRD says recognizing "pause", "stop", "halt", "resume", "status" commands from `allowed_control_user_ids` is a functional requirement. The `DaemonState.paused` field exists, the `allowed_control_user_ids` config exists, but there is zero code that bridges Slack messages to setting `paused = True`. This is not a minor omission — the kill switch is the **primary safety mechanism** for unattended operation.

**2. FR-10 Slack heartbeat and daily digest are stubs.** `_post_heartbeat()` at line ~370 of `daemon.py` updates the timestamp and logs. It never imports the Slack client or posts anything. The PRD specifies: heartbeat every 4 hours, daily digest at a configured hour. The digest isn't even mentioned in the code. The 80% budget threshold Slack alert (FR-6) is also missing.

**3. `_poll_github_issues` duplicates `poll_new_issues`.** The daemon has its own polling method (`_poll_github_issues`) in `daemon.py` that reimplements the dedup and label filtering that `poll_new_issues()` in `github.py` already does. Pick one. The `poll_new_issues` function in `github.py` is dead code — nothing calls it.

**4. `_schedule_cleanup` calls `scan_directory` on every interval with no dedup across cycles.** The `_is_duplicate` check uses `source_value` which is the full "Refactor path (N lines...)" string, but `candidate.path` is passed to the check. These won't match — the dedup key is `candidate.path` but the enqueued `source_value` is a formatted string containing that path. Stale cleanup items will pile up.

**5. The `_pending_count` method excludes CEO and cleanup items, but `_next_pending_item` doesn't.** This means the CEO scheduler checks `_pending_count() == 0` but the executor might still be processing a CEO item's pipeline when a new CEO cycle is triggered. The intent is correct (only check user-sourced items for idle detection) but the naming is misleading.

**6. `_execute_item` imports `_run_pipeline_for_queue_item` from `cli.py`.** This is a private function being used as a public interface. If that function doesn't exist yet (it's a forward reference to code that may or may not be in the current `cli.py`), this will crash at runtime. I can't verify since the diff only shows the additions to `cli.py`, not the full file.

**7. `_parse_daemon_config` has absurdly long lines.** Every validation line is 100+ characters. Break them up. This is code that gets read during debugging.

**8. `save_config` daemon section writes all fields unconditionally (once any differs from default).** The existing pattern for other config sections is to only write non-default values. The daemon section dumps everything the moment one field changes. Minor inconsistency but it'll clutter configs.

**9. No test for the `_tick` method or main loop behavior.** The tests cover individual components well (priority selection, budget, circuit breaker, dedup, PID lock, health) but the actual scheduling logic in `_tick()` — the thing that ties it all together — has zero test coverage. You're testing the parts but not the machine.

**10. `WatchdogSec=120` in systemd unit but no sd_notify calls.** The systemd watchdog will kill the daemon after 120 seconds because nothing is sending `WATCHDOG=1` pings. Either remove `WatchdogSec` or implement the watchdog notification (via `sd_notify` or writing to `$WATCHDOG_USEC`).

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/daemon.py]: FR-11 (Slack kill switch) is completely unimplemented — `paused` state exists but nothing sets it from Slack messages
- [src/colonyos/daemon.py]: `_post_heartbeat()` never posts to Slack — FR-10 heartbeat and daily digest are logging-only stubs
- [src/colonyos/daemon.py]: Budget threshold alerts (80% and 100% Slack notifications per FR-6) are not implemented
- [src/colonyos/daemon.py]: `_poll_github_issues()` duplicates the logic in `github.py:poll_new_issues()` — dead code in github.py
- [src/colonyos/daemon.py]: `_schedule_cleanup` dedup is broken — checks `candidate.path` but `source_value` is a formatted string containing the path, so they'll never match
- [src/colonyos/daemon.py]: `_execute_item` imports `_run_pipeline_for_queue_item` (private function from cli.py) — unclear if this exists; will crash at runtime if it doesn't
- [src/colonyos/config.py]: `_parse_daemon_config` has 100+ character lines — break up the validation blocks
- [deploy/colonyos-daemon.service]: `WatchdogSec=120` set but no `sd_notify(WATCHDOG=1)` calls in daemon code — systemd will kill the process
- [tests/test_daemon.py]: No integration test for `_tick()` scheduling logic — the main loop is untested
- [src/colonyos/daemon.py]: `_slack_listener_thread` starts the existing Slack listener without any daemon-aware control command routing

SYNTHESIS:
This is a solid 80% implementation. The architecture is right — single process, multiple threads, sequential execution, priority queue with static tiers. The data structures are clean, the state persistence is crash-safe, and the tests cover the individual components well. But the remaining 20% is the safety-critical stuff: the Slack kill switch (FR-11), the budget threshold alerts, the heartbeat notifications, and the systemd watchdog integration. For a daemon designed to run unattended on a VM burning real money, the observability and kill switch features aren't optional polish — they're the difference between a tool you can trust and one you can't. Fix the kill switch, wire up the Slack notifications, remove the dead code in `github.py`, fix the cleanup dedup bug, and either implement `sd_notify` or remove `WatchdogSec`. Then this ships.