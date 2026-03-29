# Tasks: ColonyOS Daemon Mode — Fully Autonomous 24/7 Engineering Agent

## Relevant Files

### Core Implementation
- `src/colonyos/daemon.py` - **NEW** — Core daemon orchestration (event loop, schedulers, state management)
- `src/colonyos/daemon_state.py` - **NEW** — `DaemonState` dataclass, atomic file persistence, daily budget tracking
- `src/colonyos/models.py` - Add `priority` field to `QueueItem` (schema v4), add `DaemonStatus` enum
- `src/colonyos/config.py` - Add `DaemonConfig` dataclass, wire into `ColonyConfig`
- `src/colonyos/cli.py` - Add `colonyos daemon` command, extract CEO scheduling logic from `auto`

### Queue & Prioritization
- `src/colonyos/models.py` - `QueueItem.priority` field, priority computation helper
- `src/colonyos/cli.py` - Modify `_next_pending_item` to sort by priority then `added_at`

### Ingestion Sources
- `src/colonyos/github.py` - Add `poll_new_issues()` function with dedup logic
- `src/colonyos/slack.py` - Add control commands (pause/resume/status), daily digest posting
- `src/colonyos/cleanup.py` - Add `generate_cleanup_queue_items()` function

### Observability
- `src/colonyos/server.py` - Add `GET /healthz` endpoint
- `src/colonyos/daemon.py` - Heartbeat posting, daily digest generation

### Deployment
- `deploy/colonyos-daemon.service` - **NEW** — systemd unit file
- `deploy/README.md` - **NEW** — VM deployment guide

### Tests
- `tests/test_daemon.py` - **NEW** — Daemon orchestration tests
- `tests/test_daemon_state.py` - **NEW** — State persistence and budget tracking tests
- `tests/test_models.py` - Priority field tests, schema migration tests
- `tests/test_config.py` - DaemonConfig parsing tests
- `tests/test_github.py` - Issue polling and dedup tests
- `tests/test_slack.py` - Control command tests
- `tests/test_server.py` - Health endpoint tests

## Tasks

- [x] 1.0 DaemonConfig & Data Models (foundation — config and data structures)
  depends_on: []
  - [x] 1.1 Write tests for `DaemonConfig` dataclass parsing, defaults, and validation in `tests/test_config.py`
  - [x] 1.2 Add `DaemonConfig` dataclass to `config.py` with fields: `daily_budget_usd`, `github_poll_interval_seconds`, `ceo_cooldown_minutes`, `cleanup_interval_hours`, `max_cleanup_items`, `heartbeat_interval_minutes`, `digest_hour_utc`, `max_consecutive_failures`, `circuit_breaker_cooldown_minutes`, `issue_labels`, `allowed_control_user_ids`
  - [x] 1.3 Wire `DaemonConfig` into `ColonyConfig` as `daemon: DaemonConfig` field
  - [x] 1.4 Add `DEFAULTS["daemon"]` with sensible defaults
  - [x] 1.5 Write tests for `QueueItem` priority field (schema v4 migration, `from_dict` backward compat)
  - [x] 1.6 Add `priority: int = 1` field to `QueueItem`, bump `SCHEMA_VERSION` to 4, update `to_dict`/`from_dict`
  - [x] 1.7 Add priority computation helper: `compute_priority(source_type: str, labels: list[str] | None) -> int` mapping source_type to P0-P3

- [x] 2.0 DaemonState & Atomic Persistence (foundation — crash-safe state management)
  depends_on: []
  - [x] 2.1 Write tests for `DaemonState` dataclass (serialization, daily budget tracking, reset at midnight UTC, circuit breaker state)
  - [x] 2.2 Create `src/colonyos/daemon_state.py` with `DaemonState` dataclass: `daily_spend_usd`, `daily_reset_date`, `consecutive_failures`, `circuit_breaker_until`, `total_items_today`, `daemon_started_at`, `last_heartbeat`, `paused` flag
  - [x] 2.3 Write tests for atomic file write (write-to-temp-then-rename)
  - [x] 2.4 Implement `atomic_write_json(path, data)` utility — writes to `{path}.tmp` then `os.rename`
  - [x] 2.5 Migrate existing `queue.json` persistence to use `atomic_write_json`
  - [x] 2.6 Add `DaemonState.check_daily_budget(cap, current_cost)` method returning `(allowed: bool, remaining: float)`
  - [x] 2.7 Add `DaemonState.record_failure()` and `DaemonState.record_success()` methods for circuit breaker tracking

- [x] 3.0 Priority Queue Execution (core queue change — priority-ordered item selection)
  depends_on: [1.0]
  - [x] 3.1 Write tests for priority-ordered queue selection: highest priority first, FIFO within tier, starvation promotion after 24h
  - [x] 3.2 Modify `_next_pending_item` in daemon.py to sort pending items by `(priority, added_at)` before selecting
  - [x] 3.3 Add starvation check: if any pending item's `added_at` is >24h old, promote its priority by 1 tier (min 0)
  - [ ] 3.4 Ensure `queue add` CLI command sets priority via `compute_priority()`
  - [ ] 3.5 Update `queue status` display to show priority tier labels (P0/P1/P2/P3)

- [x] 4.0 GitHub Issue Polling (new ingestion source)
  depends_on: [1.0]
  - [ ] 4.1 Write tests for `poll_new_issues()`: dedup by issue number, label filtering, cross-channel dedup with Slack
  - [x] 4.2 Implement `poll_new_issues(queue_state, config) -> list[QueueItem]` in `github.py` — fetches open issues, filters by labels, deduplicates against existing queue items by `(source_type="issue", source_value=issue_number)`
  - [ ] 4.3 Write tests for Slack cross-channel dedup: Slack messages containing `_ISSUE_URL_RE` matches normalize to `source_type="issue"`
  - [ ] 4.4 Add issue URL detection to Slack message processing — if message contains a GitHub issue URL, set `source_type="issue"` and `source_value=issue_number`

- [x] 5.0 Core Daemon Orchestration (main daemon loop — wires everything together)
  depends_on: [1.0, 2.0, 3.0, 4.0]
  - [x] 5.1 Write tests for `Daemon` class: startup sequence, shutdown on SIGTERM, thread lifecycle, idle detection, CEO trigger conditions, cleanup trigger conditions
  - [x] 5.2 Create `src/colonyos/daemon.py` with `Daemon` class containing:
    - `start()` — main entry point, starts all threads, enters main loop
    - `stop()` — graceful shutdown (finish current run, stop threads)
    - `_slack_listener_thread()` — wraps existing `start_socket_mode` from `slack.py`
    - `_github_poller_thread()` — periodic `poll_new_issues()` calls
    - `_queue_executor_thread()` — priority-ordered queue drain loop (adapted from `QueueExecutor`)
    - `_scheduler_thread()` — CEO idle-fill + cleanup scheduling logic
    - `_health_monitor_thread()` — heartbeat + Slack alerts + daily digest
  - [x] 5.3 Implement CEO idle-fill logic: trigger `run_ceo()` when queue is empty AND no pipeline running AND cooldown elapsed. Inject open PRs/issues/recent runs as context. Enqueue result as `QueueItem(source_type="ceo", priority=2)`.
  - [x] 5.4 Implement cleanup scheduling: run existing `cleanup.py` operations on interval. Generate `QueueItem(source_type="cleanup", priority=3)` from structural scan candidates, capped at `max_cleanup_items`.
  - [x] 5.5 Implement budget enforcement: check `DaemonState.check_daily_budget()` before starting each pipeline run. Pause queue on budget exhaustion. Reset at midnight UTC.
  - [x] 5.6 Implement circuit breaker: increment failure count on run failure, reset on success. Pause queue for `circuit_breaker_cooldown_minutes` when threshold reached.
  - [x] 5.7 Implement startup crash recovery: scan for `RUNNING` queue items on startup, mark as `FAILED`, check heartbeat age, call `preserve_and_reset_worktree` if needed, ensure clean git state.
  - [x] 5.8 Add PID lock file (`.colonyos/daemon.pid`) to prevent multiple daemon instances on same repo.

- [ ] 6.0 Slack Control Commands & Observability (user-facing interaction — deferred to next iteration)
  depends_on: [5.0]
  - [ ] 6.1 Write tests for Slack control commands: "pause", "resume", "status" recognized from `allowed_control_user_ids`
  - [ ] 6.2 Implement control command handler in `slack.py`: detect "pause"/"stop"/"halt", "resume"/"start", "status" keywords in messages from allowed control users. Set/clear `DaemonState.paused` flag. Reply with confirmation.
  - [ ] 6.3 Write tests for Slack heartbeat and daily digest message formatting
  - [ ] 6.4 Implement heartbeat posting: every `heartbeat_interval_minutes`, post "ColonyOS alive — N items today, $X spent" to configured Slack channel
  - [ ] 6.5 Implement daily digest: at `digest_hour_utc`, post summary of completed runs, failures, spend, CEO proposals, cleanup results
  - [ ] 6.6 Implement budget threshold alerts: post to Slack at 80% daily budget, post and pause at 100%

- [x] 7.0 Health Endpoint & Dashboard (observability infrastructure)
  depends_on: [2.0]
  - [ ] 7.1 Write tests for `/healthz` endpoint: returns 200 when healthy, 503 when degraded/down
  - [x] 7.2 Add `GET /healthz` to `server.py` returning: `status` (healthy/degraded/down), `heartbeat_age_seconds`, `queue_depth`, `daily_spend_usd`, `daily_budget_remaining_usd`, `circuit_breaker_active`, `current_job` (if any), `paused`
  - [ ] 7.3 Add daemon status to existing `/api/stats` endpoint (daily spend, items processed, uptime)

- [x] 8.0 CLI Command & Deployment (user-facing entry point + systemd)
  depends_on: [5.0, 6.0, 7.0]
  - [ ] 8.1 Write tests for `colonyos daemon` CLI command argument parsing
  - [x] 8.2 Add `daemon` command to `cli.py` Click group: `--max-budget`, `--max-hours`, `--verbose`, `--dry-run` flags. Instantiates `Daemon` and calls `start()`.
  - [x] 8.3 Create `deploy/colonyos-daemon.service` systemd unit file with: `Restart=on-failure`, `RestartSec=30`, `WatchdogSec=120`, `PrivateTmp=yes`, `ProtectSystem=strict`, `ReadWritePaths=<repo>`, environment variable passthrough for tokens
  - [x] 8.4 Create `deploy/README.md` with VM deployment guide: prerequisites, systemd setup, config, monitoring, troubleshooting
  - [x] 8.5 Add `colonyos daemon` to CLI help text and update README

- [ ] 9.0 Integration Testing & Validation (end-to-end verification)
  depends_on: [5.0, 6.0, 7.0, 8.0]
  - [ ] 9.1 Write integration test: daemon startup → Slack message ingestion → priority queue ordering → pipeline execution (mocked) → Slack notification
  - [ ] 9.2 Write integration test: daemon crash simulation → restart → orphaned job recovery → clean continuation
  - [ ] 9.3 Write integration test: daily budget exhaustion → pause → midnight reset → resume
  - [ ] 9.4 Write integration test: circuit breaker trigger → cooldown → auto-resume
  - [ ] 9.5 Write integration test: GitHub issue polling → dedup → queue insertion → processing
  - [ ] 9.6 Write integration test: CEO idle-fill trigger → proposal generation → queue insertion
  - [x] 9.7 Run full existing test suite to verify zero regressions (`pytest tests/ -x`)
  - [ ] 9.8 Manual smoke test: deploy daemon on a VM with systemd, verify Slack round-trip (message → PR), verify crash recovery (kill -9 → restart), verify budget pause
