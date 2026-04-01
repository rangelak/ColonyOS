# PRD: Daily Slack Thread Consolidation

## 1. Introduction/Overview

ColonyOS currently posts one top-level Slack message per queue item (via `_ensure_notification_thread` in `daemon.py:1828`), plus operational messages (heartbeats, budget alerts, circuit breaker notices, daily digests) via `_post_slack_message` (daemon.py:1775). On a busy day, this can produce 15+ top-level messages that overwhelm the channel.

This feature replaces the per-item top-level threading model with a **daily thread** that rotates at a configurable hour (default 8am). All pipeline lifecycle messages (queue arrivals, phase updates, completions, failures, PR links) post as replies inside the daily thread. The daily thread's opening message contains a structured summary of overnight activity. Critical alerts (auto-pause, circuit breaker escalation) remain top-level to ensure operator visibility.

## 2. Goals

1. **Reduce channel noise by ~90%**: Collapse N top-level messages per day into exactly 1 daily thread + rare critical alerts.
2. **Improve morning workflow**: Engineers open the daily thread and see a scannable overnight summary (completed PRs, failures, spend).
3. **Preserve per-run detail**: Each queue item's phase updates still post to a thread; the daily thread serves as an index with links.
4. **Survive restarts**: The daemon persists the daily thread's `ts` so it can resume posting after a crash or restart.
5. **Zero additional LLM cost**: V1 summaries use structured templates from existing `QueueItem`/`RunLog` data.

## 3. User Stories

**US-1**: As an engineer arriving at 8am, I open Slack and see a single new daily thread from ColonyOS containing a summary of overnight work — 3 PRs ready for review, 1 failure, $4.50 spent — so I know exactly what to look at.

**US-2**: As an operator monitoring a busy daemon, I see pipeline starts and completions flowing into the daily thread instead of cluttering the main channel, so I can still use the channel for human conversation.

**US-3**: As a team lead, I click into the daily thread and see concise one-liner status updates per queue item, each with a link to the PR or detailed per-item thread, so I can drill into any run that needs attention.

**US-4**: As an on-call engineer, I still see critical daemon alerts (auto-pause, circuit breaker) as top-level messages that I can't miss, even if I haven't opened the daily thread.

**US-5**: As a user who prefers the current per-item threading model, I can set `notification_mode: per_item` in config to keep the existing behavior.

## 4. Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | Add `notification_mode` field to `SlackConfig` with values `"daily"` (default) and `"per_item"` (legacy behavior). |
| FR-2 | Add `daily_thread_hour` (default `8`) and `daily_thread_timezone` (default `"UTC"`) fields to `SlackConfig`. |
| FR-3 | When `notification_mode == "daily"`, the daemon creates one top-level thread per day at the configured hour. The opening message contains the overnight summary. |
| FR-4 | The overnight summary is a structured template (no LLM call) that includes: completed runs with PR links, failed runs with one-line errors, total cost for the period, and current queue depth. Data sourced from `QueueItem` and `DaemonState` fields. |
| FR-5 | All pipeline lifecycle messages (queue arrivals, phase updates, completions, run summaries) post as replies inside the active daily thread instead of creating new top-level messages. Heartbeats and daily digests also post to the daily thread. |
| FR-6 | Critical alerts — auto-pause (`_post_auto_pause_same_error_alert`), circuit breaker escalation (`_post_circuit_breaker_escalation_pause_alert`), and pre-execution blocker pauses (`_pause_for_pre_execution_blocker`) — remain as top-level channel messages. |
| FR-7 | The daily thread's `ts` and date are persisted in `DaemonState` (via `daemon_state.py`). On startup, if today's thread exists in state, the daemon resumes posting to it. If state is missing or stale, a new thread is created. |
| FR-8 | When `notification_mode == "per_item"`, all existing behavior is preserved unchanged. |
| FR-9 | Triage acknowledgments (`post_triage_acknowledgment`) and skip messages (`post_triage_skip`) remain as replies to the original user message thread — they are conversational responses, not system status. |
| FR-10 | Control command responses (pause, resume, status) remain in the main channel as direct replies to the operator's message. |

## 5. Non-Goals

- **LLM-powered "smart" summarization**: Deferred to a future iteration. V1 uses structured templates only. The "agent that summarizes stuff" mentioned in the request is out of scope for V1.
- **Sub-daily thread rotation**: Only daily rotation at the configured hour. No hourly or weekly threads.
- **Per-item thread elimination**: Per-item threads continue to be created (they hold phase-level detail). The change is where the thread's anchor message lives — inside the daily thread instead of as a top-level message.
- **Multi-channel daily threads**: One daily thread per configured notification channel. Multi-channel setups are out of scope.
- **Web dashboard / TUI changes**: This feature only affects Slack output.

## 6. Technical Considerations

### 6.1 Architecture

The key change is in `_ensure_notification_thread` (daemon.py:1828). Currently it creates a new top-level message per queue item. In daily mode, it should:

1. Call a new `_ensure_daily_thread()` method that returns the current day's `(client, channel, daily_thread_ts)`.
2. Post the per-item intro message as a reply to the daily thread (not as a top-level message).
3. Store the per-item reply's `ts` as `item.notification_thread_ts` so subsequent phase updates still go to the per-item sub-thread.

This preserves the existing `SlackUI` and `FanoutSlackUI` machinery — they operate on `notification_thread_ts` which still works.

### 6.2 Daily Thread Lifecycle

```
8:00 AM (configured hour)
  ├── Create new daily thread with overnight summary
  ├── Store daily_thread_ts + daily_thread_date in DaemonState
  └── Persist state
  
Throughout the day:
  ├── _ensure_notification_thread() → posts intro as reply to daily_thread_ts
  ├── Per-item phase updates → post to item.notification_thread_ts (sub-thread)
  ├── Heartbeats → post to daily_thread_ts
  └── Daily digest → post to daily_thread_ts

Next 8:00 AM:
  └── Rotate: create new daily thread with summary of previous day
```

### 6.3 State Persistence

Add to `DaemonState` (daemon_state.py):
```python
daily_thread_ts: str | None = None
daily_thread_date: str | None = None  # ISO date, e.g. "2026-04-01"
daily_thread_channel: str | None = None
```

This mirrors the existing `daily_reset_date` and `last_heartbeat` patterns already in `DaemonState`.

### 6.4 `_post_slack_message` Routing

Currently `_post_slack_message` always posts to the main channel with no `thread_ts`. In daily mode, non-critical messages should route to the daily thread:

```python
def _post_slack_message(self, text: str, *, critical: bool = False) -> None:
    if not critical and self._notification_mode == "daily" and self._daily_thread_ts:
        # Post to daily thread
        post_message(client, channel, text, thread_ts=self._daily_thread_ts)
    else:
        # Post to main channel (legacy behavior or critical alerts)
        post_message(client, channel, text)
```

Critical callers (`_post_auto_pause_same_error_alert`, `_post_circuit_breaker_escalation_pause_alert`, `_pause_for_pre_execution_blocker`) pass `critical=True`.

### 6.5 Timezone Handling

Use `zoneinfo.ZoneInfo` (stdlib in Python 3.9+) for timezone conversion. No new dependencies. Validate timezone string in config parsing with a try/except on `ZoneInfo(tz_string)`.

### 6.6 Overnight Summary Format

```
:sunrise: *ColonyOS Daily Summary — April 1, 2026*

*Completed (3):*
• `cli-refactor` — PR #142 merged | $2.10
• `fix-auth-bug` — PR #143 ready for review | $1.80
• `update-docs` — PR #144 ready for review | $0.60

*Failed (1):*
• `add-caching` — branch conflict (see incident) | $0.45

*Spend*: $4.95 | *Queue depth*: 2 pending
```

### 6.7 Key Files to Modify

| File | Changes |
|------|---------|
| `src/colonyos/config.py` | Add `notification_mode`, `daily_thread_hour`, `daily_thread_timezone` to `SlackConfig` |
| `src/colonyos/daemon_state.py` | Add `daily_thread_ts`, `daily_thread_date`, `daily_thread_channel` fields |
| `src/colonyos/daemon.py` | New `_ensure_daily_thread()`, modify `_ensure_notification_thread()`, add `critical` param to `_post_slack_message()`, add `_create_daily_summary()`, modify heartbeat/digest to post to daily thread |
| `src/colonyos/slack.py` | Add `format_daily_summary()` formatting function |
| `tests/test_daemon.py` | Tests for daily thread creation, rotation, restart recovery |
| `tests/test_daemon_state.py` | Tests for new state fields serialization |
| `tests/test_config.py` | Tests for new config fields |
| `tests/test_slack.py` | Tests for `format_daily_summary()` |

## 7. Persona Synthesis

### Areas of Unanimous Agreement

| Topic | Consensus |
|-------|-----------|
| **Noise source** | Top-level messages from per-item thread creation + operational chatter |
| **Structured template over LLM** | All 7 personas agreed: use existing run data, zero LLM cost |
| **Configurable hour + timezone** | All 7 agreed; `DaemonConfig` already has `digest_hour_utc` as precedent |
| **Persist thread_ts in DaemonState** | All 7 agreed; mirrors existing `notification_thread_ts` pattern |
| **Keep triage acks in-context** | All 7 agreed: user-facing replies stay where the user asked |

### Areas of Tension

| Topic | Position A | Position B | Resolution |
|-------|-----------|-----------|------------|
| **Eliminate per-item threads?** | Steve Jobs, Linus: eliminate them, one daily thread only | Systems Eng, Security, Ive, Karpathy: keep for drill-down/audit | **Keep per-item threads** but nest their anchor messages inside the daily thread. Preserves auditability without adding channel noise. |
| **Config toggle for notification_mode?** | Steve Jobs, Linus, YC: no toggle, ship daily only | Systems Eng, Security, Ive, Karpathy: add toggle | **Add toggle** (`daily` vs `per_item`). Low-risk since `_ensure_notification_thread` is a single chokepoint. Backward compatibility matters. |
| **Critical alerts scope** | Steve Jobs: consolidate everything | Security Eng: auto-pause/breaker must be top-level | **Security wins**: auto-pause and circuit breaker alerts stay top-level. Burying them in a thread risks missed incidents. |
| **Timezone config approach** | Systems Eng: keep UTC, avoid complexity | Ive, Karpathy: use IANA timezone strings | **IANA timezone** via `zoneinfo` (stdlib). UTC math is a poor UX. |

## 8. Success Metrics

1. **Top-level message reduction**: ≥90% fewer top-level bot messages in configured channels (measured by counting top-level messages before/after over 1 week).
2. **No regressions**: All existing tests pass. Per-item mode produces identical behavior to current system.
3. **Thread continuity**: Daily thread survives daemon restarts (verified by integration test with state persistence round-trip).
4. **Zero LLM cost**: Summary generation uses no LLM calls.

## 9. Open Questions

1. **Slack thread reply limits**: Slack threads can hold thousands of replies, but extremely long threads degrade UX. Should there be a fallback mechanism if a daily thread exceeds ~200 replies? (Likely a future concern — most teams won't hit this.)
2. **Multiple repos sharing a channel**: If multiple ColonyOS daemons post to the same channel, should daily threads be repo-scoped? (Likely yes — include repo name in thread title.)
3. **Thread notification settings**: Slack's "Also send to channel" option on thread replies can re-introduce noise. Should the bot explicitly set `reply_broadcast=False`? (Slack default is false, so no action needed unless a user has channel-level broadcast settings.)
