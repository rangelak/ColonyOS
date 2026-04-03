# Review by Staff Security Engineer (Round 1)

I now have a thorough understanding of the implementation. Let me write the structured review output.

---

## Security Review — Staff Security Engineer

I've reviewed the full diff on branch `colonyos/let_s_add_some_cool_ui_that_we_can_deploy_at_htt_9355d48353` (~5,835 lines added across 45 files) against the PRD.

### Completeness Assessment

All 10 functional requirements (FR-1 through FR-10) are implemented. Health banner, queue page, analytics page, improved phase timeline, enhanced dashboard, daemon-embedded server, subdomain CORS, pause/resume endpoints, navigation updates, and new deps are all present. Tests exist for backend (server, daemon, daemon_state) and frontend (components + pages). No TODO/placeholder code found.

### Security-Specific Findings

**1. Daemon auto-enables write mode with no operator opt-in.** In `daemon.py` `_start_dashboard_server()`, the line `os.environ.setdefault("COLONYOS_WRITE_ENABLED", "1")` silently enables all write endpoints (pause, resume, config editing, run launching) when the daemon starts its embedded dashboard. The operator never consents to this. This violates least-privilege — the embedded dashboard should default to read-only unless the operator explicitly configures `dashboard_write_enabled: true`.

**2. Auth token is ephemeral and logged in plaintext.** The token is generated via `secrets.token_urlsafe(32)` per-process and logged to daemon logs: `"Dashboard started on http://127.0.0.1:%d (token: %s)"`. Every daemon restart generates a new token. For subdomain deployment behind a reverse proxy, this means: (a) the token changes on every restart requiring manual re-entry, (b) the token sits in plaintext in log files accessible to anyone with log access. The PRD's Open Question #1 flagged this — it remains unresolved.

**3. No rate limiting on pause/resume endpoints.** The existing `active_run_semaphore` only protects `/api/runs` (launch). The new `POST /api/daemon/pause` and `POST /api/daemon/resume` have zero rate limiting. An attacker who obtains the bearer token (e.g., from log files per finding #2) can rapidly toggle pause/resume, creating a denial-of-service against the daemon's work loop.

**4. CORS origin validation accepts arbitrary user input without sanitization.** `COLONYOS_ALLOWED_ORIGINS` is split on commas and passed directly to `CORSMiddleware.allow_origins`. There's no validation that values are actual origin URLs (scheme + host). A misconfigured `*` or wildcard value would open the API to all origins. The CORSMiddleware itself may handle some of this, but the application layer should validate origin format.

**5. `/healthz` exposes operational intelligence without authentication.** The endpoint is read-only and unauthenticated (by design), but when exposed on a subdomain it leaks: daily spend amounts, budget remaining, queue depth, failure counts, pause state. This is an information disclosure vector — an adversary can monitor your operational cadence, detect when the daemon is paused/degraded, and time attacks accordingly.

**6. `fetchDaemonHealth()` bypasses the standard `fetchJSON` base path.** In `api.ts`, the new function fetches `/healthz` directly (not `/api/healthz`), diverging from the pattern used by all other API calls. This isn't a vulnerability per se, but it means any future middleware or auth wrapper applied at the `/api/` prefix won't cover this endpoint.

**7. Token stored in localStorage — XSS exfiltration risk.** The auth token is stored in `localStorage` (key: `colonyos_auth_token`). Any XSS vulnerability in the SPA would allow an attacker to read the token and make authenticated write calls (pause/resume/launch runs). This is the standard trade-off for SPAs, but worth noting given the tool runs arbitrary code in repos. HttpOnly cookies would be more secure but require backend changes.

**8. No audit log for pause/resume actions.** The pause/resume endpoints mutate daemon state but only emit `logger.info` messages. There's no structured audit trail (who paused, when, from which IP). For an ops tool managing code execution, this is an accountability gap.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/daemon.py]: `_start_dashboard_server()` auto-sets `COLONYOS_WRITE_ENABLED=1` — embedded dashboard should default to read-only, requiring explicit opt-in for write mode
- [src/colonyos/daemon.py]: Auth token logged in plaintext at INFO level (`"Dashboard started on ... (token: %s)"`) — demote to DEBUG or mask the token
- [src/colonyos/server.py]: Pause/resume endpoints (`/api/daemon/pause`, `/api/daemon/resume`) lack rate limiting — add a simple cooldown (e.g., 1 call per 5 seconds) to prevent rapid toggling
- [src/colonyos/server.py]: `COLONYOS_ALLOWED_ORIGINS` values not validated as proper origin URLs — reject wildcards and malformed values
- [src/colonyos/server.py]: `/healthz` exposes budget, queue depth, and failure state without authentication — acceptable for localhost, but should require auth or be opt-in when `COLONYOS_ALLOWED_ORIGINS` is set (i.e., subdomain mode)
- [web/src/api.ts]: `fetchDaemonHealth()` fetches `/healthz` outside the `/api/` prefix, bypassing any future path-level auth middleware
- [src/colonyos/server.py]: No audit logging for pause/resume actions (IP, timestamp, action) — add structured log entries for state-changing operations

SYNTHESIS:
The implementation is functionally complete and well-structured — it delivers all PRD requirements with solid test coverage and clean separation of concerns. However, it introduces a material security regression: the daemon's embedded dashboard auto-enables write mode and logs the auth token in plaintext, meaning anyone with log access can pause/resume the daemon or launch runs. The most critical fix is changing the embedded dashboard to default read-only (`COLONYOS_WRITE_ENABLED=0`) with an explicit config toggle (`dashboard.write_enabled`). The token logging should be masked or dropped to DEBUG. Rate limiting on the new write endpoints and origin validation are lower-priority but should ship before any subdomain deployment. None of these are architectural — they're targeted, small fixes that align with the existing codebase patterns.
