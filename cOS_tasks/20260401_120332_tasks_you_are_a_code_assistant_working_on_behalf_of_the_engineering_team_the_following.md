# Tasks: Daily Slack Thread Consolidation

## Relevant Files

- `src/colonyos/config.py` - Add `notification_mode`, `daily_thread_hour`, `daily_thread_timezone` to `SlackConfig`; update `_parse_slack_config`
- `src/colonyos/daemon_state.py` - Add `daily_thread_ts`, `daily_thread_date`, `daily_thread_channel` to `DaemonState`; update `to_dict`/`from_dict`
- `src/colonyos/daemon.py` - Core changes: `_ensure_daily_thread()`, modify `_ensure_notification_thread()`, add `critical` param to `_post_slack_message()`, add `_create_daily_summary()`, route heartbeat/digest to daily thread
- `src/colonyos/slack.py` - Add `format_daily_summary()` formatting function
- `tests/test_config.py` - Tests for new `SlackConfig` fields
- `tests/test_daemon_state.py` - Tests for new `DaemonState` fields serialization round-trip
- `tests/test_daemon.py` - Tests for daily thread creation, rotation, restart recovery, critical alert routing
- `tests/test_slack.py` - Tests for `format_daily_summary()`

## Tasks

- [x] 1.0 Add configuration fields for daily thread mode
  depends_on: []
  - [x] 1.1 Write tests in `tests/test_config.py` for new `SlackConfig` fields: `notification_mode` (default `"daily"`, accepts `"per_item"`), `daily_thread_hour` (default `8`, int 0-23), `daily_thread_timezone` (default `"UTC"`, validated IANA string via `zoneinfo.ZoneInfo`)
  - [x] 1.2 Add `notification_mode: str = "daily"`, `daily_thread_hour: int = 8`, `daily_thread_timezone: str = "UTC"` fields to the `SlackConfig` dataclass in `src/colonyos/config.py`
  - [x] 1.3 Update `_parse_slack_config()` in `config.py` to read the new fields from the config dict, including timezone validation (try `ZoneInfo(tz_string)`, fall back to `"UTC"` with a warning on invalid input)
  - [x] 1.4 Update `DEFAULTS` dict in `config.py` to include the new fields under the `slack` key

- [x] 2.0 Extend DaemonState with daily thread persistence
  depends_on: []
  - [x] 2.1 Write tests in `tests/test_daemon_state.py` for `DaemonState` serialization round-trip with new fields: `daily_thread_ts` (str | None), `daily_thread_date` (str | None), `daily_thread_channel` (str | None)
  - [x] 2.2 Add `daily_thread_ts: str | None = None`, `daily_thread_date: str | None = None`, `daily_thread_channel: str | None = None` fields to `DaemonState` dataclass
  - [x] 2.3 Update `DaemonState.to_dict()` and `DaemonState.from_dict()` to include the new fields

- [x] 3.0 Create daily summary formatting function
  depends_on: []
  - [x] 3.1 Write tests in `tests/test_slack.py` for `format_daily_summary()`: test with completed items (PR links, cost), failed items (error one-liner, cost), empty periods, mixed results, and cost/queue depth display
  - [x] 3.2 Implement `format_daily_summary(completed_items: list[QueueItem], failed_items: list[QueueItem], total_cost: float, queue_depth: int, period_label: str) -> str` in `src/colonyos/slack.py`. Use the structured template format from the PRD (emoji headers, bulleted items with summary/PR/cost, spend + queue depth footer)

- [ ] 4.0 Implement daily thread lifecycle in daemon
  depends_on: [1.0, 2.0, 3.0]
  - [ ] 4.1 Write tests in `tests/test_daemon.py` for: (a) `_ensure_daily_thread()` creates a new thread when none exists, (b) reuses existing thread when date matches, (c) rotates thread at configured hour boundary, (d) recovers thread_ts from persisted DaemonState on restart, (e) creates new thread if persisted date is stale
  - [ ] 4.2 Implement `_ensure_daily_thread() -> tuple[Any, str, str] | None` in daemon.py: check if `self._state.daily_thread_date` matches today (in configured timezone), return cached `(client, channel, daily_thread_ts)` if so; otherwise create new daily thread with `format_daily_summary()` of items since last rotation, persist `daily_thread_ts`/`daily_thread_date`/`daily_thread_channel` to state
  - [ ] 4.3 Add `_should_rotate_daily_thread() -> bool` helper that checks current time against `daily_thread_hour` in the configured timezone using `zoneinfo.ZoneInfo`
  - [ ] 4.4 Add daily thread rotation check to the daemon's main loop (alongside existing heartbeat and digest checks). When rotation is due, create new daily thread with summary of the closing period

- [ ] 5.0 Route notification messages through daily thread
  depends_on: [4.0]
  - [ ] 5.1 Write tests for: (a) `_post_slack_message` routes to daily thread in daily mode, (b) `_post_slack_message` with `critical=True` always posts top-level, (c) `_ensure_notification_thread` posts intro as reply to daily thread in daily mode, (d) `_ensure_notification_thread` unchanged in per_item mode, (e) heartbeat posts to daily thread, (f) daily digest posts to daily thread
  - [ ] 5.2 Add `critical: bool = False` parameter to `_post_slack_message()`. When `notification_mode == "daily"` and `critical is False` and `self._state.daily_thread_ts` is set, post to the daily thread via `thread_ts`. Otherwise post to main channel (existing behavior)
  - [ ] 5.3 Mark critical callers: add `critical=True` to calls in `_post_auto_pause_same_error_alert` (line 2182), `_post_circuit_breaker_escalation_pause_alert` (line 2209), `_post_circuit_breaker_cooldown_notice` (line 2196), and `_pause_for_pre_execution_blocker` (line 2242)
  - [ ] 5.4 Modify `_ensure_notification_thread()`: when `notification_mode == "daily"`, call `_ensure_daily_thread()` to get the daily thread, then post the per-item intro as a reply to the daily thread. Use the reply's `ts` as `item.notification_thread_ts` so phase updates still nest correctly under the per-item sub-reply
  - [ ] 5.5 Modify `_post_heartbeat()` and `_post_daily_digest_if_due()` to use `_post_slack_message()` (they already do — just verify they route correctly through the daily thread in daily mode)

- [ ] 6.0 Implement overnight summary generation
  depends_on: [4.0]
  - [ ] 6.1 Write tests for `_create_daily_summary()`: collects completed and failed items since the last rotation time from `self._queue_state.items`, computes total cost, passes to `format_daily_summary()`
  - [ ] 6.2 Implement `_create_daily_summary() -> str` in daemon.py: filter `self._queue_state.items` for items completed/failed since the last daily thread date, categorize by status, compute aggregate cost for the period, count pending items, call `format_daily_summary()` to produce the formatted message
  - [ ] 6.3 Wire `_create_daily_summary()` into `_ensure_daily_thread()` as the opening message text for new daily threads

- [ ] 7.0 End-to-end integration and backward compatibility verification
  depends_on: [5.0, 6.0]
  - [ ] 7.1 Write integration test: daemon in `notification_mode: "daily"` processes 3 queue items, verify only 1 top-level message created (the daily thread), all item intros are replies to it, phase updates nest under item replies
  - [ ] 7.2 Write integration test: daemon in `notification_mode: "per_item"` processes 3 queue items, verify 3 top-level messages created (existing behavior preserved)
  - [ ] 7.3 Write integration test: daemon restarts mid-day, loads persisted `daily_thread_ts`, continues posting to same thread
  - [ ] 7.4 Write integration test: critical alert (auto-pause) posts to main channel even in daily mode
  - [ ] 7.5 Run full test suite (`pytest tests/ -x`) to verify no regressions
