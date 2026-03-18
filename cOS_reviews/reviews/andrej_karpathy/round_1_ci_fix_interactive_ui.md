# Review: Fix CI Test Failures & Transform Dashboard into Interactive Control Plane
**Reviewer**: Andrej Karpathy
**Branch**: `colonyos/the_ui_tests_are_failing_on_the_ci_there_is_no_module_found_fastapi_and_there_ar`
**PRD**: `cOS_prds/20260318_233254_prd_the_ui_tests_are_failing_on_the_ci_there_is_no_module_found_fastapi_and_there_ar.md`
**Round**: 1

## Findings

### Critical

1. **`web/package-lock.json` is gitignored but CI uses `npm ci`** — The `.gitignore` explicitly excludes `web/package-lock.json`, but the `web-build` CI job runs `npm ci` which *requires* a lockfile. This means FR-3 (web-build CI job) will fail on every CI run. Either commit the lockfile or switch to `npm install`.

2. **`fetchArtifact` double-encodes path slashes** — `api.ts:105` uses `encodeURIComponent(path)` which encodes `/` to `%2F`. A path like `cOS_prds/some_file.md` becomes `/api/artifacts/cOS_prds%2Fsome_file.md`, but the FastAPI route `GET /api/artifacts/{path:path}` expects literal slashes. The artifact preview feature (FR-15) is broken in the frontend.

### Medium

3. **No auth token prompt UI (FR-18)** — The PRD requires: "On first load, if write mode is enabled, prompt for the bearer token and store in a cookie/localStorage." The `api.ts` has `setAuthToken`/`getAuthToken` utilities but there is no UI component that prompts the user to enter the token. Write operations will silently fail with 401 for users who don't manually call `setAuthToken` from the browser console.

4. **ArtifactPreview renders raw text, not markdown (FR-15)** — The PRD says "render PRD content, review feedback text, decision rationale, and CEO proposal content inline as **rendered markdown**." The `ArtifactPreview.tsx` uses a `<pre>` tag, showing raw markdown source. No markdown renderer (e.g., `react-markdown`) is included.

5. **`POST /api/runs` does not validate budget caps server-side** — FR-6 says "Enforce server-side budget caps from the loaded config." The endpoint loads config and passes it to the orchestrator, but doesn't check if e.g. `max_total_usd` would be exceeded before launching. The orchestrator may handle this internally, but the PRD explicitly asks for server-side enforcement.

### Minor

6. **No Layout component test (FR-20)** — FR-20 requires "Component tests for all existing components: PersonaCard, PhaseTimeline, RunList, StatsPanel, **Layout**." There is no `Layout.test.tsx`.

7. **Run ID in `POST /api/runs` is synthetic, not the actual run ID** — The endpoint generates `run-{ts}-api` and returns it, but the background thread calls `run_orchestrator()` which creates its own run ID. The returned ID won't match any actual run log, so the frontend redirect to `/runs/{run_id}` will 404.

8. **CORS only enabled in dev mode** — This is actually correct for localhost-only deployment, but worth noting that the built SPA served by FastAPI won't need CORS at all. The dev-only gate is good.

## Checklist Assessment

- [x] CI fix: `pyproject.toml` adds `colonyos[ui]` to dev extras — correct
- [x] CI fix: web-build job added — correct structure, but will fail due to missing lockfile
- [x] Write endpoints implemented: PUT config, PUT personas, POST runs, GET artifacts
- [x] Bearer token auth with `secrets.token_urlsafe(32)` and `compare_digest`
- [x] `COLONYOS_WRITE_ENABLED` flag gating write endpoints
- [x] Sensitive field protection (`_SENSITIVE_CONFIG_FIELDS`)
- [x] Rate limiting on POST /api/runs (max 1 concurrent)
- [x] Path traversal protection on artifact endpoint
- [x] Frontend test infrastructure (Vitest + RTL)
- [x] Component and page tests written
- [x] API client tests with mocked fetch
- [x] Config page inline editing
- [x] Persona editing (add/remove)
- [x] Run launcher with confirmation dialog
- [x] Proposals and Reviews pages with routes and nav
- [ ] Auth token prompt UI (missing)
- [ ] Markdown rendering in artifact previews (missing)
- [ ] Layout component test (missing)
