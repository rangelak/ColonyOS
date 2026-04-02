# Changelog

## 20260402_083000 — Pipeline Lifecycle Hooks

Adds a `hooks` configuration section to `.colonyos/config.yaml` that lets users define shell commands at pipeline lifecycle points (pre/post each phase, on_failure). Hooks support blocking gates, output injection into agent prompts, timeout enforcement, and secret scrubbing. Includes a `colonyos hooks test` CLI command for validating configuration.

**Created:**
- `src/colonyos/hooks.py` — HookRunner execution engine, HookContext/HookResult data models
- `tests/test_hooks.py` — 26+ tests covering execution, blocking, timeouts, secret scrubbing, output injection

**Modified:**
- `src/colonyos/config.py` — HookConfig dataclass, hooks parsing/serialization in load_config/save_config
- `src/colonyos/orchestrator.py` — HookRunner integration at every phase boundary and on_failure
- `src/colonyos/cli.py` — `colonyos hooks test` CLI command
- `src/colonyos/sanitize.py` — `sanitize_hook_output()` for safe output injection
- `tests/test_config.py` — Hook config parsing and validation tests
- `tests/test_orchestrator.py` — Hook integration tests
- `tests/test_cli.py` — CLI hooks test command tests
- `tests/test_sanitize.py` — Hook output sanitization tests

**PRD:** `cOS_prds/20260402_071300_prd_add_a_hooks_configuration_section_to_colonyos_config_yaml_that_lets_users_define.md`
**Tasks:** `cOS_tasks/20260402_071300_tasks_add_a_hooks_configuration_section_to_colonyos_config_yaml_that_lets_users_define.md`

## 20260401_173000 — Stuck Daemon Detection and Auto-Recovery

Adds an in-process watchdog thread that detects when a pipeline has stalled (no heartbeat progress beyond a configurable threshold) and automatically recovers: canceling the stuck pipeline, marking the item as FAILED, alerting operators via Slack, and resuming the main loop. Also enriches `/healthz` with pipeline duration and stall status, adds `started_at` to `QueueItem`, and bumps the schema to v5.

**Created:**
- `tests/test_daemon.py` — Comprehensive test suite for watchdog thread, stall detection, and auto-recovery
- `tests/test_models.py` — Tests for `QueueItem.started_at` field and schema v5 migration

**Modified:**
- `src/colonyos/daemon.py` — Watchdog thread, stall detection, auto-recovery, Slack alerts, enhanced `/healthz` endpoint, monitor events
- `src/colonyos/config.py` — Added `watchdog_stall_seconds` config field to `DaemonConfig`
- `src/colonyos/models.py` — Added `started_at` field to `QueueItem`, bumped `SCHEMA_VERSION` to 5
- `tests/test_config.py` — Tests for `watchdog_stall_seconds` configuration
- `tests/test_daemon_models.py` — Updated for schema v5

**PRD:** `cOS_prds/20260401_135527_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Tasks:** `cOS_tasks/20260401_135527_tasks_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
## 20260401_153000 — Listen to All Channel Messages (trigger_mode: "all")

Adds passive channel listening so ColonyOS can process every message in configured channels, not just @mentions. When `trigger_mode` is set to `"all"`, the bot binds Slack `message` events alongside `app_mention`, extracts prompts from non-mention messages, skips the 👀 reaction for passive messages (only reacting after triage confirms actionability), and leverages existing dedup infrastructure for dual-event delivery. Startup warnings guide operators to configure `allowed_user_ids` and `triage_scope` for safe passive mode usage.

**Modified:**
- `src/colonyos/config.py` — Added `"all"` to `_VALID_TRIGGER_MODES`
- `src/colonyos/slack_queue.py` — Bound `message` event handler in `register()`, updated `_handle_event` for passive message prompt extraction and conditional 👀 reaction
- `src/colonyos/slack.py` — Added `extract_prompt_from_channel_message()` for non-mention messages
- `src/colonyos/daemon.py` — Added startup warnings for `trigger_mode: "all"` without safety configs
- `tests/test_slack_queue.py` — Comprehensive tests for all-mode flow, dedup verification, passive message handling
- `tests/test_slack.py` — Tests for channel message prompt extraction
- `tests/test_daemon.py` — Tests for startup warnings

**PRD:** `cOS_prds/20260401_131917_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Tasks:** `cOS_tasks/20260401_131917_tasks_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
## 20260401_133000 — Fix Learn Phase 100% Failure Rate

Fixes a prompt-tool constraint mismatch that caused the learn phase to fail on every pipeline run. The `learn.md` instruction template now explicitly states which tools (Read, Glob, Grep) are available, provides concrete Glob patterns for file discovery, and includes negative constraints against disallowed tools (Bash, Agent, etc.). Adds regression tests to prevent future misalignment.

**Modified:**
- `src/colonyos/instructions/learn.md` — Added "Available Tools" section, concrete Glob patterns, negative tool constraints
- `tests/test_orchestrator.py` — Added `test_learn_prompt_contains_tool_constraint_language` and `test_learn_prompt_contains_glob_pattern_for_reviews` regression tests

**PRD:** `cOS_prds/20260401_130207_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Tasks:** `cOS_tasks/20260401_130207_tasks_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## 20260401_130000 — Daily Slack Thread Consolidation

Consolidates all pipeline lifecycle messages (queue arrivals, phase updates, completions, heartbeats) into a single daily Slack thread that rotates at a configurable hour, reducing channel noise by ~90%. Critical alerts (auto-pause, circuit breaker) remain top-level. Includes overnight summary generation, daemon restart recovery via persisted thread state, and a `per_item` config toggle to preserve legacy behavior.

**Created/Modified:**
- `src/colonyos/config.py` — Added `notification_mode`, `daily_thread_hour`, `daily_thread_timezone` to `SlackConfig`
- `src/colonyos/daemon_state.py` — Added `daily_thread_ts`, `daily_thread_date`, `daily_thread_channel` fields
- `src/colonyos/daemon.py` — New `_ensure_daily_thread()`, modified `_ensure_notification_thread()` and `_post_slack_message()` routing, overnight summary generation
- `src/colonyos/slack.py` — Added `format_daily_summary()` formatting function
- `tests/test_daemon.py` — Tests for daily thread creation, rotation, restart recovery
- `tests/test_daemon_state.py` — Tests for new state field serialization
- `tests/test_config.py` — Tests for new config fields and validation
- `tests/test_slack.py` — Tests for `format_daily_summary()`

**PRD:** `cOS_prds/20260401_120332_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Tasks:** `cOS_tasks/20260401_120332_tasks_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## 20260331_220500 — Replace :eyes: Emoji with Completion Emoji on Pipeline Finish

Adds clean emoji state transitions to Slack messages: when a ColonyOS pipeline completes, the `:eyes:` (in-progress) reaction is removed before adding the terminal status emoji (`:white_check_mark:` / `:x:`), plus `:tada:` on success. This eliminates ambiguous dual-emoji states so each message shows exactly one reaction reflecting its current state.

**Modified:**
- `src/colonyos/slack.py` — Added `reactions_remove` to `SlackClient` Protocol and `remove_reaction()` helper function
- `src/colonyos/cli.py` — Added `:eyes:` removal and `:tada:` reaction to both main and fix run completion paths
- `tests/test_slack.py` — Tests for `remove_reaction()` helper
- `tests/test_cli.py` — Tests for emoji state transitions on both completion paths

**PRD:** `cOS_prds/20260331_200151_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Tasks:** `cOS_tasks/20260331_200151_tasks_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
## 20260331_210000 — Informative Slack Pipeline Notifications

Enriches Slack thread messages with human-readable context so non-technical readers can understand pipeline progress without leaving the thread. Task completion messages now include descriptions, task outlines use bullet formatting, result summaries show what each task did, and review round messages surface reviewer findings — all without additional LLM calls.

**Modified:**
- `src/colonyos/orchestrator.py` — Updated `_format_task_outline_note()`, `_format_implement_result_note()`, phase header calls, and review round messages to include descriptions and findings
- `src/colonyos/sanitize.py` — Added Slack mrkdwn sanitization and message size safety utilities
- `tests/test_slack_formatting.py` — Comprehensive test suite for all Slack formatting functions
- `tests/test_sanitize.py` — Extended tests for sanitization utilities

**PRD:** `cOS_prds/20260331_190640_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Tasks:** `cOS_tasks/20260331_190640_tasks_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## 20260331_160000 — RepoMap Module for Agent Structural Context

Adds a `RepoMap` module (`src/colonyos/repo_map.py`) that generates a condensed structural summary of the repository — file paths, class names, function signatures — and injects it into every pipeline phase prompt. This eliminates agent cold-start overhead by giving each phase a "table of contents" of the codebase from the first token. Includes a `colonyos map` CLI command for debugging visibility.

**Created:**
- `src/colonyos/repo_map.py` — Core repo map generator with Python AST extraction, JS/TS regex extraction, tree formatting, relevance ranking, and token-budget truncation
- `tests/test_repo_map.py` — Comprehensive test suite for repo map module
- `tests/test_config.py` — Tests for `RepoMapConfig` configuration
- `tests/test_orchestrator.py` — Tests for repo map injection into orchestrator phases
- `tests/test_cli.py` — Tests for `colonyos map` CLI command

**Modified:**
- `src/colonyos/config.py` — Added `RepoMapConfig` dataclass to configuration system
- `src/colonyos/cli.py` — Added `colonyos map` CLI command
- `src/colonyos/orchestrator.py` — Injected repo map context into pipeline phase prompts
- `README.md` — Added `colonyos map` documentation

**PRD:** `cOS_prds/20260331_135929_prd_build_a_repomap_module_src_colonyos_repo_map_py_that_generates_a_condensed_struc.md`
**Tasks:** `cOS_tasks/20260331_135929_tasks_build_a_repomap_module_src_colonyos_repo_map_py_that_generates_a_condensed_struc.md`
## 20260331_153500 — Parallel Slack Intake: Decouple Triage from Pipeline Execution

Decouples Slack message triage from the pipeline execution lock so that incoming messages are classified and enqueued within seconds, regardless of whether a pipeline is actively running. Also adds bounded retry for transient triage failures, marks failed triages to prevent Slack redelivery loops, and closes a TOCTOU gap in hourly rate-limit tracking.

**Modified:**
- `src/colonyos/slack_queue.py` — Removed `agent_lock` from triage path, added 1-retry with 3s backoff for transient failures, moved `increment_hourly_count` to reservation time, mark failed triages as `"triage-error"`
- `src/colonyos/daemon.py` — Added comment clarifying `agent_lock` is no longer used for triage serialization
- `tests/test_slack_queue.py` — Comprehensive test coverage for all changes including integration test

**PRD:** `cOS_prds/20260331_150608_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Tasks:** `cOS_tasks/20260331_150608_tasks_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## 20260331_140000 — Daemon PR Sync: Keep ColonyOS PRs Up-to-Date with Main

Adds a new daemon concern that automatically detects open ColonyOS-authored PRs that have fallen behind `main`, merges the latest `main` into those branches via isolated worktrees, and pushes the result — keeping PRs perpetually merge-ready. Conflict failures are reported via Slack and PR comments with automatic retry capping.

**Created:**
- `src/colonyos/pr_sync.py` — Core sync logic: detection, worktree-based merge, failure tracking, and notifications
- `src/colonyos/worktree.py` — Ephemeral worktree manager for isolated git operations
- `tests/test_pr_sync.py` — Comprehensive unit/integration tests for PR sync
- `tests/test_config.py` — Config tests for new `pr_sync` section
- `tests/test_github.py` — Tests for `post_pr_comment()` helper
- `tests/test_outcomes.py` — Tests for new sync tracking columns

**Modified:**
- `src/colonyos/config.py` — Added `PRSyncConfig` with `enabled`, `interval_minutes`, `max_sync_failures`
- `src/colonyos/daemon.py` — Wired PR sync into daemon tick loop as concern #7
- `src/colonyos/github.py` — Added `post_pr_comment()` helper
- `src/colonyos/outcomes.py` — Added `last_sync_at`, `sync_failures`, `mergeStateStatus` columns
- `README.md` — Documentation for PR sync feature

**PRD:** `cOS_prds/20260331_131622_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Tasks:** `cOS_tasks/20260331_131622_tasks_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## 20260330_193500 — Homebrew Global Installation & VM-Ready Deployment

Adds a working Homebrew distribution channel (`brew install rangelak/colonyos/colonyos`) and a single-command VM provisioning script for Ubuntu 22.04+. The release workflow now auto-updates the tap formula on every tagged release, and `colonyos doctor` detects the install method to show correct upgrade instructions.

**Created:**
- `scripts/generate-homebrew-formula.sh` — Generates a complete Homebrew formula with all Python dependency resource blocks
- `docs/homebrew-tap-setup.md` — Setup guide for the `rangelak/homebrew-colonyos` tap repository
- `deploy/provision.sh` — Single-command VM provisioning script (Ubuntu 22.04+)
- `.github/workflows/release.yml` — Release workflow with auto-updating Homebrew tap job
- `tests/test_e2e_validation.py` — End-to-end validation tests for Homebrew install and VM deploy
- `tests/test_generate_formula.sh` — Shell tests for formula generation script
- `tests/test_doctor.py` — Tests for install-method detection in doctor command

**Modified:**
- `Formula/colonyos.rb` — Updated formula with proper dependency resources and test block
- `src/colonyos/doctor.py` — Install-method detection (brew/pipx/pip/dev)
- `src/colonyos/cli.py` — Doctor command integration updates
- `src/colonyos/init.py` — Non-git-repo guard for `colonyos init`
- `README.md` — Homebrew install and VM deployment quickstart sections
- `deploy/README.md` — Updated with provisioning script documentation
- `.github/workflows/ci.yml` — CI updates for new test coverage
- `tests/test_ci_workflows.py` — Additional CI workflow tests

**PRD:** `cOS_prds/20260330_182656_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Tasks:** `cOS_tasks/20260330_182656_tasks_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## 20260330_154500 — Enforce Repo Runtime Exclusivity and Shutdown Cleanup

Hardens ColonyOS against overlapping repo-bound runtimes by introducing a shared runtime lock across daemon, Slack watcher, queue, auto, TUI, and related entrypoints. This prevents concurrent work on the same checkout, improves cancellation cleanup for Ctrl+C and SIGTERM paths, and documents the generated runtime lock artifacts.

**Created:**
- `src/colonyos/runtime_lock.py` — Shared repo runtime lock, active-process registry, and related process-tree shutdown helpers
- `tests/test_runtime_lock.py` — Regression coverage for lock acquisition, registry cleanup, and runtime termination

**Modified:**
- `src/colonyos/cancellation.py` — Shared signal fan-out with preserved SIGTERM exit semantics
- `src/colonyos/cli.py` — Guard repo-bound runtimes, harden TUI and auto shutdown paths, and align interactive signal handling
- `src/colonyos/daemon.py` — Move daemon instance locking onto the shared repo runtime guard
- `src/colonyos/server.py` — Reject dashboard-launched runs when a repo runtime is already active
- `README.md` — Document repo runtime exclusivity and watcher/daemon mutual exclusion
- `deploy/README.md` — Document runtime lock files in deployment troubleshooting guidance
- `.gitignore` — Ignore generated runtime lock and process registry artifacts
- `tests/test_cancellation.py`, `tests/test_cli.py`, `tests/test_daemon.py`, `tests/test_server.py`, `tests/test_sweep.py`, `tests/tui/test_cli_integration.py` — Add regression coverage for guarded runtimes and interactive signal behavior

## 20260330_103500 — PR Outcome Tracking System

Closes the feedback loop on ColonyOS-created PRs by tracking their fate (merged/closed/open), feeding outcome data back into the CEO prompt, memory system, and analytics dashboard so the pipeline improves over time.

**Created:**
- `src/colonyos/outcomes.py` — Core outcomes module with SQLite persistence, GitHub polling via `gh`, and aggregate stats
- `tests/test_outcomes.py` — Comprehensive test coverage for outcome tracking, polling, and stats
- `tests/test_ceo.py` — Tests for CEO prompt injection of outcome history
- `tests/test_stats.py` — Tests for delivery outcomes section in stats dashboard

**Modified:**
- `src/colonyos/cli.py` — Added `colonyos outcomes` and `colonyos outcomes poll` CLI commands
- `src/colonyos/config.py` — Added `outcome_poll_interval_minutes` to DaemonConfig
- `src/colonyos/daemon.py` — Automatic PR outcome polling in daemon `_tick()`
- `src/colonyos/orchestrator.py` — Deliver phase integration to track PRs at creation time
- `src/colonyos/stats.py` — Delivery Outcomes section in stats dashboard
- `README.md` — Updated with outcome tracking documentation

**PRD:** `cOS_prds/20260330_091744_prd_add_a_pr_outcome_tracking_system_that_monitors_the_fate_of_prs_created_by_colony.md`
**Tasks:** `cOS_tasks/20260330_091744_tasks_add_a_pr_outcome_tracking_system_that_monitors_the_fate_of_prs_created_by_colony.md`

## 20260330_091900 — Harden Daemon Monitor UI and Slack Control Defaults

Improves the autonomous daemon experience by cleaning up the TUI monitor, restoring a single daemon-specific banner, removing misleading interactive controls in monitor mode, and translating daemon phase headers into native TUI events instead of dumping raw headless CLI layout into the transcript. This release also finishes the shared cancellation/control plumbing, documents open Slack queue access, and removes tracked runtime log artifacts from git.

**Created:**
- `src/colonyos/cancellation.py` — Shared cancellation bus for daemon, CLI, TUI, and active phase runs
- `tests/test_cancellation.py` — Regression coverage for signal fan-out into shared cancellation

**Modified:**
- `src/colonyos/agent.py` — Make sync phase wrappers cancellable and tighten typing around streamed tool names/results
- `src/colonyos/cli.py` — Add daemon monitor subprocess handling, monitor-mode logging, and native TUI event mapping for daemon output
- `src/colonyos/config.py` — Preserve daemon/retry fields and allow all Slack control users via config
- `src/colonyos/daemon.py` — Improve shutdown handling, diagnostics, and budget/recovery reporting
- `src/colonyos/init.py` — Preserve existing config on re-init and align runtime-state `.gitignore` entries
- `src/colonyos/tui/app.py` — Add dedicated monitor mode and clean daemon cancel ordering
- `src/colonyos/tui/widgets/transcript.py` — Add dedicated daemon monitor banner and cleaner transcript spacing
- `deploy/README.md` — Document daemon Slack allowlist behavior and open queue submission semantics
- `tests/test_agent.py`, `tests/test_cli.py`, `tests/test_config.py`, `tests/test_daemon.py`, `tests/test_init.py`, `tests/tui/test_app.py` — Add regression coverage for cancellation, daemon monitor UX, config round-tripping, and init preservation
## 20260330_002500 — Handle 529 Overloaded Errors with Retry and Optional Model Fallback

Adds a transport-level retry layer with exponential backoff and jitter inside `run_phase()` so that transient API 529/503 errors are handled transparently without triggering the orchestrator's heavyweight recovery. Includes optional model fallback (hard-blocked on safety-critical phases), full observability via `PhaseResult.retry_info`, and configurable `RetryConfig` in `config.yaml`.

Closes #47.

**Created:**
- `tests/test_agent.py` — Comprehensive tests for retry loop, transient error detection, fallback logic
- `tests/test_config.py` — Tests for RetryConfig defaults and YAML deserialization
- `tests/test_models.py` — Tests for PhaseResult retry_info field

**Modified:**
- `src/colonyos/agent.py` — Added `_is_transient_error()`, retry loop with backoff in `run_phase()`, optional model fallback
- `src/colonyos/config.py` — Added `RetryConfig` dataclass with `max_attempts`, `base_delay_seconds`, `max_delay_seconds`, `fallback_model`
- `src/colonyos/models.py` — Added `retry_info` field to `PhaseResult`
- `src/colonyos/orchestrator.py` — Wired `RetryConfig` through to `run_phase()` calls
- `README.md` — Added retry configuration reference section

**PRD:** `cOS_prds/20260329_225200_prd_the_following_github_issue_is_the_source_feature_description_treat_it_as_the_pri.md`
**Tasks:** `cOS_tasks/20260329_225200_tasks_the_following_github_issue_is_the_source_feature_description_treat_it_as_the_pri.md`

## 20260329_235900 — Sequential Task Implementation as Default

Makes sequential task execution the default implement mode, replacing parallel worktree-based
execution. Tasks now run one-at-a-time in topological order on a single branch, with each
task committed before the next starts — eliminating merge conflicts from parallel execution
of dependent tasks. Parallel mode remains available as an explicit opt-in via config.

**Created:**
- `tests/test_sequential_implement.py` — Comprehensive tests for sequential task runner (ordering, failure isolation, budget division, DAG integration)

**Modified:**
- `src/colonyos/config.py` — Flipped `ParallelImplementConfig.enabled` default from `True` to `False`
- `src/colonyos/orchestrator.py` — Added `_run_sequential_implement()` method with per-task agent sessions, topological ordering, failure-skip logic, and per-task budget allocation
- `tests/test_orchestrator.py` — Updated for sequential default
- `tests/test_parallel_config.py` — Updated assertions for new default
- `tests/test_parallel_orchestrator.py` — Updated assertions for new default

**PRD:** `cOS_prds/20260329_213252_prd_when_we_implement_a_new_functionality_from_the_tasks_it_should_not_happen_in_par.md`
**Tasks:** `cOS_tasks/20260329_213252_tasks_when_we_implement_a_new_functionality_from_the_tasks_it_should_not_happen_in_par.md`

## 20260329_213000 — Daemon Mode: Fully Autonomous 24/7 Engineering Agent

Adds `colonyos daemon` — a single long-running command that unifies the Slack listener,
GitHub Issue poller, CEO idle-fill scheduler, and cleanup scheduler into one supervised
process. Work from all sources flows into a priority queue (user bugs > features > CEO
proposals > cleanup) and is executed sequentially through the existing pipeline. Includes
daily budget enforcement, circuit breaker, crash recovery, atomic state persistence,
a `/healthz` health endpoint, and Slack kill-switch commands (pause/resume/status).

**Created:**
- `src/colonyos/daemon.py` — Core daemon orchestration: event loop, schedulers, budget enforcer, circuit breaker, health monitor
- `src/colonyos/daemon_state.py` — `DaemonState` dataclass with atomic write-then-rename persistence
- `deploy/colonyos-daemon.service` — systemd unit file with watchdog, sandboxing, and auto-restart
- `deploy/README.md` — VM deployment guide
- `tests/test_daemon.py` — Daemon unit tests (startup, scheduling, budget, circuit breaker, kill switch)
- `tests/test_daemon_state.py` — State persistence and crash recovery tests
- `tests/test_daemon_models.py` — Priority queue model tests

**Modified:**
- `src/colonyos/cli.py` — New `colonyos daemon` CLI command with `--max-budget`, `--max-hours`, `--dry-run` flags
- `src/colonyos/config.py` — Added `DaemonConfig` dataclass with budget, polling, scheduling, and circuit breaker settings
- `src/colonyos/models.py` — Added `priority` field to `QueueItem` (schema v4), priority-ordered queue selection
- `src/colonyos/server.py` — Added `/healthz` endpoint returning daemon status, queue depth, spend, and circuit breaker state
- `src/colonyos/github.py` — Added label filtering support for issue ingestion

**PRD:** `cOS_prds/20260329_155000_prd_colonyos_needs_to_be_fully_autonomous_we_deploy_it_to_a_project_on_a_vm_it_liste.md`
**Tasks:** `cOS_tasks/20260329_155000_tasks_colonyos_needs_to_be_fully_autonomous_we_deploy_it_to_a_project_on_a_vm_it_liste.md`

## 20260327_200000 — TUI-Native Auto Mode, CEO Profile Rotation & UX Fixes

Brings the full autonomous loop (CEO → plan → implement → review → deliver) into the TUI
with real-time transcript output, iteration tracking in the StatusBar, and graceful Ctrl+C
cancellation. Adds rotating CEO persona profiles for diverse feature proposals, persistent
run log files, Ctrl+S transcript export, and fixes the auto-scroll bug that yanked users
to the bottom while reading earlier content.

**Created:**
- `src/colonyos/ceo_profiles.py` — Curated pool of CEO persona profiles with random rotation and config override support
- `src/colonyos/tui/log_writer.py` — Per-run plain-text log writer with secret sanitization and log rotation
- `tests/test_ceo_profiles.py` — Unit tests for CEO profile selection, rotation, and config loading
- `tests/tui/test_auto_in_tui.py` — Integration tests for auto mode running inside the TUI
- `tests/tui/test_log_writer.py` — Unit tests for log writer, sanitization, and file rotation
- `tests/tui/test_transcript.py` — Tests for auto-scroll fix behavior
- `tests/tui/test_app.py` — Extended TUI app tests for auto command handling

**Modified:**
- `src/colonyos/cli.py` — Wired auto loop into TUI with iteration lifecycle, budget caps, and cancellation
- `src/colonyos/tui/app.py` — Auto command handling, Ctrl+S export, StatusBar iteration display
- `src/colonyos/tui/adapter.py` — Added `IterationHeaderMsg` and `LoopCompleteMsg` message types
- `src/colonyos/tui/widgets/transcript.py` — Fixed auto-scroll with programmatic scroll guard
- `src/colonyos/tui/widgets/status_bar.py` — Iteration count and cost display during auto loops
- `src/colonyos/tui/widgets/hint_bar.py` — Added Ctrl+S keybinding hint
- `src/colonyos/config.py` — Added `ceo_profiles` and `max_log_files` config fields
- `src/colonyos/orchestrator.py` — Pass CEO persona through to pipeline phases

**PRD:** `cOS_prds/20260327_171407_prd_add_support_for_auto_inside_the_tui_the_tui_should_be_the_default_colonyos_exper.md`
**Tasks:** `cOS_tasks/20260327_171407_tasks_add_support_for_auto_inside_the_tui_the_tui_should_be_the_default_colonyos_exper.md`

## 20260326_180000 — Persistent Memory System

Adds a native persistent memory system to ColonyOS using SQLite (zero new dependencies).
Memories are automatically captured at phase boundaries and injected into phase prompts
based on relevance and recency, so agents accumulate knowledge across runs instead of
re-discovering codebase patterns, failure modes, and user preferences each time.

**Created:**
- `src/colonyos/memory.py` — SQLite-backed memory storage with FTS5 search, CRUD operations, relevance-ranked retrieval, and configurable token budget injection
- `tests/test_memory.py` — Unit tests for memory storage layer
- `tests/test_memory_integration.py` — Integration tests for memory capture and injection
- `cOS_prds/20260326_164228_prd_add_memory_to_the_system_https_github_com_thedotmack_claude_mem_git.md` — PRD
- `cOS_tasks/20260326_164228_tasks_add_memory_to_the_system_https_github_com_thedotmack_claude_mem_git.md` — Tasks

**Modified:**
- `src/colonyos/config.py` — Added `MemoryConfig` dataclass with `enabled`, `max_entries`, `max_inject_tokens`, `capture_failures` settings
- `src/colonyos/orchestrator.py` — Post-phase memory capture hooks, memory injection into phase prompts, failure capture
- `src/colonyos/cli.py` — New `colonyos memory` command group (list, search, delete, clear, stats)
- `src/colonyos/router.py` — Memory injection in direct-agent prompt builder
- `.gitignore` — Added `memory.db` pattern

**PRD:** `cOS_prds/20260326_164228_prd_add_memory_to_the_system_https_github_com_thedotmack_claude_mem_git.md`
**Tasks:** `cOS_tasks/20260326_164228_tasks_add_memory_to_the_system_https_github_com_thedotmack_claude_mem_git.md`

## 20260326_150000 — Direct-Agent Conversational State Persistence

Adds session persistence to the direct-agent path so follow-up messages like "yes"
or "do it" resolve correctly against the prior exchange. Uses the Claude Agent SDK's
native `resume` mechanism to carry conversation context between turns, with `/new`
command for explicit reset and graceful fallback on resume failure.

**Created:**
- `cOS_prds/20260326_134656_prd_no_right_now_the_direct_agent_path_is_basically_stateless_between_completed_subm.md` — PRD
- `cOS_tasks/20260326_134656_tasks_no_right_now_the_direct_agent_path_is_basically_stateless_between_completed_subm.md` — Tasks

**Modified:**
- `src/colonyos/agent.py` — Added `resume` parameter to `run_phase()` / `run_phase_sync()`
- `src/colonyos/cli.py` — Session ID threading in `_run_direct_agent()`, `_run_callback()`, CLI REPL loop, `/new` command
- `tests/test_agent.py` — Tests for resume parameter passthrough
- `tests/test_cli.py` — Tests for session persistence, `/new` command, fallback behavior

**PRD:** `cOS_prds/20260326_134656_prd_no_right_now_the_direct_agent_path_is_basically_stateless_between_completed_subm.md`
**Tasks:** `cOS_tasks/20260326_134656_tasks_no_right_now_the_direct_agent_path_is_basically_stateless_between_completed_subm.md`
## 20260325_170000 — TUI Default Mode, Smart Routing & Autonomous Sweep

Three features shipped in this release: (1) the TUI is now the default visualization
for `colonyos run` on interactive terminals, with `--no-tui` escape hatch for CI;
(2) the intent router gained complexity classification so trivial/small changes skip
planning and go straight to implement→review; and (3) a new `colonyos sweep` command
provides autonomous codebase quality analysis that feeds findings through the existing
implement→verify→review→deliver pipeline to produce fix PRs.

**Created:**
- `src/colonyos/instructions/sweep.md` — Sweep analysis agent instructions
- `src/colonyos/instructions/preflight_recovery.md` — Dirty-worktree recovery instructions
- `tests/test_sweep.py` — Full test suite for the sweep command
- `tests/test_precommit_hook.py` — Pre-commit hook integration tests
- `run_precommit_tests.py` — Pre-commit test runner

**Modified:**
- `src/colonyos/cli.py` — Added `sweep` command, TUI as default mode, `--no-tui` flag
- `src/colonyos/orchestrator.py` — Sweep analysis phase, skip-planning wiring, parallel result surfacing
- `src/colonyos/router.py` — Complexity classification, heuristic routing improvements
- `src/colonyos/config.py` — Sweep configuration support
- `src/colonyos/models.py` — Complexity field on RouterResult
- `src/colonyos/sanitize.py` — Security hardening
- `src/colonyos/tui/adapter.py` — Parallel implement result callbacks
- `tests/test_cli.py`, `tests/test_orchestrator.py`, `tests/test_router.py` — Extended test coverage

**PRDs:**
- `cOS_prds/20260323_201206_prd_the_tui_should_be_the_default_visualization_right_now_ctrl_c_doesn_t_work_well_d.md`
- `cOS_prds/20260324_112017_prd_i_want_to_introduce_a_new_feature_for_a_cleanup_agent_that_basically_functions_l.md`

**Tasks:**
- `cOS_tasks/20260323_201206_tasks_the_tui_should_be_the_default_visualization_right_now_ctrl_c_doesn_t_work_well_d.md`
- `cOS_tasks/20260324_112017_tasks_i_want_to_introduce_a_new_feature_for_a_cleanup_agent_that_basically_functions_l.md`

## 20260323_201500 — Interactive Terminal UI (Textual TUI)

Adds a full interactive terminal UI built on Textual, giving users a mission-control
experience for ColonyOS pipeline runs. Features a scrollable execution transcript,
multi-line composer for mid-run input, live status bar with phase/cost/turns/elapsed
display, and color-coded event rendering. Interactive terminals now default to the TUI
via `colonyos run`, with `--no-tui` available to force plain streaming output.

**Created:**
- `src/colonyos/tui/__init__.py` — Package init with optional-dependency guard
- `src/colonyos/tui/app.py` — AssistantApp main Textual application shell
- `src/colonyos/tui/adapter.py` — Bridge between PhaseUI callbacks and TUI widgets
- `src/colonyos/tui/styles.py` — TCSS stylesheet for the TUI layout
- `src/colonyos/tui/widgets/composer.py` — Multi-line input with auto-grow
- `src/colonyos/tui/widgets/hint_bar.py` — Keyboard shortcut hints
- `src/colonyos/tui/widgets/status_bar.py` — Persistent phase/cost/turns/elapsed bar
- `src/colonyos/tui/widgets/transcript.py` — Scrollable event display with auto-scroll
- `tests/tui/` — Full test suite for all TUI components

**Modified:**
- `src/colonyos/cli.py` — Added the Textual TUI, the deprecated `colonyos tui` alias, and the `--no-tui` escape hatch on `colonyos run`
- `src/colonyos/sanitize.py` — Fixed newline stripping bug
- `pyproject.toml` — Added `[tui]` optional dependency group
- `README.md` — Updated with TUI documentation

**PRD:** `cOS_prds/20260323_190105_prd_give_me_fucking_awesome_ux_that_is_a_fucking_amazing_experience_and_it_gets_peop.md`
**Tasks:** `cOS_tasks/20260323_190105_tasks_give_me_fucking_awesome_ux_that_is_a_fucking_amazing_experience_and_it_gets_peop.md`

## 20260321_211500 — Intent Router Agent

Adds a lightweight intent router that classifies user input before running the full pipeline.
Questions get fast, cheap answers via a read-only Q&A agent; only actual code-change requests
trigger the full Plan → Implement → Verify → Review → Deliver cycle. Reduces unnecessary
pipeline runs and saves significant time and cost for information-seeking queries.

**Created:**
- `src/colonyos/router.py` — Core routing logic: intent classification, Q&A agent, audit logging
- `src/colonyos/instructions/qa.md` — Instruction template for the read-only Q&A agent
- `tests/test_router.py` — 1100+ lines of comprehensive router tests

**Modified:**
- `src/colonyos/models.py` — Added `Phase.QA` enum value
- `src/colonyos/config.py` — Added `RouterConfig` dataclass with model, threshold, budget settings
- `src/colonyos/cli.py` — Integrated router into `run()` and REPL; added `--no-triage` flag
- `src/colonyos/slack.py` — Factored out shared triage logic, unified with router module
- `tests/test_config.py` — Extended config tests for router settings
- `tests/test_models.py` — Tests for new Phase.QA enum

**PRD:** `cOS_prds/20260321_125008_prd_right_now_the_pipeline_always_runs_this_huge_planner_implementation_orchestratio.md`
**Tasks:** `cOS_tasks/20260321_125008_tasks_right_now_the_pipeline_always_runs_this_huge_planner_implementation_orchestratio.md`

## 20260319_230625 — AI-Assisted Setup for ColonyOS Init

Adds a new default init mode where Claude Haiku reads the repository, auto-detects project
info (name, description, tech stack), selects the best persona pack and model preset, and
proposes a complete config for the user to confirm with a single "y". The manual wizard
remains available via `--manual`. Falls back gracefully on any LLM failure.

**Created / Modified:**
- `src/colonyos/models.py` — Added `RepoContext` dataclass for deterministic repo signals
- `src/colonyos/persona_packs.py` — Added `packs_summary()` helper for prompt serialization
- `src/colonyos/init.py` — Added `scan_repo_context()`, `_build_init_system_prompt()`, `_parse_ai_config_response()`, `render_config_preview()`, `run_ai_init()`, `_finalize_init()`; updated `collect_project_info()` and `run_init()` to accept pre-fill defaults
- `src/colonyos/cli.py` — Added `--manual` flag, updated routing: default → AI-assisted, `--manual` → classic wizard
- `tests/test_init.py` — Added 39 new tests for repo scanning, prompt building, response parsing, AI init flow, config preview, fallback pre-fill, and error handling
- `tests/test_cli.py` — Added 6 CLI routing tests for `--manual` flag and mutual exclusivity
- `README.md` — Updated Quickstart section to reflect AI-assisted default

**PRD:** `cOS_prds/20260319_230625_prd_can_we_make_colonyos_setup_choice_one_where_an_assistant_sets_you_up_dynamically.md`
**Tasks:** `cOS_tasks/20260319_230625_tasks_can_we_make_colonyos_setup_choice_one_where_an_assistant_sets_you_up_dynamically.md`

## 20260320_035000 — `colonyos pr-review` GitHub PR Review Auto-Fix Command

Added a new `colonyos pr-review <pr-number>` CLI command that monitors GitHub PR review
comments and automatically runs lightweight fix pipelines in response. When a reviewer
leaves actionable inline feedback on a PR, the bot triages the comment using the existing
haiku-based triage agent, applies the fix via `run_thread_fix()` (Implement → Verify → Deliver),
and replies on the original comment thread with what was fixed and a link to the commit.

**Created:**
- `src/colonyos/pr_review.py` — PR review comment fetching, filtering, state tracking, GitHub reply posting
- `src/colonyos/instructions/thread_fix_pr_review.md` — Instruction template for PR review fix context
- `tests/test_pr_review.py` — Comprehensive tests for PR review functionality

**Modified:**
- `src/colonyos/cli.py` — Added `pr-review` command with `--watch`, `--poll-interval`, `--dry-run` options
- `src/colonyos/config.py` — Added `PRReviewConfig` dataclass with `budget_per_pr`, `poll_interval_seconds`
- `src/colonyos/models.py` — Added `source_type="pr_review_fix"` support in `QueueItem`
- `src/colonyos/orchestrator.py` — Extended `run_thread_fix()` for PR review context
- `README.md` — Updated CLI reference with pr-review command documentation

**PRD:** `cOS_prds/20260320_025613_prd_add_a_colonyos_pr_review_pr_number_command_that_monitors_github_pr_review_commen.md`
**Tasks:** `cOS_tasks/20260320_025613_tasks_add_a_colonyos_pr_review_pr_number_command_that_monitors_github_pr_review_commen.md`

## 20260320_051500 — Parallel Implement Mode

Enables concurrent task execution during the Implement phase by spawning multiple agent
sessions in isolated git worktrees. Features DAG-based dependency tracking with
`depends_on: []` annotations in task files, topological task scheduling, incremental
merge strategy with asyncio locking, automatic conflict resolution via dedicated agent,
and graceful degradation to sequential mode when worktrees aren't available (e.g., shallow clones).
Includes parallelism stats in `colonyos stats` output showing wall time vs agent time savings.

**Created:**
- `src/colonyos/dag.py` — DAG parser with dependency annotation parsing, cycle detection, topological sort
- `src/colonyos/worktree.py` — Git worktree manager for ephemeral task isolation
- `src/colonyos/parallel_orchestrator.py` — ParallelImplementOrchestrator with task scheduling, merge coordination
- `src/colonyos/parallel_preflight.py` — Worktree support detection and graceful degradation
- `src/colonyos/instructions/implement_parallel.md` — Agent instructions for parallel task execution
- `src/colonyos/instructions/conflict_resolve.md` — Agent instructions for merge conflict resolution
- `tests/test_dag.py` — DAG parsing, cycle detection, topological sort tests
- `tests/test_worktree.py` — Worktree creation, cleanup, failure handling tests
- `tests/test_parallel_orchestrator.py` — Parallel orchestration, merge, conflict resolution tests
- `tests/test_parallel_preflight.py` — Worktree support detection tests
- `tests/test_parallel_config.py` — Parallel implement configuration tests

**Modified:**
- `src/colonyos/config.py` — Added `ParallelImplementConfig` dataclass, config parsing
- `src/colonyos/models.py` — Added `Phase.CONFLICT_RESOLVE`, `TaskStatus` enum, parallel metadata fields
- `src/colonyos/orchestrator.py` — Integration with parallel orchestrator, task dependency handling
- `src/colonyos/instructions/plan.md` — Instructions for annotating task dependencies
- `src/colonyos/stats.py` — Parallelism stats columns (Wall Time, Agent Time, Parallelism ratio)
- `src/colonyos/ui.py` — Task legend printing, per-task prefixes for parallel output streams
- `README.md` — Updated with parallel implement documentation
- `tests/test_stats.py`, `tests/test_ui.py`, `tests/test_models.py`, `tests/test_orchestrator.py` — Extended tests

**PRD:** `cOS_prds/20260320_041029_prd_add_a_parallel_implement_mode_that_spawns_multiple_agent_sessions_to_implement_i.md`
**Tasks:** `cOS_tasks/20260320_041029_tasks_add_a_parallel_implement_mode_that_spawns_multiple_agent_sessions_to_implement_i.md`

## 20260320_014500 — Parallel Progress Tracker for Real-Time Review Visibility

Added a parallel progress tracker that provides real-time visibility into concurrent
reviewer operations during the review phase. Shows a compact status line with per-reviewer
completion status, elapsed times, and running cost totals. Auto-detects TTY mode and
degrades gracefully to log-style output in CI environments.

**Created / Modified:**
- `src/colonyos/ui.py` — Added `ParallelProgressLine` class with TTY-aware rendering
- `src/colonyos/agent.py` — Extended `run_phases_parallel()` with `on_complete` callback using `asyncio.as_completed()`
- `src/colonyos/orchestrator.py` — Integrated progress tracker into review loop
- `src/colonyos/sanitize.py` — Added `sanitize_display_text()` for ANSI/control character stripping
- `tests/test_ui.py` — Tests for `ParallelProgressLine` rendering and TTY detection
- `tests/test_sanitize.py` — Tests for display text sanitization
- `tests/test_agent.py` — Tests for `on_complete` callback behavior

**PRD:** `cOS_prds/20260320_011056_prd_add_a_parallel_progress_tracker_that_provides_real_time_visibility_into_concurre.md`
**Tasks:** `cOS_tasks/20260320_011056_tasks_add_a_parallel_progress_tracker_that_provides_real_time_visibility_into_concurre.md`

## 20260319_152207 — Slack Thread Fix Requests — Conversational PR Iteration

Enables conversational iteration on PRs via Slack threads. When ColonyOS completes a pipeline
run triggered from Slack, users can `@mention` the bot in the same thread to request fixes on
the existing PR. The bot runs a lightweight fix pipeline (Implement → Deliver) on the same
branch, pushes new commits, and reports results back to the thread. Includes fix round limits,
Slack link sanitization, and full backwards compatibility.

**Created / Modified:**
- `src/colonyos/models.py` — Added `branch_name`, `fix_rounds`, `parent_item_id` fields to `QueueItem`
- `src/colonyos/config.py` — Added `max_fix_rounds_per_thread` to `SlackConfig`
- `src/colonyos/slack.py` — Added `should_process_thread_fix()`, `find_parent_queue_item()`, fix formatting helpers
- `src/colonyos/sanitize.py` — Added `strip_slack_links()` for Slack `<URL|text>` markup stripping
- `src/colonyos/orchestrator.py` — Added `run_thread_fix()` lightweight fix pipeline, `_build_thread_fix_prompt()`
- `src/colonyos/cli.py` — Thread-fix event handling, `_execute_fix_item()`, `slack_fix` routing in QueueExecutor
- `src/colonyos/instructions/thread_fix.md` — New instruction template for thread-initiated fixes
- `tests/test_models.py` — Tests for QueueItem thread-fix fields and backwards compatibility
- `tests/test_config.py` — Tests for `max_fix_rounds_per_thread` parsing and validation
- `tests/test_slack.py` — Tests for thread-fix detection, formatting, parent lookup
- `tests/test_sanitize.py` — Tests for Slack link sanitization
- `tests/test_orchestrator.py` — Tests for `run_thread_fix()` success, failure, and edge cases

**PRD:** `cOS_prds/20260319_152207_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Tasks:** `cOS_tasks/20260319_152207_tasks_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## 20260319_130000 — Unified Slack-to-Queue Autonomous Pipeline with LLM Triage

Unified the Slack watcher (`colonyos watch`) and queue system (`colonyos queue`) into a single
end-to-end flow: listen → triage → queue → execute → report. Added an LLM-based triage agent
(haiku model) that evaluates incoming Slack messages for actionability before queuing, plus
explicit branch targeting via `base:branch-name` syntax in messages. Includes daily budget caps,
rate limiting, circuit breaker patterns, and a `QueueExecutor` class for thread-safe queue processing.

**Created / Modified:**
- `src/colonyos/slack.py` — Triage agent integration, queue-backed watch loop, circuit breaker, daily budget tracking
- `src/colonyos/cli.py` — Updated `watch` command with queue integration, triage config, daily budget flags
- `src/colonyos/config.py` — `triage_scope`, `daily_budget_usd` fields on `SlackConfig`
- `src/colonyos/models.py` — `Phase.TRIAGE` enum, `QueueItem` triage metadata fields
- `src/colonyos/orchestrator.py` — `QueueExecutor` class, triage-to-queue pipeline, branch targeting
- `tests/test_slack.py` — Comprehensive tests for triage, queue integration, circuit breaker, budget enforcement
- `tests/test_queue.py` — Queue executor and triage metadata tests
- `tests/test_orchestrator.py` — QueueExecutor and branch targeting tests
- `tests/test_config.py` — Triage config parsing tests
- `tests/test_models.py` — Triage metadata model tests
- `README.md` — Updated with unified watch+queue documentation

**PRD:** `cOS_prds/20260319_104252_prd_i_want_to_have_the_following_flow_1_connect_to_a_slack_channel_i_e_bugs_listen_o.md`
**Tasks:** `cOS_tasks/20260319_104252_tasks_i_want_to_have_the_following_flow_1_connect_to_a_slack_channel_i_e_bugs_listen_o.md`

## 20260319_093000 — `colonyos cleanup` Codebase Hygiene & Structural Analysis

Added a `colonyos cleanup` command with three subcommands for maintaining codebase health:
`cleanup branches` prunes merged `colonyos/` branches (local and remote), `cleanup artifacts`
removes old `.colonyos/runs/` run logs, and `cleanup scan` runs an AI-powered structural
analysis that identifies complex files, long functions, and dead code. All destructive
operations default to dry-run mode, requiring `--execute` to apply changes.

**Created:**
- `src/colonyos/cleanup.py` — Branch pruning, artifact cleanup, and AI-powered structural scan logic
- `src/colonyos/instructions/cleanup_scan.md` — Agent instruction template for structural analysis
- `tests/test_cleanup.py` — Comprehensive tests for all cleanup subcommands (616 lines)

**Modified:**
- `src/colonyos/cli.py` — Added `cleanup` command group with `branches`, `artifacts`, `scan` subcommands
- `src/colonyos/config.py` — Added cleanup-related configuration fields
- `README.md` — Updated CLI reference with cleanup commands
- `tests/test_cli.py` — Extended CLI tests for cleanup commands

**PRD:** `cOS_prds/20260319_091624_prd_i_want_to_add_a_cleanup_command_that_basically_looks_for_things_to_optimize_and.md`
**Tasks:** `cOS_tasks/20260319_091624_tasks_i_want_to_add_a_cleanup_command_that_basically_looks_for_things_to_optimize_and.md`

## 20260319_091500 — Git State Pre-flight Check

Added a pre-flight git state assessment that runs at the very start of the pipeline before
any agent phases. Detects uncommitted changes, existing branches with open PRs, and stale
main branches — preventing wasted compute, duplicate PRs, and data loss. Includes `--offline`
and `--force` CLI flags, a `PreflightResult` dataclass for audit trails, and autonomous-mode
support that fails gracefully and continues to the next queue item.

**Created:**
- `tests/test_preflight.py` — Comprehensive tests for all pre-flight scenarios (607 lines)

**Modified:**
- `src/colonyos/orchestrator.py` — `_preflight_check()`, `_resume_preflight()`, `_gather_git_state()`, `_decide_action()` functions
- `src/colonyos/models.py` — `PreflightResult` dataclass, `RunLog.preflight` field
- `src/colonyos/cli.py` — `--offline` and `--force` flags on `run` and `auto` commands
- `src/colonyos/github.py` — `find_open_pr_for_branch()` helper
- `tests/test_github.py`, `tests/test_cli.py`, `tests/test_orchestrator.py`, `tests/test_ceo.py` — Extended tests

**PRD:** `cOS_prds/20260319_081958_prd_every_time_the_pipeline_starts_we_should_look_at_what_branch_we_re_on_see_the_di.md`
**Tasks:** `cOS_tasks/20260319_081958_tasks_every_time_the_pipeline_starts_we_should_look_at_what_branch_we_re_on_see_the_di.md`

## 20260319_001000 — Fix CI Failures & Interactive Dashboard Control Plane

Fixed CI test failures caused by missing `fastapi`/`uvicorn` in dev dependencies, and
transformed the read-only web dashboard into a full interactive control plane with write
API endpoints, inline config/persona editing, run launching, artifact previews, and
frontend test infrastructure (Vitest + React Testing Library).

**Created:**
- `web/src/components/ArtifactPreview.tsx`, `AuthTokenPrompt.tsx`, `InlineEdit.tsx`, `RunLauncher.tsx` — Interactive UI components
- `web/src/pages/Proposals.tsx`, `Reviews.tsx` — New dashboard pages for browsing artifacts
- `web/src/__tests__/` — Component, page, and API client tests (Vitest + RTL)
- `web/vitest.config.ts`, `web/src/setupTests.ts` — Frontend test infrastructure
- `tests/test_server_write.py` — Write API endpoint tests
- `tests/conftest.py` — Shared test fixtures

**Modified:**
- `pyproject.toml` — Added UI deps (`fastapi`, `uvicorn`) to dev extras for CI
- `.github/workflows/ci.yml` — Added `web-build` CI job
- `src/colonyos/server.py` — Write API endpoints (PUT config, POST runs, GET artifacts) with bearer token auth
- `web/src/pages/Config.tsx`, `Dashboard.tsx`, `RunDetail.tsx` — Transformed to interactive with inline editing
- `web/src/api.ts`, `web/src/types.ts` — Extended API client and type definitions
- `web/package.json` — Added Vitest, RTL, and test script

**PRD:** `cOS_prds/20260318_233254_prd_the_ui_tests_are_failing_on_the_ci_there_is_no_module_found_fastapi_and_there_ar.md`
**Tasks:** `cOS_tasks/20260318_233254_tasks_the_ui_tests_are_failing_on_the_ci_there_is_no_module_found_fastapi_and_there_ar.md`

## 20260318_181500 — ColonyOS Web Dashboard (`colonyos ui`)

Added a read-only web dashboard launched via `colonyos ui` that surfaces run history,
phase timelines, cost trends, and configuration in a local browser. Built as a Vite +
React SPA served by a thin FastAPI API layer wrapping existing data-layer functions.
Ships as an optional dependency (`pip install colonyos[ui]`), localhost-only.

**Created:**
- `src/colonyos/server.py` — FastAPI server with `/api/runs`, `/api/stats`, `/api/config` endpoints
- `src/colonyos/web_dist/` — Pre-built Vite SPA static assets (HTML, JS, CSS)
- `web/` — React + TypeScript + Tailwind source: Dashboard, RunDetail, Config pages, components
- `tests/test_server.py` — Comprehensive API tests (478 lines)
- `tests/test_cli.py` — CLI integration tests for `colonyos ui` command

**Modified:**
- `src/colonyos/cli.py` — Added `ui` subcommand to launch the web server
- `pyproject.toml` — Added optional `[ui]` dependency group (fastapi, uvicorn)
- `.gitignore` — Added web build artifacts

**PRD:** `cOS_prds/20260318_173116_prd_i_think_we_should_add_some_sort_of_ui_for_managing_all_this_seeing_runs_defining.md`
**Tasks:** `cOS_tasks/20260318_173116_tasks_i_think_we_should_add_some_sort_of_ui_for_managing_all_this_seeing_runs_defining.md`

## 20260318_173000 — `colonyos queue` Durable Multi-Item Execution Queue

Added a `colonyos queue` command that lets users enqueue multiple feature prompts
and/or GitHub issue references into a durable, file-backed queue, then execute them
sequentially through the full pipeline. Supports crash recovery (resume from first
pending item), aggregate budget/time caps, signal handling for graceful shutdown,
and a rich status display showing per-item progress and costs.

**Created:**
- `src/colonyos/models.py` — `QueueItem`, `QueueFile` dataclasses, `QueueItemStatus` enum, queue persistence logic
- `tests/test_queue.py` — Comprehensive tests for queue management, execution, crash recovery, signal handling

**Modified:**
- `src/colonyos/cli.py` — Added `queue` command group with `add`, `start`, `status`, `clear` subcommands
- `src/colonyos/orchestrator.py` — Queue execution loop with per-item error isolation and budget enforcement
- `src/colonyos/config.py` — Queue-related configuration fields

**PRD:** `cOS_prds/20260318_164532_prd_add_a_colonyos_queue_command_that_accepts_multiple_feature_prompts_and_or_github.md`
**Tasks:** `cOS_tasks/20260318_164532_tasks_add_a_colonyos_queue_command_that_accepts_multiple_feature_prompts_and_or_github.md`

## 20260318_170000 — `colonyos show <run-id>` Single-Run Inspector

Added a `colonyos show <run-id>` CLI command that loads a single run log and renders
a rich, readable breakdown: header metadata, phase-by-phase timeline with cost/duration/status,
review details, decision gate, CI section, and artifact links. Supports prefix-based
run ID lookup with disambiguation, `--json` for machine-readable output, and `--phase`
filtering for drill-down into specific phases.

**Created:**
- `src/colonyos/show.py` — Data-layer (pure functions returning dataclasses) and render-layer (Rich output) for single-run inspection
- `tests/test_show.py` — Comprehensive unit tests for resolution, collapsing, rendering, `--json`, and `--phase` filtering

**Modified:**
- `src/colonyos/cli.py` — Added `show` subcommand with `--json` and `--phase` flags

**PRD:** `cOS_prds/20260318_162724_prd_add_a_colonyos_show_run_id_cli_command_that_renders_a_detailed_single_run_inspec.md`
**Tasks:** `cOS_tasks/20260318_162724_tasks_add_a_colonyos_show_run_id_cli_command_that_renders_a_detailed_single_run_inspec.md`

## 20260318_164500 — `colonyos ci-fix` Command & CI-Aware Deliver Phase

Added a standalone `colonyos ci-fix <pr-number>` CLI command that detects CI failures,
fetches failure logs, and runs an AI agent to fix the code and push a fix commit. Also
integrated optional CI monitoring into the `auto` pipeline deliver phase so runs can
wait for CI and auto-fix failures before marking complete.

**Created:**
- `src/colonyos/ci.py` — CI check fetching, log retrieval, sanitization, fix agent orchestration, retry loop
- `src/colonyos/instructions/ci_fix.md` — Agent instruction template for CI fix sessions
- `tests/test_ci.py` — Comprehensive tests for CI module (log truncation, sanitization, retry logic)
- `tests/test_config.py` — Tests for CI fix configuration parsing
- `tests/test_stats.py` — Tests for CI_FIX phase in stats display

**Modified:**
- `src/colonyos/cli.py` — Added `ci-fix` subcommand with `--wait`, `--max-retries`, `--wait-timeout` flags
- `src/colonyos/config.py` — Added `CIFixConfig` dataclass and config parsing
- `src/colonyos/models.py` — Added `Phase.CI_FIX` enum member
- `src/colonyos/orchestrator.py` — CI monitoring loop in deliver phase
- `src/colonyos/sanitize.py` — Secret-pattern regex pass for CI log sanitization
- `tests/test_cli.py`, `tests/test_orchestrator.py`, `tests/test_sanitize.py`, `tests/test_models.py` — Extended tests

**PRD:** `cOS_prds/20260318_154057_prd_add_a_colonyos_ci_fix_command_and_integrate_ci_awareness_into_the_deliver_phase.md`
**Tasks:** `cOS_tasks/20260318_154057_tasks_add_a_colonyos_ci_fix_command_and_integrate_ci_awareness_into_the_deliver_phase.md`

## 20260318_154500 — Reorganize cOS_reviews Directory Structure

Reorganized `cOS_reviews/` from a flat directory into a structured hierarchy with
`decisions/` and `reviews/<persona_slug>/` subdirectories. All review artifact filenames
are now timestamp-prefixed and generated through centralized `naming.py` functions,
eliminating ad-hoc filename construction in the orchestrator.

**Created:**
- `cOS_reviews/decisions/` — Decision gate verdicts, timestamped
- `cOS_reviews/reviews/<persona_slug>/` — Per-persona review history with timestamped filenames

**Modified:**
- `src/colonyos/naming.py` — Added `ReviewArtifactPath` dataclass, `decision_artifact_path()`, `persona_review_artifact_path()`, `task_review_artifact_path()`
- `src/colonyos/orchestrator.py` — Updated `_save_review_artifact()` with subdirectory support; replaced all ad-hoc filename construction with `naming.py` calls
- `src/colonyos/init.py` — Creates `decisions/` and `reviews/` subdirectories with `.gitkeep` during init
- `src/colonyos/instructions/base.md`, `decision.md`, `decision_standalone.md`, `fix.md`, `fix_standalone.md`, `learn.md` — Updated to reference nested directory structure
- `tests/test_naming.py`, `tests/test_orchestrator.py`, `tests/test_init.py` — Extended with new tests

**PRD:** `cOS_prds/20260318_150423_prd_let_s_change_the_way_the_reviews_directory_is_organized_reviews_by_specific_pers.md`
**Tasks:** `cOS_tasks/20260318_150423_tasks_let_s_change_the_way_the_reviews_directory_is_organized_reviews_by_specific_pers.md`

## 20260318_113000 — Theme-Safe Markdown Rendering

Removed hardcoded dark backgrounds from `rich.Markdown` inline-code and code-block
styles so terminal output is readable on both light and dark themes.

**Modified:**
- `src/colonyos/ui.py` — Custom `Theme` on module-level `Console` overriding `markdown.code` / `markdown.code_block`
- `src/colonyos/cli.py` — Same theme applied to the CEO-proposal `Console` instance

## 20260318_110000 — Package Publishing & Multi-Channel Installation

Added CI/CD pipeline, automated release workflow, curl installer, and Homebrew tap so
ColonyOS can be installed via `pip`, `curl | sh`, or `brew install`. Adopted `setuptools-scm`
for single-source versioning from git tags, eliminating hardcoded version duplication.

**Created:**
- `.github/workflows/ci.yml` — CI pipeline running pytest on Python 3.11/3.12 for every push/PR
- `.github/workflows/release.yml` — Automated release on `v*` tags: test → build → publish to PyPI → GitHub Release
- `install.sh` — Curl one-liner installer (detects OS, installs via pipx/pip, runs `colonyos doctor`)
- `Formula/colonyos.rb` — Homebrew tap formula
- `tests/test_ci_workflows.py` — CI/release workflow validation tests
- `tests/test_install_script.sh` — Shell-based installer tests
- `tests/test_install_script_integration.py` — Python integration tests for install.sh
- `tests/test_version.py` — Version consistency tests

**Modified:**
- `pyproject.toml` — Dynamic versioning via `setuptools-scm`, added `build` dependency
- `src/colonyos/__init__.py` — Version from `importlib.metadata` instead of hardcoded string
- `src/colonyos/doctor.py` — Added pipx availability check
- `README.md` — Added installation channels section (pip, curl, brew)

**PRD:** `cOS_prds/20260318_105239_prd_there_should_be_an_easy_way_to_install_this_on_a_repository_with_curl_npm_pip_br.md`
**Tasks:** `cOS_tasks/20260318_105239_tasks_there_should_be_an_easy_way_to_install_this_on_a_repository_with_curl_npm_pip_br.md`

## 20260318_091500 — Slack Integration (`colonyos watch`)

Added Slack as a fourth input source for the ColonyOS pipeline. Team members can trigger
pipeline runs directly from Slack via `@ColonyOS` mentions, emoji reactions, or slash
commands — eliminating the context-switch between discussion and execution. The watcher
runs as a long-lived CLI command (`colonyos watch`) using Slack Bolt SDK with Socket Mode.

**Created:**
- `cOS_prds/20260318_081144_prd_the_option_to_connect_to_slack_my_vision_for_this_in_the_future_is_that_it_monit.md` — PRD
- `cOS_tasks/20260318_081144_tasks_the_option_to_connect_to_slack_my_vision_for_this_in_the_future_is_that_it_monit.md` — Tasks
- `src/colonyos/slack.py` — Slack Bolt listener, dedup ledger, threaded progress replies
- `tests/test_slack.py` — Comprehensive Slack integration tests
- `src/colonyos/sanitize.py` — Input sanitization for untrusted Slack content
- `tests/test_sanitize.py` — Sanitization tests

**Modified:**
- `src/colonyos/cli.py` — Added `colonyos watch` command with budget/time caps
- `src/colonyos/config.py` — `SlackConfig` model with channels, trigger_mode, rate limits
- `src/colonyos/doctor.py` — Slack token validation check
- `pyproject.toml` — Added `slack-bolt` dependency

**PRD:** `cOS_prds/20260318_081144_prd_the_option_to_connect_to_slack_my_vision_for_this_in_the_future_is_that_it_monit.md`
**Tasks:** `cOS_tasks/20260318_081144_tasks_the_option_to_connect_to_slack_my_vision_for_this_in_the_future_is_that_it_monit.md`

## 20260318_080000 — Interactive REPL Mode & Command Registry Sync Enforcement

Added an interactive REPL mode so that bare `colonyos` invocations drop users into a
prompt where they can type feature descriptions directly, and refactored the welcome
banner to dynamically generate its command list from the Click registry. Includes a
pytest-based sync enforcement test that fails if any registered command is missing from
the banner or README.

**Created:**
- `cOS_prds/20260318_075437_prd_the_latest_runs_added_some_new_commands_however_they_did_not_update_the_readme_n.md` — PRD
- `cOS_tasks/20260318_075437_tasks_the_latest_runs_added_some_new_commands_however_they_did_not_update_the_readme_n.md` — Tasks
- `tests/test_registry_sync.py` — Registry sync enforcement test

**Modified:**
- `src/colonyos/cli.py` — Dynamic banner generation, interactive REPL loop, session cost tracking
- `src/colonyos/ui.py` — REPL prompt styling
- `README.md` — Updated CLI Reference table with `stats` and all current commands

**PRD:** `cOS_prds/20260318_075437_prd_the_latest_runs_added_some_new_commands_however_they_did_not_update_the_readme_n.md`
**Tasks:** `cOS_tasks/20260318_075437_tasks_the_latest_runs_added_some_new_commands_however_they_did_not_update_the_readme_n.md`

## 20260318_004500 — Per-Phase Model Override Configuration

Added `phase_models` configuration to `.colonyos/config.yaml` allowing users to assign
different Claude models (opus, sonnet, haiku) to different pipeline phases. Enables
50-70% cost savings by routing mechanical phases to cheaper models while keeping opus
for deep reasoning tasks. Includes fail-fast validation, two init presets
(quality-first / cost-optimized), model usage stats in `colonyos stats`, and full
backward compatibility.

**Created:**
- `cOS_prds/20260318_003243_prd_add_per_phase_model_override_configuration_to_colonyos_currently_config_yaml_has.md` — PRD
- `cOS_tasks/20260318_003243_tasks_add_per_phase_model_override_configuration_to_colonyos_currently_config_yaml_has.md` — Tasks

**Modified:**
- `src/colonyos/config.py` — `VALID_MODELS`, `phase_models` field, `get_model()` method, validation
- `src/colonyos/models.py` — `PhaseResult.model` field
- `src/colonyos/agent.py` — Populate `PhaseResult.model` on execution
- `src/colonyos/orchestrator.py` — Replace `config.model` with `config.get_model(Phase.XXX)` across all phases
- `src/colonyos/init.py` — Model preset selection (quality-first / cost-optimized)
- `src/colonyos/stats.py` — `ModelUsageRow`, `compute_model_usage()`, model usage dashboard section
- `src/colonyos/ui.py` — Per-phase model display in phase headers
- `tests/test_config.py`, `tests/test_orchestrator.py`, `tests/test_stats.py`, `tests/test_init.py` — New tests

**PRD:** `cOS_prds/20260318_003243_prd_add_per_phase_model_override_configuration_to_colonyos_currently_config_yaml_has.md`
**Tasks:** `cOS_tasks/20260318_003243_tasks_add_per_phase_model_override_configuration_to_colonyos_currently_config_yaml_has.md`

## 20260318_002000 — `colonyos stats` Aggregate Analytics Dashboard

Added a `colonyos stats` CLI command that reads all persisted `run-*.json` files from
`.colonyos/runs/` and renders a multi-section analytics dashboard showing cost breakdown
by phase, failure hotspots, review loop efficiency, duration stats, and recent run trends.
Supports `--last N` and `--phase <name>` filtering options.

**Created:**
- `src/colonyos/stats.py` — Data computation layer (pure functions returning typed dataclasses) and rich rendering layer
- `tests/test_stats.py` — Comprehensive unit tests (empty dir, single/multi run, corrupted files, null costs, filtering)

**Modified:**
- `src/colonyos/cli.py` — `stats` command with `--last` and `--phase` options
- `src/colonyos/ui.py` — Exposed `_format_duration` for reuse

**PRD:** `cOS_prds/20260318_001555_prd_add_a_colonyos_stats_cli_command_that_reads_all_persisted_runlog_json_files_from.md`
**Tasks:** `cOS_tasks/20260318_001555_tasks_add_a_colonyos_stats_cli_command_that_reads_all_persisted_runlog_json_files_from.md`

## 20260318_000500 — GitHub Issue Integration

Added `--issue` flag to `colonyos run` that fetches a GitHub issue (by number or URL)
and uses it as the pipeline prompt. The CEO autonomous phase now sees open issues as
context for its proposals. Issue-triggered runs produce PRs with `Closes #N` for
auto-close on merge, and `colonyos status` displays source issue URLs.

**Created:**
- `src/colonyos/github.py` — `GitHubIssue` dataclass, `fetch_issue()`, `parse_issue_ref()`, `format_issue_as_prompt()`, `fetch_open_issues()`
- `tests/test_github.py` — Unit tests for all GitHub module functions

**Modified:**
- `src/colonyos/cli.py` — `--issue` flag on `run` command, status display with issue URLs
- `src/colonyos/orchestrator.py` — Plan/deliver/CEO prompts enriched with issue context
- `src/colonyos/models.py` — `RunLog.source_issue` and `source_issue_url` fields
- `tests/test_cli.py`, `tests/test_orchestrator.py`, `tests/test_ceo.py`, `tests/test_models.py` — Extended tests

**PRD:** `cOS_prds/20260317_235155_prd_add_github_issue_integration_to_colonyos_so_users_can_point_the_pipeline_at_an_i.md`
**Tasks:** `cOS_tasks/20260317_235155_tasks_add_github_issue_integration_to_colonyos_so_users_can_point_the_pipeline_at_an_i.md`

## 20260317_215200 — Pre-commit hook for test suite

Added a `pre-commit` hook to run project tests before commits and prevent
regressions from being committed.

**Created:**
- `.pre-commit-config.yaml` — Local hook entry for the pre-commit pytest runner

**Modified:**
- `pyproject.toml` — Added `[project.optional-dependencies] dev` with `pre-commit` and `pytest`

## 20260317_214623 — CEO Past-Work Context via CHANGELOG

Moved `CHANGELOG.md` to the project root, backfilled 8 missing feature entries,
and wired the changelog into the CEO prompt so proposals never duplicate past work.
The deliver phase now auto-updates the changelog after each run. CEO proposal
output renders as styled Markdown in the terminal.

**Moved:**
- `cOS_tasks/CHANGELOG.md` → `CHANGELOG.md` (project root)

**Modified:**
- `src/colonyos/orchestrator.py` — `_build_ceo_prompt()` accepts `repo_root`, reads `CHANGELOG.md`, injects into user prompt
- `src/colonyos/instructions/ceo.md` — Simplified Step 2 to reference injected changelog; added "Builds Upon" output section
- `src/colonyos/instructions/deliver.md` — New Step 2: update `CHANGELOG.md` after each run
- `src/colonyos/cli.py` — CEO proposal rendered with `rich.markdown.Markdown` inside a `Panel`
- `tests/test_ceo.py` — Updated for new `repo_root` param; added changelog injection tests

## 20260317_200233 — Cross-Run Learnings System

Added an automatic learnings extraction system that mines review artifacts after each
completed run, persists patterns to `.colonyos/learnings.md`, and injects them as
context into future implement and fix phases. Enables the pipeline to self-improve
across iterations.

**Created:**
- `src/colonyos/learnings.py` — `extract_learnings()`, `load_learnings()`, `save_learnings()`, ledger management
- `tests/test_learnings.py` — Unit tests for extraction, persistence, and injection

**Modified:**
- `src/colonyos/orchestrator.py` — Learn phase wired after deliver; learnings injected into implement/fix prompts
- `src/colonyos/config.py` — `learnings` config section (`enabled`, `max_entries`)
- `src/colonyos/cli.py` — `status` command shows learnings count
- `src/colonyos/models.py` — `Phase.LEARN` enum value

**PRD:** `cOS_prds/20260317_200233_prd_add_a_cross_run_learnings_system_that_automatically_extracts_patterns_from_revie.md`
**Tasks:** `cOS_tasks/20260317_200233_tasks_add_a_cross_run_learnings_system_that_automatically_extracts_patterns_from_revie.md`

## 20260317_200000 — Auto-approve config + README rebrand

Added `auto_approve` config setting for unattended CEO-driven runs and rebranded
the README to position ColonyOS as a fully autonomous self-building pipeline.

**Changes:**
- `src/colonyos/config.py` — Added `auto_approve: bool` field to `ColonyConfig`, parsed from YAML, serialized back
- `src/colonyos/cli.py` — `auto` command checks `config.auto_approve or no_confirm` to skip human confirmation
- `.colonyos/config.yaml` — Added `auto_approve: true` (dogfood: this repo runs fully autonomous)
- `README.md` — New tagline ("The fully autonomous AI pipeline that builds itself"), Mermaid pipeline diagrams, autonomous-first copy, expanded CLI reference
- `assets/logo.png` — Added project logo
- `tests/test_config.py` — Added `TestAutoApprove` class (default, parse, roundtrip)
- `tests/test_cli.py` — Added tests for `auto_approve` config skipping confirmation and prompting when false

## 20260317_192516 — Standalone `colonyos review <branch>` command

Added a `colonyos review <branch>` CLI command that runs only the review/fix loop
against an arbitrary Git branch, without requiring a PRD or task file. Enables
ColonyOS as a lightweight standalone multi-persona code review tool.

**Created:**
- `src/colonyos/instructions/review_standalone.md` — Standalone review instruction template
- `src/colonyos/instructions/fix_standalone.md` — Standalone fix instruction template
- `src/colonyos/instructions/decision_standalone.md` — Standalone decision instruction template

**Modified:**
- `src/colonyos/cli.py` — Added `review` command with `--base`, `--no-fix`, `--decide` options
- `src/colonyos/orchestrator.py` — Added `run_review_standalone()` function
- `tests/test_cli.py` — Tests for the review command

**PRD:** `cOS_prds/20260317_192516_prd_add_a_colonyos_review_branch_cli_command_that_runs_only_the_review_fix_loop_and.md`
**Tasks:** `cOS_tasks/20260317_192516_tasks_add_a_colonyos_review_branch_cli_command_that_runs_only_the_review_fix_loop_and.md`

## 20260317_183545 — Post-Implement Verification Gate

Added a configurable verification gate between implement and review that runs a
user-specified test command (e.g., `pytest`, `npm test`) via subprocess. Failed
tests trigger implement retries with failure context before the expensive review
phase fires.

**Created:**
- `src/colonyos/instructions/verify_fix.md` — Verify-fix instruction template
- `tests/test_verify.py` — Full unit tests for the verification loop

**Modified:**
- `src/colonyos/models.py` — `Phase.VERIFY` enum value
- `src/colonyos/config.py` — `VerificationConfig` dataclass (`verify_command`, `max_verify_retries`, `verify_timeout`)
- `src/colonyos/orchestrator.py` — `run_verify_loop()` wired between implement and review
- `src/colonyos/init.py` — Auto-detect test runner during `colonyos init` (`_detect_test_command`)
- `tests/test_config.py`, `tests/test_init.py`, `tests/test_orchestrator.py` — Extended tests

**PRD:** `cOS_prds/20260317_183545_prd_add_a_configurable_post_implement_verification_gate_that_runs_the_project_s_test.md`
**Tasks:** `cOS_tasks/20260317_183545_tasks_add_a_configurable_post_implement_verification_gate_that_runs_the_project_s_test.md`

## 20260317_180000 — Review/fix loop redesign: per-persona parallel reviews + fix agent

Replaced the monolithic subagent-based review with independent per-persona parallel
sessions and a dedicated fix agent loop. Reviews are now fast, focused, and configurable.

**Architecture change:**
- Old: 1 session per task with 7 subagents nested → holistic review → decision → fix loop
- New: N reviewer personas run in parallel via asyncio.gather → if request-changes, fix agent runs → re-review → decision gate

**Changes:**
- `src/colonyos/models.py` — Added `reviewer: bool = False` field to `Persona` dataclass
- `src/colonyos/config.py` — Parse/serialize `reviewer` in `_parse_personas`, `_parse_persona`, `save_config`
- `src/colonyos/init.py` — Ask "Should this persona participate in code reviews?" during persona collection
- `src/colonyos/agent.py` — Added `run_phases_parallel()` and `run_phases_parallel_sync()` for concurrent phase execution
- `src/colonyos/orchestrator.py` — Deleted `_build_review_persona_agents`, `_format_review_personas_block`, per-task review loop; added `_reviewer_personas`, `_build_persona_review_prompt`, `_extract_review_verdict`, `_collect_review_findings`; rewrote Phase 3 as review/fix loop
- `src/colonyos/instructions/review.md` — Persona identity baked into template (`{reviewer_role}`, `{reviewer_expertise}`, `{reviewer_perspective}`); structured VERDICT output required
- `src/colonyos/instructions/fix.md` — Staff+ Google Engineer identity; uses `{findings_text}` from reviewer findings
- `.colonyos/config.yaml` — Tagged 4 personas as reviewers; added `proposals_dir`, `max_fix_iterations`
- `tests/test_orchestrator.py` — Full rewrite for new parallel review + fix loop architecture
- `tests/test_config.py` — Added `TestReviewerField` class
- `tests/test_ceo.py` — Updated integration test for parallel review mocking

## 20260317_173500 — Welcome banner with ASCII ant and commands

Added a Claude Code–style welcome banner when running `colonyos` with no subcommand.
Shows an ASCII ant mascot, the ColonyOS logo in big letters, version/model info,
working directory, and a command reference.

**Changes:**
- `src/colonyos/cli.py` — Added `_show_welcome()` function with rich Panel/Table layout; changed `app` group to `invoke_without_command=True` with `@click.pass_context` to show banner when no subcommand given

## 20260317_172645 — Rich Streaming Terminal UI

Added a streaming terminal UI using the `rich` library that shows real-time agent
activity during pipeline execution. Each phase renders tool calls as they happen,
and parallel reviews show per-persona prefixed output.

**New:**
- `src/colonyos/ui.py` — `PhaseUI` class with streaming callbacks (tool_start, tool_input_delta, tool_done, text_delta, turn_complete); `NullUI` no-op for tests/quiet mode; `TOOL_DISPLAY` mapping for extracting primary args from partial JSON
- `-v/--verbose` flag on `run` and `auto` — streams agent text alongside tool activity
- `-q/--quiet` flag on `run` and `auto` — suppresses streaming UI
- `rich>=13.0` added to `pyproject.toml`

**Modified:**
- `src/colonyos/agent.py` — `run_phase()` accepts `ui` param; enables `include_partial_messages` when ui present; processes `StreamEvent` (content_block_start/delta/stop) and `AssistantMessage` for turn counting
- `src/colonyos/orchestrator.py` — `run()` and `run_ceo()` accept `verbose`/`quiet`; creates `PhaseUI` per phase; parallel reviews get `PhaseUI(prefix="[Role] ")`; falls back to `_log()` when ui is None
- `src/colonyos/cli.py` — Added `-v`/`-q` flags to `run` and `auto` commands; passed through to orchestrator and `_run_single_iteration`

**PRD:** `cOS_prds/20260317_172645_prd_rich_streaming_terminal_ui_for_agent_phases.md`
**Tasks:** `cOS_tasks/20260317_172645_tasks_rich_streaming_terminal_ui_for_agent_phases.md`

## 20260317_163656 — Developer Onboarding & Long-Running Autonomous Loops

Added `colonyos doctor` for prerequisite validation, overhauled the README with
badges and visual proof, and removed the artificial loop cap to enable 24+ hour
autonomous runs with time-based budget caps.

**Created:**
- `src/colonyos/doctor.py` — Prerequisite checks (Python, Claude Code CLI, Git, GitHub CLI)

**Modified:**
- `src/colonyos/cli.py` — `doctor` command; `--loop` removed iteration cap, added time-based budget enforcement
- `src/colonyos/init.py` — `check_prereqs()` runs at start of `colonyos init`
- `README.md` — Badges, terminal GIF placeholder, "wall of self-built PRs" section
- `tests/test_cli.py`, `tests/test_init.py` — Tests for doctor and prereq checks

**PRD:** `cOS_prds/20260317_163656_prd_i_want_this_to_be_super_easy_to_set_up_if_you_re_a_dev_you_should_be_able_to_be.md`
**Tasks:** `cOS_tasks/20260317_163656_tasks_i_want_this_to_be_super_easy_to_set_up_if_you_re_a_dev_you_should_be_able_to_be.md`

## 20260317_155508 — Resume Failed Runs (`--resume`)

Added `--resume <run-id>` flag to `colonyos run` that resumes a previously failed
run from the next phase after the last successfully completed one. Saves cost by
skipping phases that already succeeded.

**Modified:**
- `src/colonyos/cli.py` — `--resume` flag on `run` command; validates resumable state
- `src/colonyos/orchestrator.py` — `run()` accepts `skip_phases` set; `_compute_next_phase()` for resume logic
- `src/colonyos/models.py` — `RunLog` tracks per-phase completion status
- `src/colonyos/cli.py` — `status` command shows `[resumable]` next to failed runs

**PRD:** `cOS_prds/20260317_155508_prd_add_a_resume_run_id_flag_to_colonyos_run_that_resumes_a_previously_failed_run_fr.md`
**Tasks:** `cOS_tasks/20260317_155508_tasks_add_a_resume_run_id_flag_to_colonyos_run_that_resumes_a_previously_failed_run_fr.md`

## 20260317_150000 — Address persona review findings + decision gate

Addressed all CRITICAL/HIGH findings from the 7-persona review of the CEO stage.
Added a decision gate between review and deliver that gives a GO/NO-GO verdict.

**Fixes:**
- `src/colonyos/naming.py` — Truncate slugs to 80 chars max (fixes OSError: File name too long)
- `src/colonyos/orchestrator.py` — `_extract_feature_prompt` uses case-insensitive regex, handles ### terminators, strips code fences
- `src/colonyos/orchestrator.py` — Proposal only saved on success; removed "save your proposal" from CEO prompt
- `src/colonyos/cli.py` — CEO phase recorded in RunLog; `_print_run_summary` helper extracted; success check before display
- `src/colonyos/cli.py` — `--loop` capped at 10 iterations with aggregate budget enforcement via `per_run`
- `src/colonyos/cli.py` — `--plan-only` renamed to `--propose-only` on `auto` command
- `src/colonyos/init.py` — Preserves `ceo_persona` when re-running init

**New features:**
- `src/colonyos/instructions/decision.md` — Decision gate instruction template
- `src/colonyos/orchestrator.py` — `_build_decision_prompt`, `_extract_verdict`, wired between review and deliver
- `src/colonyos/models.py` — `Phase.DECISION` enum value
- Pipeline now: plan → implement → review → **decision gate** → deliver

## 20260317_133813 — Autonomous CEO Stage (`colonyos auto`)

Added `colonyos auto` command where an AI CEO persona analyzes the project, its
history, and strategic direction to autonomously decide what to build next. The
CEO's output feeds directly into the Plan → Implement → Review → Deliver pipeline.

**Created:**
- `src/colonyos/instructions/ceo.md` — CEO instruction template with project analysis and proposal format

**Modified:**
- `src/colonyos/cli.py` — `auto` command with `--no-confirm`, `--propose-only`, `--loop` flags
- `src/colonyos/orchestrator.py` — `run_ceo()` function, `_build_ceo_prompt()`, `_extract_feature_prompt()`
- `src/colonyos/config.py` — `ceo_persona` and `proposals_dir` config fields
- `.colonyos/config.yaml` — CEO persona definition and vision statement
- `tests/test_ceo.py` — Integration tests for the CEO phase

**PRD:** `cOS_prds/20260317_133813_prd_autonomous_ceo_stage.md`
**Tasks:** `cOS_tasks/20260317_133813_tasks_autonomous_ceo_stage.md`

## 20260317_100000 — Add iconic personas + parallel subagent Q&A

Added Steve Jobs, Jony Ive, Linus Torvalds, and Andrej Karpathy as personas.
Replaced Elon Musk and Sindre Sorhus. Each persona now runs as a separate
Agent SDK subagent during the plan phase, so all 7 personas answer clarifying
questions in parallel rather than sequentially in a single session.

**Changes:**
- `.colonyos/config.yaml` — 7 personas (was 5), fixed stack reference
- `src/colonyos/orchestrator.py` — `_build_persona_agents()` creates `AgentDefinition` per persona,
  `_format_personas_block()` now lists subagent keys and instructs parallel invocation
- `src/colonyos/agent.py` — accepts `agents` kwarg, adds `Agent` to allowed tools when subagents present
- `src/colonyos/instructions/plan.md` — explicit instruction to call all persona agents in parallel
- `tests/test_orchestrator.py` — tests for `_build_persona_agents`, `_persona_slug`, subagent plumbing

## 20260317_090603 — Persona Review Phase & cOS_ Directory Prefix

Added a multi-persona review phase between Implement and Deliver. Every defined
persona reviews completed tasks and performs a holistic assessment. All ColonyOS
output directories now use the `cOS_` prefix (`cOS_prds/`, `cOS_tasks/`, `cOS_reviews/`)
to clearly namespace agent-generated artifacts.

**Created:**
- `src/colonyos/instructions/review.md` — Review instruction template
- `cOS_reviews/` — Review artifact output directory

**Modified:**
- `src/colonyos/orchestrator.py` — Review phase wired between implement and deliver; per-persona reviews
- `src/colonyos/config.py` — Default directories changed to `cOS_prds`, `cOS_tasks`; added `reviews_dir: cOS_reviews`
- `.colonyos/config.yaml` — Updated directory defaults
- `tests/test_orchestrator.py` — Tests for review phase

**PRD:** `cOS_prds/20260317_090603_prd_persona_review_phase_and_cos_directory_prefix.md`
**Tasks:** `cOS_tasks/20260317_090603_tasks_persona_review_phase_and_cos_directory_prefix.md`

## 20260317_083203 — Prebuilt Persona Templates for `colonyos init`

Added curated persona packs ("Startup Team", "Enterprise Backend", "Frontend/Design",
etc.) that users can select during `colonyos init` instead of defining custom personas
from scratch. Reduces onboarding friction from ~12 prompts to 1 selection.

**Modified:**
- `src/colonyos/init.py` — `_PERSONA_PACKS` dict with curated templates; selection prompt during init
- `tests/test_init.py` — Tests for persona pack selection
- `tests/test_cli.py` — CLI integration tests for init with packs

**PRD:** `cOS_prds/20260317_083203_prd_we_should_be_able_to_offer_the_users_prebuilt_personas_when_they_initialize.md`
**Tasks:** `cOS_tasks/20260317_083203_tasks_we_should_be_able_to_offer_the_users_prebuilt_personas_when_they_initialize.md`

## 20260316_180500 — Migrate to Claude Agent SDK

Replaced `claude-code-sdk` (0.0.25) with the renamed `claude-agent-sdk` (0.1.49).
The old SDK had a critical incompatibility: it couldn't parse `rate_limit_event` messages
from the Claude Code CLI, causing `MessageParseError` and preventing `ResultMessage` from
being received. The new SDK handles all message types natively.

**Changes:**
- `src/colonyos/agent.py` — Rewrote to use `ClaudeAgentOptions` (was `ClaudeCodeOptions`),
  removed `MessageParseError` workaround, removed `got_assistant_msg` fallback logic.
  Now uses `max_budget_usd` option directly instead of custom budget handling.
- `pyproject.toml` — Dependency changed from `claude-code-sdk>=0.0.25` to `claude-agent-sdk>=0.1.49`
- `requirements.txt` — Same dependency update
- `README.md` — References updated from "Claude Code SDK" to "Claude Agent SDK"
- `tasks/20260316_172530_tasks_agent_loop_cli.md` — Added task 10.0 for SDK migration

## 20260316_172530 — ColonyOS v2: Clean Slate Build

Full rewrite of ColonyOS from a standalone Python CLI to an installable tool
orchestrating Claude Agent SDK sessions with full repo awareness.

**Created:**
- `src/colonyos/` — Full package: cli, config, agent, orchestrator, init, models, naming
- `src/colonyos/instructions/` — Markdown templates for each phase
- `tests/` — Unit tests for config, naming, orchestrator, CLI
- `prds/20260316_172530_prd_agent_loop_cli.md` — Self-referential PRD
- `tasks/20260316_172530_tasks_agent_loop_cli.md` — Implementation task list
- `.colonyos/config.yaml` — Project config with 5 expert personas
- `README.md` — Full documentation
- `pyproject.toml`, `requirements.txt` — Package configuration
