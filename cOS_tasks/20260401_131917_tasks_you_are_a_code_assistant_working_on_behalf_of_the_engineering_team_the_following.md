# Tasks: Listen to All Channel Messages (Not Just @Mentions)

## Relevant Files

- `src/colonyos/config.py` - `SlackConfig` dataclass and `_VALID_TRIGGER_MODES` frozenset (line 390); `_parse_slack_config()` validation (line 393)
- `src/colonyos/slack_queue.py` - `SlackQueueEngine.register()` (line 82) binds event handlers; `_handle_event()` (line 156) processes incoming messages; dedup logic (lines 120-127, 184-189); 👀 reaction (line 212)
- `src/colonyos/slack.py` - `should_process_message()` (line 151) filters events; `extract_prompt_from_mention()` (line 87) strips @mention prefix; `format_slack_as_prompt()` (line 99) wraps message for LLM
- `src/colonyos/daemon.py` - `_slack_listener_thread()` (line 1681) starts Slack connection; startup logging
- `tests/test_orchestrator.py` - Main test file for orchestrator/daemon tests
- `tests/test_slack_queue.py` - Tests for `SlackQueueEngine` (if exists)
- `tests/test_slack.py` - Tests for `should_process_message()`, `extract_prompt_from_mention()`
- `slack-app-manifest.yaml` - Slack app manifest (already subscribes to `message.channels` — no changes needed)

## Tasks

- [x] 1.0 Add `"all"` to valid trigger modes in config (no dependencies)
  depends_on: []
  - [x] 1.1 Write tests: assert `"all"` is accepted by `_parse_slack_config()` without raising `ValueError`; assert existing modes still work; assert invalid modes still raise
  - [x] 1.2 Add `"all"` to `_VALID_TRIGGER_MODES` frozenset in `src/colonyos/config.py` line 390

- [x] 2.0 Handle prompt extraction for non-mention messages (no dependencies)
  depends_on: []
  - [x] 2.1 Write tests: given a message without `<@BOT_ID>` prefix, the full text is used as the prompt; given a message with `<@BOT_ID>` prefix, `extract_prompt_from_mention()` behavior is preserved
  - [x] 2.2 Add a helper function or update `_handle_event()` logic in `src/colonyos/slack_queue.py` to detect whether the message contains a bot mention (`f"<@{bot_user_id}>"` in text) and use `extract_prompt_from_mention()` if yes, or raw text if no

- [x] 3.0 Bind `message` event in `register()` when `trigger_mode == "all"` (depends on 1.0)
  depends_on: [1.0]
  - [x] 3.1 Write tests: when `trigger_mode` is `"all"`, assert `bolt_app.event("message")` is called in `register()`; when `trigger_mode` is `"mention"`, assert only `app_mention` is bound
  - [x] 3.2 Update `SlackQueueEngine.register()` in `src/colonyos/slack_queue.py` to bind `bolt_app.event("message")(self._handle_event)` when `trigger_mode` is `"all"`

- [x] 4.0 Conditional 👀 reaction — skip for passive messages, react after triage for "all" mode (depends on 2.0, 3.0)
  depends_on: [2.0, 3.0]
  - [x] 4.1 Write tests: in `trigger_mode: "all"`, a non-mention message does NOT get 👀 reaction in `_handle_event`; a direct @mention still gets 👀; in `trigger_mode: "mention"`, behavior is unchanged
  - [x] 4.2 Update `_handle_event()` in `src/colonyos/slack_queue.py` (line 211-214) to skip 👀 reaction when the message is a passive channel message (no bot mention in text). Pass a flag through the triage queue so `_triage_and_enqueue` can add 👀 after confirming actionable.

- [x] 5.0 Dedup verification for dual-event delivery (no dependencies — test-only task)
  depends_on: []
  - [x] 5.1 Write tests: simulate an @mention in `trigger_mode: "all"` that delivers both `app_mention` and `message` events with the same `(channel, ts)`. Assert only one is processed and the second is dropped by dedup (`_is_pending_message` or `watch_state.is_processed`)

- [x] 6.0 Add startup warnings for `trigger_mode: "all"` without safety configs (depends on 1.0)
  depends_on: [1.0]
  - [x] 6.1 Write tests: when `trigger_mode` is `"all"` and `allowed_user_ids` is empty, assert a warning is logged; when `triage_scope` is empty, assert a warning is logged; when both are set, no warnings
  - [x] 6.2 Add startup warning logic in `src/colonyos/daemon.py` `_slack_listener_thread()` — log warnings if `trigger_mode == "all"` and `allowed_user_ids` or `triage_scope` are empty

- [x] 7.0 Integration test: full "all" mode flow (depends on 3.0, 4.0)
  depends_on: [3.0, 4.0]
  - [x] 7.1 Write an integration test that creates a `SlackQueueEngine` with `trigger_mode: "all"`, sends a non-mention message event through `_handle_event`, and verifies it reaches the triage queue with the correct prompt text
  - [x] 7.2 Write an integration test that sends both a passive message and an @mention in "all" mode, verifying both are processed correctly with appropriate prompt extraction and reaction behavior
  - [x] 7.3 Run the full test suite to verify zero regressions
