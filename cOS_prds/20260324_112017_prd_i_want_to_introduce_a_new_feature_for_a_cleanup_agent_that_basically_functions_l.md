# PRD: `colonyos sweep` — Autonomous Codebase Quality Agent

## 1. Introduction / Overview

`colonyos sweep` is a new top-level CLI command that acts as an autonomous "staff engineer" — it analyzes the entire codebase (or a targeted path) for code quality issues, generates a prioritized task list of findings, and then feeds those tasks through the existing implement → verify → review → decision → fix → deliver pipeline to produce fix PRs.

This bridges the gap between the existing read-only `cleanup scan` (which only reports) and the feature-oriented `run`/`auto` commands (which only build new things). `sweep` is the missing third mode: **autonomous tech debt reduction**.

### Why it matters

Every codebase accumulates cruft — dead code, inconsistent error handling, overly complex functions, missing tests. Today ColonyOS can build features (`run`) and autonomously propose features (`auto`), but it has no way to autonomously *improve existing code*. The `cleanup scan` command surfaces structural issues but cannot fix them. The `cleanup scan --refactor FILE` path can fix a single file but requires the user to identify the target manually. `sweep` closes this loop: analyze → prioritize → fix → review → ship.

## 2. Goals

1. **Ship a `colonyos sweep` command** that analyzes the codebase for code quality issues and produces actionable fix PRs through the existing pipeline.
2. **Reuse the existing pipeline** — the only new phase is the analysis; implement/verify/review/decision/fix/deliver run unchanged.
3. **Default to safe, observable behavior** — dry-run by default (report only), `--execute` to act, matching the established `cleanup` command conventions.
4. **Keep it simple for v1** — one command, one analysis phase, standard task file output, one PR per sweep run.

## 3. User Stories

### US-1: Targeted Sweep
> As a developer, I run `colonyos sweep src/colonyos/cli.py` to get a prioritized report of issues in a specific file. I review the findings, then run `colonyos sweep src/colonyos/cli.py --execute` to have the pipeline fix the top issues and open a PR.

### US-2: Whole-Codebase Sweep
> As a developer, I run `colonyos sweep` with no arguments to analyze the entire codebase. The agent identifies the worst offenders, produces a report, and with `--execute`, fixes the top 5 issues in a single PR.

### US-3: Plan-Only Sweep
> As a developer, I run `colonyos sweep --execute --plan-only` to generate the analysis report *and* the task file, but stop before implementation. I want to review/edit the task list before the pipeline acts on it.

### US-4: Budget-Constrained Sweep
> As a developer on a tight budget, I run `colonyos sweep --execute --max-tasks 3` to limit the sweep to the 3 highest-priority findings.

## 4. Functional Requirements

### FR-1: New `sweep` CLI Command
- Register `colonyos sweep` as a top-level Click command (peer to `run`, `auto`, `review`).
- Accept an optional positional `path` argument (file or directory) to scope the analysis. Default: repo root.
- Flags:
  - `--execute` — proceed from analysis into the implement→review pipeline (default: dry-run/report only)
  - `--plan-only` — generate analysis + task file but stop before implementation
  - `--max-tasks N` — cap the number of findings that become tasks (default: 5)
  - `--verbose` / `--quiet` — match existing CLI conventions
  - `--no-tui` — force plain output
  - `--force` — bypass preflight checks

### FR-2: New `Phase.SWEEP` Enum Value
- Add `SWEEP = "sweep"` to the `Phase` enum in `models.py`.
- The sweep phase must use **read-only tools only**: `["Read", "Glob", "Grep"]` — no Write, Edit, or Bash.
- Budget and model configurable via `phase_models.sweep` in config, defaulting to the global model.

### FR-3: Sweep Analysis Instruction Template
- Create `instructions/sweep.md` — the system prompt for the analysis agent.
- The agent must:
  1. Read the codebase broadly (or the targeted path).
  2. Identify issues across categories: correctness/bugs, dead code, error handling gaps, structural complexity, consistency violations, missing tests.
  3. Score each finding by Impact (1-5) and Risk (1-5).
  4. Output a structured task file in the **exact format** that `dag.py:parse_task_file()` consumes (with `depends_on:` annotations).
  5. Rank tasks by `impact * risk` score descending, capped at `--max-tasks`.
- Explicit exclusions: must NOT propose changes to auth/security code, secrets, database schemas, or public API signatures.

### FR-4: Sweep Orchestration Function
- Add `run_sweep()` in `orchestrator.py` (analogous to `run_ceo()`).
- Flow:
  1. Run the `Phase.SWEEP` analysis agent (read-only).
  2. Parse the generated task file.
  3. If dry-run mode: print the findings report and exit.
  4. If `--execute`: call `run()` (the existing orchestrator) with `skip_planning=True` and the sweep-generated task file, feeding it into the implement → review → deliver pipeline.
- The sweep prompt to the orchestrator should reference the analysis report so the implement agent has full context.

### FR-5: SweepConfig Dataclass
- Add a `SweepConfig` dataclass in `config.py` with:
  - `max_tasks: int = 5`
  - `max_files_per_task: int = 5`
  - `default_categories: list[str] = ["bugs", "dead_code", "error_handling", "complexity", "consistency"]`
- Add `sweep:` section to config YAML defaults and `ColonyConfig`.

### FR-6: Dry-Run Report Output
- In dry-run mode (no `--execute`), print a Rich-formatted table to stdout showing:
  - Finding #, Category, File(s), Impact, Risk, Score, Description
- Also persist the report as a JSON audit log via `write_cleanup_log()` (reusing existing cleanup audit infrastructure).

### FR-7: Single PR Per Sweep Run
- Each `sweep --execute` invocation produces one branch and one PR.
- The PR title should follow the pattern: `sweep: N code quality improvements in <scope>`.
- The PR body should include the analysis summary and a checklist of findings addressed.

## 5. Non-Goals (Out of Scope for v1)

- **Multiple PRs per sweep** — one PR per run is sufficient; users can run multiple sweeps.
- **Severity filtering (`--min-severity`)** — the analysis agent ranks internally; `--max-tasks` is the v1 control knob.
- **CEO integration** — the CEO will not autonomously propose sweep runs in v1.
- **Performance/security-specific analysis** — these require specialized domain knowledge and have high false-positive rates.
- **TUI integration** — sweep will use plain streaming output for v1.
- **Loop/batch mode** — no `--loop N` like `auto`; users run `sweep` once per invocation.

## 6. Technical Considerations

### Existing Patterns to Reuse
- **`run_ceo()` in `orchestrator.py`** (line 1375): The exact pattern for a custom first-phase that generates input for the pipeline. `run_sweep()` follows the same structure: run a read-only agent, capture output, optionally delegate to `run()`.
- **`cleanup scan --refactor` in `cli.py`** (line 3807): Already delegates to `run_orchestrator()` with a synthesized prompt. `sweep --execute` does the same but with a richer analysis phase.
- **`cleanup scan --ai` in `cli.py`** (line 3874): Already uses `run_phase_sync()` with read-only tools and the `cleanup_scan.md` instruction. `sweep` extends this pattern.
- **`parse_task_file()` in `dag.py`**: The universal interface between analysis and execution. Sweep must output in this format.
- **`write_cleanup_log()` in `cleanup.py`**: Audit logging for the dry-run report.
- **`_SAFETY_CRITICAL_PHASES` in `config.py`** (line 22): Review and decision phases are safety gates — sweep tasks go through them unchanged.

### Key Files to Modify
| File | Change |
|------|--------|
| `src/colonyos/models.py` | Add `Phase.SWEEP` enum value |
| `src/colonyos/config.py` | Add `SweepConfig` dataclass, wire into `ColonyConfig` |
| `src/colonyos/cli.py` | Add `sweep` command with Click decorators |
| `src/colonyos/orchestrator.py` | Add `run_sweep()` function |
| `src/colonyos/instructions/sweep.md` | New instruction template for analysis agent |

### Key Files to Create
| File | Purpose |
|------|---------|
| `src/colonyos/instructions/sweep.md` | System prompt for the sweep analysis phase |

### Dependencies
- No new external dependencies. Everything uses existing Claude Agent SDK infrastructure.
- The `cleanup.py` module's `scan_directory()` results can optionally be fed as context to the sweep agent to bootstrap its analysis.

## 7. Success Metrics

1. **Command works end-to-end**: `colonyos sweep --execute` produces a merged PR with passing tests.
2. **Analysis quality**: The sweep agent identifies at least 3 genuine code quality issues per run on a non-trivial codebase.
3. **Pipeline reuse**: Zero changes to the implement, review, decision, fix, or deliver phases.
4. **Safety**: Dry-run mode produces no side effects. Execute mode produces no regressions (tests pass in verify phase).
5. **Cost efficiency**: A full sweep run (analysis + implement + review) costs ≤ $15 (within existing per-run budget defaults).

## 8. Open Questions

1. **Should the sweep analysis consume `cleanup scan` results as input?** The existing `scan_directory()` produces `FileComplexity` results that could bootstrap the analysis. Pros: faster, cheaper analysis. Cons: couples sweep to the structural scanner's heuristics.
2. **Should sweep support `--from-tasks` to skip analysis and use a pre-existing task file?** This would let users edit the generated tasks before execution.
3. **Should the `--max-tasks` default be configurable in `config.yaml`?** Yes — via `SweepConfig.max_tasks`. The CLI flag overrides it.

## Appendix: Persona Synthesis

### Areas of Strong Agreement
- **Command name `sweep`**: All 7 personas independently converged on this name.
- **Dry-run by default**: Universal agreement, matching established `cleanup` conventions.
- **Read-only analysis phase**: Every persona emphasized the analysis agent must not have write permissions.
- **Reuse existing pipeline**: No persona suggested forking the implement/review/deliver phases.
- **Standard task file format**: Universal agreement that compatibility with `parse_task_file()` is critical.

### Areas of Tension (Resolved for v1)
- **Scope default**: Seibel/Security wanted targeted-by-default; others preferred whole-codebase. **Resolution**: Default to whole-codebase (simpler UX, zero-thought default per Jobs) but accept optional `path` argument for targeting.
- **PR strategy**: Seibel wanted single PR; Jobs/Linus/Security wanted one-per-finding. **Resolution**: Single PR per sweep run for v1 (simplest; users can run multiple times for atomic PRs).
- **Severity filtering**: Seibel said skip for v1; others wanted `--min-severity`. **Resolution**: Skip for v1; `--max-tasks` is the control knob. Agent ranks internally by severity.
- **CEO integration**: Most said yes-but-opt-in. **Resolution**: Out of scope for v1; CEO keeps its feature focus.
