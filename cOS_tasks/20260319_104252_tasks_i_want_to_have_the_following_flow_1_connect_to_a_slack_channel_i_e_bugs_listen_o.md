# Tasks: Unified Slack-to-Queue Autonomous Pipeline

**PRD:** `cOS_prds/20260319_104252_prd_i_want_to_have_the_following_flow_1_connect_to_a_slack_channel_i_e_bugs_listen_o.md`
**Date:** 2026-03-19

---

## Relevant Files

- `src/colonyos/models.py` - Add `base_branch`, `slack_ts`, `slack_channel` to `QueueItem`; add `daily_cost_usd`/`daily_cost_reset_date` to `SlackWatchState`; add `pr_url` to `RunLog`
- `tests/test_models.py` - Tests for model changes
- `src/colonyos/config.py` - Add `triage_scope`, `daily_budget_usd`, `max_queue_depth`, `triage_verbose`, `max_consecutive_failures` to `SlackConfig`
- `tests/test_config.py` - Tests for config changes
- `src/colonyos/slack.py` - Add `triage_message()` function; triage prompt construction; triage acknowledgment posting
- `tests/test_slack.py` - Tests for triage logic, filtering, acknowledgments
- `src/colonyos/cli.py` - Refactor `watch` to use `QueueState` backing; add queue executor thread; wire triage into event handler; daily budget tracking
- `tests/test_cli.py` - Tests for unified watch+queue flow
- `tests/test_queue.py` - Tests for Slack-sourced queue items, consecutive failure handling
- `src/colonyos/orchestrator.py` - Accept and use `base_branch` parameter for branch targeting
- `tests/test_orchestrator.py` - Tests for base_branch orchestration

## Tasks

- [x] 1.0 Extend data models for triage + queue unification
  - [x] 1.1 Write tests for new `QueueItem` fields (`base_branch: Optional[str]`, `slack_ts: Optional[str]`, `slack_channel: Optional[str]`, `source_type="slack"`) — verify serialization/deserialization and backwards compatibility with existing queue state files
  - [x] 1.2 Write tests for new `SlackWatchState` fields (`daily_cost_usd: float`, `daily_cost_reset_date: str`) — verify daily reset logic
  - [x] 1.3 Write tests for `pr_url: Optional[str]` on `RunLog` — fix the existing `getattr(log, "pr_url", None)` pattern
  - [x] 1.4 Implement the model changes in `models.py` — add all new fields with appropriate defaults for backwards compatibility

- [x] 2.0 Extend `SlackConfig` with triage and budget configuration
  - [x] 2.1 Write tests for new `SlackConfig` fields: `triage_scope: str`, `daily_budget_usd: Optional[float]`, `max_queue_depth: int` (default 20), `triage_verbose: bool` (default False), `max_consecutive_failures: int` (default 3)
  - [x] 2.2 Write tests verifying config.yaml parsing with new fields and backwards compatibility (missing fields use defaults)
  - [x] 2.3 Implement the config changes in `config.py`

- [x] 3.0 Implement LLM-based triage agent
  - [x] 3.1 Write tests for `triage_message()` in `slack.py` — mock the LLM call, verify structured JSON output parsing (`actionable`, `confidence`, `summary`, `base_branch`, `reasoning`), verify it handles malformed LLM output gracefully
  - [x] 3.2 Write tests for triage prompt construction — verify it includes `project.name`, `project.description`, `project.stack`, `vision`, `triage_scope`, and the sanitized message text
  - [x] 3.3 Write tests for `base_branch` extraction — verify explicit syntax parsing (`base:colonyos/feature-x`, `build on top of colonyos/feature-x`), defaulting to `None` when absent
  - [x] 3.4 Implement `triage_message()` in `slack.py` — single-turn haiku LLM call with no tool access, structured JSON output, wrapped in the existing sanitization/preamble pattern from `format_slack_as_prompt()`
  - [x] 3.5 Implement triage acknowledgment posting — post triage summary to message thread ("I can fix this — [summary]. React 👍 to approve." or "Adding to queue, position N of M.")
  - [x] 3.6 Implement optional skip posting — when `triage_verbose: true`, post brief skip reason to thread

- [x] 4.0 Refactor `watch` command to use `QueueState` backing
  - [x] 4.1 Write tests for the new watch→queue flow: Slack event → triage → `QueueItem` insertion into `QueueState` (instead of inline pipeline spawn)
  - [x] 4.2 Write tests for queue executor thread — verify it drains `QueueState` sequentially, respects `pipeline_semaphore`, posts results via `SlackUI` using stored `slack_ts`/`slack_channel`
  - [x] 4.3 Write tests for `max_queue_depth` enforcement — verify rejection when queue is full
  - [x] 4.4 Write tests for daily budget tracking — verify `daily_cost_usd` accumulates, resets at midnight UTC, and blocks new items when exceeded
  - [x] 4.5 Write tests for `max_consecutive_failures` — verify queue pauses after N consecutive failures and posts notification to channel
  - [x] 4.6 Refactor `_handle_event` in the `watch` command to: (1) call `triage_message()` after `should_process_message()`, (2) if actionable, insert `QueueItem` into `QueueState`, (3) post triage acknowledgment
  - [x] 4.7 Implement queue executor thread within `watch` — a background thread that loops over pending `QueueState` items, runs `run_orchestrator` for each, updates item status, posts results to originating Slack thread
  - [x] 4.8 Wire daily budget check into the executor — track spend per UTC day, block execution when `daily_budget_usd` is exceeded
  - [x] 4.9 Implement consecutive failure detection — track failure streak, pause queue and notify channel when `max_consecutive_failures` is reached

- [x] 5.0 Add base branch targeting to orchestrator
  - [x] 5.1 Write tests for `base_branch` parameter in orchestrator — verify preflight checks out specified branch, sets PR target correctly, and rejects invalid branches
  - [x] 5.2 Write tests for branch validation — verify that `base_branch` must exist locally or on remote, and that missing branches produce a clear error
  - [x] 5.3 Implement `base_branch` support in `orchestrator.py` — modify preflight to accept and validate `base_branch`, check it out before pipeline execution, pass it to the deliver phase for PR targeting

- [x] 6.0 Unified queue status for all sources
  - [x] 6.1 Write tests verifying `colonyos queue status` shows items from both CLI and Slack sources, displaying `source_type` and Slack channel origin
  - [x] 6.2 Update `queue status` output formatting in `cli.py` to show source type, Slack channel, and triage summary for Slack-sourced items

- [x] 7.0 Integration testing and documentation
  - [x] 7.1 Write integration tests for the full flow: mock Slack event → triage → queue insertion → pipeline execution → Slack thread reply with PR URL
  - [x] 7.2 Write integration tests for error scenarios: triage rejects message, queue full, daily budget exceeded, consecutive failures, invalid base branch
  - [x] 7.3 Update `colonyos doctor` to validate triage-related config when Slack is enabled
  - [x] 7.4 Update config.yaml example in README with new `triage_scope`, `daily_budget_usd`, `max_queue_depth` fields
