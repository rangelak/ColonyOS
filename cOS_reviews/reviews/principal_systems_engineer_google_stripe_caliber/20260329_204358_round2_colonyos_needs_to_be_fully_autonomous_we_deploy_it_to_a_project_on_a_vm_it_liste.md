# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 2)

Now let me write the review. I have a comprehensive picture.

---

## Review — Principal Systems Engineer (Google/Stripe caliber)

### Assessment Summary

The implementation is **substantially complete and well-structured**. The daemon architecture follows sound patterns: single process with threading, fcntl-based PID lock, atomic write-then-rename for state, priority queue with starvation promotion, and budget/circuit breaker safety rails. The code is clean, well-documented, and all 57 tests pass. However, there are several findings that range from a **hard 3am-incident risk** (the systemd watchdog mismatch) to moderate gaps in the PRD contract.

### Checklist

| Item | Status | Notes |
|------|--------|-------|
| **FR-1**: `colonyos daemon` CLI command | ✅ | Implemented with `--max-budget`, `--max-hours`, `--verbose`, `--dry-run` |
| **FR-2**: GitHub Issue Polling | ✅ | Background polling with label filter and dedup |
| **FR-3**: Priority Queue (P0-P3) | ✅ | `QueueItem.priority`, `compute_priority()`, starvation promotion, schema v4 |
| **FR-4**: CEO Idle-Fill | ✅ | Idle-triggered with cooldown |
| **FR-5**: Cleanup Scheduling | ✅ | Time-triggered, capped at `max_cleanup_items` |
| **FR-6**: Daily Budget Enforcement | ✅ | Reset at midnight UTC, hard stop on exhaustion |
| **FR-7**: Circuit Breaker | ✅ | Consecutive failure tracking with cooldown |
| **FR-8**: Crash Recovery | ✅ | Orphaned RUNNING→FAILED, git state preservation |
| **FR-9**: Atomic State Persistence | ✅ | `atomic_write_json` with fsync + rename |
| **FR-10**: Health (`/healthz`) | ⚠️ Partial | Endpoint works (200/503), but **no Slack heartbeat posting** and **no daily digest** |
| **FR-11**: Slack Kill Switch | ❌ | `DaemonState.paused` exists but **no Slack command handler** for pause/resume/status |
| **FR-12**: DaemonConfig | ✅ | All 11 fields with validation |
| Tests pass | ✅ | 57/57 pass |
| No secrets | ✅ | Clean |
| No TODOs | ✅ | Clean |

### Critical Findings

| Severity | File | Finding |
|----------|------|---------|
| 🔴 **P0** | `deploy/colonyos-daemon.service` | `WatchdogSec=120` is set but `daemon.py` never calls `sd_notify("WATCHDOG=1")`. **systemd will kill the daemon every 2 minutes** in production. Either remove `WatchdogSec` or add `sdnotify` calls in the heartbeat/tick loop. This is a guaranteed 3am page. |
| 🔴 **P0** | `src/colonyos/daemon.py:290` | `_execute_item()` calls `from colonyos.cli import _run_pipeline_for_queue_item` — this function **does not exist** in `cli.py`. The import will raise `ImportError` on the first real execution. All tests use `dry_run=True` so this is never exercised. |
| 🟡 **P1** | `src/colonyos/daemon.py` | **FR-11 (Slack Kill Switch) is not implemented**. The `paused` field exists on `DaemonState` but there's no code that listens for "pause"/"stop"/"resume" Slack messages and sets it. The PRD explicitly calls out this as a trust-building safety mechanism. |
| 🟡 **P1** | `src/colonyos/daemon.py` | **FR-10 partial**: No Slack heartbeat posting (just logs), no daily digest at `digest_hour_utc`. The `/healthz` endpoint works but the PRD's observability story (Slack notifications at 80%/100% budget thresholds, daily summary) is missing. |
| 🟡 **P1** | `src/colonyos/daemon.py` | **No budget threshold alerting**: PRD FR-6 specifies Slack alerts at 80% and 100% budget usage. The code silently stops execution when budget is exhausted but never notifies anyone. In unattended operation, no one would know the daemon paused. |
| 🟡 **P1** | `src/colonyos/server.py` | The `/healthz` endpoint reads `daemon_state.json` from disk on every request — it has no connection to the live `Daemon` instance's in-memory state. If the daemon is slow to persist (or crashes between persist and healthz), the endpoint returns stale data. |
| 🟠 **P2** | `src/colonyos/daemon.py` | GitHub polling runs **synchronously in the main loop tick** (not a background thread as PRD specifies). If `gh issue list` hangs or takes 30s, the entire daemon scheduling loop stalls. Should be a background thread or have a subprocess timeout. |
| 🟠 **P2** | `src/colonyos/daemon.py:200-210` | Starvation promotion mutates `item.priority` in-place during `_next_pending_item()` but this mutation is only persisted if the item is subsequently picked for execution. If no item runs this tick, the promotion is lost on restart. |
| 🟠 **P2** | `src/colonyos/github.py` | `poll_new_issues()` is added but never called — `daemon.py` uses `fetch_open_issues()` directly with its own dedup logic. Dead code. |
| 🟠 **P2** | `src/colonyos/daemon.py` | Cross-channel dedup (FR-2: Slack messages containing GitHub issue URLs should normalize to `source_type="issue"`) is not implemented. A bug reported via Slack with `https://github.com/org/repo/issues/42` will be processed twice. |
| ⚪ **P3** | `src/colonyos/config.py` | `_parse_daemon_config` has very long lines (>120 chars) with repeated validation patterns. Consider a loop or helper — though this is style, not correctness. |
| ⚪ **P3** | `deploy/colonyos-daemon.service` | `ReadWritePaths` lists `/opt/colonyos/repo` twice (parent includes `.colonyos`). Minor redundancy. |

### User Feedback Integration

The user's note about **not liking worktrees for task execution** (preferring sequential execution) is already aligned with this implementation — `_try_execute_next()` runs one pipeline at a time (`_pipeline_running` flag). Good. However, I'd note that `_execute_item` imports `_run_pipeline_for_queue_item` which doesn't exist, so we can't verify whether the actual pipeline execution respects this constraint.

---

VERDICT: request-changes

FINDINGS:
- [deploy/colonyos-daemon.service]: WatchdogSec=120 set but daemon.py never sends sd_notify("WATCHDOG=1") — systemd will kill the process every 2 minutes in production
- [src/colonyos/daemon.py:290]: `_run_pipeline_for_queue_item` import from cli.py — function does not exist, will crash on first real execution (all tests bypass via dry_run=True)
- [src/colonyos/daemon.py]: FR-11 (Slack Kill Switch) is completely unimplemented — no handler for pause/resume/status commands from Slack
- [src/colonyos/daemon.py]: FR-10 partial — no Slack heartbeat posting, no daily digest, no budget threshold alerts (80%/100%) as specified in FR-6
- [src/colonyos/daemon.py]: GitHub polling runs synchronously in main loop tick — a slow/hung `gh` command blocks the entire scheduler
- [src/colonyos/daemon.py:200-210]: Starvation promotion mutates priority in-place but doesn't persist; promotion lost on restart if item isn't picked this tick
- [src/colonyos/github.py]: `poll_new_issues()` is dead code — daemon.py uses `fetch_open_issues()` directly
- [src/colonyos/daemon.py]: Cross-channel dedup (Slack message with GitHub issue URL → normalize to issue source) not implemented per FR-2
- [src/colonyos/server.py]: /healthz reads from disk file, not live daemon state — returns stale data

SYNTHESIS:
This is a solid first-pass implementation that gets the hard architectural decisions right: single-process threading model, atomic persistence, priority queue with starvation prevention, budget enforcement, circuit breaker, PID locking, and crash recovery. The test suite is well-structured and covers the core state machine logic. However, there are two P0 blockers that would cause immediate production failures: (1) the systemd watchdog will terminate the daemon every 2 minutes because no `sd_notify` calls exist, and (2) the pipeline executor function doesn't exist, meaning the first real (non-dry-run) execution will crash. Beyond those blockers, the Slack integration story is incomplete — the kill switch (FR-11) and observability notifications (FR-10 partial) are the features that build operator trust in unattended operation, and they're missing. Fix the two P0s, implement the Slack kill switch, and add basic budget threshold alerts, and this is ready to ship.
