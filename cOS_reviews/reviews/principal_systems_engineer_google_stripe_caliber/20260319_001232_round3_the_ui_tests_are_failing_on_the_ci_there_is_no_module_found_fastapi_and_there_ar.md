# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 3)

Now I have a comprehensive view of the implementation. Let me write my review.

---

## Principal Systems Engineer Review

### Analysis

**FR-1 (CI Fix)**: ✅ `colonyos[ui]` added to `dev` extras in `pyproject.toml`. This ensures CI's `pip install -e ".[dev]"` pulls in fastapi/uvicorn.

**FR-2 (Server tests pass)**: ✅ 480 lines of read-only server tests + 342 lines of write endpoint tests added.

**FR-3 (Web build CI job)**: ✅ `web-build` job added with `npm ci`, `npm run test`, and `npm run build`.

**FR-4–FR-7 (Write endpoints)**: ✅ All implemented — PUT /api/config, PUT /api/config/personas, POST /api/runs, GET /api/artifacts/{path}.

**FR-8 (Bearer token)**: ✅ `secrets.token_urlsafe(32)` at startup, `secrets.compare_digest` for constant-time comparison, printed to terminal.

**FR-9 (Write enable flag)**: ✅ `COLONYOS_WRITE_ENABLED` env var checked; 403 if not set.

**FR-10 (Sensitive field protection)**: ✅ `_SENSITIVE_CONFIG_FIELDS` blocks `slack` and `ceo_persona` mutations.

**FR-11 (Rate limiting)**: ✅ `threading.Semaphore(1)` guards concurrent runs; returns 429 if busy.

**FR-12–FR-18 (Frontend features)**: ✅ All implemented — inline config editing, persona CRUD, run launcher with confirmation dialog, artifact previews, Proposals page, Reviews page, auth token prompt.

**FR-19–FR-22 (Frontend testing)**: ✅ Vitest + RTL configured; tests for all components, pages, and API client.

### Critical Findings

**1. POST /api/runs `run_id` is fabricated and never used by the orchestrator.** The endpoint generates `run_id = f"run-{ts}-{secrets.token_hex(3)}"` and returns it to the frontend, but `_run_in_background` calls `run_orchestrator(prompt, repo_root=repo_root, config=config, quiet=True)` without passing `run_id`. The orchestrator generates its own `run_id`. The frontend receives a stale ID that will never match a real run. The `RunLauncher` component navigates to `/` (not `/runs/{run_id}`) which avoids a 404, but the API response is misleading — it promises a `run_id` it can't deliver.

**2. `dangerouslySetInnerHTML` in ArtifactPreview — adequate but brittle.** The implementation HTML-entity-escapes content first, then produces a small set of tags from markdown patterns, then runs a sanitizer that allowlists those tags. The sanitizer regex `/<\/?([a-zA-Z][a-zA-Z0-9]*)\b[^>]*\/?>/g` strips non-allowlisted tags but preserves attributes on allowed tags. This means injected `class` attributes on, e.g., `<div onmouseover=...>` would be stripped (since the entire `<div>` tag including attrs is kept only if `div` is in the allowlist — and `div` IS in the allowlist). However, the entity-escaping layer runs first, so `<div onmouseover=...>` in the raw markdown becomes `&lt;div onmouseover=...&gt;` — which won't parse as HTML. The defense-in-depth is sound. Acceptable for a localhost tool.

**3. Artifact endpoint does not sanitize returned content.** `GET /api/artifacts/{path}` reads file content and returns it raw. The PRD requires `sanitize_untrusted_content` be applied. The frontend handles this via its markdown renderer's entity-escaping, but a direct API consumer gets raw content. Low severity for localhost but technically a PRD deviation.

**4. `threading.Semaphore` for run rate-limiting has no cleanup on crash.** If the background thread raises before reaching `finally: active_run_semaphore.release()`, the semaphore is never released and no more runs can be launched until server restart. Looking at the code, the `finally` block is present and should handle exceptions. However, if the thread is killed by the OS (OOM, signal), the semaphore leaks. Low probability for localhost use.

**5. No ETag/optimistic concurrency on PUT /api/config.** The PRD's Open Question #1 flagged this. Two browser tabs editing config simultaneously will silently clobber each other (last-write-wins). Acceptable given single-user localhost, but worth noting.

**6. `AuthTokenPrompt` verification uses GET /api/config** — a read endpoint that doesn't require auth. The verification function checks `resp.status !== 401`, but GET /api/config will return 200 regardless of token validity. Token validation only happens on write endpoints. The prompt will accept any string as "valid." Low severity (the user will get a 401 on the first actual write attempt), but the UX is misleading.

### Minor Findings

- `web/package.json` pins `vitest: "^4.1.0"` — Vitest v4 doesn't exist yet as of March 2026 in most registries. This may break `npm ci` in CI. Needs verification.
- The `RunLauncher` doesn't use the returned `run_id` at all (navigates to `/`), making the entire run_id generation in POST /api/runs dead code.
- `list_reviews` uses `rglob("*.md")` which could be slow on large repos with many markdown files in `cOS_reviews/`. No pagination.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/server.py:310-340]: POST /api/runs generates a `run_id` that is never passed to the orchestrator — the returned ID is a lie. Either pass the run_id through to the orchestrator or remove it from the response and have the frontend poll for new runs.
- [web/src/components/AuthTokenPrompt.tsx:13-19]: Token verification hits GET /api/config which never requires auth — any token passes validation. Should verify against a write endpoint or a dedicated token-check endpoint.
- [src/colonyos/server.py:350-370]: GET /api/artifacts/{path} returns raw file content without applying `sanitize_untrusted_content`, deviating from PRD requirement (FR-7 + Technical Considerations).
- [web/package.json:28]: `vitest: "^4.1.0"` may not resolve — verify this version actually exists and `npm ci` succeeds in CI.

SYNTHESIS:
The implementation is comprehensive and covers the full PRD scope — CI fix, write endpoints, interactive frontend, and test infrastructure all landed in a coherent set of commits. The security posture is reasonable for a localhost tool: constant-time token comparison, path traversal defense, sensitive field blocking, input sanitization, and CORS scoping are all present. The architecture follows sensible patterns (background thread for runs, semaphore rate limiting, SPA serving from FastAPI). However, the fabricated `run_id` in POST /api/runs is a correctness bug that will confuse any consumer relying on the returned ID, and the token verification flow validates against a no-auth endpoint making the UX misleading. These should be fixed before merge. The artifact sanitization gap is a minor PRD deviation worth addressing. Overall this is solid work that needs two targeted fixes.
