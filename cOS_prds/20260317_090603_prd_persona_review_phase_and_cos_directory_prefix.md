# PRD: Persona Review Phase & cOS_ Directory Prefix

## Introduction/Overview

ColonyOS currently runs three phases: **Plan → Implement → Deliver**. Personas are used only during the Plan phase to provide diverse Q&A on feature requests. This feature adds a **Review phase** between Implement and Deliver, where every defined persona reviews each completed parent task and performs a final holistic assessment of the entire implementation. Review artifacts are persisted to a `cOS_reviews/` directory. Additionally, all ColonyOS output directories adopt a `cOS_` prefix (`cOS_prds/`, `cOS_tasks/`, `cOS_reviews/`) to clearly namespace agent-generated artifacts within user repositories.

## Goals

1. **Multi-persona code review**: Every parent task is reviewed by all configured personas before delivery, surfacing diverse concerns (security, performance, UX, architecture) that a single-perspective self-review misses.
2. **Holistic final review**: After per-task reviews, each persona performs a cross-cutting assessment of the entire implementation against the PRD.
3. **Persistent review artifacts**: All review output is documented in structured markdown files under `cOS_reviews/`, providing an audit trail tied to specific runs.
4. **Namespaced output directories**: All ColonyOS output directories default to `cOS_` prefix, making agent artifacts instantly identifiable and trivially `.gitignore`-able with `cOS_*/`.
5. **Configurable and budget-aware**: The review phase is toggleable and respects the existing per-phase budget cap, so users control cost.

## User Stories

1. **As a solo developer**, I want each persona to review my implemented tasks so I get diverse expert feedback before a PR is opened.
2. **As a team lead**, I want review artifacts persisted in the repo so I can see what the AI reviewers flagged and whether concerns were addressed.
3. **As a cost-conscious user**, I want to toggle the review phase on/off and control its budget independently, so I'm not surprised by high API costs.
4. **As a user with an existing project**, I want my current `prds_dir`/`tasks_dir` config to keep working, while new projects get the cleaner `cOS_` prefixed defaults.
5. **As a user**, I want to easily `.gitignore` all ColonyOS artifacts with a single `cOS_*/` pattern.

## Functional Requirements

### Review Phase (FR1-FR8)

1. **FR1**: Add `REVIEW = "review"` to the `Phase` enum in `models.py`.
2. **FR2**: Add `review: bool = True` to `PhasesConfig` in `config.py`, following the existing pattern for `plan`, `implement`, `deliver`.
3. **FR3**: Add `reviews_dir: str = "cOS_reviews"` to `ColonyConfig` and `DEFAULTS` in `config.py`.
4. **FR4**: Add a `_build_review_prompt()` function in `orchestrator.py` that constructs a review system prompt by layering `base.md` + a new `review_persona.md` template, with per-persona identity injected — mirroring how `_build_plan_prompt()` layers `base.md` + `plan.md` with `{personas_block}`.
5. **FR5**: Per-task review: For each parent task in the task file, spawn all persona subagents in parallel (reusing the `_build_persona_agents` pattern) to review the diff and implementation for that task. Each persona produces a structured verdict (approve/request-changes), specific findings with file paths, and a synthesis paragraph.
6. **FR6**: Final holistic review: After per-task reviews complete, each persona reviews the full diff (`git diff main...HEAD`) against the PRD and produces a holistic assessment covering cross-cutting concerns.
7. **FR7**: Review artifacts are saved to `{reviews_dir}/{timestamp}_review_{slug}.md` — one file per parent task consolidating all persona verdicts as sections, plus one `{timestamp}_review_final_{slug}.md` for the holistic review.
8. **FR8**: The review phase is inserted between Implement and Deliver in the `run()` function in `orchestrator.py`. If the review phase fails, the run stops (same pattern as other phases). Review personas get read-only tools only (`Read`, `Glob`, `Grep`).

### Directory Prefix (FR9-FR12)

9. **FR9**: Change `DEFAULTS` in `config.py` so `prds_dir` defaults to `"cOS_prds"`, `tasks_dir` defaults to `"cOS_tasks"`.
10. **FR10**: Add `reviews_dir` to `DEFAULTS` with value `"cOS_reviews"`.
11. **FR11**: Update `colonyos init` to create directories with the new default names. Existing configs with explicit `prds_dir`/`tasks_dir` values continue to work unchanged.
12. **FR12**: Update `base.md` instruction template to reference `{reviews_dir}` alongside `{prds_dir}` and `{tasks_dir}`.

### Config & Budget (FR13-FR14)

13. **FR13**: The review phase respects the existing `per_phase` budget cap from `BudgetConfig`. No separate review-specific budget field in v1.
14. **FR14**: Update `save_config` and `load_config` in `config.py` to handle the new `review` phase toggle and `reviews_dir` field.

## Non-Goals

- **Auto-fix on rejection**: If a persona flags concerns, the system documents them but does NOT automatically re-implement. This avoids unbounded fix-review loops and keeps costs predictable. (All 7 personas agreed on this.)
- **Sub-task level reviews**: Reviews operate at the parent task level only, not individual sub-tasks. Sub-tasks are implementation details not meaningful as review units.
- **Forced migration**: Existing projects with `prds_dir: "prds"` in their config are NOT automatically migrated. Their explicit config values are respected.
- **Auto-fix retry loops**: No `--review-fix` flag or remediation passes in v1.
- **Per-persona tool customization for reviews**: All review personas get the same read-only tool set.

## Technical Considerations

### Existing Patterns to Reuse

- **Persona subagents**: `_build_persona_agents()` in `orchestrator.py` (line 40-58) already constructs `AgentDefinition` per persona with read-only tools. The review phase reuses this exact pattern.
- **Phase chaining**: The `run()` function (line 201-304) chains phases sequentially with `run_phase_sync()`. Review slots in between Implement and Deliver following the same pattern.
- **Instruction layering**: `_build_plan_prompt()` layers `base.md` + `plan.md` with template variables. Review prompt follows the same approach.
- **Naming conventions**: `naming.py` already generates timestamped filenames. Extend `PlanningNames` or add a parallel `ReviewNames` dataclass.
- **Config persistence**: `save_config`/`load_config` in `config.py` already handle all config fields with YAML serialization.

### Key Files to Modify

| File | Change |
|------|--------|
| `src/colonyos/models.py` | Add `Phase.REVIEW`, update `PhasesConfig` |
| `src/colonyos/config.py` | Add `reviews_dir`, update `DEFAULTS`, update `PhasesConfig`, update load/save |
| `src/colonyos/orchestrator.py` | Add `_build_review_prompt()`, insert review phase in `run()`, build review persona agents |
| `src/colonyos/naming.py` | Add review filename generation |
| `src/colonyos/instructions/review.md` | Refactor into persona-aware review template |
| `src/colonyos/instructions/base.md` | Add `{reviews_dir}` reference |
| `src/colonyos/init.py` | Create `reviews_dir` during init, update `.gitignore` pattern |
| `tests/test_orchestrator.py` | Add review phase tests |
| `tests/test_config.py` | Test new config fields |
| `tests/test_naming.py` | Test review filename generation |

### Review Document Structure

Each per-task review file contains persona sections:

```markdown
# Task Review: 1.0 <Task Title>
Run: run-20260317-abcdef1234
Timestamp: 2026-03-17T09:06:03Z

## Steve Jobs
- **Verdict**: approve
- **Findings**: ...
- **Synthesis**: ...

## Linus Torvalds
- **Verdict**: request-changes
- **Findings**: ...
- **Synthesis**: ...
```

### Persona Agreement & Tension Summary

**Strong consensus (7/7)**:
- Review parent tasks only, not sub-tasks
- Separate REVIEW phase between Implement and Deliver
- New `Phase.REVIEW` enum value (not embedded in implement)
- Document-only on rejection (no auto-fix in v1)
- Holistic final review (not re-review of tasks)
- `cOS_` prefix as new default
- Both toggle and budget controls needed
- Existing `review.md` becomes base template extended per-persona

**Tension areas**:
- **File storage granularity**: Security Engineer argued for one file per persona per task (isolation from prompt injection in one persona corrupting another's review). Linus argued for one file per run (less clutter). Majority (4/7) favored one file per task with consolidated persona sections. **Decision**: One file per task with persona sections — balances readability with traceability. The holistic final review gets its own file.
- **Default toggle state**: Security Engineer and Karpathy argued for default `false` (opt-in) until battle-tested. Others said `true`. **Decision**: Default to `true` — the feature is the point of this change; users can disable it.
- **Separate review budget field**: Principal SysEng argued for a dedicated `review_budget` in `BudgetConfig`. **Decision**: Use existing `per_phase` for v1 — simpler, and the review phase is just another phase.

## Success Metrics

1. Review phase completes successfully for runs with 1-7 personas and 4-8 parent tasks without exceeding per-phase budget.
2. Review artifacts are generated in `cOS_reviews/` with correct structure and all persona sections populated.
3. New projects created via `colonyos init` use `cOS_` prefixed directories by default.
4. Existing projects with explicit `prds_dir`/`tasks_dir` config continue to work without changes.
5. The review phase can be toggled off via `phases.review: false` in config, and the run proceeds directly from Implement to Deliver.
6. All existing tests continue to pass with the new defaults.

## Open Questions

1. **Review phase for `--from-prd` runs**: When a user skips planning with `--from-prd`, should the review phase still run? (Likely yes, since the implementation still needs review.)
2. **Persona subset for reviews**: Should users be able to specify which personas participate in reviews vs. planning? (Defer to v2.)
3. **Review-aware deliver phase**: Should the deliver phase include review summaries in the PR description? (Nice-to-have, not blocking.)
4. **`colonyos migrate` command**: Should we provide an explicit migration command for renaming `prds/` → `cOS_prds/`? (Deferred — print a warning if old dirs exist.)
