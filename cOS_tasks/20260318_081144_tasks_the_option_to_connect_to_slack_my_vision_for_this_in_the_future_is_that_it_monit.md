# Tasks: Slack Integration for ColonyOS

## Relevant Files

- `src/colonyos/config.py` - Add `SlackConfig` dataclass, parse `slack` section from config.yaml, save slack config
- `src/colonyos/models.py` - Add `SlackWatchState` dataclass for dedup ledger and watcher state tracking
- `src/colonyos/slack.py` - **New file** — Slack Bolt listener, message formatting, content sanitization, threaded reply helpers
- `src/colonyos/cli.py` - Add `watch` CLI command with budget/time caps, heartbeat, graceful shutdown
- `src/colonyos/doctor.py` - Add Slack token environment variable validation check
- `src/colonyos/github.py` - Extract `_sanitize_untrusted_content` for shared reuse (or import from new location)
- `src/colonyos/orchestrator.py` - Minor: ensure `run_orchestrator` can be called from Slack context (already works, verify)
- `pyproject.toml` - Add `slack-bolt[socket-mode]` as optional dependency
- `tests/test_slack.py` - **New file** — Unit tests for Slack message parsing, sanitization, formatting, dedup, config
- `tests/test_config.py` - Add tests for `SlackConfig` parsing and validation
- `tests/test_doctor.py` - Add tests for Slack token doctor check (if doctor tests exist; otherwise add to test_slack.py)
- `.colonyos/config.yaml` - Example: add `slack` section documentation

## Tasks

- [x] 1.0 Add Slack configuration to ColonyConfig
  - [x] 1.1 Write tests for `SlackConfig` parsing: valid config, missing fields with defaults, invalid channel format, enabled/disabled toggle (`tests/test_config.py`)
  - [x] 1.2 Add `SlackConfig` dataclass to `src/colonyos/config.py` with fields: `enabled` (bool, default false), `channels` (list[str], default []), `trigger_mode` (str, default "mention"), `auto_approve` (bool, default false), `max_runs_per_hour` (int, default 3), `allowed_user_ids` (list[str], default [])
  - [x] 1.3 Update `load_config()` and `save_config()` in `config.py` to parse/persist the `slack` section
  - [x] 1.4 Add `slack` field to `ColonyConfig` dataclass with default `SlackConfig()`

- [x] 2.0 Add Slack dependency and doctor check
  - [x] 2.1 Write tests for Slack doctor check: token present, token missing, token empty (`tests/test_slack.py`)
  - [x] 2.2 Add `slack-bolt[socket-mode]>=1.18` as an optional dependency in `pyproject.toml` under `[project.optional-dependencies]` (e.g., `slack = ["slack-bolt[socket-mode]>=1.18"]`)
  - [x] 2.3 Add a Slack token validation check to `doctor.py` — verify `COLONYOS_SLACK_BOT_TOKEN` and `COLONYOS_SLACK_APP_TOKEN` environment variables are set (soft check, only when slack is enabled in config)

- [x] 3.0 Create Slack message ingestion and sanitization module
  - [x] 3.1 Write tests for message sanitization (XML tag stripping applied to Slack content), prompt extraction from mention text, `<slack_message>` wrapper formatting, bot/edit message filtering (`tests/test_slack.py`)
  - [x] 3.2 Create `src/colonyos/slack.py` with:
    - `sanitize_slack_content(text: str) -> str` — reuse `_sanitize_untrusted_content` pattern from `github.py`
    - `extract_prompt_from_mention(text: str, bot_user_id: str) -> str` — strip the `@bot` mention prefix, return clean prompt
    - `format_slack_as_prompt(message_text: str, channel: str, user: str) -> str` — wrap in `<slack_message>` delimiters with role-anchoring preamble, mirroring `format_issue_as_prompt` in `github.py`
    - `should_process_message(event: dict, config: SlackConfig, bot_user_id: str) -> bool` — filter: channel allowlist, ignore bots, ignore edits, ignore threads, check allowed_user_ids if configured
  - [x] 3.3 Extract `_sanitize_untrusted_content` and `_XML_TAG_RE` from `github.py` into a shared location (either a new `src/colonyos/sanitize.py` or make `_sanitize_untrusted_content` public in `github.py` and import from `slack.py`)

- [x] 4.0 Add Slack feedback (threaded reply helpers)
  - [x] 4.1 Write tests for Slack message formatting functions: acknowledgment message, phase update message, final summary message with PR link (`tests/test_slack.py`)
  - [x] 4.2 Add to `src/colonyos/slack.py`:
    - `post_acknowledgment(client, channel: str, thread_ts: str, prompt: str) -> None` — post "Starting pipeline for: {prompt}" as threaded reply
    - `post_phase_update(client, channel: str, thread_ts: str, phase: str, success: bool, cost: float) -> None` — post phase completion
    - `post_run_summary(client, channel: str, thread_ts: str, run_log: RunLog) -> None` — post final summary mirroring `_print_run_summary`
    - `react_to_message(client, channel: str, timestamp: str, emoji: str) -> None` — add emoji reaction (👀 on start, ✅/❌ on completion)
  - [x] 4.3 Add a `SlackUI` class that implements a similar interface to `PhaseUI`/`NullUI` from `ui.py` but posts updates to Slack threads instead of the terminal

- [x] 5.0 Add deduplication ledger (SlackWatchState)
  - [x] 5.1 Write tests for `SlackWatchState`: add processed message, check if already processed, persist to JSON, load from JSON, atomic file writes (`tests/test_slack.py`)
  - [x] 5.2 Add `SlackWatchState` dataclass to `src/colonyos/models.py` with fields: `watch_id` (str), `processed_messages` (dict mapping `{channel_id}:{message_ts}` → `run_id`), `aggregate_cost_usd` (float), `runs_triggered` (int), `start_time_iso` (str), `hourly_trigger_counts` (dict mapping hour → count for rate limiting)
  - [x] 5.3 Add `save_watch_state()` and `load_watch_state()` functions to `slack.py` using the atomic temp+rename pattern from `_save_loop_state` in `cli.py`
  - [x] 5.4 Add rate limiting logic: `check_rate_limit(state: SlackWatchState, config: SlackConfig) -> bool` — returns True if under `max_runs_per_hour`

- [x] 6.0 Implement `colonyos watch` CLI command
  - [x] 6.1 Write tests for the `watch` command: missing config, missing tokens, basic argument parsing, graceful shutdown signal handling (`tests/test_cli.py` or `tests/test_slack.py`)
  - [x] 6.2 Add `watch` command to `cli.py` with options: `--max-hours` (float), `--max-budget` (float), `--verbose/-v` (flag), `--quiet/-q` (flag), `--dry-run` (flag, log triggers without executing pipeline)
  - [x] 6.3 Implement the Bolt Socket Mode app setup in `slack.py`:
    - `create_slack_app(config: SlackConfig) -> App` — initialize Bolt app with Socket Mode handler
    - Register event handler for `app_mention` events
    - Register event handler for `reaction_added` events (for emoji-based triggers)
    - Wire event handlers to call `run_orchestrator()` in a background thread (Bolt handlers must return quickly)
  - [x] 6.4 Integrate heartbeat (`_touch_heartbeat`), budget caps, time caps, and `SlackWatchState` persistence into the watch loop
  - [x] 6.5 Handle SIGINT/SIGTERM for graceful shutdown: save state, post "ColonyOS watcher shutting down" to monitored channels, disconnect socket

- [x] 7.0 Integration testing and documentation
  - [x] 7.1 Write an integration test that mocks the Bolt app, simulates an `app_mention` event, verifies the full flow: message received → sanitized → prompt extracted → confirmation posted → `run_orchestrator` called → summary posted (`tests/test_slack.py`)
  - [x] 7.2 Update `colonyos doctor` output to show Slack status (connected/not configured/token missing)
  - [x] 7.3 Ensure `colonyos status` shows active watch sessions alongside loop summaries (read `SlackWatchState` files)
  - [x] 7.4 Add Slack setup instructions to the welcome banner in `_show_welcome()` when Slack is configured but tokens are missing
