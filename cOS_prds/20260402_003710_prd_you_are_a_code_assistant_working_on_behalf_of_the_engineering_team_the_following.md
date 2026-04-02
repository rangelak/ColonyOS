# PRD: Daemon Inter-Queue Maintenance — Self-Update, Branch Sync & CI Fix

## Introduction/Overview

When the ColonyOS daemon runs in the ColonyOS repo itself (self-improving mode), it merges its own PRs into `main` but continues running stale code until manually restarted. Additionally, between queue items, stale `colonyos/`-prefixed branches accumulate and CI failures on open PRs go unaddressed until a human notices.

This feature adds an **inter-queue maintenance cycle** to the daemon that runs between queue items, specifically when switching back to `main`. It performs three sequential operations:

1. **Self-update**: Detect code changes on `main`, run `uv pip install .`, and `os.execv` to restart with the new version
2. **Branch sync scan**: Identify `colonyos/`-prefixed branches that are stale or diverged from `main`, report via Slack
3. **CI fix enqueueing**: Find open PRs with failing CI and enqueue `ci-fix` items into the regular queue

This is scoped exclusively to repos that opt in via a config flag (`daemon.self_update: true`). The default is `false`.

## Goals

1. **Zero-downtime self-improvement**: The daemon automatically picks up its own code changes without manual restart
2. **Branch hygiene**: Stale/diverged branches are surfaced proactively, not discovered days later
3. **CI health**: Failing CI on open PRs is automatically detected and fix attempts are enqueued
4. **Budget safety**: Maintenance operations have their own budget cap to prevent crowding out user work
5. **Reliability**: Self-update failures are detected and rolled back automatically

## User Stories

1. **As the ColonyOS operator**, I want the daemon to automatically install and restart with the latest code after merging a self-improvement PR, so I don't need to SSH in and restart it manually.

2. **As a developer reviewing PRs**, I want to see a Slack summary of which `colonyos/` branches have fallen behind `main`, so I can decide which need attention.

3. **As the ColonyOS operator**, I want the daemon to automatically attempt CI fixes on its own open PRs between queue items, so PRs don't sit with red CI for hours.

4. **As a budget-conscious operator**, I want maintenance tasks to have their own budget cap separate from the daily budget, so CI-fix loops don't consume all resources.

## Functional Requirements

### FR-1: Self-Update Detection & Installation
- After `restore_to_branch()` succeeds (daemon is back on `main`), pull latest from remote
- Compare the pre-pull and post-pull commit SHAs
- If SHAs differ AND `daemon.self_update` is `true` in config, run `uv pip install .`
- If install succeeds, persist daemon state via `_persist_state()` and `_persist_queue()`, then `os.execv(sys.executable, [sys.executable] + sys.argv)` to restart
- Log a `SELF_UPDATE_RESTART` event with old/new commit SHAs

### FR-2: Self-Update Rollback
- Before running `uv pip install .`, record the current commit SHA in `.colonyos/last_good_commit`
- On daemon startup, if a `last_good_commit` file exists AND the daemon crashes within 60 seconds of starting, treat this as a failed self-update
- Roll back: `git checkout <last_good_sha>`, reinstall from that SHA, exec again
- After 2 consecutive rollbacks from the same SHA, disable self-update and alert via Slack
- On successful startup (survived > 60 seconds), update `last_good_commit` to current SHA

### FR-3: Branch Sync Scan
- After self-update check (whether or not an update occurred), scan all `colonyos/`-prefixed branches
- For each branch, determine: commits behind `main`, commits ahead of `main`, whether it has an open PR
- Post a Slack summary of diverged branches (behind `main` by > 0 commits) with counts
- Do NOT auto-rebase — identification and reporting only
- Merged branches are already handled by the existing `_schedule_cleanup()` at `daemon.py:1227`

### FR-4: CI Fix Enqueueing
- After branch scan, for each `colonyos/`-prefixed branch with an open PR and failing CI:
  - Check CI status via `gh pr checks` (reuse existing `ci.py` infrastructure)
  - If CI is failing, enqueue a `QueueItem` with `source_type="ci-fix"` into the regular queue
  - Deduplicate: skip if a `ci-fix` item for this PR already exists in the queue
  - Cap at `daemon.max_ci_fix_items` (default 2) per maintenance cycle
- CI-fix items flow through the normal queue with standard priority, budget tracking, and circuit breaker

### FR-5: Maintenance Budget Cap
- Add `daemon.maintenance_budget_usd` config field (default `20.0`)
- Track maintenance spend (CI-fix items tagged with `source_type="ci-fix"`) separately
- Stop enqueuing new CI-fix items when maintenance budget is exhausted for the current day
- Self-update and branch scan are free (git/pip operations only, no AI spend)

### FR-6: Configuration
- Add to `DaemonConfig` dataclass in `config.py`:
  - `self_update: bool = False` — opt-in flag for self-update behavior
  - `self_update_command: str = "uv pip install ."` — configurable install command
  - `maintenance_budget_usd: float = 20.0` — daily budget cap for maintenance AI tasks
  - `max_ci_fix_items: int = 2` — max CI-fix items to enqueue per maintenance cycle
  - `branch_sync_enabled: bool = True` — toggle for branch sync scan (on by default when daemon runs)

## Non-Goals

- **Auto-rebasing branches onto main** — too destructive, breaks force-push expectations and PR review state. All 7 personas unanimously agreed: identify only, do not rebase.
- **Parallel maintenance execution** — the daemon is explicitly single-pipeline, sequential execution (`daemon.py` line 8). Maintenance runs sequentially between queue items.
- **Self-update in non-ColonyOS repos** — gated behind `daemon.self_update: true` which defaults to `false`
- **Worktree-based maintenance** — maintenance runs in the main worktree between queue items, not in isolated worktrees
- **Modifying the thread-fix checkout flow** — must NOT pull during thread-fix, as it would break SHA integrity checks

## Technical Considerations

### Integration Points

| Component | File | How It's Affected |
|-----------|------|-------------------|
| Daemon tick loop | `src/colonyos/daemon.py:544` (`_tick()`) | New maintenance step after queue execution |
| Post-pipeline restore | `src/colonyos/daemon.py:1681` | Maintenance runs after `restore_to_branch()` in `_run_pipeline_for_item()` finally block |
| Recovery module | `src/colonyos/recovery.py:303` | `restore_to_branch()` unchanged, but a new `pull_and_check_update()` helper added nearby |
| Config | `src/colonyos/config.py:300` | `DaemonConfig` gets new fields |
| CI module | `src/colonyos/ci.py` | Reused for CI status checks (existing `fetch_pr_checks()`) |
| Cleanup module | `src/colonyos/cleanup.py` | Reused for `list_merged_branches()` pattern |
| Queue models | `src/colonyos/models.py` | New `source_type="ci-fix"` for queue items |
| Daemon state | `src/colonyos/daemon_state.py` | New fields for self-update tracking |

### Exec-Replace Strategy (5/7 Persona Consensus)

The daemon uses `os.execv(sys.executable, [sys.executable] + sys.argv)` to restart after self-update. This:
- Preserves the PID and PID file at `.colonyos/daemon.pid`
- Preserves the systemd cgroup and log stream
- Requires no external supervisor coordination
- Only runs when `_pipeline_running` is `False` (between queue items)

The security engineer prefers graceful shutdown + supervisor restart to avoid FD inheritance, but the exec approach is simpler and the daemon already persists all state to disk. Acceptable trade-off for v1.

### Rollback Circuit Breaker

Uses the existing circuit breaker pattern (`max_consecutive_failures` / `circuit_breaker_cooldown_minutes` in `DaemonConfig`) as a model. Self-update gets its own counter stored in `DaemonState`.

### Persona Consensus Summary

| Decision | Agreement | Notes |
|----------|-----------|-------|
| Sequential maintenance execution | 7/7 | Self-update → branch scan → CI fix |
| Do NOT auto-rebase branches | 7/7 | Report only, too destructive |
| Only fix CI on branches with open PRs | 7/7 | Don't waste budget on abandoned branches |
| Reuse existing ci.py infrastructure | 7/7 | Enqueue as queue items, not parallel path |
| Budget caps for maintenance | 7/7 | Prevent CI-fix loops consuming daily budget |
| Config flag for self-update (opt-in) | 5/7 | Steve Jobs & Linus prefer auto-detect; config flag is safer |
| exec-replace restart | 5/7 | Security engineer prefers supervisor; acceptable for v1 |
| Trigger on any main change vs source-only | 4/3 | Slight preference for source-only detection; `uv pip install .` is fast either way |

## Success Metrics

1. **Self-update latency**: Time from PR merge to daemon running new code < 5 minutes (one queue cycle)
2. **Branch hygiene**: All diverged branches surfaced in Slack within 24 hours
3. **CI fix rate**: >50% of CI failures auto-fixed within one maintenance cycle
4. **Budget adherence**: Maintenance spend never exceeds configured `maintenance_budget_usd`
5. **Rollback reliability**: Failed self-updates automatically rolled back within 120 seconds

## Open Questions

1. **Should `uv pip install .` run unconditionally or only when source files changed?** — 4/7 personas say filter to `src/colonyos/`, `pyproject.toml`; 3/7 say just always reinstall since it's fast and idempotent. Recommendation: always reinstall (simpler, no edge cases with instruction templates being package data).

2. **Should the startup health check be a simple timer (60s survival) or an active smoke test (import check)?** — Timer is simpler and catches most cases. Active smoke test before exec could catch import errors but adds complexity. Recommendation: start with timer, add smoke test if needed.

3. **Should branch sync report go to a dedicated Slack channel or the default daemon channel?** — Recommendation: use the existing default notification channel for v1.
