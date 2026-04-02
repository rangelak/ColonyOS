# PRD: Auto-Pull Latest on Branch Switch

## 1. Introduction/Overview

When ColonyOS switches to a branch (especially `main`) at pipeline entry points, it should automatically pull the latest version from the remote. Currently, the codebase has multiple locations where `git checkout <branch>` is called without a subsequent `git pull`, resulting in pipelines running against stale code. This produces PRs based on outdated main branches, wasted CI minutes, and merge conflicts that could have been avoided.

The CLI's auto-loop already has `_ensure_on_main()` (`cli.py:1940`) which does `checkout main` + `pull --ff-only`, but this pattern is not applied to the daemon's `restore_to_branch()`, the orchestrator's base-branch checkout, or the preflight check. This PRD standardizes auto-pull behavior across all pipeline entry points.

## 2. Goals

1. **Eliminate stale-branch starts**: Every new pipeline run begins from the latest remote state of its base branch.
2. **Consistent behavior**: All pipeline entry points (CLI auto-loop, daemon queue, orchestrator base-branch) use the same pull logic.
3. **Respect existing contracts**: Offline mode skips pulling; thread-fix SHA verification is not broken; `restore_to_branch()`'s never-raises contract is preserved.
4. **Minimal blast radius**: Only add pulls at pipeline entry points, not at every internal `git checkout`.

## 3. User Stories

- **As a daemon operator**, I want the daemon to pull the latest `main` between queue items so that each feature branch starts from the freshest code, avoiding stale-base merge conflicts.
- **As a developer using base branches**, I want the orchestrator to pull the latest base branch before forking a feature branch, so my PR is not immediately behind.
- **As a developer running in offline mode**, I want the pipeline to skip pulling and work with local state, so I can operate without network access.
- **As a developer using thread-fix**, I want the thread-fix flow to NOT pull, preserving the HEAD SHA integrity check that guards against force-push tampering.

## 4. Functional Requirements

| ID | Requirement |
|----|------------|
| FR-1 | Add a `pull_branch()` helper to `recovery.py` that runs `git pull --ff-only` on the current branch, only if the branch has a remote tracking branch. |
| FR-2 | `restore_to_branch()` in `recovery.py` must call `pull_branch()` after a successful checkout. Pull failure is logged as a warning (preserving the never-raises contract). |
| FR-3 | The orchestrator's base-branch checkout (`orchestrator.py:~4210`) must pull after checkout. Pull failure raises `PreflightError` (hard-fail — starting from stale base is the exact failure mode we're fixing). |
| FR-4 | The orchestrator's preflight check (`orchestrator.py:~396-428`) should pull `main` instead of just fetching and warning. On failure, add a warning (existing behavior, but now with an actual pull attempt). |
| FR-5 | All new pull calls must be gated by the `offline` flag — skip when `offline=True`. |
| FR-6 | The thread-fix checkout (`orchestrator.py:~3920`) must NOT pull. The SHA integrity check (FR-7 defense) must remain intact. |
| FR-7 | `_ensure_on_main()` in `cli.py` should be refactored to use the new `pull_branch()` helper for consistency, and must respect offline mode. |
| FR-8 | `pull_branch()` must check for a remote tracking branch via `git rev-parse --abbrev-ref @{upstream}` before attempting to pull. If no upstream exists, skip silently. |
| FR-9 | Structured logging: log pull success/failure with branch name and whether fast-forward succeeded. |

## 5. Non-Goals

- **Pulling in worktrees**: Worktrees (`worktree.py`, `parallel_orchestrator.py`) are ephemeral and already fetch from `origin/<branch>` at creation time. No changes needed.
- **Changing `pr_sync.py`**: PR sync already does its own `fetch origin main` + merge in isolated worktrees. Leave untouched.
- **Pulling mid-pipeline**: Internal branch switches during review, fix, verify phases should not pull. The pipeline should operate on a deterministic snapshot.
- **Config flag for auto-pull**: Not needed for v1. The behavior should be on by default, skipped only in offline mode.
- **Replacing `git pull --ff-only` with `git fetch` + `git reset --hard`**: While some personas suggested this, `--ff-only` is safer (fails on diverged local state rather than silently discarding commits) and matches the existing pattern in `_ensure_on_main()`.

## 6. Technical Considerations

### Existing Code Patterns

- **`_ensure_on_main()` (`cli.py:1940-1972`)**: Already does checkout + `pull --ff-only` for the auto-loop path, but doesn't respect offline mode and uses raw `subprocess.run` instead of the `_git()` helper.
- **`_git()` helper (`recovery.py`)**: Wraps `subprocess.run` with consistent error handling. The new `pull_branch()` should use this.
- **`checkout_branch()` (`recovery.py:170`)**: Generic helper. Should NOT be modified to auto-pull — callers have different needs.
- **`restore_to_branch()` (`recovery.py:303-339`)**: Never-raises contract. Pull failure must be swallowed with a warning log.
- **Preflight fetch (`orchestrator.py:396-428`)**: Currently fetches `origin/main`, counts behind commits, and warns. Can be enhanced to pull instead of just warning.

### Key Interactions

| Location | Should Pull? | Failure Mode | Reason |
|----------|-------------|--------------|--------|
| `restore_to_branch()` | Yes | Warn-and-continue | Never-raises contract; stale main is better than dead daemon |
| Base-branch checkout in `run()` | Yes | Hard-fail (`PreflightError`) | Starting from stale base guarantees a broken PR |
| Preflight check | Yes (replace fetch+warn) | Warn-and-continue | Consistent with existing warning behavior |
| Thread-fix checkout | **No** | N/A | SHA integrity check must not be undermined |
| `_ensure_on_main()` CLI | Already pulls | Warn-and-continue | Existing behavior, just refactor to shared helper |
| Worktrees | **No** | N/A | Already fetch from origin at creation |
| `pr_sync.py` | **No** | N/A | Already manages its own fetches in isolated worktrees |

### Offline Mode

The `offline` flag is threaded through the orchestrator via `_preflight_check(offline=...)` and `run(offline=...)`. For `restore_to_branch()`, which doesn't currently accept an `offline` parameter, we add an optional `pull: bool = True` parameter that the daemon can set based on its config.

## 7. Persona Consensus

All 7 personas reached remarkably strong agreement on this feature:

| Decision | Agreement | Resolution |
|----------|-----------|-----------|
| Pull only at entry points, not every checkout | **7/7** | `restore_to_branch()`, base-branch checkout, preflight |
| Skip pull in offline mode | **7/7** | Gate behind `if not offline` |
| Do NOT pull in thread-fix flow | **7/7** | SHA integrity check takes priority |
| Do NOT pull in worktrees | **7/7** | Already handled by fetch-at-creation |
| Check for tracking branch before pull | **7/7** | `git rev-parse --abbrev-ref @{upstream}` |
| `pr_sync.py` needs no changes | **7/7** | Operates in isolated worktrees |
| Use `git pull --ff-only` | **5/7** | Fails safely on diverged state (2 suggested fetch+reset) |
| Hard-fail on base-branch pull failure | **6/7** | Starting from stale base is the core bug |
| Warn-and-continue for `restore_to_branch()` | **5/7** | Never-raises contract must be preserved (2 wanted hard-fail) |

**Area of tension**: Whether `restore_to_branch()` pull failures should hard-fail (security engineer, Michael Seibel) or warn-and-continue (systems engineer, Karpathy, Jony Ive). Resolution: preserve the never-raises contract — a stale main is recoverable, a dead daemon is not.

## 8. Success Metrics

1. **Zero stale-base PRs**: PRs opened by ColonyOS should never be behind `origin/main` at creation time.
2. **No regression in offline mode**: Pipeline runs with `--offline` must not attempt network calls.
3. **Thread-fix integrity preserved**: Thread-fix SHA checks continue to pass for legitimate requests.
4. **Test coverage**: All new pull logic has unit tests covering success, network failure, no-upstream, and offline scenarios.

## 9. Open Questions

1. **Timeout for pull**: The preflight fetch uses 5s timeout; `_ensure_on_main` uses 30s. Should `pull_branch()` use a configurable timeout or a fixed reasonable default (e.g., 30s)?
2. **Retry on transient failure**: Should we retry once on network timeout before failing? (Consensus: no, keep it simple for v1.)
