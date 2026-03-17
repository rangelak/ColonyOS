# PRD: Standalone `colonyos review <branch>` Command

## 1. Introduction / Overview

ColonyOS currently runs code reviews only as part of the full pipeline (`colonyos run`), tightly coupled to a prior plan and implement phase. This PRD defines a standalone `colonyos review <branch>` command that runs the parallel per-persona review, optional fix loop, and optional decision gate against any existing branch — without requiring a prior ColonyOS run or PRD.

This unlocks two critical use cases: (1) developers can get AI-powered multi-persona reviews on any branch they've built manually, and (2) the command can serve as a CI gate (exit code 0 = approve, 1 = reject) for pull request quality checks.

## 2. Goals

1. **Decouple review from the full pipeline** — allow review of any git branch, regardless of how it was created.
2. **CI-ready by default** — deterministic exit codes (0 = approve, 1 = reject) and structured output make the command usable in GitHub Actions or any CI system.
3. **Optional PRD context** — when provided, reviewers assess against a PRD; when omitted, they assess the diff on its own merits.
4. **Reuse existing infrastructure** — extract the review/fix/decision loop from `orchestrator.run()` into a shared function, avoiding code duplication.
5. **Full observability** — run logs, review artifacts, and a summary table give developers clear insight into review outcomes.

## 3. User Stories

- **As a developer**, I want to run `colonyos review my-feature` to get multi-persona AI reviews on my branch before opening a PR, so I can catch issues early.
- **As a developer**, I want to run `colonyos review my-feature --prd cOS_prds/xxx.md` to verify my implementation meets the PRD requirements, even if I implemented it manually.
- **As a developer**, I want to run `colonyos review my-feature --fix` to have an AI agent automatically fix issues flagged by reviewers, saving me time.
- **As a CI engineer**, I want to add `colonyos review $BRANCH --base main -q` to my GitHub Actions workflow and gate merges on the exit code.
- **As a team lead**, I want to see standalone review runs in `colonyos status` alongside full pipeline runs.

## 4. Functional Requirements

### 4.1 CLI Command

- **FR-1**: Register a new `review` subcommand on the Click `app` group in `src/colonyos/cli.py`.
- **FR-2**: Accept a positional `branch` argument (required) — the branch to review.
- **FR-3**: Support `--prd <path>` option — path to a PRD file. When provided, reviewers assess against it. When omitted, the standalone review template is used.
- **FR-4**: Support `--fix` flag — enables the fix loop when reviewers request changes. Without it, the command is read-only.
- **FR-5**: Support `--base <branch>` option — override the auto-detected base branch. Default: auto-detect.
- **FR-6**: Support existing `-v/--verbose` and `-q/--quiet` flags with the same semantics as `run` and `auto`.

### 4.2 Base Branch Detection

- **FR-7**: Auto-detect the base branch by checking (in order): `main`, `master`, then falling back to `HEAD~1`.
- **FR-8**: Validate the branch exists and has a non-empty diff against the base before spawning any agents. Exit with a clear error message if no diff is found.

### 4.3 PRD-less Review Prompt

- **FR-9**: Add a new instruction template `src/colonyos/instructions/review_standalone.md` that instructs the reviewer to assess a branch diff without a PRD.
- **FR-10**: The standalone review prompt must instruct the reviewer to: read all changed files, assess code quality, correctness, test coverage, and potential issues from their persona's perspective, and produce the same `VERDICT: approve | request-changes` structured output.
- **FR-11**: Add a `_build_persona_standalone_review_prompt()` function in `orchestrator.py` that builds the system+user prompts using the standalone template.

### 4.4 Review Loop Extraction

- **FR-12**: Extract the review/fix/decision loop (currently lines ~770-920 of `orchestrator.py`) into a reusable `run_review_loop()` function that both `orchestrator.run()` and the new `review` command can call.
- **FR-13**: The extracted function must accept: `repo_root`, `config`, `branch_name`, `prd_rel` (optional), `task_rel` (optional), `log`, `verbose`, `quiet`, and `enable_fix` (bool).
- **FR-14**: When `prd_rel` is None, the function uses the standalone review prompt and standalone fix prompt (with findings as the sole specification).

### 4.5 Standalone Fix Prompt

- **FR-15**: Add a new instruction template `src/colonyos/instructions/fix_standalone.md` (or make `prd_path` and `task_path` optional in the existing fix template) for PRD-less fix iterations.
- **FR-16**: When no PRD is provided, the fix agent uses reviewer findings and the branch diff as its sole context.

### 4.6 Review Artifacts

- **FR-17**: Save review files to `cOS_reviews/` using the existing `_save_review_artifact` pattern.
- **FR-18**: Use filenames: `review_standalone_{branch_slug}_round{N}_{persona_slug}.md`.
- **FR-19**: Save the decision gate output as `decision_standalone_{branch_slug}.md`.

### 4.7 Run Logging

- **FR-20**: Reuse the existing `RunLog` model from `src/colonyos/models.py`.
- **FR-21**: Generate run IDs with a `review-` prefix: `review-{timestamp}-{hash}`.
- **FR-22**: Set `prompt` to `"review:<branch_name>"`, `branch_name` to the reviewed branch, and `prd_rel` to the PRD path or None.
- **FR-23**: The `colonyos status` command must display review runs alongside regular runs (no changes needed — the existing glob `*.json` already picks them up).

### 4.8 Summary Output

- **FR-24**: Print a summary table at the end showing: each reviewer persona name, their verdict (approve/request-changes), and the overall decision (GO/NO-GO or aggregate verdict if no decision gate).
- **FR-25**: Use the Rich library (already a dependency) for table formatting in non-quiet mode.

### 4.9 Exit Codes

- **FR-26**: Exit 0 if all reviewers approve (or decision gate says GO).
- **FR-27**: Exit 1 if any reviewer requests changes (or decision gate says NO-GO).

### 4.10 Pre-flight Checks

- **FR-28**: Verify the target branch exists locally. If not, exit with error.
- **FR-29**: Verify the diff against base is non-empty. If empty, exit with message "No changes to review on branch X against Y."
- **FR-30**: When `--fix` is used, verify the working tree is clean (no uncommitted changes) to prevent the fix agent from silently including unrelated changes.

## 5. Non-Goals

- **PR comment posting** — no automatic GitHub PR comments; users can pipe output to `gh pr comment` themselves.
- **`--json` output mode** — structured JSON output for CI consumption is a future enhancement. Exit codes are sufficient for v1.
- **`--ci` flag** — a dedicated CI mode with restricted tool access is a future enhancement.
- **Reviewing merged branches** — the command targets unmerged feature branches only.
- **Resume capability for review runs** — review runs are lightweight enough that re-running is simpler than resuming.
- **New `Phase` enum values** — reuse `Phase.REVIEW`, `Phase.FIX`, `Phase.DECISION` as-is.

## 6. Technical Considerations

### 6.1 Architecture

The core change is extracting the review/fix/decision loop from `orchestrator.run()` (lines ~770-920) into a standalone `run_review_loop()` function. This function becomes the shared core that both the pipeline's review phase and the new `colonyos review` command call.

**Key files to modify:**
- `src/colonyos/cli.py` — add `review` command with argument/option parsing
- `src/colonyos/orchestrator.py` — extract `run_review_loop()`, add `_build_persona_standalone_review_prompt()`, add `_build_standalone_fix_prompt()`, add `_build_review_run_id()`, add `detect_base_branch()`
- `src/colonyos/instructions/review_standalone.md` — new template (no PRD reference)
- `src/colonyos/instructions/fix_standalone.md` — new template (no PRD/task reference)

**Key files unchanged:**
- `src/colonyos/models.py` — `RunLog`, `PhaseResult`, `Phase` all reused as-is
- `src/colonyos/agent.py` — `run_phase_sync`, `run_phases_parallel_sync` reused as-is
- `src/colonyos/config.py` — `ColonyConfig`, `BudgetConfig` reused as-is

### 6.2 Prompt Construction

When a PRD is provided, the existing `_build_persona_review_prompt()` and `_build_fix_prompt()` are used directly. When no PRD is provided, new standalone variants are used that replace PRD-specific instructions with diff-focused ones.

### 6.3 Budget Controls

The review command inherits the existing budget system:
- `config.budget.per_phase` caps each individual agent call
- `config.budget.per_run` caps the total review run spend
- `config.max_fix_iterations` caps the fix loop

### 6.4 Existing Patterns Reused

| Pattern | Source | Reuse |
|---------|--------|-------|
| `_save_review_artifact()` | `orchestrator.py:397` | Artifact saving |
| `_extract_review_verdict()` | `orchestrator.py:190` | Verdict parsing |
| `_collect_review_findings()` | `orchestrator.py:196` | Finding aggregation |
| `_extract_verdict()` | `orchestrator.py:232` | Decision gate parsing |
| `_save_run_log()` | `orchestrator.py:411` | Run log persistence |
| `_print_run_summary()` | `cli.py:39` | Summary output |
| `run_phases_parallel_sync()` | `agent.py` | Parallel review execution |

### 6.5 Persona Consensus

**Strong agreement across all personas:**
- Extract review logic (don't duplicate) — unanimous
- Commit fixes on the reviewed branch directly (consistent with existing `fix.md`) — 6/7 agree (security engineer dissents, preferring a separate branch for provenance; we follow the majority for consistency with existing pipeline behavior)
- Reuse `RunLog` as-is — unanimous
- Fail fast on empty diff — unanimous
- Output a summary table — unanimous
- Design for CI compatibility via exit codes — unanimous
- Require clean working tree for `--fix` — strong agreement (Jobs, Systems Engineer, Security Engineer)

**Notable tension:**
- Security engineer recommends restricting `--fix` agent tools (no Bash) and requiring branch authorship validation. These are valid concerns but are deferred to a future `--ci` mode to avoid scope creep. The `--fix` flag is already opt-in.

## 7. Success Metrics

1. `colonyos review my-feature-branch` completes and produces review artifacts in `cOS_reviews/`
2. `colonyos review my-feature-branch --prd cOS_prds/xxx.md` reviews against the PRD
3. `colonyos review my-feature-branch --fix` enables the fix loop
4. `colonyos review my-feature-branch --base develop` overrides the base branch
5. Exit code 0 on all-approve, exit code 1 on any request-changes or NO-GO
6. Review runs appear in `colonyos status` output
7. All existing tests continue to pass
8. New test coverage for: argument parsing, base branch detection, prompt construction, artifact naming, exit codes

## 8. Open Questions

1. **Should `--fix` require confirmation by default?** The `auto` command has `--no-confirm` / `auto_approve` for this. We could add the same pattern, but for v1 the explicit `--fix` flag is sufficient opt-in.
2. **Should we add `--max-fix-rounds N` to override `config.max_fix_iterations`?** Useful but can be added later without breaking changes.
3. **Should we run the decision gate when `--fix` is not enabled?** Recommendation: yes — the decision gate summarizes the review outcome and its verdict drives the exit code, even in read-only mode.
