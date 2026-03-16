# Start Here

This repository is not the full ColonyOS platform yet. Right now it is a working v1 of the **PM workflow**: give it a rough feature request, and it generates clarifying questions, autonomous expert answers, a PRD, and a risk assessment.

If you want the practical entrypoint for this repo, use this file first. The long-form product context and vision live in `README.md`.

## What This Repo Does Today

Implemented now:

- Generates 8-12 clarifying questions from a rough prompt.
- Routes each question to a persona such as designer, engineer, CEO, or YC partner.
- Generates autonomous answers using the OpenAI API.
- Produces a PRD in markdown.
- Produces a risk assessment and handoff payload.
- Saves output artifacts to `generated/pm-workflow/<work_id>/`.

Not implemented yet:

- Full multi-agent orchestration.
- Dev, QA, review, and release agent execution.
- CI gates, merge automation, and repo policy enforcement across product repos.
- A real `AGENTS.md` contract for downstream repos.

## One-Time Local Setup

From the repo root:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Then edit `.env` and set real LLM credentials.

Preferred Azure setup:

```env
AZURE_OPENAI_API_KEY=your-azure-key-here
AZURE_OPENAI_ENDPOINT=https://your-resource-name.cognitiveservices.azure.com/
AZURE_OPENAI_MODEL=gpt-5.4-pro
# Optional override if your Azure deployment requires a different supported version.
# AZURE_OPENAI_API_VERSION=2025-03-01-preview
```

Optional non-Azure fallback:

```env
OPENAI_API_KEY=sk-your-key-here
```

If you skip credentials, the runtime will fail in `src/colonyos_pm/client.py`.

## Sanity Check

Run the tests first:

```bash
./.venv/bin/python -m pytest -v
```

These tests are mocked and do **not** require an API key.

## Main Entrypoint

The safest way to run this repo is the wrapper script:

```bash
./.venv/bin/python scripts/run_pm_workflow.py "Build an autonomous PM workflow for startup teams"
```

Optional model override:

```bash
./.venv/bin/python scripts/run_pm_workflow.py --model gpt-4o "Your feature request"
```

Notes:

- The shared client lives in `src/colonyos_pm/client.py` and is reused by all workflow agents.
- Azure GPT-5 deployments are queried through the Responses API, so the shared wrapper in `src/colonyos_pm/llm.py` uses `client.responses.create(...)` rather than `chat.completions`.
- The repo defaults Azure Responses calls to `2025-03-01-preview`, which matches the working live deployment we verified.
- If you paste a full Azure portal URL that includes `/openai/...`, the client normalizes it back to the Azure resource endpoint automatically.

Why this is the best entrypoint:

- `scripts/run_pm_workflow.py` adds `src/` to `sys.path`.
- `src/colonyos_pm/cli.py` loads `.env`, parses args, runs the workflow, and saves artifacts.
- `src/colonyos_pm/workflow.py` orchestrates question generation, persona answers, risk assessment, and PRD creation.

## What You Get Back

Each run writes files to:

```text
generated/pm-workflow/<work_id>/
```

Main outputs:

- `prd.md` - the generated PRD
- `artifact_bundle.json` - the full structured workflow output

The CLI also prints:

- `work_id`
- `risk_tier`
- `escalate_to_human`
- question and answer counts
- artifact paths

## File Map

If you are trying to understand or extend the repo, read these in order:

1. `START_HERE.md` - practical setup and runtime entrypoint.
2. `README.md` - product thesis, scope, and future-state architecture.
3. `scripts/run_pm_workflow.py` - top-level executable entrypoint.
4. `src/colonyos_pm/cli.py` - CLI and artifact save boundary.
5. `src/colonyos_pm/workflow.py` - end-to-end orchestration.
6. `src/colonyos_pm/naming.py` - deterministic helper for PRD names, task names, and changelog headings.
7. `src/colonyos_pm/prompts/` - prompt contracts for each workflow stage.
8. `tests/test_pm_workflow.py` and `tests/test_naming.py` - fastest way to see expected behavior.

## Planning File Naming

Do not hand-roll PRD or task filenames.

Generate a matched set of names with:

```bash
./.venv/bin/python -m colonyos_pm.naming bundle "Billing Reconciliation" --title "Billing Reconciliation"
```

Generate the task filename from an existing PRD path with:

```bash
./.venv/bin/python -m colonyos_pm.naming task-from-prd "tasks/20260316_111129_prd_billing_reconciliation.md"
```

## If You Are Continuing Development

The next useful work is not another README. It is finishing the operational pieces the vision doc already calls out:

1. Add deterministic repo commands such as `make setup`, `make test`, and `make verify`.
2. Add packaging or an installable CLI entrypoint so the script wrapper is no longer required.
3. Add `AGENTS.md` for repo-local operational rules.
4. Build the downstream task-generation handoff into a real next-stage flow.
5. Add CI so the tests and future checks run automatically.
