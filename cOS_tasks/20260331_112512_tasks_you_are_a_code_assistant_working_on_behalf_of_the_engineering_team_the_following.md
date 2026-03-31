# Tasks: ColonyOS Web Dashboard Overhaul

## Relevant Files

- `web/src/App.tsx` - Router, add new routes for Queue and Analytics pages
- `web/src/api.ts` - API client, add daemon health/pause/resume functions
- `web/src/types.ts` - TypeScript types, add DaemonHealth type, extend QueueItem
- `web/src/pages/Dashboard.tsx` - Enrich with daemon health and queue summary
- `web/src/pages/RunDetail.tsx` - Run detail page (improved phase timeline)
- `web/src/pages/Queue.tsx` - **New** Queue page
- `web/src/pages/Analytics.tsx` - **New** Analytics page with charts
- `web/src/components/Layout.tsx` - Sidebar nav, add health indicator and new nav items
- `web/src/components/PhaseTimeline.tsx` - Replace with vertical timeline + duration bars
- `web/src/components/StatsPanel.tsx` - Enrich with more stats
- `web/src/components/DaemonHealthBanner.tsx` - **New** persistent health indicator
- `web/src/components/QueueTable.tsx` - **New** queue items table
- `web/src/components/CostChart.tsx` - **New** cost trend chart
- `web/src/components/PhaseBreakdownChart.tsx` - **New** phase breakdown charts
- `web/src/components/RunList.tsx` - Add source type badges and PR links
- `web/src/util.ts` - Add utility helpers for queue status colors, etc.
- `web/package.json` - Add recharts and lucide-react dependencies
- `web/src/__tests__/` - Frontend tests for new components
- `src/colonyos/server.py` - Add daemon pause/resume endpoints, configurable CORS
- `src/colonyos/daemon.py` - Embed uvicorn server on background thread
- `src/colonyos/config.py` - Add dashboard config options
- `src/colonyos/models.py` - Extend QueueItem if needed for missing fields
- `deploy/README.md` - Reverse proxy documentation
- `tests/test_server.py` - Tests for new API endpoints

## Tasks

- [x] 1.0 Frontend dependencies and type foundations
  depends_on: []
  - [x] 1.1 Add `recharts` and `lucide-react` to `web/package.json` and run `npm install`
  - [x] 1.2 Add `DaemonHealth` interface to `web/src/types.ts` mirroring the `/healthz` response shape (status, heartbeat_age_seconds, queue_depth, daily_spend_usd, daily_budget_remaining_usd, circuit_breaker_active, paused, total_items_today, consecutive_failures)
  - [x] 1.3 Extend `QueueItem` interface in `web/src/types.ts` with missing fields from the Python model (priority, demand_count, urgency_score, summary, notification_channel, related_item_ids, merged_sources)
  - [x] 1.4 Add `fetchDaemonHealth()`, `pauseDaemon()`, `resumeDaemon()` functions to `web/src/api.ts`
  - [x] 1.5 Add queue status color/icon utilities to `web/src/util.ts` (pending=yellow, running=blue, completed=green, failed=red)
  - [x] 1.6 Write Vitest tests for new API functions and utility helpers

- [x] 2.0 Daemon health banner component (visible on every page)
  depends_on: [1.0]
  - [x] 2.1 Write Vitest tests for `DaemonHealthBanner` component (renders healthy/degraded/stopped states, shows budget, shows circuit breaker warning)
  - [x] 2.2 Create `web/src/components/DaemonHealthBanner.tsx` — compact health indicator that polls `/healthz` every 5s, shows status badge (green/yellow/red dot), daily spend vs budget bar, circuit breaker + paused warnings
  - [x] 2.3 Integrate `DaemonHealthBanner` into `web/src/components/Layout.tsx` sidebar header (below the ColonyOS title)
  - [x] 2.4 Add pause/resume button to the health banner (gated by write_enabled, with confirmation dialog)

- [ ] 3.0 Queue page and component
  depends_on: [1.0]
  - [ ] 3.1 Write Vitest tests for `QueueTable` component (renders items, filters by status, shows empty state)
  - [ ] 3.2 Create `web/src/components/QueueTable.tsx` — table of queue items with status badge, source type pill, truncated source value, priority, demand count, cost, duration, PR link, error tooltip
  - [ ] 3.3 Create `web/src/pages/Queue.tsx` — page with status filter tabs (All/Pending/Running/Completed/Failed), polls `/api/queue` at 5s, shows aggregate cost
  - [ ] 3.4 Add `/queue` route to `web/src/App.tsx` and "Queue" nav item to `web/src/components/Layout.tsx`

- [ ] 4.0 Analytics page with charts
  depends_on: [1.0]
  - [ ] 4.1 Write Vitest tests for chart components (render with sample data, handle empty data)
  - [ ] 4.2 Create `web/src/components/CostChart.tsx` — Recharts `AreaChart` showing cost trend from `recent_trend` data
  - [ ] 4.3 Create `web/src/components/PhaseBreakdownChart.tsx` — Recharts `BarChart` for phase cost breakdown and failure hotspots
  - [ ] 4.4 Create `web/src/pages/Analytics.tsx` — page assembling charts: cost trend, phase cost breakdown, failure hotspots, model usage breakdown, duration stats, review loop summary
  - [ ] 4.5 Add `/analytics` route to `web/src/App.tsx` and "Analytics" nav item to `Layout.tsx`

- [ ] 5.0 Enhanced Dashboard and improved existing components
  depends_on: [2.0, 3.0]
  - [ ] 5.1 Write Vitest tests for enhanced Dashboard (renders health summary, queue summary, enriched run list)
  - [ ] 5.2 Update `web/src/pages/Dashboard.tsx` — add daemon health summary card at top (from `/healthz`), add queue summary section showing pending count + currently running item
  - [ ] 5.3 Update `web/src/components/RunList.tsx` — add source type badge column, add PR URL link column, improve prompt display
  - [ ] 5.4 Update `web/src/components/StatsPanel.tsx` — add failure rate card, avg cost per run card, review loop stats (first-pass approval rate)

- [ ] 6.0 Improved Phase Timeline
  depends_on: [1.0]
  - [ ] 6.1 Write Vitest tests for improved PhaseTimeline (renders vertical connector, duration bars, Lucide icons, expandable errors)
  - [ ] 6.2 Rewrite `web/src/components/PhaseTimeline.tsx` — vertical connector line between phases, proportional duration bars (width relative to longest phase), Lucide icons (CheckCircle/XCircle/SkipForward) replacing unicode, expandable error details on click
  - [ ] 6.3 Add visual grouping for review/fix loop iterations (indent or group repeated REVIEW+FIX phases with a loop indicator)

- [ ] 7.0 Backend: Daemon-embedded server and pause/resume endpoints
  depends_on: []
  - [ ] 7.1 Write pytest tests for new `/api/daemon/pause` and `/api/daemon/resume` endpoints (auth required, toggles paused state, returns updated health)
  - [ ] 7.2 Write pytest tests for configurable CORS (respects `COLONYOS_ALLOWED_ORIGINS` env var)
  - [ ] 7.3 Add `POST /api/daemon/pause` and `POST /api/daemon/resume` endpoints to `src/colonyos/server.py` — require write auth, toggle `DaemonState.paused`, save state, return updated health response
  - [ ] 7.4 Add configurable CORS support in `server.py` — read `COLONYOS_ALLOWED_ORIGINS` env var (comma-separated), add to CORS middleware allow_origins
  - [ ] 7.5 Add `--host` flag to the `colonyos serve` / `colonyos ui` CLI command (default `127.0.0.1`)
  - [ ] 7.6 Embed uvicorn server in `src/colonyos/daemon.py` — start on a daemon thread during `Daemon.start()`, set `app.state.daemon_instance = self`, add `dashboard_port` config option under `daemon` section
  - [ ] 7.7 Update `src/colonyos/config.py` — add `dashboard_port: int = 8741` and `dashboard_enabled: bool = True` to `DaemonConfig`

- [ ] 8.0 Deployment docs and build integration
  depends_on: [7.0]
  - [ ] 8.1 Update `deploy/README.md` with reverse proxy examples (Caddy 2-liner, nginx server block) for subdomain deployment
  - [ ] 8.2 Build the frontend (`cd web && npm run build`) and copy output to `src/colonyos/web_dist/`
  - [ ] 8.3 Smoke test: run `colonyos daemon` and verify the dashboard is accessible, health banner shows live data, queue page populates, analytics charts render
