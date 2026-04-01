# Review by Linus Torvalds (Round 1)

---

## Linus Torvalds — Review Round 1: Stuck Daemon Detection (Watchdog)

All 7 functional requirements implemented. 377 tests pass, 0 failures, 38 new.

### The architecture is correct

The whole feature hinges on one decision: the watchdog thread never touches `_agent_lock` — the lock held by stuck pipelines. It reads three unlocked fields (`_pipeline_running`, `_pipeline_started_at`, heartbeat file mtime) and resets state under `self._lock` (the queue/state lock, which is *not* the lock that's stuck). This is right.

### What I liked

- **Simple data structures**: Three new fields on `Daemon` (`_pipeline_started_at`, `_pipeline_stalled`, `_current_running_item`) tell the full story. No clever abstractions, no inheritance hierarchies — just the data the watchdog needs.
- **Two-phase cancellation**: `request_active_phase_cancel()` → 30s grace → `request_cancel()` → force-reset. Conservative and correct. The grace period uses `_stop_event.wait(30)` so shutdown aborts cleanly.
- **Every external call in recovery is independently try/excepted**: Slack failure doesn't prevent cancellation, cancellation failure doesn't prevent state reset. The force-reset under `self._lock` at the end is the hard guarantee.
- **~4:1 test-to-code ratio** with proper coverage: thread lifecycle, stall detection, false-positive prevention, grace-period fallback, Slack failure resilience, monitor events, end-to-end integration.

### Non-blocking findings

1. **Dead `None` check** (daemon.py:1731): `stall_seconds` is typed `int = 1920` and clamped to ≥120 during parsing. Can never be `None`. Delete it.
2. **Dead `is not None` check** (daemon.py:1700-1702): `_start_watchdog_thread()` always assigns the field.
3. **No explicit Slack timeout**: `_post_slack_message` could block if the Slack API hangs. The try/except catches exceptions but not infinite blocking. Fine for v1, add a timeout in v2.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/daemon.py:1731]: Dead `None` check on `stall_seconds` — field is always `int`, never `None`
- [src/colonyos/daemon.py:1700-1702]: Dead `is not None` check on `_watchdog_thread`
- [src/colonyos/daemon.py:1795]: `_post_slack_message` has no explicit timeout — v2 hardening opportunity
- [src/colonyos/daemon.py:1821-1829]: Force-reset correctly uses `self._lock` (not `_agent_lock`) — key architectural correctness

SYNTHESIS:
~162 lines of production code across 4 files. The code is simple, obvious, and does exactly what the PRD says. The watchdog is fully independent of the locks that stuck pipelines hold. The recovery path is defensive without being paranoid. 377 tests pass. Ship it.