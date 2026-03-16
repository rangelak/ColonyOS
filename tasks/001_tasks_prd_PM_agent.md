## Relevant Files

- `ColonyOS/.cursor/rules/create_prd.mdc` - Existing PRD contract the PM workflow must target.
- `ColonyOS/.cursor/rules/generate_tasks.mdc` - Downstream task-generation contract this workflow must hand off into.
- `ColonyOS/tasks/001_prd_PM_agent.md` - Source PRD that defines the autonomous PM workflow requirements.
- `ColonyOS/tasks/001_tasks_prd_PM_agent.md` - Implementation task list derived from the PRD.
- `ColonyOS/README.md` - Current project context and likely place to align or document the PM workflow.
- `ColonyOS/src/colonyos_pm/models.py` - Core domain models for questions, answers, risk, handoff, and workflow artifacts.
- `ColonyOS/src/colonyos_pm/llm.py` - Thin OpenAI client wrapper (`chat()` and `chat_json()`).
- `ColonyOS/src/colonyos_pm/questions.py` - LLM-backed clarifying question generation.
- `ColonyOS/src/colonyos_pm/personas.py` - Persona-selection rules per question category.
- `ColonyOS/src/colonyos_pm/answers.py` - LLM-backed autonomous answer generation with persona system prompts.
- `ColonyOS/src/colonyos_pm/prd.py` - LLM-backed PRD assembly from Q&A output.
- `ColonyOS/src/colonyos_pm/risk.py` - LLM-backed risk-tier classification and escalation policy.
- `ColonyOS/src/colonyos_pm/workflow.py` - End-to-end PM workflow orchestration with progress logging.
- `ColonyOS/src/colonyos_pm/storage.py` - Local artifact persistence and long-term memory hooks.
- `ColonyOS/src/colonyos_pm/cli.py` - CLI entrypoint with `.env` loading and `--model` override.
- `ColonyOS/tests/test_pm_workflow.py` - Unit/integration-style coverage for workflow behavior (14 tests).
- `ColonyOS/tests/conftest.py` - Auto-mocking fixture for OpenAI so tests run offline.
- `ColonyOS/pyproject.toml` - Python project and pytest configuration.
- `ColonyOS/.env.example` - Template for `OPENAI_API_KEY` and optional model override.
- `ColonyOS/requirements.txt` - Runtime dependencies: `openai`, `python-dotenv`, `pytest`.

### Notes

- Unit tests should typically be placed alongside the code files they are testing.
- Use `./.venv/bin/python -m pytest [optional/path/to/test_file.py]` to run tests.
- Tests-first policy: for coding tasks, sub-task `x.1` is reserved for writing/updating tests before implementation.
- Generated planning artifacts should remain operational outputs and should not be committed to git by default.
- v1 should stay scoped to PM artifact generation and handoff readiness, not coding-agent or orchestration automation.

## Tasks

- [x] 1.0 Define the autonomous PM workflow contract and artifact boundaries
  - [x] 1.1 Read `tasks/prd_PM_agent.md`, `README.md`, and the existing Cursor rules to extract the exact PM workflow inputs, outputs, and non-goals.
  - [x] 1.2 Define the end-to-end PM workflow stages from raw prompt intake through clarifying questions, autonomous answers, PRD generation, risk classification, and task-generation handoff.
  - [x] 1.3 Decide what data must be captured for each workflow run, including prompt, clarifying questions, persona assignments, answers, risk tier, escalation status, PRD body, and task-handoff metadata.
  - [x] 1.4 Specify which artifacts are user-visible in v1 versus internal planning trace so the system exposes enough reasoning without turning output into noise.
  - [x] 1.5 Document v1 boundaries clearly so the implementation does not drift into coding-agent, QA, review, release, or full validation-engine work.
- [x] 2.0 Build the clarifying-question generation and autonomous-answer pipeline
  - [x] 2.1 Write/update tests first for question generation and answer-pipeline behavior, then implement bounded clarifying-question generation.
  - [x] 2.2 Create a persona-selection mechanism that routes each question to the most appropriate expert voice: senior designer, senior engineer, startup CEO, or YC partner.
  - [x] 2.3 Implement autonomous answer generation for each question and store both the selected persona and the reasoning path alongside the answer.
  - [x] 2.4 Add safeguards so the generated questions and answers stay concrete, opinionated, and directly useful for downstream implementation.
  - [x] 2.5 Add test coverage for question generation, persona routing, and answer formatting, including edge cases where the initial user prompt is vague.
- [x] 3.0 Implement PRD assembly using the existing `create_prd.mdc` structure
  - [x] 3.1 Write/update tests first for PRD structure and section completeness, then map workflow outputs into the exact `create_prd.mdc` format.
  - [x] 3.2 Build a formatter that produces a readable PRD suitable for a junior developer while preserving the autonomous clarifying-question trail.
  - [x] 3.3 Decide whether the clarifying questions and autonomous answers should appear in the PRD body, attached metadata, or both in v1, and implement that decision consistently.
  - [x] 3.4 Ensure the PRD output remains deterministic enough that the later task-generation flow can reliably consume it.
  - [x] 3.5 Add tests that verify the generated PRD follows the expected structure and includes the required persona and reasoning data where intended.
- [x] 4.0 Add risk-tier classification, escalation handling, and long-term memory hooks
  - [x] 4.1 Write/update tests first for risk classification and escalation thresholds, then define and implement the v1 risk-tier taxonomy.
  - [x] 4.2 Implement risk classification based on the generated planning artifact, touched systems, ambiguity level, and sensitivity of the requested work.
  - [x] 4.3 Implement decision logic that marks whether the workflow may continue autonomously or should escalate to a human exception path.
  - [x] 4.4 Design the data contract for storing rare human interventions so future runs can reuse that guidance as long-term memory.
  - [x] 4.5 Add tests for risk-tier assignment and escalation decisions, especially around ambiguous, sensitive, or multi-system requests.
- [x] 5.0 Prepare downstream handoff and persistence foundations for generated artifacts
  - [x] 5.1 Write/update tests first for handoff payload and artifact persistence output, then define the downstream artifact package.
  - [x] 5.2 Implement file or storage output boundaries for v1 so the system can emit generated artifacts cleanly without coupling them to git commits.
  - [x] 5.3 Design a backend-friendly persistence shape that can later map to Supabase for multi-user support, stored artifacts, and long-term memory.
  - [x] 5.4 Add placeholders or interfaces for future persistence adapters so local artifact output can evolve into backend-backed storage without rewriting the workflow core.
  - [x] 5.5 Add integration-style tests or fixtures that verify a full PM workflow run produces the expected planning artifacts and a clean handoff payload.
- [x] 6.0 Integrate OpenAI as the LLM provider for all workflow stages
  - [x] 6.1 Write/update tests first with auto-mocked OpenAI fixtures (`conftest.py`) so all tests run offline without an API key.
  - [x] 6.2 Create `llm.py` thin OpenAI client wrapper with `chat()` (plain text) and `chat_json()` (structured JSON responses) helpers. Default model: `gpt-4o`, configurable via `COLONYOS_MODEL` env var.
  - [x] 6.3 Replace static question generation with real LLM call that produces 8-12 context-specific clarifying questions per prompt.
  - [x] 6.4 Replace static answer lookup with per-question LLM calls using full persona system prompts (designer/engineer/CEO/YC partner).
  - [x] 6.5 Replace static PRD string assembly with LLM-based synthesis of Q&A into a structured PRD following `create_prd.mdc`.
  - [x] 6.6 Replace keyword-matching risk assessment with LLM-based risk tier classification returning tier, score, escalation flag, and rationale.
  - [x] 6.7 Update `workflow.py` to orchestrate real LLM calls with stderr progress logging.
  - [x] 6.8 Update `cli.py` to load `.env` via `python-dotenv` and support `--model` override flag.
  - [x] 6.9 Add `openai` and `python-dotenv` to `requirements.txt`, create `.env.example`, add `.env` to `.gitignore`.
  - [x] 6.10 Expand test suite from 5 to 14 tests covering question generation, persona routing, risk escalation, full workflow output, PRD structure, tests-first policy, and artifact persistence.
