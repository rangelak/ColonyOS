# PRD: PR Lifecycle Watcher

**Generated:** 2026-03-20T03:38:55Z
**Feature Slug:** pr-lifecycle-watcher
**Status:** Draft

---

## 1. Introduction/Overview

The PR Lifecycle Watcher is a background polling task within `colonyos watch` that monitors merged PRs created by ColonyOS and posts completion notifications back to the originating Slack thread. This feature closes the feedback loop for users who request features via Slack: **request → progress updates → shipped notification**.

Currently, ColonyOS posts progress updates during pipeline execution (acknowledgment, phase completions, run summary with PR URL), but users don't receive notification when their work actually ships (PR merged). This creates an incomplete experience where users must manually check GitHub to know if their feature landed.

The watcher polls GitHub for merge status every 5 minutes (configurable), detects merged PRs, posts a celebratory Slack notification to the originating thread, and updates the `RunLog` with a `merged_at` timestamp for analytics.

---

## 2. Goals

1. **Complete the feedback loop**: Users who request features in Slack receive automatic notification when the PR merges
2. **Enable time-to-merge analytics**: Track `merged_at` timestamps in `RunLog` for `colonyos stats` dashboards
3. **Minimal infrastructure**: Polling-based implementation that works within existing `colonyos watch` architecture (no webhooks, no external servers)
4. **Configurable**: Teams can opt-out via `slack.notify_on_merge: false` if notifications are noisy

---

## 3. User Stories

### US-1: Feature Requester Notification
> As a developer who requested a feature via Slack, I want to receive a notification in the same thread when the PR is merged, so I know my feature shipped without checking GitHub manually.

### US-2: Team Visibility
> As a team lead monitoring a ColonyOS channel, I want to see completion notifications for all merged PRs, so I can track what's shipping without context-switching to GitHub.

### US-3: Analytics Consumer
> As a user of `colonyos stats`, I want to see time-to-merge metrics, so I can understand end-to-end delivery latency for autonomous pipelines.

### US-4: Notification Control
> As a team admin, I want to disable merge notifications globally, so my channel isn't overwhelmed if we merge many PRs.

---

## 4. Functional Requirements

### FR-1: Merge Detection via Polling
- Poll GitHub for PR merge status using `gh pr view {number} --json state,mergedAt` every N seconds (default: 300, configurable via `slack.merge_poll_interval_sec`)
- Only poll PRs from completed `QueueItem` entries where `pr_url` is set and `merge_notified` is false
- Bound polling to PRs added within the last 7 days (use `QueueItem.added_at` timestamp)
- Extract PR number from `pr_url` using regex: `https://github.com/.+/.+/pull/(\d+)`

### FR-2: Slack Notification Posting
- When a merge is detected, post a threaded reply to the originating Slack thread using `QueueItem.slack_ts` and `QueueItem.slack_channel`
- Notification format: `"🎉 PR #{number} merged! Your feature '{title}' is now live."`
- Feature title sourced from `QueueItem.raw_prompt` (original user message), truncated to 80 chars with ellipsis if longer
- Fall back to PR title from `gh pr view --json title` if `raw_prompt` is not available

### FR-3: RunLog Update with `merged_at`
- Add `merged_at: str | None = None` field to `RunLog` dataclass
- When merge is detected, load the corresponding `RunLog` JSON file from `.colonyos/runs/run-{run_id}.json`
- Update `merged_at` with the ISO timestamp from GitHub's `mergedAt` field
- Persist the updated RunLog atomically (temp file + rename pattern)

### FR-4: State Tracking to Prevent Duplicate Notifications
- Add `merge_notified: bool = False` field to `QueueItem` dataclass
- Increment `QueueItem.SCHEMA_VERSION` to 3
- After successfully posting a Slack notification, set `merge_notified = True` and persist `queue_state.json`

### FR-5: Configuration
- Add `notify_on_merge: bool = True` to `SlackConfig` dataclass
- Add `merge_poll_interval_sec: int = 300` to `SlackConfig` dataclass
- Parse both fields in `_parse_slack_config()` with validation (poll interval must be >= 30 seconds)

### FR-6: Background Polling Thread
- Spawn a daemon thread within `colonyos watch` that runs the merge polling loop
- Use `shutdown_event.wait(timeout=poll_interval)` for interruptible sleep
- Acquire `state_lock` only when reading/writing `queue_state` (not during GitHub API calls)
- Make the thread a daemon so it doesn't block graceful shutdown

### FR-7: Error Handling
- Network failures during `gh pr view`: Log at WARNING, skip that PR, continue to next
- Slack API failures: Log at WARNING, do not mark `merge_notified=True` (will retry next cycle)
- Missing/corrupted RunLog: Log at WARNING, still post notification (RunLog update is best-effort)
- GitHub rate limit approaching: Log at INFO, pause polling for remainder of hour

### FR-8: Audit Logging
- `logger.info("AUDIT: pr_merge_detected pr_url=%s item_id=%s merged_at=%s", ...)`
- `logger.info("AUDIT: merge_notification_sent channel=%s thread_ts=%s pr_url=%s", ...)`
- `logger.info("AUDIT: run_log_updated run_id=%s merged_at=%s", ...)`

---

## 5. Non-Goals

- **Webhooks**: Real-time merge detection via GitHub webhooks is out of scope; polling is sufficient for V1
- **Per-channel configuration**: `notify_on_merge` is a global setting; per-channel granularity deferred
- **Retry queues**: Failed notifications are retried on the next poll cycle, not via a dedicated retry queue
- **Time-to-merge dashboard panels**: Stats storage is in scope; dashboard visualization is deferred
- **Backfilling historical PRs**: Only PRs created after this feature ships will be tracked

---

## 6. Technical Considerations

### 6.1 Existing Architecture

The `colonyos watch` command (defined in `/src/colonyos/cli.py` starting at line 1841) runs as a long-lived process with:
- Slack Bolt SDK Socket Mode listener for real-time events
- `threading.Lock` (`state_lock`) guarding `SlackWatchState` and `QueueState` mutations
- `threading.Semaphore` (`pipeline_semaphore`) limiting concurrent pipeline runs
- `QueueExecutor` class processing pending queue items

### 6.2 Data Model Changes

**`QueueItem` (`/src/colonyos/models.py`):**
```python
@dataclass
class QueueItem:
    SCHEMA_VERSION: ClassVar[int] = 3  # bump from 2
    # ... existing fields ...
    merge_notified: bool = False  # NEW
```

**`RunLog` (`/src/colonyos/models.py`):**
```python
@dataclass
class RunLog:
    # ... existing fields ...
    merged_at: str | None = None  # NEW
```

**`SlackConfig` (`/src/colonyos/config.py`):**
```python
@dataclass
class SlackConfig:
    # ... existing fields ...
    notify_on_merge: bool = True  # NEW
    merge_poll_interval_sec: int = 300  # NEW
```

### 6.3 GitHub API Rate Limits

- Authenticated users get 5,000 requests/hour
- With 5-minute polling and max 20 active PRs (`max_queue_depth`), worst case is 240 requests/hour (4.8% of limit)
- Add a rate limit guard: track `gh_api_calls_this_hour`, pause if approaching limit

### 6.4 Thread Safety

The polling thread must:
1. Acquire `state_lock` to snapshot `queue_state.items`
2. Release lock before calling `gh pr view` (network I/O)
3. Re-acquire lock to update `merge_notified` and persist state

This prevents blocking Slack event handlers during GitHub API latency.

### 6.5 Security Considerations

Based on Staff Security Engineer review:
- **Validate PR URLs** before passing to `gh pr view` using regex `^https://github\.com/[\w.-]+/[\w.-]+/pull/\d+$`
- **Bound polling set** to PRs from last 7 days to prevent DoS via unbounded state growth
- **Log all merge events** with structured AUDIT logging for forensic investigation

---

## 7. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Notification delivery rate | >95% of merged PRs get notifications | `merge_notified=True` count vs total merged PRs |
| Time from merge to notification | <10 minutes (2 poll cycles) | `gh mergedAt` vs notification timestamp in logs |
| No increase in watch process crashes | 0 crash increase | Error logs, process restarts |
| User opt-out rate | <10% disable notifications | Config analysis across repos |

---

## 8. Open Questions

### Resolved by Persona Review

| Question | Resolution | Source |
|----------|------------|--------|
| Polling vs webhooks? | Polling first (simpler, no infrastructure) | YC Partner, Steve Jobs, Karpathy |
| State tracking location? | `merge_notified` field on `QueueItem` | Systems Engineer, Linus |
| Feature title source? | `QueueItem.raw_prompt` (user's original message) | Jony Ive, Karpathy |
| Retry strategy? | Log and continue; next poll cycle retries | YC Partner, Steve Jobs |
| Deduplication ledger? | Not needed; `merge_notified` flag is sufficient | YC Partner |

### Remaining Open Questions

1. **Notification format details**: Should we include cost and duration in the notification? (Jony Ive suggested yes: "Total: $3.42, 47 minutes")
2. **PR URL validation strictness**: Should we validate against the repo's actual GitHub remote, or just validate URL format?
3. **Maximum PR age for polling**: 7 days is proposed; should this be configurable?

---

## 9. Persona Q&A Synthesis

### Areas of Agreement

All personas agreed on:
- **Polling over webhooks** for V1 (simplicity, no infrastructure)
- **Global config toggle** rather than per-channel settings
- **No retry queues** — failed notifications retry on next poll cycle
- **Feature title from user's original message** (not PR title)
- **Background daemon thread** within existing watch process

### Areas of Tension

| Topic | Tension | Resolution |
|-------|---------|------------|
| **Polling latency** | Jony Ive wanted 30-second polling; others accepted 5 minutes | Configurable via `merge_poll_interval_sec`, default 5 min |
| **Notification content** | Jony Ive wanted cost/duration; others wanted minimal | Include cost/duration in V1 (actionable feedback) |
| **State location** | Linus preferred SlackWatchState; Systems Engineer preferred QueueItem | QueueItem (colocated with PR lifecycle) |
| **Separate module** | Linus suggested `/src/colonyos/pr_watcher.py`; others inline | Create separate module for clean separation |

### Security Concerns (Staff Security Engineer)

- **PR URL tampering**: Validate URL format before `gh pr view`
- **Unbounded polling set**: Cap at 7 days + `max_queue_depth`
- **Rate limit exhaustion**: Track API calls, pause if approaching limit
- **Audit logging**: Log all merge-related events with structured fields

---

## Appendix: File References

| File | Relevance |
|------|-----------|
| `/src/colonyos/models.py` | `QueueItem`, `RunLog` dataclasses to modify |
| `/src/colonyos/config.py` | `SlackConfig` to extend |
| `/src/colonyos/cli.py` | `watch()` command to add polling thread |
| `/src/colonyos/slack.py` | `SlackWatchState`, `post_*` helper patterns |
| `/src/colonyos/github.py` | `check_open_pr()` pattern for subprocess calls |
| `/src/colonyos/stats.py` | Reference for time-to-merge dashboard (future) |
