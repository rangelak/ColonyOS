## Relevant Files

- `src/colonyos_pm/client.py` - Shared LLM client construction for Azure OpenAI and non-Azure OpenAI across all workflow agents.
- `src/colonyos_pm/llm.py` - Thin chat helpers now delegate client creation and default-model resolution to the shared client module and call the Responses API.
- `src/colonyos_pm/cli.py` - CLI help text updated to describe provider-neutral model overrides.
- `src/colonyos_pm/workflow.py` - Workflow orchestration now overlaps independent calls and parallelizes per-question answer generation.
- `src/colonyos_pm/questions.py` - Question generation now uses a tighter Responses API token budget.
- `src/colonyos_pm/answers.py` - Answer generation now uses a tighter Responses API token budget.
- `src/colonyos_pm/risk.py` - Risk generation now uses a tighter Responses API token budget.
- `src/colonyos_pm/prd.py` - PRD assembly now uses a larger output budget so full markdown synthesis does not truncate on Azure Responses API.
- `src/colonyos_pm/storage.py` - Workflow artifacts now also write a task-style PRD into `tasks/` using the repo naming helper.
- `tests/conftest.py` - Global test fixture updated to patch the shared client constructors and clear the client cache between tests.
- `tests/test_client.py` - Coverage for Azure env selection, endpoint normalization, model precedence, and partial-config failure behavior.
- `tests/test_llm.py` - Coverage for Responses API request shape and JSON parsing from `output_text`.
- `tests/test_pm_workflow.py` - Coverage for preserving question order while answer generation runs in parallel.
- `.env.example` - Updated to document the preferred Azure configuration and optional non-Azure fallback.
- `START_HERE.md` - Updated to explain the Azure-first setup path and the shared client location.
- `README.md` - Updated to align setup instructions with the actual shared client behavior.
- `tasks/20260316_155339_prd_colonyos_next_phase_roadmap_and_agent_ready_implementation_plan.md` - Example generated PM workflow PRD now written into `tasks/` using the repo's task PRD format.
- `tasks/20260316_114331_tasks_azure_shared_client.md` - Task tracking for the shared Azure/OpenAI client refactor.
- `tasks/CHANGELOG.md` - Repository changelog entry for the shared client refactor and setup/doc updates.

### Notes

- The client is shared at the `src` package level so all workflow agents reuse the same provider-selection logic.
- Azure configuration is preferred when `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT` are present.
- `COLONYOS_MODEL` still acts as the explicit override; otherwise the client falls back to `AZURE_OPENAI_MODEL` and then the package default.

## Tasks

- [x] 1.0 Add a shared `src`-level LLM client for all workflow agents
  - [x] 1.1 Introduce a dedicated client module that constructs either an Azure OpenAI client or a non-Azure OpenAI client from environment variables.
  - [x] 1.2 Normalize Azure endpoint input so pasted portal URLs with `/openai/...` still resolve to the correct resource root.
  - [x] 1.3 Update the existing `llm.py` helpers to delegate client creation and default-model selection to the shared module.
- [x] 2.0 Add tests first for shared client provider selection and env handling
  - [x] 2.1 Add coverage for Azure-first client construction, endpoint normalization, and model resolution.
  - [x] 2.2 Add coverage for non-Azure fallback and partial Azure configuration failures.
  - [x] 2.3 Update the global test fixture to patch the shared client constructors and clear cache state between tests.
  - [x] 2.4 Add regression coverage for explicit Azure API version overrides and the no-credentials failure path.
- [x] 3.0 Align onboarding and setup docs with the shared Azure client implementation
  - [x] 3.1 Update `.env.example` to document the preferred Azure env vars and optional non-Azure fallback.
  - [x] 3.2 Update `START_HERE.md` and `README.md` to describe the real setup path and shared client location.
  - [x] 3.3 Record the completed work in this task file and `tasks/CHANGELOG.md`.
- [x] 4.0 Move Azure GPT-5 workflow calls onto the Responses API
  - [x] 4.1 Update the shared client to normalize Azure request URLs back to the Azure resource endpoint and default Azure Responses calls to `2025-03-01-preview`, with `AZURE_OPENAI_API_VERSION` still available as an explicit override.
  - [x] 4.2 Rework `src/colonyos_pm/llm.py` to call `client.responses.create(...)` and parse `response.output_text` for both text and JSON helpers.
  - [x] 4.3 Extend tests to cover Responses API client configuration, direct `llm.py` request shape, and fenced JSON parsing.
  - [x] 4.4 Add retry handling for transient Azure Responses API connection failures and log retries to stderr for debugging.
  - [x] 4.5 Tune token budgets for question, answer, and risk generation and raise a clear error when Azure truncates output at `max_output_tokens`.
- [x] 5.0 Reduce PM workflow latency for multi-call Azure runs
  - [x] 5.1 Parallelize per-question answer generation while preserving the original answer ordering in workflow artifacts.
  - [x] 5.2 Overlap risk assessment with question generation so independent work starts earlier.
  - [x] 5.3 Update the recommended Azure model from `gpt-5.4-pro` to `gpt-5.4` for the latency-sensitive PM workflow.
  - [x] 5.4 Add regression coverage that proves parallel answer generation still preserves question order.
  - [x] 5.5 Increase the PRD synthesis output budget so full markdown generation can complete after the faster answer stage.
- [x] 6.0 Make token caps optional and write generated PRDs in task-document form
  - [x] 6.1 Update the shared LLM wrapper so `max_tokens=None` omits `max_output_tokens` from the Responses API request.
  - [x] 6.2 Remove the hard token ceiling from PRD synthesis and normalize the generated markdown into the same Q&A formatting used by `tasks/*_prd_*.md`.
  - [x] 6.3 Save each generated PRD into `tasks/` with a helper-generated timestamped filename in addition to the runtime artifact directory.
  - [x] 6.4 Add regression coverage for uncapped Responses calls, task-style PRD normalization, and writing task PRDs during artifact persistence.
