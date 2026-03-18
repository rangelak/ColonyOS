# PRD: ColonyOS Web Dashboard

## Introduction/Overview

ColonyOS is a CLI-only autonomous software engineering pipeline. Users interact with it through terminal commands (`colonyos run`, `colonyos stats`, `colonyos show`, etc.) and all state is stored as JSON/Markdown files in `.colonyos/runs/`. While the Rich terminal UI provides excellent real-time streaming during runs, there is no persistent, browsable interface for post-hoc visibility — understanding what happened across runs, tracking cost trends, comparing review outcomes, or quickly auditing agent behavior.

This feature adds a **read-only web dashboard** launched via `colonyos ui` that surfaces existing run data, stats, and configuration in a browser. The dashboard is a **local-only** tool (localhost, no hosting) backed by a thin FastAPI API layer that wraps the existing data-layer functions in `stats.py`, `show.py`, and `config.py`. The frontend is a Vite + React SPA bundled as static assets inside the Python package.

### Persona Synthesis

**Strong consensus across all 7 personas on:**
- Start **read-only** — no CRUD, no run triggering in V1
- Use **Vite SPA** (not Next.js) — no SSR/Node runtime needed for a local tool
- Build a **thin FastAPI server** wrapping existing data-layer functions
- Deploy as **local-only** (`colonyos ui` on localhost, never `0.0.0.0`)
- Use **polling** (3-5s) for updates, not WebSockets in V1
- Persona editing stays in YAML — read-only display in the UI
- Ship as **optional dependency** (`pip install colonyos[ui]`)

**Key tension:**
- **Michael Seibel, Steve Jobs, Linus Torvalds** caution this is a distraction from the core pipeline value and should only be built if there's proven demand
- **Security Engineer** sees genuine value in an audit dashboard — "how do I know what the agent did?" is the #1 objection from serious users
- **Karpathy** and **Jony Ive** agree it's secondary but valuable for cost visibility and the "glance at a tab" workflow during long queue runs
- **Systems Engineer** notes the clean data/rendering separation in `stats.py` and `show.py` makes this cheap to build

**Resolution:** Build it, but with ruthless scope containment — read-only, local-only, optional dependency, under 200 lines of Python API code and ~1000 lines of TypeScript. If it grows beyond that, re-evaluate.

## Goals

1. **Post-hoc visibility**: Let users browse run history, drill into phase details, and understand costs without memorizing CLI flags or parsing JSON files
2. **Cross-run analysis**: Show trends, failure hotspots, and cost accumulation across all runs in a single view
3. **Audit trail**: Surface what the agent did (phases, tools, costs, review verdicts) in a persistent, browsable format
4. **Zero-friction launch**: `colonyos ui` starts a local server and opens the browser — no separate install, no Node.js requirement
5. **Zero impact on core**: The web UI is an optional dependency that does not affect `pip install colonyos` or the CLI experience for users who never use it

## User Stories

1. **As a solo developer**, I want to kick off a queue of features with `colonyos queue start` and then glance at a browser tab to see progress, phase status, and costs — instead of keeping the terminal visible.

2. **As a ColonyOS user reviewing costs**, I want to see a dashboard showing total spend across runs, per-phase cost breakdowns, and failure rates — so I can tune my budget config and identify expensive phases.

3. **As a developer auditing an autonomous run**, I want to click into a specific run and see every phase result, its duration, cost, model used, success/failure, and links to generated artifacts (PRDs, reviews, decisions) — so I can understand what the agent did and why.

4. **As a new ColonyOS user**, I want to see a visual overview of my configured personas, project settings, and phase configuration — so I can understand the current setup without reading YAML.

5. **As a developer running `colonyos auto --loop`**, I want to see the loop state — completed iterations, failed runs, aggregate cost — without scrolling through terminal history.

## Functional Requirements

### FR1: `colonyos ui` CLI Command
- Add a new Click command `ui` to `src/colonyos/cli.py`
- Starts a local FastAPI server on `127.0.0.1` (configurable port, default `7400`)
- Serves the built Vite SPA as static files
- Opens the default browser automatically (with `--no-open` flag to suppress)
- Graceful shutdown on Ctrl+C
- Prints the URL to the terminal

### FR2: FastAPI API Server
- New module `src/colonyos/server.py` (~150-200 lines)
- Endpoints:
  - `GET /api/runs` — calls `load_run_logs()` from `stats.py`, returns list of run summaries
  - `GET /api/runs/{run_id}` — calls `compute_show_result()` from `show.py`, returns full run detail
  - `GET /api/stats` — calls `compute_stats()` from `stats.py`, returns aggregate statistics
  - `GET /api/config` — calls `load_config()` from `config.py`, returns project config and personas (redacting any sensitive fields)
  - `GET /api/queue` — reads queue state from `.colonyos/queue.json` if present
  - `GET /api/health` — returns server status
- All endpoints are **read-only** (GET only)
- Input validation: `run_id` parameter validated via `validate_run_id_input()` from `show.py` to prevent path traversal
- Responses use existing dataclass `to_dict()` methods for serialization

### FR3: Vite + React Frontend
- Located in `web/` directory at repository root
- Tech: Vite, React 18, TypeScript, Tailwind CSS
- Pages:
  - **Dashboard** (`/`) — run list with status badges, cost column, duration, phase count; aggregate stats panel (total runs, total cost, success rate, cost trend)
  - **Run Detail** (`/runs/:id`) — phase timeline, per-phase cost/duration/model/status, artifacts links, review verdicts, error details
  - **Config** (`/config`) — read-only display of project info, personas (role, expertise, perspective, reviewer flag), model settings, budget limits, phase toggles
- Responsive layout (but optimized for desktop — this is a dev tool)
- Auto-refresh via polling every 5 seconds on active pages
- Built assets bundled into `src/colonyos/web_dist/` for inclusion in the Python package

### FR4: Optional Dependency Group
- Add `[project.optional-dependencies] ui = ["fastapi>=0.100", "uvicorn>=0.20"]` to `pyproject.toml`
- The `colonyos ui` command checks for FastAPI/uvicorn availability and prints a helpful install message if missing
- Core ColonyOS functionality is completely unaffected when `[ui]` extras are not installed

### FR5: Build Integration
- `web/package.json` with Vite build script
- `npm run build` outputs to `src/colonyos/web_dist/`
- Built assets are committed to the repo (no npm install required at pip-install time)
- Add `web_dist/` to `package-data` in `pyproject.toml`

## Non-Goals

- **No CRUD operations**: The UI does not create, edit, or delete personas, configs, or any state. Config changes happen via `config.yaml` or `colonyos init`.
- **No run triggering**: The UI does not start, stop, or resume runs. Use the CLI for that.
- **No hosted/cloud deployment**: V1 is local-only on `127.0.0.1`. No auth, no multi-tenancy.
- **No WebSocket streaming**: V1 uses polling. Real-time streaming of phase tool calls is a V2 feature.
- **No database**: Continue using JSON files in `.colonyos/runs/`. No SQLite, no ORM.
- **No mobile optimization**: Desktop-first, responsive but not mobile-designed.
- **No dark/light theme toggle**: Ship with one clean theme (dark, to match terminal aesthetic).

## Technical Considerations

### Existing Architecture Fit
The codebase is well-structured for this feature. Key data-layer functions are already cleanly separated from Rich rendering:

- **`src/colonyos/stats.py`**: `load_run_logs()` returns `list[RunLog]`, `compute_stats()` returns a `StatsResult` dataclass with `recent_runs`, `total_cost`, `success_rate`, `phase_breakdown`, `failure_hotspots`. These are ready to serialize as JSON.
- **`src/colonyos/show.py`**: `compute_show_result()` returns a `ShowResult` dataclass with full phase details, artifact paths, review info. Also has `validate_run_id_input()` for safe input handling.
- **`src/colonyos/config.py`**: `load_config()` returns `ColonyConfig` dataclass with `to_dict()` method. `save_config()` exists but should NOT be exposed via API.
- **`src/colonyos/models.py`**: All domain models (`RunLog`, `PhaseResult`, `QueueState`, `LoopState`) have `to_dict()`/`from_dict()` serialization.

### Dependencies
- **Python side**: FastAPI + uvicorn as optional extras. Already present in virtualenv (`uvicorn-0.42.0.dist-info` observed).
- **JS side**: Vite, React 18, TypeScript, Tailwind CSS. Build toolchain only — no Node.js required for end users since assets are pre-built and committed.

### Security
- Bind to `127.0.0.1` only — never `0.0.0.0` (the agent runs with `permission_mode="bypassPermissions"`, so exposing the API to the network would be dangerous)
- Validate `run_id` parameters to prevent path traversal (use existing `validate_run_id_input()`)
- Do not expose `save_config()` or any write operations
- Sanitize any user-generated content in run logs before returning via API (reuse `sanitize.py`)
- Do not serve the `.colonyos/` directory as static files

### File Structure
```
web/                          # Frontend source (not shipped to users)
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.js
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api.ts               # API client functions
│   ├── pages/
│   │   ├── Dashboard.tsx
│   │   ├── RunDetail.tsx
│   │   └── Config.tsx
│   ├── components/
│   │   ├── RunList.tsx
│   │   ├── StatsPanel.tsx
│   │   ├── PhaseTimeline.tsx
│   │   ├── PersonaCard.tsx
│   │   └── Layout.tsx
│   └── types.ts              # TypeScript types mirroring Python dataclasses

src/colonyos/
├── server.py                 # FastAPI app (~150-200 lines)
├── web_dist/                 # Built Vite assets (committed)
│   ├── index.html
│   └── assets/
│       ├── index-[hash].js
│       └── index-[hash].css
```

## Success Metrics

1. **Adoption**: >50% of `colonyos` users try `colonyos ui` within a month of release
2. **Usefulness**: Users keep the dashboard tab open during queue/loop runs (measured by session duration > 1 minute)
3. **Scope containment**: API server stays under 200 lines of Python; frontend under 1500 lines of TypeScript
4. **Zero regressions**: All existing tests pass; `pip install colonyos` (without `[ui]`) works identically to before
5. **Performance**: Dashboard loads in <1 second, API responses <100ms (reading local JSON files)

## Open Questions

1. **Port selection**: Should `colonyos ui` use a fixed default port (7400) or find a random available port? Fixed is simpler for bookmarking; random avoids conflicts.
2. **Asset bundling**: Should we commit built JS assets to the repo (simpler, no build step for contributors) or build them in CI (cleaner repo, but requires Node.js in CI)?
3. **Queue/Loop live state**: Should the API expose loop state (`loop_state_*.json`) and queue state (`queue.json`) as additional endpoints, or is run-level data sufficient for V1?
4. **Artifact rendering**: Should the UI render Markdown artifacts (PRDs, reviews) inline, or just link to the files on disk? Inline is nicer but requires a Markdown renderer.
5. **Future write operations**: If we eventually allow triggering runs from the UI, what auth model (even for localhost) would prevent accidental triggers? Could use a confirmation token pattern.
