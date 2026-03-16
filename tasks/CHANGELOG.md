# ColonyOS Changelog

Sequential log of all work done in this repository. Each entry documents what changed, why, and which artifacts were involved.

---

## 001 — Autonomous PM Workflow (v1)

**PRD:** `tasks/001_prd_PM_agent.md`
**Tasks:** `tasks/001_tasks_prd_PM_agent.md`
**Status:** Complete

### What was built

An end-to-end autonomous PM workflow that takes a rough feature request and produces a full PRD with no human intervention.

### Implementation log

#### Phase 1: Foundation & rules
- Created Cursor rules for PRD generation (`create_prd.mdc`) and task generation (`generate_tasks.mdc`).
- Wrote the PRD for the PM agent workflow itself (`001_prd_PM_agent.md`).
- Generated implementation tasks (`001_tasks_prd_PM_agent.md`).
- Set up Python venv, `.gitignore`, `pyproject.toml`, and `requirements.txt`.
- Added Cursor rule enforcing `.venv` usage for all Python commands (`python_venv.mdc`).

#### Phase 2: Static prototype
- Built initial Python package `src/colonyos_pm/` with static/deterministic implementations.
- Modules: `models.py`, `questions.py`, `personas.py`, `answers.py`, `prd.py`, `risk.py`, `workflow.py`, `storage.py`.
- Added CLI entrypoint (`cli.py`, `scripts/run_pm_workflow.py`).
- Added pytest suite with 5 passing tests.

#### Phase 3: Tests-first policy
- Updated `generate_tasks.mdc` to enforce tests-first sub-task ordering for all coding tasks.
- Workflow handoff metadata now includes `execution_policy: tests_first`.
- PRD output includes tests-first as a functional requirement.
- Task list updated so `x.1` sub-tasks are explicitly test-writing steps.

#### Phase 4: Real OpenAI integration
- Replaced all static/hardcoded logic with real OpenAI API calls (`gpt-4o` default).
- `llm.py` — thin OpenAI client wrapper with `chat()` and `chat_json()`.
- `questions.py` — LLM generates 8-12 context-specific clarifying questions per prompt.
- `answers.py` — each question answered by LLM with full persona system prompt (designer/engineer/CEO/YC partner).
- `prd.py` — LLM synthesizes Q&A into structured PRD following `create_prd.mdc`.
- `risk.py` — LLM-based risk tier classification with score, escalation flag, and rationale.
- `workflow.py` — orchestrates all LLM calls with progress logging.
- `cli.py` — loads `.env`, supports `--model` override.
- `conftest.py` — auto-mocks OpenAI for offline tests.
- Test suite expanded to 14 tests, all passing.
- Added `.env.example` and `python-dotenv` for API key management.
- `generated/` directory ignored by git.

#### Phase 5: Prompt extraction and work-tracking rule
- Created `src/colonyos_pm/prompts/` package with dedicated prompt modules.
- Rewrote all system prompts to senior-staff-engineer-at-Anthropic quality: precise constraints, explicit output schemas, no hedging or filler.
- Prompt modules: `questions.py`, `answers.py` (with persona identities), `prd.py`, `risk.py`.
- Rewired `questions.py`, `answers.py`, `prd.py`, `risk.py` to import prompts from `prompts/` rather than defining them inline.
- Updated `conftest.py` mock router to match new prompt wording.
- Added mandatory always-apply Cursor rule `track_work.mdc` requiring task and changelog updates on every change.
- Updated `create_prd.mdc` and `generate_tasks.mdc` with sequential `NNN_` file naming and changelog update steps.

### Files created or modified

```
.cursor/rules/create_prd.mdc
.cursor/rules/generate_tasks.mdc
.cursor/rules/python_venv.mdc
.env.example
.gitignore
README.md
pyproject.toml
pyrightconfig.json
requirements.txt
scripts/run_pm_workflow.py
src/colonyos_pm/__init__.py
src/colonyos_pm/__main__.py
src/colonyos_pm/answers.py
src/colonyos_pm/cli.py
src/colonyos_pm/llm.py
src/colonyos_pm/models.py
src/colonyos_pm/personas.py
src/colonyos_pm/prd.py
src/colonyos_pm/questions.py
src/colonyos_pm/risk.py
src/colonyos_pm/storage.py
src/colonyos_pm/workflow.py
tasks/001_prd_PM_agent.md
tasks/001_tasks_prd_PM_agent.md
src/colonyos_pm/prompts/__init__.py
src/colonyos_pm/prompts/answers.py
src/colonyos_pm/prompts/prd.py
src/colonyos_pm/prompts/questions.py
src/colonyos_pm/prompts/risk.py
tasks/CHANGELOG.md
tests/conftest.py
tests/test_pm_workflow.py
.cursor/rules/track_work.mdc
```
