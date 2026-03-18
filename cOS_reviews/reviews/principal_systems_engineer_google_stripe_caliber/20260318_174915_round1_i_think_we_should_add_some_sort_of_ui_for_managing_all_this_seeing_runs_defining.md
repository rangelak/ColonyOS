# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

Now let me write up my review. I have all the information I need.

---

Here is my review as **Principal Systems Engineer**:

## Review: ColonyOS Web Dashboard

### Completeness Assessment

All functional requirements from the PRD are implemented:
- **FR1** (`colonyos ui` CLI command): ✅ Implemented with `--port` (default 7400), `--no-open`, 127.0.0.1 binding, browser auto-open, graceful Ctrl+C
- **FR2** (FastAPI API Server): ✅ All 6 endpoints implemented (`/api/health`, `/api/runs`, `/api/runs/{id}`, `/api/stats`, `/api/config`, `/api/queue`), all GET-only
- **FR3** (Vite + React Frontend): ✅ Dashboard, RunDetail, Config pages with all specified components
- **FR4** (Optional dependency): ✅ `pyproject.toml` has `ui = ["fastapi>=0.100", "uvicorn>=0.20"]`, CLI shows helpful install message
- **FR5** (Build integration): ✅ Built assets committed to `web_dist/`, package-data updated

All 8 task groups (34 subtasks) marked complete. No TODOs or FIXMEs found. All 936 tests pass.

### Findings

VERDICT: request-changes

FINDINGS:
- [src/colonyos/server.py:205-212]: **Path traversal in SPA catch-all** — The `serve_spa` handler resolves `_WEB_DIST_DIR / full_path` without verifying the resolved path stays within `_WEB_DIST_DIR`. An attacker on localhost could craft a URL like `GET /..%2F..%2Fetc%2Fpasswd` to read arbitrary files. Need to add `file_path.resolve().is_relative_to(_WEB_DIST_DIR.resolve())` check before serving.
- [src/colonyos/server.py]: **No sanitization of user-generated content** — PRD explicitly requires "Sanitize any user-generated content in run logs before returning via API (reuse `sanitize.py`)". The server returns raw `prompt` strings and `error` messages from run logs without sanitization. While XSS risk is low for localhost, the PRD requirement is unmet.
- [src/colonyos/server.py:130-131]: **`list_runs` returns raw JSON dicts** — Unlike other endpoints that use structured serialization (`_stats_result_to_dict`, `_show_result_to_dict`), `list_runs` returns `load_run_logs()` output directly. This could leak unexpected fields if `RunLog` JSON files contain extra data not intended for the API surface.
- [web/src/pages/RunDetail.tsx:629-637]: **Stale closure in polling interval** — The `setInterval` callback captures `data?.header.status` from the render that created the effect, but `data` is also in the dependency array. This creates a new interval on every status change, which is correct, but the initial interval checks `data?.header.status` which is `null` (data hasn't loaded yet), so the first poll never fires. The interval is recreated after data loads, but there's a 5-second dead period. Consider using `useRef` for the status check or restructuring.
- [src/colonyos/server.py]: **No request timeout or rate limiting** — `compute_stats()` and `compute_show_result()` read and process all run JSON files synchronously. With hundreds of runs, the `/api/stats` endpoint could block the single uvicorn worker for seconds. Combined with 5-second polling from the frontend, this could queue up requests. Consider adding `asyncio.to_thread()` for the data-loading calls or documenting the scaling limits.
- [web/src/pages/Dashboard.tsx:569]: **Polling continues when tab is hidden** — `setInterval` fires regardless of tab visibility. For a dashboard polling every 5s, this wastes resources when the user isn't looking. Minor but worth noting for V2.
- [src/colonyos/server.py]: **Server line count at 214 lines** — PRD specified "under 200 lines of Python API code". At 214 lines it's close but technically over the scope containment target. Trivial to fix by consolidating the `_*_to_dict` helpers.

SYNTHESIS:
The implementation is well-scoped, clean, and closely follows the PRD. The architecture is sound — thin API layer wrapping existing data functions, optional dependency gating, localhost-only binding. Test coverage is solid with 315 lines of server tests covering all endpoints, read-only enforcement, and path traversal. The frontend is minimal (~600 lines of TypeScript) with proper polling, error states, and empty states. The one blocking issue is the **path traversal vulnerability in the SPA catch-all route** — while this is localhost-only, an attacker with network access (e.g., on a shared dev machine) could read arbitrary files from the server process. The `validate_run_id_input()` protection on the API endpoints is good, but the static file serving needs the same discipline. The missing `sanitize.py` integration is a gap versus the PRD spec but lower severity. Fix the path traversal, add the resolve check, and this is ready to ship.