# PRD: ColonyOS Web Dashboard Overhaul

## Introduction/Overview

The ColonyOS web dashboard (`web/`) is a React SPA served by a FastAPI backend (`src/colonyos/server.py`). While the backend API already exposes rich data — daemon health (`/healthz`), queue state (`/api/queue`), run history (`/api/runs`), detailed stats (`/api/stats`), artifacts, proposals, and reviews — the frontend surfaces only a fraction of it. The Dashboard page shows 4 stat cards and a flat run table. Queue data and daemon health are completely invisible. The `PhaseTimeline` component is a plain list with unicode icons.

This feature overhauls the web dashboard to become a genuine operational command center: showing live daemon health, queue visualization, richer run/pipeline detail, and analytics charts — all deployable behind a reverse proxy at a subdomain like `colonyos.myapp.com`.

## Goals

1. **Surface existing data**: Wire up `/healthz`, `/api/queue`, and the full `/api/stats` response (cost breakdown, failure hotspots, model usage, duration stats) to the UI — all data the backend already serves but the frontend ignores.
2. **Daemon health at a glance**: A persistent, unmistakable health indicator (green/yellow/red) visible on every page showing daemon status, budget remaining, circuit breaker state, and pause status.
3. **Queue visibility**: A dedicated Queue page showing all queue items with status, priority, source type, cost, duration, and demand signals.
4. **Richer run detail**: Improve `PhaseTimeline` with a vertical connector timeline, proportional duration bars, and expandable phase details.
5. **Analytics page**: Charts for cost over time, phase cost breakdown, failure hotspots, and model usage — using data already returned by `/api/stats`.
6. **Daemon-embedded server**: The daemon auto-starts the web server so operators get the dashboard without running a separate process.
7. **Subdomain-ready deployment**: Configurable `--host`/`--port`, configurable CORS origins, and documented reverse proxy setup.
8. **Pause/resume daemon**: A single critical write operation allowing operators to pause/resume the daemon from the UI.

## User Stories

1. **As an operator**, I open the dashboard and immediately see whether the daemon is healthy, degraded, or stopped — with budget remaining and circuit breaker status — without SSH-ing into the VM.
2. **As an engineer**, I browse the queue to see what's pending, what's currently running, and what completed or failed, so I can understand the daemon's workload.
3. **As an engineer**, I click into a completed run and see a proper visual timeline of phases with proportional duration bars, cost per phase, and expandable error details.
4. **As a team lead**, I check the analytics page to see cost trends, which phases are most expensive, failure hotspot patterns, and model usage breakdown.
5. **As an operator**, I hit a "Pause" button in the dashboard to stop the daemon from picking up new work when something looks wrong, without killing the systemd service.
6. **As an operator**, I access the dashboard at `colonyos.myapp.com` through my existing Caddy/nginx reverse proxy without any special ColonyOS configuration.

## Functional Requirements

### FR-1: Daemon Health Banner
- Add a persistent health status indicator in the sidebar (`Layout.tsx`) that polls `/healthz` every 5 seconds.
- Display: status badge (green healthy / yellow degraded / red stopped), daily spend vs. budget, circuit breaker active, paused state, queue depth, consecutive failures.
- The indicator must be visible on every page.

### FR-2: Enhanced Dashboard
- Surface daemon health summary (from `/healthz`) at the top of the Dashboard page.
- Show queue summary: pending count, currently running item (if any), recent completions.
- Keep existing `StatsPanel` and `RunList` but enrich with source type badges and PR links.

### FR-3: Queue Page
- New route `/queue` with a dedicated `Queue.tsx` page.
- Table/list of all queue items showing: status (color-coded), source type, source value (truncated), priority, demand count, added time, cost, duration, PR URL, error.
- Filter/tab by status: All, Pending, Running, Completed, Failed.
- Poll `/api/queue` at 5-second intervals.

### FR-4: Analytics Page
- New route `/analytics` with a dedicated `Analytics.tsx` page.
- Charts (using Recharts):
  - Cost trend over time (from `recent_trend` in StatsResult)
  - Phase cost breakdown (bar chart from `cost_breakdown`)
  - Failure hotspots (bar chart from `failure_hotspots`)
  - Model usage breakdown (from `model_usage`)
  - Duration stats (from `duration_stats`)
- Review loop stats summary (from `review_loop`).

### FR-5: Improved Phase Timeline
- Replace flat list with a vertical timeline with connector lines between phases.
- Add proportional duration bars (width relative to longest phase).
- Replace unicode icons with Lucide icons.
- Expandable error details on failed phases.
- Visual grouping of review/fix loop iterations.

### FR-6: Daemon-Embedded Web Server
- When the daemon starts, it also starts the FastAPI/uvicorn server on a background thread.
- Use `app.state.daemon_instance = self` (the hook already exists in `server.py` line 127) to provide live in-memory health data.
- Add `dashboard.port` and `dashboard.enabled` config options under the `daemon` config section.
- Keep `colonyos serve` / `colonyos ui` as a standalone fallback for read-only historical browsing.

### FR-7: Subdomain-Ready Deployment
- Add `--host` flag to the serve command (default: `127.0.0.1`).
- Add `COLONYOS_ALLOWED_ORIGINS` env var for configurable CORS origins.
- Update `deploy/README.md` with example Caddy and nginx reverse proxy configurations.
- Ensure Vite build produces correct relative asset paths for arbitrary base paths.

### FR-8: Pause/Resume Daemon Endpoint
- New `POST /api/daemon/pause` endpoint (requires write auth) that toggles `DaemonState.paused`.
- New `POST /api/daemon/resume` endpoint (requires write auth).
- UI button in the daemon health banner to pause/resume with confirmation.

### FR-9: Navigation Updates
- Add "Queue" and "Analytics" to the sidebar navigation in `Layout.tsx`.
- Highlight the daemon health indicator in the sidebar header area.

### FR-10: New Frontend Dependencies
- Add `recharts` for chart components.
- Add `lucide-react` for icon components.
- No component libraries (no shadcn, no MUI, no Radix).

## Non-Goals

- **Live log streaming / SSE / WebSocket**: Polling at 5s is sufficient for v1. Streaming requires plumbing the daemon's `_CombinedUI` / `encode_monitor_event` machinery through to the web server — that's a separate project.
- **TLS termination**: Users handle HTTPS via reverse proxy. We do not build TLS into the Python process.
- **Queue reordering from UI**: The daemon has its own priority logic with demand signals; manual reordering creates conflicts between two priority systems.
- **Run cancellation from UI**: The `request_cancel` mechanism exists but needs careful coordination. Defer to v2.
- **Multi-tenant / role-based access**: v1 has a single bearer token for write ops. RBAC is a future consideration.
- **Mobile-responsive design**: This is an ops dashboard viewed on desktop monitors.

## Technical Considerations

### Existing Code to Modify
- **`web/src/App.tsx`**: Add routes for `/queue` and `/analytics`.
- **`web/src/components/Layout.tsx`**: Add nav items, add daemon health indicator in sidebar.
- **`web/src/pages/Dashboard.tsx`**: Add health summary and queue summary sections.
- **`web/src/components/PhaseTimeline.tsx`**: Replace with vertical timeline, duration bars, Lucide icons.
- **`web/src/components/StatsPanel.tsx`**: Enrich with more stats from the full `StatsResult`.
- **`web/src/api.ts`**: Add `fetchDaemonHealth()`, `pauseDaemon()`, `resumeDaemon()` functions.
- **`web/src/types.ts`**: Add `DaemonHealth` type, extend `QueueItem` with missing fields.
- **`src/colonyos/server.py`**: Add `/api/daemon/pause` and `/api/daemon/resume` endpoints, configurable CORS.
- **`src/colonyos/daemon.py`**: Embed uvicorn server startup on a background thread.
- **`src/colonyos/config.py`**: Add `dashboard.port` and `dashboard.enabled` config options.
- **`web/package.json`**: Add `recharts` and `lucide-react` dependencies.

### New Files to Create
- **`web/src/pages/Queue.tsx`**: Queue page component.
- **`web/src/pages/Analytics.tsx`**: Analytics page with charts.
- **`web/src/components/DaemonHealthBanner.tsx`**: Persistent health indicator component.
- **`web/src/components/QueueTable.tsx`**: Queue items table/list component.
- **`web/src/components/CostChart.tsx`**: Cost trend chart component.
- **`web/src/components/PhaseBreakdownChart.tsx`**: Phase cost/failure chart component.

### Architecture Decisions
- **Polling over WebSocket**: All persona subagents agreed (7/7). 5-second polling is already in use and sufficient for a dashboard that 1-3 people view.
- **Daemon embeds server**: 5/7 personas agreed. The `app.state.daemon_instance` hook already exists. Keep `colonyos serve` as standalone fallback.
- **Reverse proxy for HTTPS**: 7/7 unanimous. Document, don't implement.
- **Minimal dependencies**: 7/7 agreed. Recharts + Lucide only. No component libraries.

### Key Risks
- **Security (Staff Security Engineer)**: Exposing beyond localhost requires configurable CORS, persistent auth token (not ephemeral), and rate limiting on all endpoints. Streaming live output could leak secrets — completed-only results are safer.
- **Daemon coupling (Ive, Linus)**: Embedding the server in the daemon must not introduce new crash modes. Uvicorn on a daemon thread with proper exception isolation.
- **Test coverage**: All new API endpoints need tests. Frontend components need Vitest tests matching existing patterns in `web/src/__tests__/`.

## Persona Synthesis

### Areas of Agreement (7/7)
- The existing UI criminally underuses the API surface — `/api/queue`, `/healthz`, cost breakdown, failure hotspots are all invisible.
- Polling at 5s is fine for v1. No WebSocket/SSE needed.
- HTTPS/TLS is the user's responsibility via reverse proxy.
- Minimal dependencies: Recharts + Lucide only. No component libraries.
- Target audience is the engineering team operating ColonyOS. Do not design for managers.
- Completed phase results only — no live log streaming in v1.

### Areas of Agreement (5-6/7)
- Daemon should embed the web server (5/7 — Security and Ive dissented, preferring process separation for isolation).
- Pause/resume daemon is the only write operation worth adding (6/7 — Jobs said "no new writes yet").

### Key Tensions
- **Priority order**: Systems Engineer and Security prioritized subdomain-readiness early (infrastructure-first). YC Partner and Karpathy prioritized daemon health visibility (value-first). **Resolution**: Daemon health first since it's pure frontend work with zero risk; subdomain-readiness is a small backend task that can run in parallel.
- **Daemon embedding**: Security Engineer argued for process separation to limit blast radius. Majority argued the `app.state.daemon_instance` hook already assumes embedding. **Resolution**: Embed but with proper exception isolation — uvicorn errors must not crash the daemon.
- **"Cool" vs. functional**: Jobs and Ive argued for 20% on polish (typography, timeline connectors, proportional bars — "making data legible"). YC Partner and Linus argued for near-zero cosmetics. **Resolution**: Invest in data legibility (duration bars, timeline connectors) but not gratuitous animations.

## Success Metrics

1. **Data coverage**: 100% of API endpoints surfaced in the UI (currently ~50%).
2. **Time to health check**: Operator can assess daemon health in < 3 seconds from page load (vs. SSH + curl today).
3. **Queue visibility**: All queue items visible with status filtering, zero CLI required.
4. **Page load**: Dashboard loads in < 2 seconds on a standard connection.
5. **Test coverage**: All new API endpoints have test coverage. All new React components have Vitest tests.

## Open Questions

1. **Persistent auth token**: The current bearer token is generated ephemerally per server process. For subdomain deployment, should we store it in `.colonyos/` so it survives restarts? (Security Engineer flagged this.)
2. **Daemon health polling cadence**: Should the health banner poll faster than 5s (e.g., 2s) since it's lightweight?
3. **Queue archive browsing**: The queue archives terminal items to `.colonyos/archive/queue_history.jsonl`. Should the UI expose archived items, or only the active queue?
4. **Build pipeline**: Should we add a `npm run build` step to the Python package build so `web_dist/` is always fresh, or keep the current manual build + commit approach?
