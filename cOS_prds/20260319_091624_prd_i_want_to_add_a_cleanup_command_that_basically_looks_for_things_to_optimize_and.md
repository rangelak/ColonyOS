# PRD: `colonyos cleanup` — Codebase Hygiene & Structural Analysis

## 1. Introduction/Overview

ColonyOS autonomously generates branches, PRDs, tasks, reviews, and run logs with every pipeline execution. Over time, this creates significant codebase entropy: stale `colonyos/` branches accumulate locally and on origin, `.colonyos/runs/` fills with old run artifacts, and the codebase itself may develop structural debt (overly long files, complex functions, dead code).

This feature adds a `colonyos cleanup` command that provides two distinct capabilities:

1. **Git & Artifact Hygiene** (`colonyos cleanup branches`, `colonyos cleanup artifacts`) — Deterministic, safe operations that prune merged branches and old run artifacts. No AI agent needed.
2. **Structural Analysis** (`colonyos cleanup scan`) — An AI-powered scan that analyzes the codebase for structural issues (complex files, long functions, dead code) and produces a prioritized report. Refactoring is then delegated to the existing `colonyos run` pipeline with proper review gates.

### Design Philosophy

All 7 expert personas reached strong consensus on several critical points:

- **Git cleanup and code refactoring are fundamentally different operations** with different risk profiles and must not be bundled into one undifferentiated action.
- **Deterministic operations (branch pruning) should not use the AI agent** — they waste budget on what `git branch --merged` already solves.
- **Code refactoring must go through the existing review pipeline** — bypassing review/decision gates for autonomous code changes would be the single worst safety decision.
- **Default to dry-run** — every destructive operation must show what it would do before doing it, requiring explicit `--execute` opt-in.
- **v1 should be conservative** — analysis and reporting first, autonomous refactoring later.

### Tensions Between Personas

| Topic | Position A | Position B |
|-------|-----------|-----------|
| Scope of v1 | YC/Jobs/Linus: Ship only branch pruning, code refactoring via existing `run` | Karpathy/Ive: Include structural scan as analysis-only output |
| Separate commands vs subcommands | Linus/Systems: Completely separate commands (`prune`, `lint-structure`) | Ive/YC: One `cleanup` command with subcommands for cohesive UX |
| LLM for analysis | Karpathy: LLMs are excellent at code analysis | Linus/YC: Static analysis (line counts) is cheaper and sufficient |
| AI-driven refactoring | Karpathy: Multi-pass focused agent calls | Security/Linus: Never autonomous, always human-reviewed PR |

**Resolution**: We adopt subcommands under `cleanup` for cohesive UX, include both deterministic hygiene and AI-powered structural scan, but strictly separate them. All code-changing actions go through the existing pipeline.

## 2. Goals

1. **Reduce branch clutter** — Automatically identify and prune merged `colonyos/` branches (local + remote) with zero AI budget cost.
2. **Reclaim disk space** — Clean up old `.colonyos/runs/` artifacts beyond a configurable retention period.
3. **Surface structural debt** — Produce a prioritized report of complex files, long functions, and potential dead code.
4. **Bridge to action** — Allow users to pipe scan findings directly into `colonyos run` for AI-driven refactoring with full review gates.
5. **Zero-risk defaults** — Every invocation without `--execute` is purely informational (dry-run).

## 3. User Stories

**US-1: Branch Hygiene**
> As a developer using ColonyOS heavily, I want to clean up the dozens of stale `colonyos/` branches cluttering my local and remote repo so that `git branch` output is manageable and my team isn't confused by old branches.

**US-2: Artifact Cleanup**
> As a developer, I want to reclaim disk space by removing old `.colonyos/runs/` directories (completed runs older than 30 days) without losing recent run history.

**US-3: Structural Scan**
> As a developer, I want to see which files and functions in my codebase are most complex so I can prioritize refactoring work, either manually or via `colonyos run`.

**US-4: Scan-to-Refactor Pipeline**
> As a developer, after seeing the structural scan report, I want to easily kick off a `colonyos run` to refactor a specific file, with the refactoring going through the full review pipeline.

## 4. Functional Requirements

### 4.1 CLI Structure

| # | Requirement |
|---|-------------|
| FR-1 | Add a `colonyos cleanup` command group with three subcommands: `branches`, `artifacts`, and `scan`. |
| FR-2 | `colonyos cleanup` with no subcommand prints help showing all subcommands. |

### 4.2 Branch Cleanup (`colonyos cleanup branches`)

| # | Requirement |
|---|-------------|
| FR-3 | List all local branches that are fully merged into the default branch (main/master). |
| FR-4 | By default, only target branches matching the configured `branch_prefix` (default: `colonyos/`). Support `--all-branches` to include all merged branches. |
| FR-5 | Display a Rich-formatted table of candidate branches with: name, last commit date, merge status. |
| FR-6 | Default mode is dry-run (display only). Require `--execute` flag to actually delete. |
| FR-7 | Support `--include-remote` flag to also prune merged branches from origin. |
| FR-8 | Never delete the current branch or the default branch (main/master). |
| FR-9 | Never delete branches with open PRs (reuse `check_open_pr` from `github.py`). |
| FR-10 | Print a summary: N branches deleted (local), M branches deleted (remote), K branches skipped (with reasons). |

### 4.3 Artifact Cleanup (`colonyos cleanup artifacts`)

| # | Requirement |
|---|-------------|
| FR-11 | Scan `.colonyos/runs/` for completed run directories older than a configurable retention period (default: 30 days). |
| FR-12 | Display a table of candidate artifacts with: run ID, date, status, size on disk. |
| FR-13 | Default mode is dry-run. Require `--execute` to delete. |
| FR-14 | Support `--retention-days N` flag to override the default retention period. |
| FR-15 | Never delete runs with status `RUNNING`. |
| FR-16 | Print a summary: N run directories removed, M MB reclaimed. |

### 4.4 Structural Scan (`colonyos cleanup scan`)

| # | Requirement |
|---|-------------|
| FR-17 | Use static analysis (no AI agent) to compute: file line counts, function counts per file, and identify files exceeding configurable thresholds (`--max-lines`, default 500; `--max-functions`, default 20). |
| FR-18 | Display a Rich-formatted table of flagged files sorted by severity: file path, line count, function count, and a complexity category (large/very-large/massive). |
| FR-19 | Support `--ai` flag to additionally run an AI agent scan that provides qualitative analysis (dead code detection, naming issues, architectural suggestions). This uses the existing `run_phase` machinery with a dedicated `cleanup_scan.md` instruction template. |
| FR-20 | The AI scan output is a structured markdown report saved to `.colonyos/runs/cleanup_<timestamp>.md`. |
| FR-21 | Support `--refactor FILE` flag that synthesizes a refactoring prompt and delegates to `colonyos run` (through the full pipeline with review gates). |

### 4.5 Configuration

| # | Requirement |
|---|-------------|
| FR-22 | Add an optional `cleanup:` section to `ColonyConfig` with fields: `branch_retention_days` (int, default 0 = merged-only), `artifact_retention_days` (int, default 30), `scan_max_lines` (int, default 500), `scan_max_functions` (int, default 20). |
| FR-23 | CLI flags override config values. |

### 4.6 Safety & Audit

| # | Requirement |
|---|-------------|
| FR-24 | Log all cleanup actions to a JSON file under `.colonyos/runs/cleanup_<timestamp>.json` with: operation type, items affected, items skipped (with reasons), timestamp. |
| FR-25 | The cleanup log must never be deletable by the cleanup command itself. |
| FR-26 | The `--ai` scan must inherit the `base.md` instruction constraints (no direct main commits, no force-push). |
| FR-27 | The `--ai` scan instruction must explicitly forbid modifying files related to authentication, authorization, secrets, or sanitization. |

## 5. Non-Goals

- **Autonomous code refactoring** — The cleanup command does NOT modify source code. Code changes flow through `colonyos run` with full Plan/Implement/Review/Decision/Deliver pipeline.
- **Performance optimization** — The scan identifies structural complexity, not runtime performance issues.
- **Linting/formatting** — Use dedicated tools (ruff, black, eslint). ColonyOS is not a linter.
- **Dependency updates** — Out of scope. Too high-risk for a "cleanup" context.
- **Scheduled/automatic execution** — v1 is manual invocation only. No cron, no hook into the `run` pipeline.
- **Complexity scoring/grading** — Report raw metrics (line count, function count), not subjective grades.

## 6. Technical Considerations

### Architecture

The cleanup command should follow the pattern established by `doctor.py` — a standalone module (`cleanup.py`) with reusable functions, called from `cli.py` via Click commands. This avoids adding more code to the already-large `cli.py` (1,866 lines).

### Key Files to Modify

| File | Change |
|------|--------|
| `src/colonyos/cleanup.py` | **New** — Core cleanup logic (branch pruning, artifact cleanup, static scan) |
| `src/colonyos/cli.py` | Add `cleanup` command group with `branches`, `artifacts`, `scan` subcommands |
| `src/colonyos/config.py` | Add `CleanupConfig` dataclass and wire into `ColonyConfig` |
| `src/colonyos/models.py` | No changes needed — reuse existing `RunLog` for audit trail |
| `src/colonyos/instructions/cleanup_scan.md` | **New** — AI scan instruction template (for `--ai` flag) |
| `tests/test_cleanup.py` | **New** — Comprehensive tests |

### Existing Code to Reuse

- `github.py` → `check_open_pr()` for safe branch deletion
- `config.py` → `ColonyConfig`, `runs_dir_path()` for artifact discovery
- `agent.py` → `run_phase()` for AI scan (only when `--ai` flag is used)
- `ui.py` → Rich formatting patterns for consistent output
- `orchestrator.py` → `run()` for `--refactor` delegation

### Dependencies

No new dependencies. Uses only `subprocess` (git commands), `pathlib` (file ops), `rich` (output), and optionally `claude-agent-sdk` (AI scan).

## 7. Success Metrics

| Metric | Target |
|--------|--------|
| Branch cleanup correctly identifies all merged `colonyos/` branches | 100% accuracy |
| Zero false deletions (unmerged branches, branches with open PRs) | 0 incidents |
| Artifact cleanup reclaims space from old runs | Measurable MB freed |
| Structural scan flags files over threshold | All files > 500 lines identified |
| `--execute` flag required for all destructive operations | No accidental deletions possible |
| AI scan (when used) stays within budget constraints | Respects `per_phase` budget |
| All cleanup operations produce audit logs | 100% of executions logged |

## 8. Open Questions

1. **Should `cleanup scan --refactor` auto-create a GitHub issue instead of (or in addition to) starting a run?** This would allow teams to triage refactoring work.
2. **Should the CEO agent (`colonyos auto`) be taught to periodically suggest cleanup?** Multiple personas noted this would be more natural than a standalone command.
3. **Should `cleanup branches` support age-based heuristics (delete branches older than N days even if not merged)?** The Systems Engineer argues merged-only is the only safe heuristic; others see value in age-based cleanup with explicit opt-in.
4. **Should `cleanup artifacts` also clean old PRDs/tasks/proposals?** These are committed to git and serve as audit trails, so probably not, but worth discussing.
5. **Should there be a `colonyos cleanup all` that runs branches + artifacts in sequence?** Convenient but risks making destructive operations too casual.
