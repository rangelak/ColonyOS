# PRD: Daemon PR Sync — Keep ColonyOS PRs Up-to-Date with Main

**Date**: 2026-03-31
**Status**: Draft
**Author**: ColonyOS Plan Phase

---

## 1. Introduction / Overview

ColonyOS creates pull requests as the final step of its autonomous pipeline (plan → implement → review → deliver). These PRs can sit open for hours or days waiting for human review, during which `main` advances. When a PR falls behind main, it may have stale CI results, silent merge conflicts, or fail GitHub's branch protection "require branches to be up to date" rule — all of which create friction for human reviewers.

This feature adds a new daemon concern that automatically detects ColonyOS-authored PRs that are behind `main`, merges the latest `main` into those branches, and pushes the result — keeping PRs perpetually merge-ready.

## 2. Goals

1. **Keep ColonyOS PRs merge-ready**: Automatically sync open `colonyos/*` PRs with `main` so CI results are always current and merge conflicts surface early.
2. **Zero-cost for clean merges**: The common case (no conflicts, just behind) should use plain `git merge` with no AI budget consumption.
3. **Safe failure handling**: When conflicts exist that git cannot auto-resolve, abort cleanly, notify via Slack and PR comment, and leave the branch untouched.
4. **Minimal blast radius**: Only touch branches the daemon owns (`branch_prefix`), operate in isolated worktrees, and never force-push.
5. **Opt-in activation**: Default to disabled; operators explicitly enable via config.

## 3. User Stories

- **As a human reviewer**, I want ColonyOS PRs to always be up-to-date with main so I can trust the CI status and merge without additional steps.
- **As a daemon operator**, I want PR syncing to be opt-in and configurable so I control when and how often it runs.
- **As a daemon operator**, I want to be notified via Slack when a PR has conflicts that can't be auto-resolved so I can intervene manually.
- **As a developer**, I want the sync to use merge (not rebase) so PR review comments and approval state are preserved.

## 4. Functional Requirements

### Detection

- **FR-1**: During each sync cycle, fetch the list of open PRs tracked in `OutcomeStore` (already populated by the deliver phase) and check whether each is behind `main`.
- **FR-2**: Use `gh pr view --json mergeStateStatus` to detect staleness without local git operations. PRs with `mergeStateStatus == "BEHIND"` or `"DIRTY"` (behind + conflicts) are candidates.
- **FR-3**: Only consider PRs on branches matching `config.branch_prefix` (default `colonyos/`).

### Sync Execution

- **FR-4**: For each candidate PR, perform the merge in an isolated ephemeral worktree (via `WorktreeManager`) to avoid corrupting the main working tree or interfering with an active pipeline.
- **FR-5**: Attempt `git merge origin/main --no-edit` in the worktree. If the merge succeeds cleanly (exit code 0), push the result and tear down the worktree.
- **FR-6**: Process at most 1 PR per tick cycle, consistent with the daemon's sequential execution model. Round-robin through candidates across ticks.
- **FR-7**: Do not sync a PR if its branch is currently the target of a RUNNING queue item (check `_queue_state`).

### Failure Handling

- **FR-8**: If `git merge` fails due to conflicts, run `git merge --abort`, tear down the worktree, and skip the PR for this cycle.
- **FR-9**: Post a Slack notification and a PR comment (via `gh pr comment`) when sync fails due to conflicts, including the list of conflicting files.
- **FR-10**: Track sync attempts and failures per PR in the `pr_outcomes` SQLite table (new columns: `last_sync_at`, `sync_failures`). After a configurable number of consecutive failures (default 3), stop retrying and post a final escalation notification.
- **FR-11**: Sync failures do NOT feed into the daemon's global `consecutive_failures` counter or trip the circuit breaker — they are expected operational noise.

### Configuration

- **FR-12**: Add a `pr_sync` section to `DaemonConfig` with:
  - `enabled: bool = False` — opt-in activation
  - `interval_minutes: int = 60` — how often to check for stale PRs
  - `max_sync_failures: int = 3` — per-PR retry cap before abandoning
- **FR-13**: Sync must be gated behind `COLONYOS_WRITE_ENABLED` (or `dashboard_write_enabled`) since it pushes to remote branches.

### Observability

- **FR-14**: Log each sync operation with structured fields: branch name, PR number, pre-sync HEAD SHA, post-sync HEAD SHA, outcome (success/conflict/error).
- **FR-15**: Add a `synced_at` timestamp to the `pr_outcomes` table for dashboard visibility.

## 5. Non-Goals (Explicit Scope Exclusions)

- **AI-powered conflict resolution**: V1 only handles clean merges. AI conflict resolution (using the existing `conflict_resolve.md` template and `Phase.CONFLICT_RESOLVE`) is deferred to V2 once we have data on how often conflicts occur.
- **Rebase strategy**: We use merge-into-branch exclusively. Rebase requires force-push which destroys review comments and introduces race conditions.
- **Syncing non-ColonyOS PRs**: Only branches matching `config.branch_prefix` are touched.
- **PR description updates**: The PR body is not modified. A PR comment is the correct artifact for an operational event.
- **Dashboard UI for sync status**: V1 surfaces sync data via the existing `pr_outcomes` API; dedicated UI is deferred.

## 6. Technical Considerations

### Existing Code to Leverage

| Component | File | How It's Used |
|---|---|---|
| `OutcomeStore` | `src/colonyos/outcomes.py` | Provides list of open ColonyOS PRs via `get_open_outcomes()` |
| `_call_gh_pr_view` | `src/colonyos/outcomes.py:187` | Already calls `gh pr view --json` — add `mergeStateStatus` to fields |
| `WorktreeManager` | `src/colonyos/worktree.py` | Ephemeral worktrees for isolated merge operations |
| `DaemonConfig` | `src/colonyos/config.py:260` | Extend with `pr_sync` settings |
| `_tick()` loop | `src/colonyos/daemon.py:532` | Add sync as concern #7 with its own timer |
| `_post_slack_message` | `src/colonyos/daemon.py` | Slack notifications on conflict |
| `fetch_open_prs` | `src/colonyos/github.py:299` | Branch name filtering |
| `branch_prefix` | `src/colonyos/config.py:291` | Scope filtering |

### Architecture Decisions

- **Worktree isolation**: Every sync happens in a fresh worktree created by `WorktreeManager`. This prevents corruption of the main working tree and avoids contention with `RepoRuntimeGuard` / `_agent_lock`.
- **Merge strategy**: `git merge origin/main --no-edit` — non-destructive, preserves review state, no force-push required.
- **Detection via GitHub API**: Use `mergeStateStatus` from `gh pr view` (already called during outcome polling) rather than local `git rev-list` comparisons. This avoids fetching branches locally just to check staleness.
- **Sequential processing**: 1 PR per tick, matching the daemon's single-pipeline philosophy.

### Persona Consensus & Tensions

**Unanimous agreement** across all 7 personas:
- Scope to `colonyos/` branches only
- Use merge (not rebase) strategy
- Try plain git merge first; AI only for conflicts (deferred to V2)
- Use isolated worktrees
- 1 PR per tick
- Slack + PR comment on failure

**Key tensions resolved**:
- *AI in V1?* — Steve Jobs, Linus Torvalds, and YC Partner all said no; Karpathy and Jony Ive said yes with a two-tier approach. **Decision**: Ship without AI first per user direction ("ship the smallest thing that works first"). The existing `conflict_resolve.md` template and `Phase.CONFLICT_RESOLVE` enum are ready for V2.
- *Separate interval vs piggyback?* — Systems Engineer wanted a separate interval; others said piggyback on outcome polling. **Decision**: Separate interval (default 60min) because sync has different cost characteristics (git push, CI triggers) than status checking.
- *Security gating* — Staff Security Engineer strongly advocated opt-in + write-enabled gating. **Decision**: Adopted — `enabled: False` default + write-enabled gate.

## 7. Success Metrics

- **Sync rate**: % of open ColonyOS PRs that are ≤1 commit behind main at any given time (target: >90%)
- **Clean merge rate**: % of sync attempts that succeed without conflicts (expected: >80%)
- **Time-to-merge reduction**: Decrease in time between PR creation and merge for synced PRs
- **Zero regressions**: No increase in daemon failures or pipeline errors after enabling sync

## 8. Open Questions

1. **V2 AI conflict resolution**: When we have data on conflict frequency, should the AI resolution go through a review phase before pushing, or is test-pass sufficient validation?
2. **CI cost amplification**: Each sync push triggers CI. For repos with many open ColonyOS PRs and a fast-moving main, should there be a global "syncs per day" cap to control CI spend?
3. **Approved PR handling**: Should PRs with approved reviews be synced (risks re-triggering required review workflows on some GitHub configurations) or skipped?
