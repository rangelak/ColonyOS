# PRD: Autonomous CEO Stage ("colonyos auto")

## 1. Introduction/Overview

ColonyOS currently requires a human to provide a feature prompt via `colonyos run "<prompt>"`. This PRD introduces an autonomous **CEO stage** — a new `colonyos auto` command where an AI CEO persona analyzes the project, its history, and its strategic direction to autonomously decide **what to build next**. The CEO's output becomes the prompt that feeds into the existing Plan -> Implement -> Review -> Deliver pipeline.

This transforms ColonyOS from a "human directs, machine executes" tool into a fully autonomous development loop where the system can identify the most impactful next feature and ship it end-to-end.

## 2. Goals

1. **Autonomous feature ideation**: A single `colonyos auto` command that produces a well-reasoned feature request without human input.
2. **Pipeline integration**: The CEO output feeds directly into the existing `run()` function in `orchestrator.py` as the `prompt` argument — no changes to downstream phases.
3. **Safe defaults**: Human confirmation checkpoint by default; fully autonomous mode requires explicit `--no-confirm` flag.
4. **History awareness**: The CEO reads all prior PRDs (`cOS_prds/`), tasks (`cOS_tasks/`), and reviews (`cOS_reviews/`) to avoid duplicate work and build on momentum.
5. **Strategic grounding**: An optional `vision` field in `.colonyos/config.yaml` lets users define business priorities the CEO navigates toward.

## 3. User Stories

### US-1: Solo developer, autonomous mode
> As a solo developer, I want to run `colonyos auto` and have the system figure out the most impactful next feature for my project, generate a PRD, implement it, review it, and open a PR — all while I'm away.

### US-2: Team lead, guided ideation
> As a team lead, I want to run `colonyos auto`, review the CEO's feature proposal, and either approve it to proceed or reject it and run again for a different suggestion.

### US-3: Strategic direction
> As a project owner, I want to write a `vision` statement in my config so the CEO's suggestions align with my business goals rather than just doing generic engineering improvements.

### US-4: Continuous autonomous development
> As a power user, I want to run `colonyos auto --no-confirm --loop 3` to have the system autonomously pick and ship 3 features in sequence, each building on the last.

## 4. Functional Requirements

### 4.1 New CLI Command: `colonyos auto`
- **FR-1**: Add a `colonyos auto` Click command in `cli.py` alongside existing `run`, `init`, `status` commands.
- **FR-2**: Accept `--no-confirm` flag to skip human approval checkpoint (default: require confirmation).
- **FR-3**: Accept `--plan-only` flag to generate only the CEO proposal without triggering the pipeline.
- **FR-4**: Accept `--loop N` flag for continuous mode (max N iterations, single-shot by default).
- **FR-5**: Require `colonyos init` to have been run (config must exist with `project` info).

### 4.2 CEO Phase Execution
- **FR-6**: Add `CEO = "ceo"` to the `Phase` enum in `models.py`.
- **FR-7**: Create a new `_build_ceo_prompt()` function in `orchestrator.py` that constructs the CEO's system prompt and user prompt.
- **FR-8**: The CEO phase runs with **read-only tools only** (`Read`, `Glob`, `Grep`) — no `Write`, `Edit`, or `Bash`. This mirrors the existing pattern in `_build_persona_agents()` and `_build_review_persona_agents()`.
- **FR-9**: The CEO phase uses the project's configured `model` and `budget.per_phase` settings.

### 4.3 CEO Instruction Template
- **FR-10**: Create a new `instructions/ceo.md` template that instructs the CEO to:
  - Read the project description, stack, and vision from config context.
  - Scan all files in `cOS_prds/`, `cOS_tasks/`, and `cOS_reviews/` to understand what has been built.
  - Read the README and key source files to understand the current codebase.
  - Analyze gaps, opportunities, and next logical steps.
  - Produce a single, actionable feature request as a clear natural-language prompt.
  - Include a brief rationale (2-3 sentences) for why this feature is the top priority.
- **FR-11**: The CEO prompt must include scope constraints: "Propose features that can be implemented in a single PR, are aligned with the project's stack and description, and have clear acceptance criteria."

### 4.4 CEO Persona Configuration
- **FR-12**: Add an optional `ceo_persona` field to `ColonyConfig` in `config.py` — a single `Persona` instance (not a list).
- **FR-13**: Provide a sensible default CEO persona if none is configured (e.g., role: "Product CEO", expertise: "Product strategy, prioritization, user value", perspective: "What is the single most impactful thing to build next?").
- **FR-14**: Add an optional `vision` string field to `ColonyConfig` for strategic direction (freetext where users describe priorities, constraints, and goals).

### 4.5 Proposal Artifacts
- **FR-15**: Save the CEO's proposal to `cOS_proposals/{timestamp}_proposal_{slug}.md` with title, rationale, and the feature prompt.
- **FR-16**: Add a `proposals_dir` field to `ColonyConfig` (default: `cOS_proposals`).
- **FR-17**: Add `proposal_names()` function to `naming.py` following the existing `planning_names()` / `review_names()` pattern.

### 4.6 Human Checkpoint
- **FR-18**: After the CEO generates a proposal, print it to stdout and prompt `Proceed with this feature? [y/N]` using `click.confirm()`.
- **FR-19**: If the user rejects, exit with code 0 (not an error). The proposal file is still saved for reference.
- **FR-20**: `--no-confirm` bypasses the checkpoint entirely.

### 4.7 Pipeline Integration
- **FR-21**: After approval (or `--no-confirm`), call the existing `run_orchestrator()` function with the CEO-generated prompt string.
- **FR-22**: The CEO phase result is logged as the first entry in the `RunLog.phases` list.
- **FR-23**: In `--loop N` mode, each iteration re-reads the codebase (including artifacts from prior iterations) before proposing the next feature.

### 4.8 Run Logging
- **FR-24**: Log CEO runs to `.colonyos/runs/` using the existing `RunLog` and `_save_run_log()` infrastructure.
- **FR-25**: The run log should include the CEO's proposed prompt in a new `proposal` field or in `artifacts`.

## 5. Non-Goals

- **Multiple CEO profiles**: V1 ships a single configurable CEO persona. Multiple profiles (growth-CEO, technical-CEO, etc.) are deferred.
- **External integrations**: No GitHub Issues, Slack, Jira, or analytics dashboard integration. The CEO works from the repo and config only.
- **Structured proposal schema**: The CEO produces a natural-language prompt string, not a formal JSON/YAML schema. The Plan phase handles structuring.
- **Backlog generation**: The CEO picks one feature, not a ranked list. A separate `colonyos brainstorm` command could be built later.
- **CEO writing code**: The CEO phase is strictly read-only. It never modifies files.
- **Unbounded continuous mode**: `--loop` requires an explicit iteration count N. Infinite loops are not supported.

## 6. Technical Considerations

### Architecture
The CEO stage is **not** a new phase inserted into the existing pipeline. It is a **pre-pipeline command** that produces the input to `run()`. This preserves the clean contract of the existing `run()` function in `orchestrator.py` (line 291), which takes `prompt: str` as its core input.

```
colonyos auto:  CEO -> [human checkpoint] -> run(prompt) -> Plan -> Implement -> Review -> Deliver
colonyos run:                                 run(prompt) -> Plan -> Implement -> Review -> Deliver
```

### Key Files to Modify
| File | Change |
|------|--------|
| `src/colonyos/models.py` | Add `CEO = "ceo"` to `Phase` enum |
| `src/colonyos/config.py` | Add `ceo_persona`, `vision`, `proposals_dir` fields to `ColonyConfig`; update `load_config`/`save_config` |
| `src/colonyos/cli.py` | Add `colonyos auto` command with `--no-confirm`, `--plan-only`, `--loop` options |
| `src/colonyos/orchestrator.py` | Add `_build_ceo_prompt()`, `run_ceo()` functions |
| `src/colonyos/naming.py` | Add `ProposalNames` dataclass and `proposal_names()` function |
| `src/colonyos/instructions/ceo.md` | New instruction template for CEO phase |
| `src/colonyos/init.py` | Add optional CEO persona and vision collection during init |

### New Files
| File | Purpose |
|------|---------|
| `src/colonyos/instructions/ceo.md` | CEO phase instruction template |
| `tests/test_ceo.py` | Tests for CEO phase logic |

### Security Considerations (Persona Consensus)
All 7 personas agreed on these security principles:
- **Read-only tools**: The CEO must only have `Read`, `Glob`, `Grep` — no `Write`, `Edit`, or `Bash`. This prevents the CEO from modifying the repo during analysis.
- **Human checkpoint by default**: The CEO's output is an untrusted prompt that will drive a pipeline running with `bypassPermissions`. A mandatory confirmation step is the primary guardrail.
- **Budget caps**: The existing `per_phase` and `per_run` budget limits in `BudgetConfig` constrain blast radius. The CEO phase itself should have a low budget since it only reads.
- **Scope constraints in prompt**: The CEO instruction template must explicitly forbid proposals that require new external services, infrastructure changes, or touching more than a reasonable number of files.

### Persona Synthesis

**Strong consensus (all 7 agree):**
- Standalone command, not a pipeline phase
- Single CEO persona (not multiple profiles)
- Read-only tools for the CEO
- Human checkpoint by default, `--no-confirm` opt-in
- Must read prior PRDs/tasks to avoid duplication
- Single-shot by default, loop is opt-in with cap
- CEO output feeds directly into existing `run()` as prompt string

**Points of tension:**
- **Structured vs. freeform output**: The Systems Engineer and Security Engineer favored structured schemas (`CEOProposal` dataclass with title/rationale/scope/risk fields). All others preferred a simple natural-language string. **Resolution**: The CEO produces a natural-language prompt (matching existing `run()` contract) but saves a structured proposal artifact for auditability.
- **Ranked list vs. single pick**: The Systems Engineer and Security Engineer suggested 3-5 ranked candidates. All others insisted on a single decisive pick. **Resolution**: Single pick for V1; a future `colonyos brainstorm` command can generate ranked lists.
- **Vision source**: Jony Ive suggested a `cOS_strategy.md` file in the repo. Karpathy suggested a `vision` field in config. The YC Partner wanted it minimal. **Resolution**: An optional `vision` field in `config.yaml` — lightweight and version-controlled. Users who want more detail can reference a separate file in their vision text.

## 7. Success Metrics

1. **Feature quality**: CEO-proposed features are approved by humans at the checkpoint >70% of the time (measured by proposal accept/reject logs).
2. **No duplication**: The CEO never proposes a feature that matches an existing PRD in `cOS_prds/`.
3. **Pipeline completion**: When a CEO proposal is approved, the full pipeline (Plan -> Implement -> Review -> Deliver) succeeds >60% of the time.
4. **Budget efficiency**: The CEO phase itself costs <$1 per invocation (read-only analysis).
5. **User adoption**: Users invoke `colonyos auto` at least as often as `colonyos run` within 30 days of the feature shipping.

## 8. Open Questions

1. **CEO persona during init**: Should `colonyos init` ask the user to configure their CEO persona, or should we silently use the default until they customize it in config?
2. **Loop cooldown**: In `--loop N` mode, should there be a mandatory delay between iterations to allow prior PRs to be merged?
3. **Failed run awareness**: Should the CEO factor in recently failed runs (from `.colonyos/runs/`) when deciding what to build, e.g., retrying a failed feature or avoiding a known-problematic area?
4. **Vision field format**: Should the `vision` field support markdown or just plain text? Should it support referencing external files (e.g., `vision: "See ROADMAP.md"`)?
5. **Budget isolation for CEO**: Should the CEO phase have its own budget cap separate from `per_phase`, since it's read-only and should be cheap?
