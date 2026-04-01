# PRD: Listen to All Channel Messages (Not Just @Mentions)

## Introduction/Overview

ColonyOS currently processes Slack messages only when the bot is explicitly @mentioned. This feature adds the ability to listen to **every message** in configured channels, catching engineering requests that users drop without remembering to tag the bot. The implementation activates the existing but unwired `trigger_mode: "all"` configuration value to bind Slack `message` events in addition to `app_mention` events.

This is a low-risk, high-leverage change because:
- The Slack app manifest already subscribes to `message.channels` events
- The `SlackConfig.trigger_mode` field already documents "all" as an intended mode
- The `register()` method already branches on `trigger_mode` for reaction events
- The dedup infrastructure (`_pending_messages`, `watch_state.is_processed`) already keys on `channel:ts`, naturally handling dual-event delivery
- The triage LLM already classifies messages as actionable or not

## Goals

1. **Enable passive channel listening**: When `trigger_mode: "all"`, the bot processes all top-level messages in configured channels, not just @mentions
2. **Zero false executions**: The existing triage LLM filters out casual chat, greetings, and off-topic messages — only actionable engineering requests proceed
3. **Invisible until relevant**: The bot does not react or respond to non-mention messages unless triage determines they are actionable
4. **Backward compatible**: Default behavior (`trigger_mode: "mention"`) is unchanged; no config migration needed

## User Stories

1. **As an engineer**, I want to post "fix the flaky login test" in #eng-requests without remembering to @mention the bot, and have ColonyOS pick it up and act on it.
2. **As a team lead**, I want to configure a dedicated channel where any engineering request is automatically triaged, while keeping other channels mention-only.
3. **As an operator**, I want to enable passive listening with confidence that casual conversations won't trigger unnecessary agent runs or budget spend.

## Functional Requirements

1. **FR-1**: Add `"all"` to `_VALID_TRIGGER_MODES` in `src/colonyos/config.py` (currently `frozenset({"mention", "reaction", "slash_command"})`)
2. **FR-2**: In `SlackQueueEngine.register()` (`src/colonyos/slack_queue.py` line 82), bind `bolt_app.event("message")` to `_handle_event` when `trigger_mode` is `"all"`
3. **FR-3**: In `_handle_event()`, detect whether the incoming event is a direct @mention or a passive channel message. For passive messages, use the full message text as the prompt (skip `extract_prompt_from_mention()` which strips the `<@BOT_ID>` prefix)
4. **FR-4**: Skip the 👀 reaction for passively-ingested messages. Only react with 👀 after triage confirms the message is actionable and it gets enqueued
5. **FR-5**: Existing dedup (`_is_pending_message`, `watch_state.is_processed`) handles dual-event delivery (when @mention fires both `app_mention` and `message` events) — verify this with tests but no new code needed
6. **FR-6**: Log a warning at daemon startup if `trigger_mode` is `"all"` and `allowed_user_ids` is empty, recommending operators restrict who can trigger the bot
7. **FR-7**: Log a warning at daemon startup if `trigger_mode` is `"all"` and `triage_scope` is empty, since triage needs scope guidance to filter effectively in passive mode
8. **FR-8**: All existing filters in `should_process_message()` continue to apply: channel allowlist, bot message rejection, edit rejection, threaded reply rejection, sender allowlist

## Non-Goals

- **Per-channel trigger mode**: All 7 personas were split on this (4 for per-channel, 3 for global). For v1, `trigger_mode` remains a global setting. The `channels` allowlist already controls which channels the bot listens in. Per-channel config is a v2 feature if users request it.
- **Separate rate limits for passive messages**: The existing `max_runs_per_hour` and `daily_budget_usd` controls apply uniformly. If "all" mode is too noisy, operators should tighten `triage_scope` or lower `max_runs_per_hour`.
- **Pre-triage heuristic filter**: Some personas suggested a cheap keyword filter before the LLM triage. This adds complexity for marginal savings — the triage call is already cheap. Not in v1.
- **Mandatory `allowed_user_ids` enforcement**: The security engineer argued this should be required in "all" mode. We compromise with a startup warning (FR-6) rather than a hard error, since some teams use private channels where all members are trusted.
- **Changes to thread-fix behavior**: Thread-fix requests still require @mentioning the bot, regardless of `trigger_mode`.

## Technical Considerations

### Files to Modify

| File | Change |
|------|--------|
| `src/colonyos/config.py` line 390 | Add `"all"` to `_VALID_TRIGGER_MODES` frozenset |
| `src/colonyos/slack_queue.py` line 82-88 | Bind `message` event handler when `trigger_mode == "all"` |
| `src/colonyos/slack_queue.py` line 156-224 | Update `_handle_event` to handle passive messages (prompt extraction, conditional 👀 reaction) |
| `src/colonyos/slack.py` | Add `extract_prompt_from_channel_message()` or modify `extract_prompt_from_mention()` to handle non-mention messages |
| `src/colonyos/daemon.py` | Add startup warnings for `trigger_mode: "all"` without `allowed_user_ids` or `triage_scope` |

### Key Design Decision: Prompt Extraction

Currently, `extract_prompt_from_mention()` strips the `<@BOT_ID>` prefix from the message text. For passive channel messages, there is no such prefix — the full message text is the prompt. The handler needs to detect whether the message contains a bot mention:
- If yes: use `extract_prompt_from_mention()` (existing behavior)
- If no: use the raw message text directly (after sanitization)

This detection is straightforward: check if `f"<@{bot_user_id}>"` is in `event["text"]`.

### Deduplication

When `trigger_mode: "all"` and a user @mentions the bot, Slack fires both `app_mention` and `message` events with the same `(channel, ts)`. The existing dedup in `_handle_event` (lines 184-189) catches the second delivery. We bind both event types and let dedup handle the race.

### Slack Manifest

The manifest at `slack-app-manifest.yaml` already subscribes to `message.channels` — no manifest changes needed.

### Persona Consensus Summary

| Question | Consensus | Tension |
|----------|-----------|---------|
| Repurpose `trigger_mode: "all"`? | **Unanimous yes** | None |
| Triage LLM as filter? | **Unanimous yes** | None |
| Top-level messages only? | **Unanimous yes** | None |
| No 👀 on passive messages? | **Unanimous yes** | Some suggest 👀 after triage confirms actionable |
| Dedup already works? | **Unanimous yes** | None |
| Per-channel vs global? | **Split** | Security/Ive/Karpathy/Systems: per-channel; Seibel/Jobs/Linus: global |
| Separate rate limits? | **Split** | Systems/Karpathy/Security: yes; Seibel/Jobs/Linus: no |
| Mandatory `allowed_user_ids`? | **Split** | Security: hard require; all others: optional with warning |

## Success Metrics

1. **Zero regressions**: All existing tests pass; mention-mode behavior unchanged
2. **Passive pickup rate**: >80% of actionable engineering requests in "all" mode channels are correctly triaged as actionable
3. **False positive rate**: <5% of non-engineering messages are incorrectly triaged as actionable
4. **No creepy UX**: Zero 👀 reactions on messages the bot doesn't act on

## Open Questions

1. Should the triage prompt be modified to note that a message was passively ingested (not directed at the bot), potentially raising the bar for what counts as actionable?
2. If the `triage_queue` (maxsize=64) fills up in a busy channel, should we silently drop messages or log a warning? (Current behavior: `put_nowait` raises `Full`, caught and logged)
3. Should there be a `max_triage_per_hour` config to cap LLM triage costs independently from `max_runs_per_hour`? (Deferred to v2 based on observed usage)
