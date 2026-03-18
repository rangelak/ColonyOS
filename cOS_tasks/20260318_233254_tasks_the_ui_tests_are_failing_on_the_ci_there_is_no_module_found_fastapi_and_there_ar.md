# Tasks: Fix CI Test Failures & Transform Dashboard into Interactive Control Plane

## Relevant Files

### Backend (Python)
- `pyproject.toml` - Add UI deps to dev extras; the CI fix point (line 28)
- `.github/workflows/ci.yml` - CI workflow; may need web-build job (line 38)
- `src/colonyos/server.py` - FastAPI server; add write endpoints (PUT config, POST runs, GET artifacts)
- `src/colonyos/config.py` - `save_config()` at line 279; `load_config()` for round-trip
- `src/colonyos/models.py` - `Persona`, `ColonyConfig`, `RunLog` dataclasses
- `src/colonyos/orchestrator.py` - `run()` function invoked by POST /api/runs
- `src/colonyos/sanitize.py` - Input sanitization for write endpoints
- `src/colonyos/show.py` - `validate_run_id_input()` pattern for input validation
- `src/colonyos/cli.py` - `ui` command (line 2108); may need `--write` flag
- `tests/test_server.py` - Existing 26 server tests; extend with write endpoint tests

### Frontend (React/TypeScript)
- `web/package.json` - Add test dependencies (vitest, RTL)
- `web/src/api.ts` - Add POST/PUT API client functions
- `web/src/types.ts` - Add types for write request/response shapes
- `web/src/App.tsx` - Add new routes (/proposals, /reviews)
- `web/src/pages/Config.tsx` - Transform to inline-editable
- `web/src/pages/Dashboard.tsx` - Add run launcher prompt input
- `web/src/pages/RunDetail.tsx` - Add artifact content previews
- `web/src/pages/Proposals.tsx` - New page for CEO proposal listing (to create)
- `web/src/pages/Reviews.tsx` - New page for past reviews listing (to create)
- `web/src/components/PersonaCard.tsx` - Transform to editable card
- `web/src/components/Layout.tsx` - Add nav links for new pages
- `web/src/components/RunLauncher.tsx` - New run launcher component (to create)
- `web/src/components/ArtifactPreview.tsx` - New markdown content viewer (to create)
- `web/src/components/InlineEdit.tsx` - New reusable inline edit component (to create)

### Test Files (to create)
- `web/src/__tests__/api.test.ts` - API client tests
- `web/src/__tests__/pages/Dashboard.test.tsx` - Dashboard page tests
- `web/src/__tests__/pages/Config.test.tsx` - Config page tests
- `web/src/__tests__/pages/RunDetail.test.tsx` - RunDetail page tests
- `web/src/__tests__/components/PersonaCard.test.tsx` - PersonaCard component tests
- `web/src/__tests__/components/RunList.test.tsx` - RunList component tests
- `web/src/__tests__/components/StatsPanel.test.tsx` - StatsPanel component tests
- `web/src/__tests__/components/PhaseTimeline.test.tsx` - PhaseTimeline component tests
- `tests/test_server_write.py` - Backend tests for new write endpoints (to create)

## Tasks

- [x] 1.0 Fix CI: Ensure server tests run in CI and add web build job
  - [x] 1.1 Add `"colonyos[ui]"` to the `dev` optional-dependencies in `pyproject.toml` (line 28) so CI's `pip install -e ".[dev]"` includes fastapi/uvicorn/starlette
  - [x] 1.2 Verify all 26 server tests in `tests/test_server.py` pass locally with the updated deps
  - [x] 1.3 Add a `web-build` job to `.github/workflows/ci.yml` that runs `npm ci && npm run build` in the `web/` directory to catch TypeScript errors
  - [x] 1.4 Push the CI fix and verify the workflow passes on GitHub

- [x] 2.0 Add frontend testing infrastructure
  - [x] 2.1 Add `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`, and `jsdom` as devDependencies in `web/package.json`
  - [x] 2.2 Create `web/vitest.config.ts` with jsdom environment and setup file
  - [x] 2.3 Create `web/src/setupTests.ts` importing `@testing-library/jest-dom`
  - [x] 2.4 Add `"test": "vitest run"` and `"test:watch": "vitest"` scripts to `web/package.json`
  - [x] 2.5 Write component tests for existing components: `PersonaCard`, `PhaseTimeline`, `RunList`, `StatsPanel` — verify they render correctly with fixture data derived from `types.ts`
  - [x] 2.6 Write page tests for `Dashboard`, `RunDetail`, `Config` — mock `fetchJSON` and verify correct rendering
  - [x] 2.7 Write API client tests for all 6 functions in `api.ts` — mock `fetch` and verify URL construction, error handling
  - [x] 2.8 Add `npm run test` step to the `web-build` CI job from task 1.3

- [x] 3.0 Add write API endpoints with security (backend)
  - [x] 3.1 Write tests for write endpoints in new `tests/test_server_write.py`: test PUT /api/config, PUT /api/config/personas, POST /api/runs, GET /api/artifacts/{path}; test auth token required; test sensitive field rejection; test invalid input rejection; test rate limiting
  - [x] 3.2 Implement bearer token auth middleware in `server.py`: generate `secrets.token_urlsafe(32)` at startup, print to terminal, require on non-GET endpoints. Add `COLONYOS_WRITE_ENABLED` env var check — if not set, write endpoints return 403.
  - [x] 3.3 Implement `PUT /api/config` endpoint: accept JSON body, validate against `ColonyConfig` constraints, reject mutations to `_SENSITIVE_CONFIG_FIELDS`, call `save_config()`, return updated config
  - [x] 3.4 Implement `PUT /api/config/personas` endpoint: accept JSON array of Persona objects, validate each (role, expertise, perspective required), update config personas section only
  - [x] 3.5 Implement `POST /api/runs` endpoint: accept `{"prompt": str}`, validate prompt non-empty, enforce budget caps, launch run via `run_orchestrator()` in background thread, return `{"run_id": str}` immediately. Add max-1-concurrent-run guard.
  - [x] 3.6 Implement `GET /api/artifacts/{path}` endpoint: serve content from `cOS_prds/`, `cOS_tasks/`, `cOS_reviews/`, `cOS_proposals/` directories. Validate path stays within allowed directories (defense-in-depth path traversal check). Apply `sanitize_untrusted_content` if content contains user-generated text.
  - [x] 3.7 Implement `GET /api/proposals` endpoint: list all files in `cOS_proposals/` with filenames and modification times
  - [x] 3.8 Implement `GET /api/reviews` endpoint: list all files in `cOS_reviews/` organized by subdirectory (decisions/, reviews/<persona>/)
  - [x] 3.9 Update CORS middleware to allow POST/PUT methods when `COLONYOS_WRITE_ENABLED` is set and `COLONYOS_DEV` is set
  - [x] 3.10 Add `--write` flag to the `ui` CLI command in `cli.py` that sets `COLONYOS_WRITE_ENABLED`

- [x] 4.0 Add API client functions for write operations (frontend)
  - [x] 4.1 Write tests for new API client functions in `web/src/__tests__/api.test.ts`
  - [x] 4.2 Add `updateConfig(config: Partial<ConfigResult>)` function to `api.ts` — PUT to `/api/config` with auth header
  - [x] 4.3 Add `updatePersonas(personas: Persona[])` function — PUT to `/api/config/personas`
  - [x] 4.4 Add `launchRun(prompt: string)` function — POST to `/api/runs`
  - [x] 4.5 Add `fetchArtifact(path: string)` function — GET `/api/artifacts/{path}`, returns text content
  - [x] 4.6 Add `fetchProposals()` and `fetchReviews()` functions — GET `/api/proposals` and `/api/reviews`
  - [x] 4.7 Add auth token storage utility: store token in localStorage, attach as Bearer header on write requests. Add a simple token prompt component.

- [x] 5.0 Transform Config page to inline-editable
  - [x] 5.1 Write tests for editable Config page: verify edit mode toggle, form submission, API call, optimistic update, error handling
  - [x] 5.2 Create `web/src/components/InlineEdit.tsx` — reusable inline edit component (click to edit, blur/Enter to save, Escape to cancel)
  - [x] 5.3 Update Config.tsx Project section: make name, description, stack fields inline-editable using InlineEdit
  - [x] 5.4 Update Config.tsx Model Settings section: make default model a dropdown (opus/sonnet/haiku), phase models editable
  - [x] 5.5 Update Config.tsx Budget section: make per_phase, per_run, max_total_usd, max_duration_hours inline-editable with number inputs
  - [x] 5.6 Update Config.tsx Phases section: make phase pills clickable toggles that call PUT /api/config
  - [x] 5.7 Transform PersonaCard.tsx into editable card: click to expand edit form with role/expertise/perspective textareas and reviewer toggle. Add "Add Persona" and "Remove" buttons. Call PUT /api/config/personas on save.

- [x] 6.0 Add run launcher to Dashboard
  - [x] 6.1 Write tests for RunLauncher component: verify prompt input, submit button, API call, navigation to new run
  - [x] 6.2 Create `web/src/components/RunLauncher.tsx` — prompt textarea + "Launch Run" button. On submit, call `launchRun()`, show loading state, then navigate to `/runs/{run_id}`
  - [x] 6.3 Integrate RunLauncher at the top of Dashboard.tsx above the stats panel
  - [x] 6.4 Add confirmation dialog before launching (shows prompt text, warns about cost)

- [x] 7.0 Add artifact previews and content pages
  - [x] 7.1 Write tests for ArtifactPreview component and new pages
  - [x] 7.2 Create `web/src/components/ArtifactPreview.tsx` — fetches artifact content via `fetchArtifact()`, renders markdown as formatted text (or use a lightweight markdown renderer like `react-markdown`)
  - [x] 7.3 Update RunDetail.tsx: add artifact preview sections for PRD (`prd_rel`), tasks (`task_rel`), review feedback, and decision rationale using ArtifactPreview
  - [x] 7.4 Create `web/src/pages/Proposals.tsx` — lists CEO proposals from `fetchProposals()`, click to expand content preview via ArtifactPreview
  - [x] 7.5 Create `web/src/pages/Reviews.tsx` — lists past reviews from `fetchReviews()`, organized by persona/round, click to expand
  - [x] 7.6 Add routes for `/proposals` and `/reviews` in `App.tsx`
  - [x] 7.7 Add "Proposals" and "Reviews" nav links to `Layout.tsx`

- [x] 8.0 Integration testing and polish
  - [x] 8.1 Run full Python test suite (`pytest --tb=short -q`) and verify all tests pass including new write endpoint tests
  - [x] 8.2 Run full frontend test suite (`npm run test` in `web/`) and verify all tests pass
  - [x] 8.3 Manual E2E test: start server with `colonyos ui --write`, verify config editing round-trips correctly to YAML, verify run launch creates a run, verify artifact previews render
  - [x] 8.4 Verify the React build succeeds (`npm run build` in `web/`) and the SPA is served correctly by FastAPI
  - [x] 8.5 Update `TestReadOnly` class in `test_server.py` to account for new write endpoints when `COLONYOS_WRITE_ENABLED` is set (and verify they still return 405 when it's not set)
