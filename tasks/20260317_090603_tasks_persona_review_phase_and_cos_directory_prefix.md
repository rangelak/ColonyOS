# Tasks: Persona Review Phase & cOS_ Directory Prefix

## Relevant Files

- `src/colonyos/models.py` - Add `Phase.REVIEW` enum value, update data models
- `src/colonyos/config.py` - Add `reviews_dir` field, update `DEFAULTS` to `cOS_` prefix, add `review` toggle to `PhasesConfig`, update load/save
- `src/colonyos/naming.py` - Add review filename generation functions
- `src/colonyos/orchestrator.py` - Add `_build_review_prompt()`, insert REVIEW phase between Implement and Deliver, build review persona agents
- `src/colonyos/instructions/review.md` - Refactor into persona-aware review instruction template with `{persona_block}` placeholder
- `src/colonyos/instructions/base.md` - Add `{reviews_dir}` reference to output conventions
- `src/colonyos/init.py` - Create `reviews_dir` during init, update `.gitignore` handling
- `src/colonyos/agent.py` - No changes expected (already supports subagents)
- `src/colonyos/cli.py` - No changes expected (phases driven by config)
- `tests/test_orchestrator.py` - Tests for review phase integration, prompt building, persona agents
- `tests/test_config.py` - Tests for new config fields, load/save round-trip
- `tests/test_naming.py` - Tests for review filename generation

## Tasks

- [x]1.0 Update data models and Phase enum
  - [x]1.1 Write tests in `tests/test_orchestrator.py` for `Phase.REVIEW` existence and `PhasesConfig.review` field
  - [x]1.2 Add `REVIEW = "review"` to `Phase` enum in `src/colonyos/models.py`

- [x]2.0 Update config system with `cOS_` defaults and review support
  - [x]2.1 Write tests in `tests/test_config.py` for: new `DEFAULTS` values (`cOS_prds`, `cOS_tasks`, `cOS_reviews`), `reviews_dir` field on `ColonyConfig`, `review` toggle on `PhasesConfig`, load/save round-trip with new fields
  - [x]2.2 Add `review: bool = True` to `PhasesConfig` in `src/colonyos/config.py`
  - [x]2.3 Add `reviews_dir: str = "cOS_reviews"` to `ColonyConfig` in `src/colonyos/config.py`
  - [x]2.4 Update `DEFAULTS` dict: `prds_dir` → `"cOS_prds"`, `tasks_dir` → `"cOS_tasks"`, add `reviews_dir` → `"cOS_reviews"`, add `review` phase toggle
  - [x]2.5 Update `load_config()` to read `reviews_dir` and `phases.review` from YAML
  - [x]2.6 Update `save_config()` to write `reviews_dir` and `phases.review` to YAML

- [x]3.0 Add review filename generation to naming module
  - [x]3.1 Write tests in `tests/test_naming.py` for `review_names()` function generating `{timestamp}_review_task_{N}_{slug}.md` and `{timestamp}_review_final_{slug}.md`
  - [x]3.2 Implement `review_names()` in `src/colonyos/naming.py` that generates per-task and final review filenames

- [x]4.0 Create persona-aware review instruction template
  - [x]4.1 Refactor `src/colonyos/instructions/review.md` into a persona-aware template with `{persona_block}`, `{task_description}`, `{prd_path}`, and `{branch_name}` placeholders. Remove the "fix them directly" instruction (review agents are read-only). Keep the completeness/quality/safety checklist as the base.
  - [x]4.2 Update `src/colonyos/instructions/base.md` to include `{reviews_dir}` in the Output Conventions section

- [x]5.0 Implement review phase in orchestrator
  - [x]5.1 Write tests in `tests/test_orchestrator.py` for: `_build_review_prompt()` output, review phase inserted between implement and deliver, review phase skipped when `config.phases.review` is false, review phase failure stops the run, persona subagents built for review with read-only tools
  - [x]5.2 Add `_build_review_prompt()` function in `src/colonyos/orchestrator.py` that layers `base.md` + `review.md` with persona block and task context
  - [x]5.3 Add `_build_review_persona_agents()` function (or reuse `_build_persona_agents` with review-specific prompts) that configures each persona for reviewing with read-only tools (`Read`, `Glob`, `Grep`)
  - [x]5.4 Insert REVIEW phase in the `run()` function between Implement and Deliver: parse task file to extract parent tasks, run per-task persona reviews (parallel subagents), run final holistic review, save review artifacts to `{reviews_dir}/`
  - [x]5.5 Handle review phase result: append `PhaseResult` to log, fail the run if review phase fails (same pattern as other phases)

- [x]6.0 Update init flow for new directory defaults
  - [x]6.1 Write tests in `tests/test_init.py` for: `reviews_dir` directory created during init, `.gitignore` updated with `cOS_*/` pattern
  - [x]6.2 Update `run_init()` in `src/colonyos/init.py` to create `reviews_dir` directory alongside prds and tasks dirs
  - [x]6.3 Update `.gitignore` handling to add `cOS_*/` pattern (or keep specific entries for each dir)
  - [x]6.4 Add warning log if old `prds/` or `tasks/` directories exist alongside new `cOS_` prefixed dirs

- [x]7.0 End-to-end integration verification
  - [x]7.1 Update existing tests in `tests/test_orchestrator.py` that mock `run_phase_sync` to account for the new REVIEW phase call (full run now has 4 phases: plan, implement, review, deliver)
  - [x]7.2 Verify all existing tests pass with updated `DEFAULTS` (tests that hardcode `prds_dir="prds"` may need fixture updates)
  - [x]7.3 Run full test suite and fix any regressions
