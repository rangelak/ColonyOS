# PRD: Fix CI Test Failures & Transform Dashboard into Interactive Control Plane

## Introduction/Overview

The ColonyOS web dashboard (`web/`) is currently a read-only monitoring layer served by a FastAPI backend (`src/colonyos/server.py`). Two categories of problems need to be addressed:

1. **CI Failure (Blocking)**: The CI workflow (`.github/workflows/ci.yml`) installs only `.[dev]` dependencies, which excludes `fastapi` and `uvicorn` (in the `[ui]` optional extra). The 26 server tests in `tests/test_server.py` import `from colonyos.server import create_app` which triggers a top-level `from fastapi import FastAPI`, causing `ModuleNotFoundError` on every CI run.

2. **Limited UI Functionality**: The dashboard is display-only — users cannot edit personas/config, launch agent runs, or view artifact content (PRDs, reviews, CEO proposals). The feature request asks to transform it from a passive monitoring dashboard into a full interactive control plane.

Additionally, the React frontend (`web/`) has zero test infrastructure — no Vitest, no React Testing Library, no test scripts in `web/package.json`.

## Goals

1. **Fix CI immediately**: Ensure all 945+ tests pass in CI, including the 26 server tests
2. **Add write endpoints to the FastAPI server**: Config editing (PUT), run launching (POST), artifact content serving (GET)
3. **Make the dashboard interactive**: Inline config/persona editing, run launching with prompt input, artifact previews
4. **Add frontend testing infrastructure**: Vitest + React Testing Library for component tests
5. **Maintain security posture**: Auth token for write endpoints, localhost-only binding, budget cap enforcement, input validation

## User Stories

1. **As a developer**, I want the CI pipeline to pass so I can safely merge PRs without worrying about false failures from missing dependencies.

2. **As a ColonyOS user**, I want to edit my personas and configuration from the dashboard so I don't have to manually edit YAML files.

3. **As a ColonyOS user**, I want to launch agent runs from the dashboard with a prompt input so I can drive the pipeline without the CLI.

4. **As a ColonyOS user**, I want to preview PRDs, review feedback, decision rationale, and CEO proposals inline in the run detail view so I can understand what the agents did.

5. **As a ColonyOS user**, I want to see live cost accumulation and phase progress when a run is active so I can intervene if something goes wrong.

6. **As a contributor**, I want frontend tests that catch regressions so UI changes don't silently break the dashboard.

## Functional Requirements

### CI Fix
1. **FR-1**: CI must install UI dependencies so server tests execute. Add `"colonyos[ui]"` to the `dev` extras in `pyproject.toml`, or add a separate CI job that installs `.[dev,ui]`.
2. **FR-2**: All 26 server tests in `tests/test_server.py` must pass in CI on both Python 3.11 and 3.12.
3. **FR-3**: Add a `web-build` CI job that runs `npm ci && npm run build` to catch TypeScript compilation errors.

### Write API Endpoints
4. **FR-4**: `PUT /api/config` — Accept a JSON body matching the `ConfigResult` schema, validate against `ColonyConfig` dataclass constraints, and persist to `.colonyos/config.yaml` via the existing `save_config()` function (`config.py` line 279). Return the updated config.
5. **FR-5**: `PUT /api/config/personas` — Accept a JSON array of `Persona` objects, validate each, and update only the personas section of the config.
6. **FR-6**: `POST /api/runs` — Accept `{ "prompt": string }`, launch an agent run in a background task, return the new `run_id` immediately. Enforce server-side budget caps from the loaded config.
7. **FR-7**: `GET /api/artifacts/{path}` — Serve the content of PRD, task, review, and proposal files from `cOS_prds/`, `cOS_tasks/`, `cOS_reviews/`, and `cOS_proposals/` directories. Validate path stays within repo root (same pattern as SPA path traversal protection).

### Security for Write Endpoints
8. **FR-8**: Generate a cryptographic bearer token at server startup (`secrets.token_urlsafe(32)`), print it to the terminal. Require it as `Authorization: Bearer <token>` on all non-GET endpoints.
9. **FR-9**: Add a `COLONYOS_WRITE_ENABLED` flag (env var or CLI option) that must be explicitly set for write endpoints to be active. Default is read-only.
10. **FR-10**: All write endpoints must validate input against strict schemas. Config writes must not allow mutation of `_SENSITIVE_CONFIG_FIELDS` (slack, ceo_persona) via the API.
11. **FR-11**: Rate-limit the `POST /api/runs` endpoint (max 1 concurrent run, configurable).

### Frontend Interactive Features
12. **FR-12**: Config page (`web/src/pages/Config.tsx`) — Transform from display-only to inline-editable. Each section (Project, Model Settings, Budget, Phases, Personas) becomes editable in-place. Click a value → it becomes an input → blur/Enter saves via PUT.
13. **FR-13**: Persona editing — `PersonaCard.tsx` expands into an inline edit form when clicked. Support add/remove/reorder personas.
14. **FR-14**: Dashboard run launcher — Add a prominent prompt input field + "Launch Run" button at the top of `Dashboard.tsx`. On submit, POST to `/api/runs`, then navigate to the new run's detail page.
15. **FR-15**: Artifact previews — On `RunDetail.tsx`, render PRD content, review feedback text, decision rationale, and CEO proposal content inline as rendered markdown. Use the `prd_rel` and `task_rel` paths from `RunHeader` to fetch via the new artifact endpoint.
16. **FR-16**: Proposals page — New route `/proposals` listing CEO proposals from `cOS_proposals/` with content preview.
17. **FR-17**: Reviews page — New route `/reviews` listing past reviews from `cOS_reviews/` organized by persona and round.
18. **FR-18**: Auth flow — On first load, if write mode is enabled, prompt for the bearer token and store in a cookie/localStorage. Pass on all write requests.

### Frontend Testing
19. **FR-19**: Add Vitest and `@testing-library/react` to `web/package.json`. Add `"test": "vitest run"` script.
20. **FR-20**: Component tests for all existing components: `PersonaCard`, `PhaseTimeline`, `RunList`, `StatsPanel`, `Layout`.
21. **FR-21**: Page-level tests for `Dashboard`, `RunDetail`, `Config` with mocked `fetchJSON` responses.
22. **FR-22**: API client tests for all functions in `api.ts` with mocked fetch.

## Non-Goals

- **Generic React UI testing framework**: The request for a "generic way to navigate and test any React-based UI with credential management" is a separate product concern. It is explicitly out of scope for this work. The ColonyOS dashboard needs its own tests (Vitest + RTL), not a generic testing framework.
- **Multi-user authentication / OAuth**: This is a single-user localhost tool. Full auth systems (user accounts, OAuth, RBAC) are out of scope. A simple bearer token suffices.
- **WebSocket real-time streaming**: The existing 5-second polling is adequate for now. SSE may be added as a follow-up but is not in this scope.
- **Playwright E2E tests**: Out of scope for initial work. Component tests provide sufficient coverage for the current UI surface.
- **Remote/cloud deployment**: The dashboard is designed for localhost use. Network-accessible deployment is a different product decision.

## Technical Considerations

### Existing Code to Leverage
- **`save_config()` in `config.py` (line 279)**: Already implements atomic YAML write with validation. The PUT endpoint wraps this.
- **`run` in `orchestrator.py`**: The main orchestration function. The POST /api/runs endpoint invokes this in a background thread/task.
- **`_SENSITIVE_CONFIG_FIELDS` in `server.py`**: Already defines fields to redact/protect. Extend to block writes.
- **`sanitize_untrusted_content` in `sanitize.py`**: Must be applied to all user input on write endpoints and all streamed content.
- **`validate_run_id_input` in `show.py`**: Pattern for input validation on API endpoints.

### Dependency Changes
- `pyproject.toml` line 28: Add `"colonyos[ui]"` to `dev` extras so CI tests the server
- `web/package.json`: Add `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom`

### Architecture Decisions
- **Single source of truth**: Config edits persist directly to `.colonyos/config.yaml`. No shadow state. Git provides undo/audit history.
- **Background run execution**: Use `asyncio.create_task` or `threading.Thread` for agent runs launched via API. The run writes to `.colonyos/runs/{run_id}.json` and existing polling picks up changes.
- **Token auth**: Follows the Jupyter Notebook pattern — token generated at startup, printed to terminal, required for write ops.

### Persona Consensus & Tensions

**Strong agreement across all 7 personas:**
- Fix CI first (5-minute fix), then build features
- Persist config edits to YAML (single source of truth)
- Split out the "generic UI testing framework" — it's a different product
- Keep polling for now, SSE as follow-up
- Localhost binding is sufficient auth for read endpoints
- UI deps should remain optional (`[ui]` extra), but dev extras must include them

**Key tensions:**
- **Steve Jobs & Jony Ive** want the UI to become the primary interface with fastapi as a core dependency. **Seibel, Linus, and Security** want it to remain optional to avoid bloating the core CLI tool.
- **Security Engineer** strongly advocates auth token before ANY write endpoint ships and suggests agent launch should remain CLI-only until proper auth exists. **Karpathy & Jobs** prioritize shipping the interactive features with minimal friction.
- **Resolution**: Ship with bearer token auth (simple, secure) and keep UI optional. This satisfies both camps.

## Success Metrics

1. **CI green**: All tests pass on Python 3.11 and 3.12, including server tests and the new web-build job
2. **Frontend test coverage**: ≥80% of components and pages have Vitest tests
3. **Config editing works**: User can modify all non-sensitive config fields from the UI and see changes reflected in `.colonyos/config.yaml`
4. **Run launching works**: User can submit a prompt from the dashboard and see the new run appear and progress through phases
5. **Artifact previews render**: PRDs, reviews, proposals, and decisions are viewable inline in the UI
6. **No security regressions**: Write endpoints reject unauthenticated requests, sensitive fields remain protected, path traversal is blocked

## Open Questions

1. **ETag / optimistic concurrency**: Should `PUT /api/config` use an `If-Match` header based on file mtime to prevent concurrent-edit races? (Linus recommends yes)
2. **Diff preview before config save**: Should the UI show a diff of changes before persisting? (Karpathy recommends yes for persona edits since they are effectively prompts)
3. **Auto-commit config changes**: Should config edits made via the UI be auto-committed to git? (Provides audit trail but may be noisy)
4. **Run cancellation**: Should the UI support cancelling an in-progress run? (Requires a cancellation mechanism in the orchestrator)
5. **Cost projection**: Should the run launcher show estimated cost before launching? (Would require historical cost data analysis)
