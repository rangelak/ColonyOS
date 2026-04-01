# Tasks: Stuck Daemon Detection

## Relevant Files

- `src/colonyos/daemon.py` - Main daemon loop, `_tick()`, `_run_pipeline_for_item()`, `get_health()`, pipeline execution. Add watchdog thread, `_pipeline_started_at`, recovery logic, enhanced health endpoint.
- `src/colonyos/models.py` - `QueueItem` dataclass (line 414). Add `started_at` field, bump `SCHEMA_VERSION` to 5.
- `src/colonyos/config.py` - `DaemonConfig` dataclass (line 290). Add `watchdog_stall_seconds` config field.
- `src/colonyos/orchestrator.py` - `_touch_heartbeat()` (line 91). Read-only reference; no changes needed.
- `src/colonyos/agent.py` - `request_active_phase_cancel()`. Read-only reference for recovery calls.
- `src/colonyos/cancellation.py` - `request_cancel()`. Read-only reference for fallback recovery.
- `src/colonyos/server.py` - Dashboard `/healthz` endpoint. May need updates if health dict changes propagate.
- `tests/test_daemon.py` - Main test file for daemon behavior. Add tests for watchdog, recovery, alerting, config.
- `tests/test_models.py` - Tests for models. Add tests for `QueueItem.started_at` and schema version.
- `tests/test_config.py` - Tests for config loading. Add tests for `watchdog_stall_seconds` validation.

## Tasks

- [x] 1.0 Add `started_at` field to QueueItem and bump schema version (foundation — no dependencies)
  depends_on: []
  - [x] 1.1 Write tests in `tests/test_models.py`: assert `QueueItem` has `started_at: str | None` field defaulting to `None`, assert `SCHEMA_VERSION == 5`, assert serialization/deserialization round-trips with `started_at` present and absent (backward compatibility).
  - [x] 1.2 Add `started_at: str | None = None` field to `QueueItem` in `src/colonyos/models.py` (after `added_at`, line ~440). Bump `SCHEMA_VERSION` from 4 to 5.
  - [x] 1.3 Set `started_at` in daemon.py at the `RUNNING` transition (line 708, inside the existing `with self._lock:` block): `item.started_at = datetime.now(timezone.utc).isoformat()`.

- [ ] 2.0 Add `watchdog_stall_seconds` config field (foundation — no dependencies)
  depends_on: []
  - [ ] 2.1 Write tests in `tests/test_config.py`: assert `DaemonConfig` has `watchdog_stall_seconds` defaulting to 1920, assert loading from YAML with custom value works, assert minimum floor of 120 is enforced (values below 120 are clamped to 120).
  - [ ] 2.2 Add `watchdog_stall_seconds: int = 1920` to `DaemonConfig` in `src/colonyos/config.py` (after `pipeline_timeout_seconds`, line ~309).
  - [ ] 2.3 Add validation in config loading: if `watchdog_stall_seconds < 120`, log a warning and clamp to 120.

- [ ] 3.0 Add `_pipeline_started_at` tracking to daemon (depends on 1.0 for `started_at`)
  depends_on: [1.0]
  - [ ] 3.1 Write tests in `tests/test_daemon.py`: assert `_pipeline_started_at` is `None` when no pipeline is running, assert it is set to a monotonic timestamp when a pipeline starts, assert it is reset to `None` when a pipeline completes or fails.
  - [ ] 3.2 Add `self._pipeline_started_at: float | None = None` to `Daemon.__init__()` (line ~341, alongside `_pipeline_running`).
  - [ ] 3.3 Set `self._pipeline_started_at = time.monotonic()` at the same point `_pipeline_running = True` is set (daemon.py:709, inside the `with self._lock:` block).
  - [ ] 3.4 Reset `self._pipeline_started_at = None` at every point `_pipeline_running = False` is set (daemon.py:735 in success path, daemon.py:756+ in failure/exception paths). Audit all code paths that set `_pipeline_running = False` to ensure `_pipeline_started_at` is also reset.

- [ ] 4.0 Implement watchdog thread with stall detection and auto-recovery (core feature)
  depends_on: [2.0, 3.0]
  - [ ] 4.1 Write tests in `tests/test_daemon.py`:
    - Test that the watchdog thread starts when the daemon starts and stops when the daemon stops.
    - Test stall detection: mock `_pipeline_running = True`, set heartbeat file mtime to >1920s ago, assert watchdog calls `request_active_phase_cancel()`.
    - Test auto-recovery: after stall detection, assert `_pipeline_running` is reset to `False`, current item status is set to FAILED with appropriate error message.
    - Test no false positive: mock `_pipeline_running = True` with fresh heartbeat file mtime, assert watchdog does NOT fire.
    - Test watchdog is inactive when no pipeline is running: mock `_pipeline_running = False`, assert watchdog does not check heartbeat.
    - Test grace period: after initial cancel, if still stuck after 30s, assert `request_cancel()` is called as fallback.
  - [ ] 4.2 Add `_watchdog_loop()` method to `Daemon`:
    - Runs in a `while not self._stop_event.is_set()` loop, waking every 30 seconds via `self._stop_event.wait(30)`.
    - If `self._pipeline_running` is False, skip (no-op).
    - If `self._pipeline_running` is True, stat the heartbeat file mtime. Calculate `stall_duration = time.monotonic() - heartbeat_mtime_monotonic`. If `stall_duration > watchdog_stall_seconds`, trigger recovery.
    - Note: heartbeat file mtime is wall-clock (`os.path.getmtime`) but we need to compare against pipeline start. Use `_pipeline_started_at` as the reference: compute `time_since_last_heartbeat = time.time() - os.path.getmtime(heartbeat_path)`. If this exceeds `watchdog_stall_seconds` AND `time.monotonic() - _pipeline_started_at > watchdog_stall_seconds`, declare stall.
  - [ ] 4.3 Add `_watchdog_recover()` method:
    - Call `request_active_phase_cancel("watchdog: no progress for N seconds")`.
    - Wait 30 seconds (via `self._stop_event.wait(30)`).
    - If `_pipeline_running` is still True, call `request_cancel("watchdog: forced cancellation after grace period")`.
    - Set `_pipeline_running = False` and `_pipeline_started_at = None` under `self._lock`.
    - Mark the current running item as FAILED with error `"watchdog: no progress for {stall_duration}s"`.
    - Persist queue state.
  - [ ] 4.4 Start the watchdog thread in `Daemon.start()` (after existing thread starts, around line ~400). Store as `self._watchdog_thread`. Set `daemon=True`.
  - [ ] 4.5 Track `self._current_running_item: QueueItem | None = None` in `Daemon.__init__()`. Set it when transitioning to RUNNING, clear it when pipeline completes/fails. The watchdog needs this to mark the correct item as FAILED.

- [ ] 5.0 Add Slack alert and monitor event on stall detection (depends on watchdog)
  depends_on: [4.0]
  - [ ] 5.1 Write tests in `tests/test_daemon.py`:
    - Test that `_post_slack_message()` is called with appropriate stuck-detection message when watchdog fires.
    - Test that the Slack post uses a timeout to avoid the alert itself hanging.
    - Test that a monitor event is emitted with type `"watchdog_stall_detected"`.
  - [ ] 5.2 In `_watchdog_recover()`, call `self._post_slack_message()` with a formatted alert: `"⚠️ *Stuck Pipeline Detected*\nItem {item.id} ({source_type}) running for {duration}. No progress for {stall}s. Auto-recovery initiated."`. Wrap in a try/except with a 10-second timeout.
  - [ ] 5.3 Emit a structured monitor event via `encode_monitor_event()` with event type `"watchdog_stall_detected"`, including `item_id`, `stall_duration_seconds`, and `action_taken: "auto_cancel"`.

- [ ] 6.0 Enhance `/healthz` endpoint with pipeline duration and stall status (depends on 3.0)
  depends_on: [3.0]
  - [ ] 6.1 Write tests in `tests/test_daemon.py`:
    - Test `get_health()` returns `pipeline_started_at: None` and `pipeline_duration_seconds: None` when no pipeline is running.
    - Test `get_health()` returns correct `pipeline_started_at` ISO timestamp and `pipeline_duration_seconds` when a pipeline is running.
    - Test `get_health()` returns `pipeline_stalled: True` when watchdog has detected a stall.
  - [ ] 6.2 Add `self._pipeline_stalled: bool = False` to `Daemon.__init__()`. Set to `True` in watchdog recovery, reset to `False` when a new pipeline starts.
  - [ ] 6.3 Update `get_health()` (daemon.py:2062) to include:
    - `"pipeline_started_at"`: ISO timestamp from current running item's `started_at`, or `None`.
    - `"pipeline_duration_seconds"`: `time.monotonic() - self._pipeline_started_at` if pipeline is running, else `None`.
    - `"pipeline_stalled"`: `self._pipeline_stalled`.

- [ ] 7.0 Integration tests and startup logging (depends on all above)
  depends_on: [4.0, 5.0, 6.0]
  - [ ] 7.1 Write integration test: simulate a full stuck-pipeline scenario end-to-end:
    - Start daemon with short `watchdog_stall_seconds` (e.g., 5 seconds for testing).
    - Mock `run_pipeline_for_queue_item` to block indefinitely.
    - Mock heartbeat file with old mtime.
    - Assert: watchdog fires, item marked FAILED, Slack alert posted, `_pipeline_running` reset, daemon resumes processing next item.
  - [ ] 7.2 Add startup log line in `Daemon.start()`: `logger.info("Watchdog enabled: stall threshold=%ds", self.daemon_config.watchdog_stall_seconds)`.
  - [ ] 7.3 Run full test suite (`pytest tests/`) to confirm zero regressions.
