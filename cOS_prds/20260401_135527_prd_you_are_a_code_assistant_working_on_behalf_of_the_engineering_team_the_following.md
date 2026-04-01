# PRD: Stuck Daemon Detection

## 1. Introduction / Overview

ColonyOS runs as a long-lived daemon process (`src/colonyos/daemon.py`) that processes tasks from Slack and GitHub issues through multi-phase pipelines (plan → implement → review → fix). The daemon's single-threaded main loop (`_tick()`) processes one pipeline at a time, holding `_agent_lock` for the entire duration of a pipeline run.

**The problem:** When a pipeline phase hangs — due to a stuck Claude API call, an infinite tool-use loop, or a failed asyncio cancellation — the entire main loop blocks. No heartbeats are posted, no new tasks are processed, no health status updates, and the daemon becomes a silent corpse. The existing `pipeline_timeout_seconds` (2-hour) watchdog uses a `threading.Timer` that fires `request_active_phase_cancel()`, but if cancellation is cooperative and the subprocess ignores it, the daemon remains stuck indefinitely. There is **no mechanism to detect or recover from this state**.

The orchestrator already writes a heartbeat file (`.colonyos/runs/heartbeat`) between phases via `_touch_heartbeat()` (orchestrator.py:91-95), but **nothing reads it for staleness**. The `/healthz` endpoint reports `pipeline_running: true` but not *how long* it has been running.

This feature adds an in-process watchdog thread that detects stuck pipelines and automatically recovers: canceling the stuck pipeline, marking the item as FAILED, alerting operators via Slack, and resuming the main loop.

## 2. Goals

1. **Detect stuck pipelines** — Identify when a pipeline has made no progress (no heartbeat file update) for longer than a configurable threshold while `_pipeline_running` is True.
2. **Auto-recover** — Force-cancel the stuck pipeline, mark the queue item as FAILED, reset `_pipeline_running = False`, and resume the main loop without human intervention.
3. **Alert operators** — Post a Slack notification when a stuck condition is detected and recovered from.
4. **Improve observability** — Add `started_at` to `QueueItem`, add `pipeline_started_at` and `pipeline_duration_seconds` to the `/healthz` endpoint, and emit a structured monitor event for the TUI.
5. **Zero disruption to healthy runs** — The watchdog must never fire during normal pipeline execution. False positives are unacceptable.

## 3. User Stories

- **As a daemon operator**, I want to be notified on Slack when the daemon gets stuck, so I don't have to manually check its status every few hours.
- **As a daemon operator**, I want the daemon to automatically recover from stuck pipelines, so it resumes processing work without requiring a manual restart at 3am.
- **As a developer monitoring the dashboard**, I want `/healthz` to tell me how long the current pipeline has been running, so I can spot slow or stuck runs at a glance.
- **As a developer debugging a failed run**, I want to see `started_at` on the queue item, so I can distinguish "waited 2 hours in queue then ran for 5 minutes" from "ran for 2 hours."

## 4. Functional Requirements

### FR-1: Watchdog Thread
- A dedicated `threading.Thread(daemon=True)` that wakes every 30 seconds, independent of `_agent_lock` and `_lock`.
- Checks the mtime of `.colonyos/runs/heartbeat` relative to `time.monotonic()` when `_pipeline_running` is True.
- If the heartbeat file has not been touched for longer than `watchdog_stall_seconds` (default: 1920s = phase_timeout + 120s buffer), declares the pipeline stalled.

### FR-2: Auto-Recovery
- On stall detection, the watchdog:
  1. Calls `request_active_phase_cancel()` to cancel the in-flight phase.
  2. If still stuck after a 30-second grace period, calls `request_cancel()` as a fallback.
  3. Sets `_pipeline_running = False` under `_lock`.
  4. Marks the current `QueueItem` as FAILED with error `"watchdog: no progress for N seconds"`.
  5. Persists queue state.

### FR-3: Slack Alert
- Posts a message to the daemon's Slack channel: `"⚠️ *Stuck Pipeline Detected*\nItem {item.id} ({source_type}) has been running for {duration} with no progress for {stall_duration}. Auto-recovery initiated."`
- Uses the existing `_post_slack_message()` helper. Posts with a timeout to avoid the alert itself hanging.

### FR-4: `started_at` on QueueItem
- Add `started_at: str | None = None` field to `QueueItem` (models.py:414).
- Set it to `datetime.now(timezone.utc).isoformat()` at the same point `status` is set to `RUNNING` (daemon.py:708).
- Bump `SCHEMA_VERSION` from 4 to 5.

### FR-5: Enhanced `/healthz` Endpoint
- Add `pipeline_started_at: str | None` — ISO timestamp of current pipeline start.
- Add `pipeline_duration_seconds: float | None` — wall-clock seconds since pipeline started.
- Add `pipeline_stalled: bool` — True if the watchdog has detected a stall.
- Existing `pipeline_running` field remains unchanged.

### FR-6: Monitor Event
- Emit a structured monitor event via `encode_monitor_event()` when a stall is detected, for TUI consumption.
- Event type: `"watchdog_stall_detected"` with fields: `item_id`, `stall_duration_seconds`, `action_taken`.

### FR-7: Configurable Threshold
- Add `watchdog_stall_seconds: int = 1920` to `DaemonConfig` (config.py:294).
- Enforce a minimum floor of 120 seconds to prevent false positives.
- Log the configured threshold at daemon startup.

## 5. Non-Goals (Explicitly Out of Scope for v1)

- **External systemd watchdog integration** (`WatchdogSec=`): The in-process watchdog covers the primary failure mode. Systemd integration for hard process hangs (GIL deadlock, segfault) is deferred to v2.
- **Slack listener crash detection**: The Slack listener runs as a daemon thread with no health check. Detecting its silent death is a separate feature.
- **Abandoned thread cleanup**: Leaked worker threads (agent.py:563-568) are a symptom; the watchdog addresses the root cause by recovering the main loop.
- **Intra-phase progress tracking**: Tracking tool-use events or API responses within a single phase is desirable but adds complexity. The inter-phase heartbeat file is sufficient for v1.
- **Per-channel or per-item timeout configuration**: Global config only for v1.

## 6. Technical Considerations

### Architecture
The watchdog thread must be fully independent of `_agent_lock` (the lock held by stuck pipelines). It reads only:
- `self._pipeline_running` (a boolean, safe to read without lock)
- `self._pipeline_started_at` (a float, new field, set atomically)
- The mtime of `.colonyos/runs/heartbeat` via `os.path.getmtime()` (filesystem stat, no lock)

### Heartbeat File as Progress Signal
The orchestrator's `_touch_heartbeat()` (orchestrator.py:91-95) is called between every phase transition. During a single long phase (e.g., a 25-minute implement phase), the file goes stale — this is expected. The `watchdog_stall_seconds` threshold (default 1920s = 32 minutes) accounts for this by exceeding the phase timeout (1800s), giving the existing phase-level timeout a chance to fire first. The watchdog is a **second layer of defense** that catches cases where the phase timeout itself fails.

### Interaction with Existing Timeouts
| Timeout | Default | Purpose | Watchdog Relationship |
|---------|---------|---------|----------------------|
| `phase_timeout_seconds` | 1800s (30min) | Cancels a single hung phase | Fires first; watchdog is backup |
| `pipeline_timeout_seconds` | 7200s (2hr) | Cancels entire pipeline | Hard ceiling; watchdog fires earlier for stalls |
| `watchdog_stall_seconds` | 1920s (32min) | Detects progress stalls | Between phase and pipeline timeouts |

### Data Integrity
`started_at` must be set atomically with the `RUNNING` status transition inside the existing `with self._lock:` block (daemon.py:703-710). This ensures no crash can leave an item marked RUNNING without a `started_at` timestamp.

### Existing Files to Modify
- `src/colonyos/daemon.py` — Watchdog thread, `_pipeline_started_at`, recovery logic, enhanced `get_health()`
- `src/colonyos/models.py` — `QueueItem.started_at`, `SCHEMA_VERSION` bump
- `src/colonyos/config.py` — `DaemonConfig.watchdog_stall_seconds`
- `tests/test_daemon.py` — Tests for all new behavior

### Persona Consensus & Tensions

**Unanimous agreement across all 7 personas:**
- The main-loop-blocking scenario (stuck pipeline holding `_agent_lock`) is the highest-priority failure mode
- `started_at` on `QueueItem` is a trivial, high-value addition
- The watchdog must be an in-process daemon thread for v1
- Slack alert is the primary notification channel

**Area of tension: Heartbeat file vs. tick-time tracking**
- **Michael Seibel, Steve Jobs, Andrej Karpathy** favor using the existing `_touch_heartbeat()` file mtime — it's already wired, just needs a reader.
- **Jony Ive, Linus Torvalds, Security Engineer** prefer a daemon-level `_last_tick_time` monotonic timestamp, arguing the heartbeat file only fires between phases and goes stale during long phases.
- **Resolution:** Use the heartbeat file as the primary signal with a threshold (1920s) that exceeds the phase timeout, so intra-phase staleness is not misinterpreted. This avoids adding a new signaling mechanism while providing correct detection. The `_pipeline_started_at` monotonic timestamp provides a wall-clock anchor for duration reporting.

**Area of tension: Detection-only vs. auto-recovery in v1**
- **Linus Torvalds, Security Engineer** prefer detection-only in v1 — "you cannot write correct recovery code until you understand actual failure modes from production data."
- **Michael Seibel, Steve Jobs, Jony Ive, PSE, Karpathy** favor auto-recovery — "detection without recovery means you get an alert at 3am and the daemon is dead until a human wakes up."
- **Resolution:** Include auto-recovery in v1 using the existing cancellation infrastructure (`request_active_phase_cancel` + `request_cancel`). The recovery is conservative: cancel → wait → force-reset `_pipeline_running` → mark FAILED. No thread killing or process restart.

**Security considerations (Staff Security Engineer):**
- The heartbeat file at `.colonyos/runs/heartbeat` is writable by the Claude CLI subprocess; a malicious instruction could keep touching it to mask a hang. The watchdog should use the heartbeat file mtime as a signal but also track `_pipeline_started_at` as a wall-clock ceiling that cannot be spoofed.
- The `/healthz` stuck-detection additions must not leak queue item contents or source values.
- Configurable thresholds must have enforced minimums to prevent misconfiguration.

## 7. Success Metrics

- **Zero false positives**: The watchdog never fires during healthy pipeline runs in production.
- **Stuck recovery**: Any stuck pipeline is detected and recovered from within `watchdog_stall_seconds + 30s` (grace period).
- **Operator awareness**: 100% of stuck events result in a Slack alert within 60 seconds of detection.
- **Observability**: `/healthz` includes pipeline duration for all running pipelines.
- **No regressions**: All existing tests pass; new tests cover watchdog detection, recovery, alerting, config validation, and QueueItem `started_at`.

## 8. Open Questions

1. **Should the watchdog also enforce a hard wall-clock ceiling** independent of the heartbeat file? (e.g., if `_pipeline_started_at` exceeds `pipeline_timeout_seconds`, force-kill regardless of heartbeat freshness) — this would provide defense against heartbeat file spoofing, as the Security Engineer suggested.
2. **Should we add `finished_at` to QueueItem alongside `started_at`?** — Karpathy suggested this for duration metrics. Low cost, but not strictly needed for stuck detection.
3. **What happens if the watchdog's Slack alert itself hangs?** — The alert should use a timeout (e.g., 10 seconds) to prevent the watchdog thread from blocking on Slack API.
