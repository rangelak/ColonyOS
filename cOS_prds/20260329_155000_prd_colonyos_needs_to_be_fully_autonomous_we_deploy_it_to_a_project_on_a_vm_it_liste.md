# PRD: ColonyOS Daemon Mode — Fully Autonomous 24/7 Engineering Agent

## Introduction/Overview

ColonyOS today is a powerful semi-autonomous engineering pipeline — but it requires a human to start each run, babysit the process, and restart after crashes. This PRD defines the architecture to make ColonyOS a **fully autonomous daemon** that runs 24/7 on a VM, ingests work from Slack and GitHub Issues, auto-queues CEO-proposed features and cleanup jobs, and processes everything through the existing plan→implement→verify→review→fix→deliver pipeline without human intervention.

The core value proposition: **a user reports a bug in Slack at 2am, and wakes up to a PR.** The system fills idle time by having the CEO agent propose high-impact features and running maintenance cleanup — creating a self-driving engineering team that never sleeps.

This builds directly on existing infrastructure: `colonyos watch` (Slack listener), `colonyos auto` (CEO loop), the queue system (`QueueState`/`QueueItem`), GitHub issue fetching (`github.py`), cleanup tools (`cleanup.py`), and the recovery system (`recovery.py`). The daemon is primarily a **unification and hardening** of these existing components, not a ground-up rebuild.

## Goals

1. **Single daemon command** (`colonyos daemon`) that unifies `watch`, `auto`, and `queue start` into one supervised long-running process
2. **Multi-source ingestion**: Slack messages (real-time via Socket Mode) + GitHub Issues (polling) + CEO proposals (idle-fill) + cleanup jobs (scheduled) all flow into a unified priority queue
3. **Priority-ordered execution**: User bugs > user features > GitHub issues > CEO features > cleanup — deterministic, static tiers with FIFO within each tier
4. **Budget safety**: Hard daily budget cap, per-run caps, circuit breaker on consecutive failures, and Slack alerting at thresholds — preventing runaway costs in unattended operation
5. **Crash resilience**: Atomic state persistence, startup crash recovery (orphaned RUNNING items), systemd integration with watchdog, and graceful degradation
6. **Observability**: Health endpoint (`/healthz`), Slack heartbeat notifications, daily digest summaries, and dashboard status indicators

## User Stories

1. **As a developer**, I deploy ColonyOS to a VM once, and it automatically processes bug reports from our Slack channel and GitHub Issues into PRs — I wake up to PRs ready for review.
2. **As a team lead**, I see a daily Slack digest of what the daemon accomplished (X bugs fixed, Y features proposed, Z cleanup tasks done, $W spent) so I can trust the system without monitoring it constantly.
3. **As a developer**, when I report a bug in Slack, my bug is processed before the CEO's speculative feature work — the system respects urgency.
4. **As an operator**, I can set a daily budget cap ($50/day) and know the daemon will halt gracefully and notify me when the limit is reached, preventing surprise bills.
5. **As an operator**, if the daemon crashes mid-pipeline, it recovers cleanly on restart — marking the interrupted job as failed, preserving git state, and continuing with the next queued item.
6. **As a developer**, I can type "pause" or "stop" in Slack and the daemon immediately halts autonomous work — a kill switch I trust.

## Functional Requirements

### FR-1: `colonyos daemon` Command
- New CLI command that starts a long-running process combining Slack listener, GitHub Issue poller, CEO scheduler, cleanup scheduler, and queue executor
- Accepts `--max-budget` (daily cap), `--max-hours` (max runtime), `--verbose`, `--dry-run`
- Loads config from `.colonyos/config.yaml` with new `daemon` config section
- Handles SIGINT/SIGTERM for graceful shutdown (existing pattern from `watch`)

### FR-2: GitHub Issue Polling
- Background thread polls `gh issue list` every 2-5 minutes (configurable `poll_interval_seconds`)
- Uses existing `fetch_open_issues()` from `src/colonyos/github.py`
- Converts each new issue to a `QueueItem` with `source_type="issue"`
- Deduplicates by `(source_type, source_value)` — skips issues already in queue (any non-terminal status)
- Respects issue label filters (configurable `issue_labels` to control which issues are ingested)
- Cross-channel dedup: Slack messages containing GitHub issue URLs (detected by existing `_ISSUE_URL_RE` regex) normalize to `source_type="issue"` to prevent double-processing

### FR-3: Priority Queue
- Add `priority: int` field to `QueueItem` (schema version bump to 4)
- Priority tiers: P0 (user bug — Slack with bug signal), P1 (user feature — Slack/issue), P2 (CEO proposal), P3 (cleanup)
- Priority computed deterministically from `source_type` + optional label signals
- Queue executor pops highest-priority pending item (lowest priority number), FIFO within tier
- Starvation prevention: items pending > 24 hours are promoted one tier

### FR-4: CEO Idle-Fill Scheduling
- CEO cycle runs only when: queue is empty (no pending user-sourced items) AND no pipeline is running AND cooldown elapsed (configurable `ceo_cooldown_minutes`, default 60)
- Reuses existing `run_ceo()` with CEO profile rotation from `ceo_profiles.py`
- Injects context: open PRs (`fetch_open_prs`), open issues (`fetch_open_issues`), recent run summaries, `directions.md` — so CEO doesn't propose duplicates
- CEO proposals enqueued as `QueueItem` with `source_type="ceo"`, `priority=2`

### FR-5: Cleanup Scheduling
- Cleanup runs on a configurable schedule (`cleanup_interval_hours`, default 24) or when queue is idle and CEO cooldown hasn't elapsed
- Runs existing `cleanup.py` operations: merged branch pruning, stale artifact deletion
- Structural complexity scan (`scan_directory`) produces candidates but does NOT auto-refactor — it generates cleanup `QueueItem`s with `source_type="cleanup"`, `priority=3`
- Cleanup items are capped at `max_cleanup_items` (default 3) per cycle to prevent queue flooding

### FR-6: Daily Budget Enforcement
- New top-level `daemon.daily_budget_usd` config field (default $50)
- Tracked via cumulative spend counter, reset at midnight UTC
- Hard stop: when daily budget is reached, daemon pauses queue execution (keeps listening for Slack messages but doesn't start new runs)
- Slack alert at 80% threshold ("ColonyOS has used 80% of today's $50 budget")
- Slack alert at 100% ("ColonyOS has paused — daily budget of $50 exhausted. Resuming at midnight UTC.")
- Per-run budget enforcement via existing `BudgetConfig.per_run` ($15 default)

### FR-7: Circuit Breaker
- Promote existing `max_consecutive_failures` (default 3) and `circuit_breaker_cooldown_minutes` (default 30) from `SlackConfig` to daemon-level config
- Applies globally across all source types, not just Slack
- When triggered: pause queue, post Slack alert with failure details, auto-resume after cooldown
- Track failures in `DaemonState` (new persistent state alongside `QueueState`)

### FR-8: Crash Recovery on Startup
- On daemon start, scan `QueueState` for items with `status=RUNNING`
- Mark orphaned running items as `FAILED` with `error="daemon crash recovery"`
- Check heartbeat file age — if recent (<5 min) and running item exists, call `preserve_and_reset_worktree` from `recovery.py` to snapshot dirty git state
- Ensure git working tree is clean before accepting new work

### FR-9: Atomic State Persistence
- Replace `Path.write_text(json.dumps(...))` for `queue.json` with write-to-temp-then-rename pattern
- Prevents queue corruption from crashes during write
- Apply same pattern to `DaemonState` persistence

### FR-10: Health & Observability
- Add `GET /healthz` endpoint to FastAPI server (`server.py`) returning daemon status, heartbeat age, queue depth, daily spend, circuit breaker state
- Slack heartbeat: configurable interval (default every 4 hours), posts "ColonyOS is alive — N items processed today, $X spent"
- Daily digest: summary of all work completed, spend, failures — posted at configurable time (default 9am local)
- Dashboard status: green (healthy), amber (degraded — circuit breaker active or >80% budget), red (stopped — budget exhausted or daemon down)

### FR-11: Slack Kill Switch
- Recognize "pause", "stop", "halt" commands in Slack from allowed users
- Immediately halt queue execution (finish current run gracefully, don't start new ones)
- "resume" command re-enables execution
- "status" command returns current queue state, daily spend, active job

### FR-12: DaemonConfig
- New `DaemonConfig` dataclass added to `config.py`:
  - `daily_budget_usd: float = 50.0`
  - `github_poll_interval_seconds: int = 120`
  - `ceo_cooldown_minutes: int = 60`
  - `cleanup_interval_hours: int = 24`
  - `max_cleanup_items: int = 3`
  - `heartbeat_interval_minutes: int = 240`
  - `digest_hour_utc: int = 14` (9am EST)
  - `max_consecutive_failures: int = 3`
  - `circuit_breaker_cooldown_minutes: int = 30`
  - `issue_labels: list[str] = []` (empty = all issues)
  - `allowed_control_user_ids: list[str] = []` (users who can pause/resume)

## Non-Goals (Explicitly Out of Scope)

1. **Self-modification** — The daemon will NOT autonomously modify files under `src/colonyos/`. If the CEO proposes a ColonyOS improvement, the PR requires human merge approval. Self-modification is deferred until rollback mechanisms are rock-solid.
2. **Dynamic priority scoring** — AI-driven priority reranking is future scope. V1 uses static priority tiers.
3. **Multi-repo support** — The daemon operates on a single repository. Multi-repo orchestration is future scope.
4. **Preemptive scheduling** — Running jobs are not interrupted when higher-priority work arrives. The queue sorts pending items only.
5. **Containerization/sandboxing** — While the security personas strongly recommend it, containerization is a separate infrastructure concern. V1 runs as a systemd service with filesystem-level protections.
6. **Automated dependency updates** — Dependabot-style updates are out of scope for cleanup jobs.
7. **Custom supervisor** — No custom process supervision. Use systemd.

## Technical Considerations

### Existing Infrastructure to Extend

| Component | File | What It Does Today | What Changes |
|---|---|---|---|
| `watch` command | `cli.py:2776` | Slack listener + PR review watcher | Becomes the core of `daemon` command |
| `auto` command | `cli.py:1846` | CEO loop with budget/time caps | CEO scheduling logic extracted, runs on idle |
| `QueueItem` | `models.py:328` | Queue data model with `source_type` | Add `priority` field (schema v4) |
| `QueueState` | `models.py:444` | Persistent queue state | Add daily spend tracking |
| `QueueExecutor` | `cli.py:~3293` | Sequential queue processor | Priority-ordered item selection |
| `fetch_open_issues` | `github.py` | Fetches issues via `gh` CLI | Called on polling interval |
| `fetch_open_prs` | `github.py` | Fetches open PRs | Fed into CEO context |
| `cleanup.py` | `cleanup.py` | Branch/artifact cleanup | Scheduled periodic execution |
| `recovery.py` | `recovery.py` | Git state recovery | Startup crash recovery |
| `server.py` | `server.py` | FastAPI dashboard | Add `/healthz` endpoint |
| `SlackConfig` | `config.py:197` | Slack settings | Circuit breaker promoted to daemon level |

### Architecture

```
colonyos daemon
├── Slack Listener (Socket Mode, real-time) ──→ QueueItem(source_type="slack")
├── GitHub Issue Poller (background thread) ──→ QueueItem(source_type="issue")
├── CEO Scheduler (idle-triggered) ──────────→ QueueItem(source_type="ceo")
├── Cleanup Scheduler (time-triggered) ──────→ QueueItem(source_type="cleanup")
├── Queue Executor (sequential, priority-ordered)
│   └── run() → existing pipeline (plan→implement→verify→review→fix→deliver)
├── Budget Enforcer (daily cap + per-run cap)
├── Circuit Breaker (consecutive failure detection)
├── Health Monitor (heartbeat, Slack alerts, daily digest)
└── Control Handler (Slack pause/resume/status commands)
```

### New Files
- `src/colonyos/daemon.py` — Core daemon orchestration (event loop, schedulers, state management)
- `src/colonyos/daemon_state.py` — `DaemonState` dataclass and atomic persistence
- `deploy/colonyos-daemon.service` — systemd unit file
- `deploy/README.md` — VM deployment guide
- `tests/test_daemon.py` — Daemon unit tests
- `tests/test_daemon_state.py` — State persistence tests

### Key Design Decisions

1. **Single process, multiple threads** — Matches the existing `watch` architecture. Slack Socket Mode runs in its own thread, GitHub poller in another, queue executor in another. Shared state protected by `threading.Lock` (same pattern as existing `state_lock` in `watch`).

2. **Sequential execution** — One pipeline run at a time (same as current `pipeline_semaphore`). Parallel execution within a run is handled by the existing `ParallelOrchestrator` with worktrees.

3. **Idle-based CEO, not time-based** — CEO only runs when queue drains. Prevents busywork when real work is waiting. 60-minute cooldown prevents rapid-fire CEO cycles.

4. **Static priority, not AI-driven** — Deterministic priority ordering builds trust. Users always know their bug report beats the CEO's idea.

5. **Write-then-rename for state** — Crash consistency for `queue.json` and `daemon_state.json` without introducing SQLite for queue storage (keeping it simple).

### Persona Consensus Summary

| Topic | Agreement | Dissent |
|---|---|---|
| **Idle-based CEO scheduling** | 7/7 unanimous | — |
| **Static priority tiers** | 7/7 unanimous | — |
| **systemd for supervision** | 6/7 agree | Linus says "fix the foundation first" |
| **No self-modification in V1** | 7/7 unanimous | — |
| **Daily budget cap is essential** | 7/7 unanimous | — |
| **Slack as primary channel** | 6/7 agree | Ive wants equal treatment |
| **Cleanup = branch/artifact only** | 6/7 agree | Karpathy wants code quality metrics |
| **`allowed_user_ids` must be mandatory** | 5/7 agree | Jobs/Seibel say "ship it" |
| **Containerization in V1** | 2/7 (security only) | Others say it's V2 |
| **GitHub Issues = attack surface** | 4/7 concerned | Seibel/Jobs say label filtering is enough |

### Security Considerations (from Staff Security Engineer)

- **Prompt injection via Slack/Issues**: Existing `sanitize_untrusted_content` with XML tag stripping and role-anchoring preambles is defense-in-depth, not a security boundary. Mandatory `allowed_user_ids` for Slack and label-gating for GitHub Issues are the primary controls.
- **`bypassPermissions`**: Acknowledged risk. V1 mitigates with `allowed_user_ids`, budget caps, and human merge approval for all PRs. V2 should add filesystem scope jailing.
- **Secrets in memory**: Four API tokens in a long-running process. V1 relies on systemd `ProtectSystem` and `PrivateTmp`. V2 should scope tokens to the subprocess that needs them.
- **Self-modification blocked**: `src/colonyos/` paths should be flagged in the CEO prompt as off-limits for autonomous work.

## Success Metrics

1. **Uptime**: Daemon runs >99% of the time over a 7-day period (measured by heartbeat gaps)
2. **Response latency**: Slack bug reports → PR created in <30 minutes (median)
3. **Budget adherence**: Zero instances of daily budget being exceeded
4. **Crash recovery**: 100% of daemon restarts recover cleanly (no corrupted queue, no dangling branches)
5. **Queue throughput**: Processes 10+ items/day without human intervention
6. **Zero regressions**: Existing `watch`, `auto`, and `queue` commands continue to work independently

## Open Questions

1. **GitHub Issue label gating**: Should the daemon process ALL issues or only those with a specific label (e.g., `colonyos`)? Label gating is safer but requires manual triage. Starting with label gating as default.
2. **PR merge policy**: Should the daemon's PRs be draft PRs (requiring human merge) or regular PRs? All personas agree on human merge in V1. Draft PR as default.
3. **Multi-daemon conflicts**: What happens if two daemon instances are started against the same repo? Need a PID lock file to prevent this.
4. **Slack workspace permissions**: Does the Slack app manifest need updates for the new control commands (pause/resume/status)?
5. **Daily budget reset timezone**: UTC is simple but may not align with team working hours. Configurable `digest_hour_utc` partially addresses this.
