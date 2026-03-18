# Review by Staff Security Engineer (Round 1)

Now I have a comprehensive view of the implementation. Let me write up my security review.

---

## Staff Security Engineer Review

### Checklist Assessment

**Completeness:**
- [x] All functional requirements from the PRD are implemented (FR1–FR5 all present)
- [x] All tasks in the task file are marked complete (1.0–8.0 all checked)
- [x] No placeholder or TODO code remains

**Quality:**
- [x] All tests pass (17/17 in test_server.py)
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies added (only fastapi/uvicorn as optional)
- [x] No unrelated changes included

**Safety:**
- [x] No secrets or credentials in committed code
- [x] No destructive database operations
- [x] Error handling is present for failure cases

### Security-Specific Findings

**1. SPA catch-all route — potential arbitrary file read (server.py:206-212)**

The `serve_spa` handler does `file_path = _WEB_DIST_DIR / full_path` and serves it via `FileResponse` if it exists. While Starlette normalizes URL paths (stripping `..`), there is no explicit guard verifying the resolved path stays within `_WEB_DIST_DIR`. A defense-in-depth approach would add: `if not file_path.resolve().is_relative_to(_WEB_DIST_DIR.resolve()): return FileResponse(...)`. This is medium-severity since Starlette's router typically catches traversal, but it's a missing defense-in-depth layer.

**2. No sanitization of run log content (server.py, PRD FR2)**

The PRD explicitly requires: *"Sanitize any user-generated content in run logs before returning via API (reuse `sanitize.py`)"*. The implementation does not import or call any sanitization. Run logs contain user prompts and potentially agent-generated error messages that could include malicious content. If rendered as HTML without escaping in the React frontend, this becomes an XSS vector. React auto-escapes by default in JSX, mitigating this somewhat, but server-side sanitization was explicitly required and is missing.

**3. Config endpoint lacks sensitive field redaction (server.py:174-177)**

The PRD states the config endpoint should *"return project config and personas (redacting any sensitive fields)"*. The `_config_to_dict()` function serializes the entire config without any redaction. If a user has custom fields or environment variable references in their config, they could be exposed. Low-severity given localhost binding, but the PRD requirement is unmet.

**4. CORS allows all headers (server.py:125)**

`allow_headers=["*"]` is overly permissive. Since the API only serves GET requests and all communication is same-origin in production (SPA served by same FastAPI server), the CORS middleware is only needed for the Vite dev server scenario. The `allow_headers` should be restricted to the minimum set needed (e.g., `["Content-Type", "Accept"]`).

**5. Error messages may leak internal paths (server.py:144-145, 163)**

`raise HTTPException(status_code=400, detail=str(exc))` and similar patterns forward raw Python exception messages to the client. These could contain internal filesystem paths (e.g., from `FileNotFoundError`), leaking information about the server's directory structure. For localhost this is low-risk but still poor practice.

**6. Positive security controls noted:**
- Server hardcoded to `127.0.0.1` — verified in both CLI and uvicorn call ✅
- Only GET endpoints registered; tests verify POST/PUT/DELETE return 405 ✅
- `validate_run_id_input()` rejects `/`, `\`, and `..` — tested with path traversal cases ✅
- `save_config()` is not imported or exposed ✅
- OpenAPI docs (`/docs`, `/redoc`) disabled ✅
- FastAPI/uvicorn are optional dependencies — core pipeline unaffected ✅
- Proper `try/except` with error handling on queue JSON parsing ✅

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/server.py:206-212]: SPA catch-all `serve_spa` handler does not verify the resolved file path stays within `_WEB_DIST_DIR`. Add `file_path.resolve().is_relative_to(_WEB_DIST_DIR.resolve())` check as defense-in-depth against path traversal.
- [src/colonyos/server.py]: PRD requires sanitization of user-generated content in run log responses (reuse `sanitize.py`) but no sanitization is performed. While React auto-escapes JSX, this server-side requirement is explicitly unmet.
- [src/colonyos/server.py:174-177]: Config endpoint does not redact sensitive fields as required by PRD FR2. Should filter out or mask any fields that could contain secrets.
- [src/colonyos/server.py:125]: CORS `allow_headers=["*"]` is overly permissive; restrict to `["Content-Type", "Accept"]`.
- [src/colonyos/server.py:144,163]: Exception messages forwarded raw to HTTP responses may leak internal filesystem paths.

SYNTHESIS:
From a security posture standpoint, this implementation gets the most critical control right — binding exclusively to `127.0.0.1` and enforcing read-only access. The `run_id` path traversal validation and absence of any write endpoints are solid. However, there are several defense-in-depth gaps that should be addressed before merging: the SPA catch-all route lacks an explicit path containment check, output sanitization required by the PRD is entirely missing, and the config endpoint doesn't redact sensitive fields as specified. None of these are exploitable in a catastrophic way given the localhost constraint, but for a tool that runs with `bypassPermissions` in people's repositories, every layer of defense matters. The SPA path traversal guard and the missing sanitization are the two changes I'd want to see before approving — the rest are improvements that could land in a fast-follow.