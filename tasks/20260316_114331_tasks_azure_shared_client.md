## Relevant Files

- `src/colonyos_pm/client.py` - Shared LLM client construction for Azure OpenAI and non-Azure OpenAI across all workflow agents.
- `src/colonyos_pm/llm.py` - Thin chat helpers now delegate client creation and default-model resolution to the shared client module and call the Responses API.
- `src/colonyos_pm/cli.py` - CLI help text updated to describe provider-neutral model overrides.
- `src/colonyos_pm/questions.py` - Question generation now uses a tighter Responses API token budget.
- `src/colonyos_pm/answers.py` - Answer generation now uses a tighter Responses API token budget.
- `src/colonyos_pm/risk.py` - Risk generation now uses a tighter Responses API token budget.
- `tests/conftest.py` - Global test fixture updated to patch the shared client constructors and clear the client cache between tests.
- `tests/test_client.py` - Coverage for Azure env selection, endpoint normalization, model precedence, and partial-config failure behavior.
- `tests/test_llm.py` - Coverage for Responses API request shape and JSON parsing from `output_text`.
- `.env.example` - Updated to document the preferred Azure configuration and optional non-Azure fallback.
- `START_HERE.md` - Updated to explain the Azure-first setup path and the shared client location.
- `README.md` - Updated to align setup instructions with the actual shared client behavior.
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
