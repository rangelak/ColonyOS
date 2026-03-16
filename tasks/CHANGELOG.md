# ColonyOS Changelog

Chronological log of all work done in this repository. Each entry documents what changed, why, and which artifacts were involved.

---

## 20260316_071300 — Autonomous PM Workflow (v1)

**PRD:** `tasks/20260316_071300_prd_pm_agent.md`
**Tasks:** `tasks/20260316_071300_tasks_pm_agent.md`
**Status:** Complete

### What was built

An end-to-end autonomous PM workflow that takes a rough feature request and produces a full PRD with no human intervention.

### Implementation log

#### Phase 1: Foundation & rules
- Created Cursor rules for PRD generation (`create_prd.mdc`) and task generation (`generate_tasks.mdc`).
- Wrote the PRD for the PM agent workflow itself (`20260316_071300_prd_pm_agent.md`).
- Generated implementation tasks (`20260316_071300_tasks_pm_agent.md`).
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
tasks/20260316_071300_prd_pm_agent.md
tasks/20260316_071300_tasks_pm_agent.md
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

---

## 20260316_110306 — Project Setup Entrypoint

**Tasks:** `tasks/20260316_110306_tasks_project_setup_entrypoint.md`
**Status:** Complete

### What was built

A practical startup guide for the repository that explains the real local setup flow, the runnable entrypoint, the current scope of the codebase, and the gaps between the implemented PM workflow and the larger ColonyOS vision.

### Implementation log

- Created a repo-level `START_HERE.md` that acts as the first-stop guide for setup and execution.
- Documented the required `.venv` workflow, dependency installation, `.env` configuration, test command, and primary run command.
- Documented the actual entrypoint chain from `scripts/run_pm_workflow.py` to `src/colonyos_pm/cli.py` and `src/colonyos_pm/workflow.py`.
- Clarified what is implemented now versus what is still future-state so the docs do not oversell the repo.
- Updated `README.md` to point readers to the new practical startup guide first.
- Verified local setup by creating `.venv`, installing dependencies, and running the test suite successfully.
- Added an always-apply Cursor rule requiring review of `START_HERE.md` and `README.md` after meaningful completed tasks, with explicit triggers for setup, entrypoint, dependency, scope, and artifact changes.

### Files created or modified

```
START_HERE.md
README.md
.cursor/rules/update_entry_docs.mdc
tasks/20260316_110306_tasks_project_setup_entrypoint.md
tasks/CHANGELOG.md
```

---

## 20260316_110817 — Git Finalization Workflow Rule

**Tasks:** `tasks/20260316_110817_tasks_git_finalization_rule.md`
**Status:** Complete

### What was built

An always-apply Cursor rule that defines the default git finalization workflow for explicit user requests: use a non-`main` branch, commit the work, push the branch, and open a PR.

### Implementation log

- Added `.cursor/rules/git_finalize_on_request.mdc` to make branch, commit, push, and PR creation the default flow when the user explicitly asks to finalize completed work.
- Kept the rule aligned with existing safety constraints by explicitly forbidding automatic commit, push, or PR creation without user approval in the current conversation.
- Documented reuse of an existing correct branch and the requirement to ask when remote access, auth, or branch strategy is unclear.
- Reviewed `START_HERE.md` and `README.md` for impact and made no changes because this task affects agent git workflow policy rather than project setup or runtime behavior.

### Files created or modified

```
.cursor/rules/git_finalize_on_request.mdc
tasks/20260316_110817_tasks_git_finalization_rule.md
tasks/CHANGELOG.md
```

---

## 20260316_110957 — Timestamped Task and PRD Naming

**Tasks:** `tasks/20260316_110957_tasks_timestamp_naming_rule.md`
**Status:** Complete

### What was built

Updated the repository planning rules to use timestamp-based PRD and task filenames instead of sequential numeric prefixes, so parallel feature work across branches does not collide on file naming.

### Implementation log

- Updated `.cursor/rules/create_prd.mdc` to require PRD filenames in the form `YYYYMMDD_HHMMSS_prd_[feature-name].md` and matching timestamp-based changelog headings.
- Updated `.cursor/rules/generate_tasks.mdc` to require task filenames in the form `YYYYMMDD_HHMMSS_tasks_[feature-name].md`, reusing the source PRD timestamp.
- Updated `.cursor/rules/track_work.mdc` to require timestamp-based task filenames for newly created task logs.
- Updated the changelog intro text from "Sequential" to "Chronological" and initially left older numbered entries in place pending later backfill.
- Reviewed `START_HERE.md` and `README.md` for impact and made no changes because this task affects planning file naming conventions rather than project setup or runtime behavior.

### Files created or modified

```
.cursor/rules/create_prd.mdc
.cursor/rules/generate_tasks.mdc
.cursor/rules/track_work.mdc
tasks/20260316_110957_tasks_timestamp_naming_rule.md
tasks/CHANGELOG.md
```

---

## 20260316_111129 — Deterministic Naming Helper

**Tasks:** `tasks/20260316_111129_tasks_deterministic_naming_helper.md`
**Status:** Complete

### What was built

Added a deterministic Python naming helper so PRD filenames, task filenames, and changelog headings are generated by code instead of being hand-formatted by the AI.

### Implementation log

- Added `src/colonyos_pm/naming.py` with helpers for slug normalization, timestamp validation, PRD/task filename generation, changelog heading generation, and paired task-name derivation from a PRD path.
- Added a small CLI via `python -m colonyos_pm.naming` so agents can generate names deterministically from the repo's own code.
- Re-exported the naming helpers from `src/colonyos_pm/__init__.py`.
- Added `tests/test_naming.py` covering the helper logic and CLI output.
- Updated `.cursor/rules/create_prd.mdc`, `.cursor/rules/generate_tasks.mdc`, and `.cursor/rules/track_work.mdc` so planning filenames must come from the helper rather than manual formatting.
- Updated `START_HERE.md` to document the helper for contributors.
- Reviewed `README.md` and made no changes because the operational detail properly belongs in `START_HERE.md`.

### Files created or modified

```
src/colonyos_pm/naming.py
src/colonyos_pm/__init__.py
tests/test_naming.py
.cursor/rules/create_prd.mdc
.cursor/rules/generate_tasks.mdc
.cursor/rules/track_work.mdc
START_HERE.md
tasks/20260316_111129_tasks_deterministic_naming_helper.md
tasks/CHANGELOG.md
```

---

## 20260316_111929 — Backfill Legacy Planning Timestamps

**Tasks:** `tasks/20260316_111929_tasks_backfill_legacy_planning_timestamps.md`
**Status:** Complete

### What was built

Backfilled timestamp-based names onto the older planning artifacts that still used `001`, `002`, and `003`, then updated repo references so the planning history now follows the same timestamp convention throughout.

### Implementation log

- Renamed the original PM workflow PRD and task files from sequential numeric names to `tasks/20260316_071300_prd_pm_agent.md` and `tasks/20260316_071300_tasks_pm_agent.md` using the best available historical commit timestamp.
- Renamed the later setup and git-workflow task logs to `tasks/20260316_110306_tasks_project_setup_entrypoint.md` and `tasks/20260316_110817_tasks_git_finalization_rule.md` using filesystem creation timestamps because those files had not yet been committed.
- Updated changelog headings and file references so the old numbered task and PRD paths are no longer the canonical names.
- Updated the earlier timestamp-migration task note to reflect that the temporary decision to leave old numbered files in place was later superseded by this backfill.
- Reviewed `START_HERE.md` and `README.md` for impact and made no changes because this task affects planning artifact history rather than project setup or runtime behavior.

### Files created or modified

```
tasks/20260316_071300_prd_pm_agent.md
tasks/20260316_071300_tasks_pm_agent.md
tasks/20260316_110306_tasks_project_setup_entrypoint.md
tasks/20260316_110817_tasks_git_finalization_rule.md
tasks/20260316_110957_tasks_timestamp_naming_rule.md
tasks/20260316_111929_tasks_backfill_legacy_planning_timestamps.md
tasks/CHANGELOG.md
```

---

## 20260316_114331 — Azure Shared Client Config

**Tasks:** `tasks/20260316_114331_tasks_azure_shared_client.md`
**Status:** Complete

### What was built

A shared `src`-level LLM client that makes Azure OpenAI the first-class configuration path for the PM workflow while preserving the existing non-Azure OpenAI fallback.

### Implementation log

- Added `src/colonyos_pm/client.py` as the shared client module used by all workflow agents.
- The shared client now prefers `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT`, uses `AZURE_OPENAI_MODEL` as the provider default model, and still honors `COLONYOS_MODEL` as an explicit override.
- Added Azure endpoint normalization so pasted portal URLs containing `/openai/...` are trimmed to the correct resource root automatically.
- Updated `src/colonyos_pm/llm.py` to delegate provider selection and default model resolution to the shared client module.
- Updated `tests/conftest.py` to patch the shared client constructors and clear cache state between tests.
- Added `tests/test_client.py` to cover Azure-first configuration, OpenAI fallback, model precedence, and partial Azure config failures.
- Extended `tests/test_client.py` with regression coverage for custom Azure API version overrides and the no-credentials failure path.
- Updated `.env.example`, `START_HERE.md`, and `README.md` so setup instructions match the real shared client implementation.
- Verified the change with `./.venv/bin/python -m pytest -q` (`28 passed`).

### Files created or modified

```
.env.example
README.md
START_HERE.md
src/colonyos_pm/client.py
src/colonyos_pm/llm.py
tasks/20260316_114331_tasks_azure_shared_client.md
tasks/CHANGELOG.md
tests/conftest.py
tests/test_client.py
```
