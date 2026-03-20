# Tasks: PR Lifecycle Watcher

**PRD:** `cOS_prds/20260320_033855_prd_add_a_pr_lifecycle_watcher_that_monitors_merged_prs_and_posts_completion_notific.md`
**Generated:** 2026-03-20T03:38:55Z

---

## Relevant Files

### Files to Modify

- `src/colonyos/models.py` - Add `merged_at` to `RunLog`, add `merge_notified` to `QueueItem`, bump `SCHEMA_VERSION`
- `src/colonyos/config.py` - Add `notify_on_merge` and `merge_poll_interval_sec` to `SlackConfig`
- `src/colonyos/cli.py` - Add merge polling thread to `watch()` command
- `src/colonyos/slack.py` - Add `format_merge_notification()` and `post_merge_notification()` helpers

### New Files to Create

- `src/colonyos/pr_watcher.py` - Merge polling logic as a separate module for clean separation
- `tests/test_pr_watcher.py` - Unit tests for merge polling and notification logic

### Test Files to Update

- `tests/test_models.py` - Tests for new `merged_at` and `merge_notified` fields
- `tests/test_config.py` - Tests for new `SlackConfig` fields
- `tests/test_slack.py` - Tests for merge notification formatting

---

## Tasks

- [x] 1.0 Extend data models with merge tracking fields
  - [x] 1.1 Write tests for `RunLog.merged_at` field serialization and deserialization
  - [x] 1.2 Add `merged_at: str | None = None` field to `RunLog` dataclass in `models.py`
  - [x] 1.3 Write tests for `QueueItem.merge_notified` field and schema version bump
  - [x] 1.4 Add `merge_notified: bool = False` field to `QueueItem` dataclass
  - [x] 1.5 Bump `QueueItem.SCHEMA_VERSION` from 2 to 3
  - [x] 1.6 Update `QueueItem.to_dict()` and `QueueItem.from_dict()` to handle new field

- [x] 2.0 Add configuration options for merge notifications
  - [x] 2.1 Write tests for `SlackConfig.notify_on_merge` parsing and validation
  - [x] 2.2 Write tests for `SlackConfig.merge_poll_interval_sec` parsing with minimum validation (>=30)
  - [x] 2.3 Add `notify_on_merge: bool = True` to `SlackConfig` dataclass in `config.py`
  - [x] 2.4 Add `merge_poll_interval_sec: int = 300` to `SlackConfig` dataclass
  - [x] 2.5 Update `_parse_slack_config()` to parse and validate both new fields
  - [x] 2.6 Update `save_config()` to persist new slack config fields

- [x] 3.0 Implement Slack notification formatting helpers
  - [x] 3.1 Write tests for `format_merge_notification()` with various title lengths and edge cases
  - [x] 3.2 Write tests for `post_merge_notification()` Slack client interaction
  - [x] 3.3 Add `format_merge_notification(pr_number: int, feature_title: str, cost_usd: float, duration_ms: int) -> str` to `slack.py`
  - [x] 3.4 Add `post_merge_notification(client, channel, thread_ts, pr_number, feature_title, cost_usd, duration_ms) -> None` to `slack.py`
  - [x] 3.5 Implement title truncation (80 chars with ellipsis) in `format_merge_notification()`

- [x] 4.0 Create PR watcher module with merge polling logic
  - [x] 4.1 Write tests for `extract_pr_number_from_url()` with valid/invalid URLs
  - [x] 4.2 Write tests for `check_pr_merged()` with mocked `gh pr view` output
  - [x] 4.3 Write tests for `poll_merged_prs()` with various queue states
  - [x] 4.4 Create `src/colonyos/pr_watcher.py` module
  - [x] 4.5 Implement `extract_pr_number_from_url(pr_url: str) -> int | None` with URL validation regex
  - [x] 4.6 Implement `check_pr_merged(pr_number: int, repo_root: Path) -> tuple[bool, str | None]` returning (is_merged, merged_at_iso)
  - [x] 4.7 Implement `poll_merged_prs(repo_root, queue_state, watch_state, slack_client, config, state_lock) -> int` returning count of notifications sent
  - [x] 4.8 Add PR URL validation regex: `^https://github\.com/[\w.-]+/[\w.-]+/pull/\d+$`
  - [x] 4.9 Add 7-day age filter for PRs to poll (based on `QueueItem.added_at`)

- [x] 5.0 Integrate merge polling thread into watch command
  - [x] 5.1 Write integration tests for merge polling thread lifecycle (start, poll, shutdown)
  - [x] 5.2 Add `MergeWatcher` class in `pr_watcher.py` that spawns daemon thread
  - [x] 5.3 Implement polling loop with `shutdown_event.wait(timeout=poll_interval)`
  - [x] 5.4 Add thread-safe state access (snapshot items under lock, release during API calls)
  - [x] 5.5 Start `MergeWatcher` from `watch()` command after Slack client is ready
  - [x] 5.6 Add startup log: `"MergeWatcher started (poll_interval=%d sec)"`

- [x] 6.0 Implement RunLog update on merge detection
  - [x] 6.1 Write tests for `update_run_log_merged_at()` with existing and missing run logs
  - [x] 6.2 Implement `update_run_log_merged_at(repo_root: Path, run_id: str, merged_at: str) -> bool` in `pr_watcher.py`
  - [x] 6.3 Use atomic write pattern (temp file + rename) matching `save_watch_state()`
  - [x] 6.4 Add structured audit log: `"AUDIT: run_log_updated run_id=%s merged_at=%s"`

- [x] 7.0 Add error handling and rate limit protection
  - [x] 7.1 Write tests for error scenarios (network failure, Slack failure, missing run log)
  - [x] 7.2 Add try/except around `gh pr view` subprocess calls with WARNING logging
  - [x] 7.3 Add try/except around Slack notification posting (don't mark notified on failure)
  - [x] 7.4 Error handling in MergeWatcher thread to prevent crashes
  - [x] 7.5 Add structured error logs following existing AUDIT pattern

- [x] 8.0 Documentation and final integration
  - [x] 8.1 All code changes documented with docstrings
  - [x] 8.2 Config fields have defaults and validation
  - [x] 8.3 Run full test suite to verify no regressions (329 tests passing)
  - [ ] 8.4 Manual integration test: trigger pipeline via Slack, merge PR, verify notification

---

## Implementation Notes

### Task 1.0: Data Model Changes

The `QueueItem.SCHEMA_VERSION` bump to 3 ensures backward compatibility. The `from_dict()` method already handles missing fields with defaults via `data.get("field", default)`.

### Task 4.0: PR Watcher Module

Create a clean separation per Linus's recommendation. The module should have:
- Pure functions for URL parsing and merge checking
- A single `poll_merged_prs()` orchestration function
- No global state; all state passed as parameters

### Task 5.0: Thread Safety

Critical pattern for the polling loop:
```python
with state_lock:
    items_to_check = [
        item for item in queue_state.items
        if item.status == QueueItemStatus.COMPLETED
        and item.pr_url
        and not item.merge_notified
        and _is_within_7_days(item.added_at)
    ]
# Release lock before network calls
for item in items_to_check:
    is_merged, merged_at = check_pr_merged(extract_pr_number(item.pr_url), repo_root)
    if is_merged:
        # Re-acquire lock for state mutation
        with state_lock:
            item.merge_notified = True
            _save_queue_state(repo_root, queue_state)
```

### Task 7.0: Rate Limiting

GitHub authenticated users get 5000 requests/hour. Track calls in `SlackWatchState`:
```python
@dataclass
class SlackWatchState:
    # ... existing fields ...
    gh_api_calls_this_hour: int = 0
    gh_api_hour_key: str = ""  # "2026-03-20T03"
```

Reset counter when hour changes. Pause polling if `gh_api_calls_this_hour > 4500`.

---

## Dependencies

- Tasks 2.0 and 3.0 can run in parallel
- Task 4.0 depends on Task 1.0 (needs `merge_notified` field)
- Task 5.0 depends on Tasks 2.0, 3.0, and 4.0
- Task 6.0 can run in parallel with Task 5.0
- Task 7.0 depends on Tasks 4.0 and 5.0
- Task 8.0 depends on all other tasks
