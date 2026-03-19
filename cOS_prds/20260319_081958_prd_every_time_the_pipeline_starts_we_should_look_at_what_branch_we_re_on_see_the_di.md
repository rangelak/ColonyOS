# PRD: Git State Pre-flight Check

## Introduction/Overview

Every time the ColonyOS pipeline starts, it blindly generates a branch name from the prompt slug (line 1419 of `orchestrator.py`: `branch_name = f"{config.branch_prefix}{slug}"`) and proceeds to the Plan phase with zero awareness of the current git state. This means the pipeline can:

- Build on top of a stale or half-finished feature branch from a prior run
- Create a duplicate branch/PR for work that already has an open PR
- Implement against a `main` branch that is dozens of commits behind `origin/main`
- Start modifying files when the user has uncommitted changes, leading to data loss or confused diffs

This feature adds a **pre-flight git state assessment** that runs at the very start of `run()` — before any agent phases — to evaluate the repository state and make an informed decision about whether to proceed, switch to main, adopt an existing branch, or fail with actionable guidance.

## Clarifying Q&A

### Questions & Persona Synthesis

**Q1: What specific failure modes does this prevent?**

All 7 personas converged on three core failure modes:
1. **Stale branch building**: Re-running a prompt lands on a leftover feature branch with diverged history, causing the implement phase to layer new work on garbage state.
2. **Duplicate PRs**: The deterministic slug means re-running the same prompt creates a collision — either clobbering the branch or creating an orphan PR.
3. **Stale main**: Implementing against a `main` that is far behind `origin/main` guarantees merge conflicts the CI fix loop cannot resolve.

The Security Engineer additionally flagged a **branch pre-population attack vector**: an attacker could pre-create a branch matching the predictable slug and pre-load malicious instruction files that the agent would execute with `bypassPermissions`.

**Q2: Should this be a separate phase or procedural logic?**

**Strong consensus (6/7)**: This should be **procedural logic**, not an LLM phase. Git state assessment is deterministic — `git status`, `git branch --list`, `gh pr list` — and burning agent dollars on a closed-form answer is wasteful. A standalone function like `_preflight_check(repo_root, branch_name, config)` should be called at the top of `run()` between line 1419 (branch name computation) and line 1428 (Plan phase start).

**Dissent**: The Security Engineer advocated for a formal phase with its own `PhaseResult` for audit trail purposes. **Resolution**: We'll add a `PreflightResult` dataclass to `RunLog` (not a full `PhaseResult`) to get auditability without polluting cost tracking with $0.00 entries.

**Q3: What should happen when dirty state is detected?**

**Unanimous**: Fail fast with a clear, actionable error message. Never auto-resolve (no stashing, no auto-committing). The pipeline runs with `bypassPermissions` — silently mutating the user's working tree is dangerous. Error messages should state exactly what was found and suggest the fix (e.g., "uncommitted changes detected, please commit or stash before running colonyos").

**Q4: If an open PR exists for the branch, what should happen?**

**Strong consensus (6/7)**: Refuse by default and print the PR URL. Point the user to `--resume` for continuing existing work. Do not create suffixed branches (`-v2`, `-2`) as they create orphan PRs.

**Tension**: Steve Jobs and Jony Ive suggested adopting the existing PR's branch context in some cases. **Resolution**: Default to refuse; a future `--adopt-branch` flag can be added as a V2 follow-up.

**Q5: Should the pipeline fetch main before starting?**

**Split decision**:
- **Fetch by default** (4 personas: Seibel, Jobs, Ive, Karpathy): A sub-second network call that prevents an entire failed pipeline run. The pipeline already depends on network for `gh` calls.
- **Warn only, no fetch** (3 personas: Torvalds, Security Engineer, Systems Engineer): Network calls introduce trust boundaries and should be opt-in.

**Resolution**: Fetch by default with a tight timeout (5s) and graceful degradation to local-only checks on failure. Add `--offline` flag to skip all network calls.

**Q6: How should autonomous mode handle ambiguous state?**

**Consensus**: In `colonyos auto`, always start from a fresh branch off latest `origin/main`. If the working tree is dirty or the branch already exists with an open PR, mark the queue item as FAILED/REJECTED and move to the next iteration. Never make destructive git operations without human authorization.

**Q7: How should this interact with `--resume`?**

**Unanimous**: Skip the full pre-flight on resume — `prepare_resume()` already validates branch existence and PRD/task file presence. Only add two lightweight checks: (a) working tree is clean, and (b) branch HEAD hasn't diverged from what the RunLog recorded (to detect tampering between runs).

**Q8: Should network calls be opt-in or always-on?**

**Resolution**: Always-on with graceful degradation and tight timeouts. Add `--offline` flag for air-gapped environments. The pipeline already requires `gh` for PR creation in the deliver phase.

**Q9: Should uncommitted changes be in scope?**

**Unanimous**: Yes. This is the most important check. A single `git status --porcelain` call. If non-empty, refuse to proceed. This prevents data loss and confused diffs.

**Q10: How to test this?**

**Consensus**: Use `tmp_path` fixtures with real `git init` repos. Construct specific states (clean main, dirty tree, diverged branch, existing PR). Mock `subprocess.run` only for `gh` CLI calls. Separate state-gathering from decision logic for clean unit tests.

## Goals

1. **Prevent wasted compute**: Catch git state problems before spending dollars on agent phases
2. **Prevent data loss**: Refuse to start when uncommitted changes exist
3. **Prevent duplicate work**: Detect existing branches and open PRs before creating new ones
4. **Ensure fresh foundations**: Verify main is up-to-date before branching
5. **Maintain audit trail**: Record pre-flight decisions in the RunLog for debugging

## User Stories

1. **As a developer running `colonyos run`**, I want the pipeline to check my git state before starting so that I don't waste time and money building on a stale branch.
2. **As a developer with uncommitted changes**, I want the pipeline to refuse to start and tell me exactly what to do, so I don't lose my work.
3. **As a developer re-running a prompt**, I want the pipeline to detect the existing branch/PR and point me to `--resume` instead of creating duplicate work.
4. **As an operator running `colonyos auto`**, I want the pipeline to silently skip iterations with bad git state and continue to the next task, so the autonomous loop doesn't halt on a recoverable error.
5. **As a developer on a slow network**, I want the pipeline to gracefully degrade to local-only checks if remote calls fail, so I'm not blocked by network issues.

## Functional Requirements

1. **FR-1**: Add a `_preflight_check(repo_root, branch_name, config)` function in `orchestrator.py` that runs before any agent phases.
2. **FR-2**: Check for uncommitted changes via `git status --porcelain`. If non-empty, raise `click.ClickException` with the list of dirty files and suggested actions.
3. **FR-3**: Check if the computed branch name already exists locally via `git branch --list`. If it does, check for an open PR via `gh pr list --head <branch> --json number,url --limit 1`. If a PR exists, refuse with the PR URL and suggest `--resume`.
4. **FR-4**: Run `git fetch origin main` (with 5-second timeout) and compare local main against `origin/main` via `git rev-list --count main..origin/main`. If behind, warn and suggest `git pull`. If `--offline` flag is set, skip this check.
5. **FR-5**: Add a `PreflightResult` dataclass to `models.py` capturing: `current_branch`, `is_clean`, `branch_exists`, `open_pr_number`, `open_pr_url`, `main_behind_count`, `action_taken` (e.g., "proceed", "switched_to_main", "refused").
6. **FR-6**: Store the `PreflightResult` on `RunLog` so it appears in run logs for debugging.
7. **FR-7**: In autonomous mode (`colonyos auto` / queue), always ensure a clean working tree on `main` before starting. If state is bad, mark the iteration as failed and continue to the next.
8. **FR-8**: Skip the full pre-flight when `--resume` is active. Only validate: (a) working tree is clean, and (b) branch HEAD matches the RunLog's last known state.
9. **FR-9**: Add `--offline` flag to `colonyos run` and `colonyos auto` CLI commands to skip all network calls in pre-flight.
10. **FR-10**: Add a `--force` flag to `colonyos run` to bypass pre-flight checks (for power users who know what they're doing).

## Non-Goals

- **Auto-stashing or auto-committing**: The pipeline will never touch the user's uncommitted changes
- **Auto-rebasing**: The pipeline will not automatically rebase branches; it will only warn about staleness
- **Branch suffix generation**: No `colonyos/feature-2` naming; one branch per prompt slug
- **Merge conflict resolution**: Out of scope; the pipeline will warn about divergence, not fix it
- **Interactive prompts during pre-flight**: All decisions are deterministic; no user input during pre-flight (use flags instead)

## Technical Considerations

### Where to Insert Pre-flight Logic

The pre-flight check slots into `run()` in `orchestrator.py` between the branch name computation (line 1419) and the Plan phase (line 1428). The flow becomes:

```
run() called
  → compute branch_name (existing line 1419)
  → _preflight_check(repo_root, branch_name, config)  ← NEW
  → if resume: skip preflight, run _resume_preflight() instead  ← NEW
  → Phase 1: Plan (existing line 1428)
```

### Existing Code to Leverage

- `validate_branch_exists()` (line 820): Already checks local branches; can be reused
- `_get_branch_diff()` (line 850): Already extracts diffs; useful for context
- `github.py`: Already has `gh` subprocess patterns with timeout handling
- `_validate_resume_preconditions()` (line 719): Pattern for fail-fast with `click.ClickException`

### New Dependencies

None. All operations use `git` and `gh` CLI tools already required by the pipeline.

### CLI Changes

- Add `--offline` flag to `run` and `auto` commands in `cli.py`
- Add `--force` flag to `run` command to bypass pre-flight
- Pass these through to `run()` in `orchestrator.py`

### Data Model Changes

- Add `PreflightResult` dataclass to `models.py`
- Add `preflight` field to `RunLog` dataclass (optional `PreflightResult`)

## Success Metrics

1. **Zero duplicate PRs** from re-running the same prompt
2. **Zero data loss** from pipeline starting with uncommitted changes
3. **Pre-flight completes in < 5 seconds** (including network calls)
4. **100% of pre-flight decisions are logged** in the RunLog
5. **Autonomous loop continues** past git state issues without halting

## Open Questions

1. Should the `main_behind_count` threshold for warning be configurable in `.colonyos/config.yaml`, or is a hardcoded default (e.g., 50 commits) sufficient for V1?
2. Should we store the branch HEAD SHA in `RunLog` during implement phase for resume validation, or is this over-engineering for V1?
3. Should `colonyos doctor` also run pre-flight checks as a diagnostic tool?
