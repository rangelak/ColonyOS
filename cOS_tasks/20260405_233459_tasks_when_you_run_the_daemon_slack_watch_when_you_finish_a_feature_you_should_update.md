# Tasks: Slack Thread Message Consolidation & LLM Content Surfacing

**PRD**: `cOS_prds/20260405_233459_prd_when_you_run_the_daemon_slack_watch_when_you_finish_a_feature_you_should_update.md`

## Relevant Files

- `src/colonyos/slack.py` - SlackUI class (L620-720), FanoutSlackUI (L725-770), SlackClient protocol (L38-59), formatting functions, `generate_plain_summary()` (L1044+)
- `src/colonyos/sanitize.py` - Secret pattern sanitization; needs outbound slack sanitization function
- `src/colonyos/daemon/_ui.py` - CombinedUI that delegates to SlackUI; `slack_note` forwarding (L85-86)
- `src/colonyos/orchestrator.py` - Calls `slack_note`/`phase_note` ~27 times; should NOT change (SlackUI handles consolidation)
- `src/colonyos/cli.py` - Reaction handling (L3696-3712, L3968-3983); already correct, no changes needed
- `src/colonyos/config.py` - Configuration models; may need minor additions for debounce settings
- `src/colonyos/models.py` - QueueItem model with slack metadata
- `tests/test_slack.py` - Tests for slack module
- `tests/test_slack_queue.py` - Tests for slack queue engine
- `tests/test_sanitize.py` - Tests for sanitization (if exists)

## Tasks

- [x] 1.0 Add `chat_update` to SlackClient protocol and add outbound sanitization
  depends_on: []
  - [x] 1.1 Write tests for `chat_update` on the SlackClient protocol — verify the method signature accepts `(channel, ts, text, **kwargs)` and that mock clients can implement it
  - [x] 1.2 Add `chat_update` method to the `SlackClient` protocol class in `slack.py` L38-59 — should call `self.web_client.chat_update(channel=channel, ts=ts, text=text, **kwargs)` or similar
  - [x] 1.3 Write tests for `sanitize_outbound_slack()` — verify it redacts `sk-ant-*` keys, PEM headers, GCP service account fragments, and enforces 3,000-char ceiling
  - [x] 1.4 Implement `sanitize_outbound_slack(text: str, max_chars: int = 3000) -> str` in `sanitize.py` — compose secret pattern redaction + length cap + existing `sanitize_for_slack()`
  - [x] 1.5 Add missing secret patterns to `SECRET_PATTERNS` in `sanitize.py`: `sk-ant-api03-*`, `-----BEGIN (RSA |EC )?PRIVATE KEY-----`, `"type": "service_account"`

- [x] 2.0 Refactor SlackUI to use edit-in-place message consolidation
  depends_on: [1.0]
  - [x] 2.1 Write tests for the new SlackUI edit-in-place behavior:
    - `phase_header()` posts one message and stores its `ts`
    - `phase_note()` calls `chat_update` on the stored `ts` (appending content)
    - `phase_complete()` does a final `chat_update` with completion label
    - Multiple `phase_note()` calls result in ONE message (not multiple)
    - Debounce: rapid `phase_note` calls are batched within a time window
  - [x] 2.2 Add `_current_msg_ts: str | None` and `_note_buffer: list[str]` instance variables to SlackUI
  - [x] 2.3 Refactor `phase_header()` to call `chat_postMessage`, capture response `ts` into `_current_msg_ts`, and clear the note buffer
  - [x] 2.4 Refactor `phase_note()` and `slack_note()` to append text to `_note_buffer` and flush via `chat_update` to `_current_msg_ts` (with debounce — flush on phase transitions or every ~5 seconds)
  - [x] 2.5 Refactor `phase_complete()` to flush any remaining buffer, then `chat_update` the current message with the completion label appended
  - [x] 2.6 Keep `phase_error()` posting a NEW message (never edit) so errors are always visible
  - [x] 2.7 Add a `_flush_buffer()` helper that composes the phase header + accumulated notes + optional completion into a single message body, calls `chat_update`, and handles failures (fall back to `chat_postMessage` if update fails)

- [ ] 3.0 Generate concise LLM summaries for plan and review phases
  depends_on: [1.0]
  - [ ] 3.1 Write tests for `generate_phase_summary(phase_name, context, repo_root)` — verify it returns ≤280 chars, handles empty context, falls back to deterministic summary on LLM failure
  - [ ] 3.2 Implement `generate_phase_summary()` in `slack.py` — reuse the `generate_plain_summary()` pattern (L1044+) with a tighter prompt: "Summarize this {phase} output for a Slack notification in under 280 characters. Be specific about what changed."
  - [ ] 3.3 Use a cheap model (Haiku-class) for phase summaries to keep cost negligible (~$0.001 per call)
  - [ ] 3.4 Apply `sanitize_outbound_slack()` to all generated summaries before posting

- [ ] 4.0 Update FanoutSlackUI for edit-in-place pattern
  depends_on: [2.0]
  - [ ] 4.1 Write tests for FanoutSlackUI with the new edit pattern — each target must independently track its own `_current_msg_ts` and buffer
  - [ ] 4.2 Update `FanoutSlackUI` to ensure each `SlackUI` target manages its own message state — the fanout just delegates calls, each target handles its own `chat_update` lifecycle
  - [ ] 4.3 Verify that merged request threads (via `notification_targets()`) each get properly consolidated messages

- [ ] 5.0 Wire phase summaries into the pipeline execution flow
  depends_on: [2.0, 3.0]
  - [ ] 5.1 Write integration tests: mock a full pipeline run and verify the Slack thread receives ≤7 messages total (acknowledgment, plan summary, implement progress, review verdict, final summary)
  - [ ] 5.2 After plan phase completes, call `generate_phase_summary("plan", plan_output)` and post via `slack_note()` — this will be consolidated into the plan phase message by the new SlackUI
  - [ ] 5.3 After review phase completes, call `generate_phase_summary("review", review_output)` and post the verdict + top finding
  - [ ] 5.4 For implement phase: ensure the task outline note (`_format_task_outline_note`) and per-task result notes (`_format_implement_result_note`) flow through the new buffered `phase_note()` and get consolidated into one message
  - [ ] 5.5 Verify that the existing `generate_plain_summary()` call at completion (cli.py L3714-3730) still works correctly with the new SlackUI

- [ ] 6.0 End-to-end testing and message count verification
  depends_on: [4.0, 5.0]
  - [ ] 6.1 Write an end-to-end test that simulates a full 7-phase pipeline run with SlackUI and counts total `chat_postMessage` calls — assert ≤7
  - [ ] 6.2 Write a test for the fix-round scenario (thread-fix request) — verify fix rounds also use consolidated messages
  - [ ] 6.3 Write a test for error scenarios — verify `phase_error()` always posts a new message, never gets hidden in an edit
  - [ ] 6.4 Write a test for `chat_update` failure fallback — if edit fails, SlackUI falls back to posting a new message
  - [ ] 6.5 Verify no regressions in existing `test_slack.py` and `test_slack_queue.py`
  - [ ] 6.6 Manual smoke test: run `colonyos daemon slack watch` against a test Slack channel and verify thread has ≤7 messages with rich LLM content
