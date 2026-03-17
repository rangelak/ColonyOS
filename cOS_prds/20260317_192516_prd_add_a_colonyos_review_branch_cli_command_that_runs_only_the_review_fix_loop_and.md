# PRD: Standalone `colonyos review <branch>` Command

## 1. Introduction/Overview

ColonyOS currently requires running the full pipeline (Plan → Implement → Verify → Review/Fix → Decision → Deliver) to get multi-persona code reviews. This PRD defines a standalone `colonyos review <branch>` CLI command that runs only the review/fix loop against an arbitrary Git branch, without requiring a PRD or task file. This enables ColonyOS to function as a lightweight, standalone multi-persona code review tool — the primary use case being a developer self-review before opening a PR.

## 2. Goals

1. **Enable standalone reviews**: Developers can run `colonyos review my-feature` to get multi-persona feedback on any local branch without running the full pipeline.
2. **Reuse existing infrastructure**: Leverage `_reviewer_personas()`, `run_phases_parallel_sync()`, `_extract_review_verdict()`, `_collect_review_findings()`, and `_save_review_artifact()` from `orchestrator.py` rather than reimplementing.
3. **CI-friendly exit codes**: Exit 0 when all reviewers approve, exit 1 when changes are requested, enabling `colonyos review feature-branch || echo "Review failed"`.
4. **Budget enforcement**: Use existing `BudgetConfig` (per_phase and per_run) to cap costs.
5. **Safe defaults**: Review-only by default (no branch mutation); fixes require explicit `--fix` flag.

## 3. User Stories

1. **Developer self-review**: "As a developer, I want to run `colonyos review my-feature` before opening a PR so I can get expert persona feedback on my changes against `main`."
2. **Custom base branch**: "As a developer working on a release branch, I want `colonyos review my-feature --base develop` to compare against `develop` instead of `main`."
3. **Quick review without fixes**: "As a developer, I want `colonyos review my-feature --no-fix` to get review feedback without any automated fix attempts."
4. **CI gate**: "As a CI engineer, I want to add `colonyos review $BRANCH` to our pipeline and fail the build if any reviewer requests changes."
5. **Decision gate**: "As a team lead, I want `colonyos review my-feature --decide` to produce a formal GO/NO-GO verdict after reviews complete."

## 4. Functional Requirements

### 4.1 CLI Command Registration

- **FR-1**: Register a new `review` subcommand on the `app` Click group in `src/colonyos/cli.py`.
- **FR-2**: Accept a required `branch` argument (the Git branch to review).
- **FR-3**: Accept `--base <branch>` option (default: `main`) specifying the comparison base.
- **FR-4**: Accept `-v/--verbose` and `-q/--quiet` flags matching the existing `run` and `auto` commands.
- **FR-5**: Accept `--no-fix` flag to skip the fix loop and only produce review artifacts. (Default behavior: fix loop runs if any reviewer requests changes.)
- **FR-6**: Accept `--decide` flag (default off) to run the decision gate after reviews.

### 4.2 Branch Validation

- **FR-7**: Before running, verify the target branch exists locally using `git branch --list <branch>`. If not found, print an error suggesting `git fetch` and `git checkout`.
- **FR-8**: Verify the base branch exists locally. If not found, print an error.
- **FR-9**: Strictly local branches only — do not accept remote refs like `origin/feature`. If a remote-style ref is detected, suggest checking out the branch first.

### 4.3 Diff-Aware Review Prompt

- **FR-10**: Create a new instruction template `src/colonyos/instructions/review_standalone.md` for standalone reviews (no PRD references).
- **FR-11**: Build a new `_build_standalone_review_prompt()` function in `orchestrator.py` that formats the standalone template with persona identity, branch name, base branch, and an optional diff summary.
- **FR-12**: Extract `git diff <base>...<branch>` output. If the diff exceeds 10,000 characters, truncate it and append a summary line indicating truncation. Include the (possibly truncated) diff in the review prompt as context.
- **FR-13**: The standalone review template should instruct reviewers to focus on the diff changes and infer intent from commit messages rather than checking against a PRD.

### 4.4 Parallel Persona Reviews

- **FR-14**: Reuse `_reviewer_personas(config)` to get the list of reviewer personas from config.
- **FR-15**: Build review calls for each persona and execute them via `run_phases_parallel_sync()`.
- **FR-16**: Each reviewer gets read-only tools: `["Read", "Glob", "Grep", "Bash"]` (same as pipeline review at `orchestrator.py` line 981).
- **FR-17**: Each reviewer produces a `VERDICT: approve | request-changes` and structured `FINDINGS` / `SYNTHESIS` sections.

### 4.5 Fix Loop (Opt-in)

- **FR-18**: Unless `--no-fix` is passed, if any reviewer requests changes, run the fix agent loop up to `max_fix_iterations` from config, followed by re-review.
- **FR-19**: Create a new `_build_standalone_fix_prompt()` (or adapt `_build_fix_prompt()`) that works without PRD/task file references.
- **FR-20**: The fix agent operates on the target branch with full write tools (same as pipeline fix phase).
- **FR-21**: After each fix iteration, re-run all reviewers. If all approve, stop early.

### 4.6 Review Artifacts

- **FR-22**: Save each persona's review to `{reviews_dir}/review_standalone_{branch_slug}_round{N}_{persona_slug}.md`.
- **FR-23**: Save a summary file `{reviews_dir}/review_standalone_{branch_slug}_summary.md` listing all verdicts, key findings, and cost.
- **FR-24**: If `--decide` is passed, save the decision artifact to `{reviews_dir}/decision_standalone_{branch_slug}.md`.

### 4.7 Decision Gate

- **FR-25**: When `--decide` is passed, after reviews complete, run the decision gate using existing `_build_decision_prompt()` (adapted for no PRD) to produce a GO/NO-GO verdict.

### 4.8 Output and Exit Codes

- **FR-26**: Print a human-readable summary table to stdout: each reviewer persona, their verdict, and a one-line finding summary, plus total cost.
- **FR-27**: Exit 0 if all reviewers approve (after fix loop if applicable).
- **FR-28**: Exit 1 if any reviewer still requests changes after fix loop exhaustion.
- **FR-29**: If `--decide` is used, exit 0 for GO, exit 1 for NO-GO.

### 4.9 Budget Enforcement

- **FR-30**: Use `config.budget.per_phase` for each individual reviewer/fix session.
- **FR-31**: Use `config.budget.per_run` as the total cap. Track cumulative cost across all phases and stop if budget is exhausted (same guard pattern as pipeline at `orchestrator.py` lines 986-995).

### 4.10 No RunLog

- **FR-32**: Do not create a `RunLog` entry. Track cost via `PhaseResult` objects and print a cost summary at the end.

## 5. Non-Goals

- **No remote branch support**: Will not auto-fetch or resolve remote refs. Users must check out branches locally.
- **No worktree isolation**: Operates in-place on the repo working tree, consistent with all other ColonyOS phases.
- **No `--json` output**: Machine-readable output format is deferred to a future iteration.
- **No `--personas` CLI override**: Uses config personas only. CLI persona override is deferred.
- **No RunLog integration**: This is a lightweight command, not a full pipeline run.

## 6. Technical Considerations

### 6.1 Files to Modify

| File | Change |
|------|--------|
| `src/colonyos/cli.py` | Add `review` command with Click decorators, branch validation, summary printing, exit code logic |
| `src/colonyos/orchestrator.py` | Add `run_standalone_review()` function, `_build_standalone_review_prompt()`, `_build_standalone_fix_prompt()`, `_get_branch_diff()`, `_validate_branch_exists()` |
| `src/colonyos/instructions/review_standalone.md` | New template for standalone reviews (no PRD references) |
| `src/colonyos/instructions/fix_standalone.md` | New template for standalone fix phase (no PRD/task file references) |
| `src/colonyos/instructions/decision_standalone.md` | New template for standalone decision gate (no PRD references) |
| `tests/test_cli.py` | Tests for the `review` CLI command (flags, exit codes, config validation) |
| `tests/test_standalone_review.py` | Tests for branch validation, diff extraction, prompt building, parallel execution, artifact saving |

### 6.2 Architecture

The new `run_standalone_review()` function in `orchestrator.py` encapsulates the standalone review flow:

```
run_standalone_review(branch, base, repo_root, config, verbose, quiet, no_fix, decide)
  ├── _validate_branch_exists(branch)
  ├── _validate_branch_exists(base)
  ├── _get_branch_diff(base, branch)  →  diff text (truncated if needed)
  ├── Loop: review rounds
  │   ├── _build_standalone_review_prompt() for each persona
  │   ├── run_phases_parallel_sync()  →  parallel reviews
  │   ├── _save_review_artifact() for each result
  │   ├── _collect_review_findings()
  │   ├── If findings and not --no-fix:
  │   │   ├── _build_standalone_fix_prompt()
  │   │   └── run_phase_sync(Phase.FIX, ...)
  │   └── If no findings: break
  ├── Optional: decision gate (--decide)
  ├── Save summary artifact
  └── Return (all_approved: bool, phase_results: list, total_cost: float)
```

### 6.3 Reuse Strategy

Functions reused directly from `orchestrator.py`:
- `_reviewer_personas()` (line 155)
- `run_phases_parallel_sync()` from `agent.py` (line 185)
- `_extract_review_verdict()` (line 190)
- `_collect_review_findings()` (line 196)
- `_save_review_artifact()` (line 575)
- `_persona_slug()` (used at line 1020)
- `_extract_verdict()` (line 232) — for decision gate
- `_format_base()` and `_load_instruction()` — for prompt building

### 6.4 Config Resolution

The `review` command loads config via `load_config(repo_root)` exactly as `run` and `auto` do. The command uses:
- `config.personas` (filtered by `reviewer=True`)
- `config.model`
- `config.budget.per_phase` and `config.budget.per_run`
- `config.reviews_dir`
- `config.max_fix_iterations`

### 6.5 Naming Convention

Branch slug is derived from the branch name using the existing `_persona_slug()` pattern (lowercase, hyphens to underscores, strip non-alphanumeric). Example: `feature/my-thing` → `feature_my_thing`.

## 7. Success Metrics

1. `colonyos review my-feature-branch` completes successfully with parallel persona reviews.
2. Review artifacts appear in `cOS_reviews/` with correct `review_standalone_*` filenames.
3. `--no-fix` skips the fix loop entirely.
4. `--base develop` changes the comparison base from `main`.
5. Exit code 0 when all approve, 1 when changes requested.
6. Budget is enforced — reviews stop if per_run budget is exhausted.
7. All existing tests pass (`pytest tests/`).
8. New tests cover: branch validation, diff extraction/truncation, prompt building, parallel execution (mocked), artifact saving with correct filenames, exit code logic, `--no-fix` flag, `--base` flag, and `--decide` flag.

## 8. Open Questions

1. **Diff truncation strategy**: The initial implementation uses simple character truncation at 10,000 chars. Should we later add per-file truncation with hunk-boundary awareness? (Personas were split: Jony Ive and Systems Engineer favored smarter truncation; Linus, Michael Seibel, and Karpathy favored simple truncation for v1 since agents have tool access.)

2. **Bash tool for reviewers**: The Staff Security Engineer raised a valid concern that Bash in review tools is not truly read-only (could `curl` secrets, `rm -rf`, etc.). Should we restrict reviewers to `["Read", "Glob", "Grep"]` only? This is a broader concern affecting the pipeline review phase too. (Deferred — tracked separately.)

3. **Fix loop safety on shared branches**: Should we add a `--allow-fixes` confirmation or warning when `--fix` is used on branches that appear to be shared (e.g., `develop`, `release/*`)? (Consensus: not needed for v1 since `--fix` is already opt-in.)

---

### Persona Consensus Summary

| Question | Consensus | Tension |
|----------|-----------|---------|
| Primary use case | Developer workflow (7/7) | None |
| In-place vs worktree | In-place (6/7) | Security Engineer prefers worktree for blast-radius containment |
| Local vs remote branches | Local only (7/7) | None |
| Prompt builder approach | Make existing flexible (7/7) | None |
| Print summary table | Yes (7/7) | Security Engineer suggests stderr for human output, stdout for JSON |
| Diff truncation | Simple for v1 (5/7) | Jony Ive and Systems Engineer want hunk-boundary-aware truncation |
| Fix loop default | Review-only, `--fix` opt-in (7/7) | None |
| Config + CLI overrides | Config default, CLI wins (7/7) | Security Engineer wants CLI to only tighten, never loosen |
| Read-only tools for reviewers | Yes (7/7) | Security Engineer wants Bash removed entirely |
| Decision artifacts location | Same `reviews_dir` (7/7) | None |
