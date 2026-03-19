# Tasks: ColonyOS Web Dashboard

## Relevant Files

### Existing Files to Modify
- `src/colonyos/cli.py` - Add `colonyos ui` command
- `src/colonyos/stats.py` - Existing data layer (`load_run_logs`, `compute_stats`) used by API; may need minor adjustments for JSON serialization
- `src/colonyos/show.py` - Existing data layer (`compute_show_result`, `validate_run_id_input`) used by API
- `src/colonyos/config.py` - Existing `load_config()` used by API; ensure `to_dict()` handles all fields
- `src/colonyos/models.py` - Existing dataclasses; verify `to_dict()` covers all fields needed by frontend
- `pyproject.toml` - Add optional `[ui]` dependency group, add `web_dist/` to package-data
- `tests/test_cli.py` - Add tests for `colonyos ui` command

### New Files to Create
- `src/colonyos/server.py` - FastAPI application with API endpoints
- `tests/test_server.py` - Tests for FastAPI API endpoints
- `web/package.json` - Frontend dependencies and build scripts
- `web/vite.config.ts` - Vite configuration (proxy to FastAPI in dev)
- `web/tsconfig.json` - TypeScript configuration
- `web/tailwind.config.js` - Tailwind CSS configuration
- `web/index.html` - SPA entry point
- `web/src/main.tsx` - React app entry point
- `web/src/App.tsx` - Router and layout
- `web/src/api.ts` - API client (fetch wrapper with types)
- `web/src/types.ts` - TypeScript types mirroring Python dataclasses
- `web/src/pages/Dashboard.tsx` - Run list + stats overview page
- `web/src/pages/RunDetail.tsx` - Single run detail page
- `web/src/pages/Config.tsx` - Read-only config/persona display page
- `web/src/components/Layout.tsx` - App shell (nav, header)
- `web/src/components/RunList.tsx` - Sortable/filterable run table
- `web/src/components/StatsPanel.tsx` - Aggregate statistics display
- `web/src/components/PhaseTimeline.tsx` - Phase progress visualization
- `web/src/components/PersonaCard.tsx` - Persona display card
- `src/colonyos/web_dist/` - Built Vite output (committed)

## Tasks

- [x] 1.0 FastAPI Server & API Endpoints
  - [x] 1.1 Write tests for API endpoints in `tests/test_server.py` — test all 6 endpoints (`/api/health`, `/api/runs`, `/api/runs/{id}`, `/api/stats`, `/api/config`, `/api/queue`), verify read-only behavior, test `run_id` validation rejects path traversal attempts, test 404 for missing runs, test responses match expected `to_dict()` output shape
  - [x] 1.2 Add `fastapi` and `uvicorn` to `pyproject.toml` as optional `[ui]` dependency group
  - [x] 1.3 Implement `src/colonyos/server.py` — FastAPI app with endpoints wrapping existing data-layer functions (`load_run_logs`, `compute_stats`, `compute_show_result`, `load_config`), static file serving for `web_dist/`, CORS middleware for dev mode, `127.0.0.1` binding only
  - [x] 1.4 Verify `to_dict()` methods on `RunLog`, `PhaseResult`, `StatsResult`, `ShowResult`, `ColonyConfig`, `QueueState` produce complete JSON-serializable output; fix any gaps

- [x] 2.0 CLI `colonyos ui` Command
  - [x] 2.1 Write tests for the `ui` command in `tests/test_cli.py` — test command registration, test graceful error when FastAPI not installed, test `--port` and `--no-open` flags
  - [x] 2.2 Implement `ui` command in `src/colonyos/cli.py` — starts uvicorn server on `127.0.0.1:{port}`, optionally opens browser via `webbrowser.open()`, handles Ctrl+C gracefully, prints URL to terminal
  - [x] 2.3 Add `--port` (default 7400) and `--no-open` options

- [x] 3.0 Frontend Project Scaffolding
  - [x] 3.1 Initialize `web/` directory with Vite + React + TypeScript template (`npm create vite@latest`)
  - [x] 3.2 Add Tailwind CSS configuration
  - [x] 3.3 Configure `vite.config.ts` with API proxy to `localhost:7400` for development and build output to `../src/colonyos/web_dist/`
  - [x] 3.4 Define TypeScript types in `web/src/types.ts` mirroring Python dataclasses (`RunLog`, `PhaseResult`, `StatsResult`, `ShowResult`, `Persona`, `ColonyConfig`, `QueueState`)
  - [x] 3.5 Implement API client in `web/src/api.ts` — typed fetch functions for each endpoint with error handling

- [x] 4.0 Dashboard Page (Run List + Stats)
  - [x] 4.1 Implement `StatsPanel` component — total runs, total cost, success rate, average duration, cost-per-run trend
  - [x] 4.2 Implement `RunList` component — sortable table with columns: status (badge), run ID (linked), prompt (truncated), cost, duration, phases completed, timestamp
  - [x] 4.3 Implement `Dashboard` page combining stats panel and run list, with 5-second polling via `setInterval` + `useEffect`
  - [x] 4.4 Implement `Layout` component — app shell with sidebar navigation (Dashboard, Config), header with ColonyOS branding

- [x] 5.0 Run Detail Page
  - [x] 5.1 Implement `PhaseTimeline` component — vertical timeline showing each phase with status icon, model used, cost, duration, and error message if failed
  - [x] 5.2 Implement `RunDetail` page — header with run ID/status/total cost, phase timeline, artifact links (PRD, tasks, reviews, decision), review verdicts summary
  - [x] 5.3 Add auto-refresh polling (5s) when run status is `RUNNING`

- [x] 6.0 Config Page
  - [x] 6.1 Implement `PersonaCard` component — displays role, expertise, perspective, reviewer badge
  - [x] 6.2 Implement `Config` page — project info section, persona grid, model settings, budget limits, phase toggles, all read-only

- [x] 7.0 Build Pipeline & Packaging
  - [x] 7.1 Add `npm run build` script that outputs to `src/colonyos/web_dist/`
  - [x] 7.2 Run initial build and commit `web_dist/` assets to the repo
  - [x] 7.3 Update `pyproject.toml` to include `web_dist/**` in `package-data`
  - [x] 7.4 Verify `pip install colonyos` (without `[ui]`) still works correctly and does not require web dependencies
  - [x] 7.5 Verify `pip install colonyos[ui]` installs FastAPI/uvicorn and `colonyos ui` launches correctly

- [x] 8.0 Integration Testing & Polish
  - [x] 8.1 End-to-end test: run `colonyos ui`, verify all 3 pages render with real run data from `.colonyos/runs/`
  - [x] 8.2 Test with empty state (no runs yet) — dashboard should show empty state message, not crash
  - [x] 8.3 Test with a running queue — verify polling updates the run list and active run detail
  - [x] 8.4 Verify all existing tests still pass (`pytest tests/`)
  - [x] 8.5 Update `colonyos doctor` to optionally check for `[ui]` dependencies when `colonyos ui` is used
