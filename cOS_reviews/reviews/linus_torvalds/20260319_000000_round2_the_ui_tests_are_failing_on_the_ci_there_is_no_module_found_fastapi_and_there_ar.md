# Review: Fix CI Test Failures & Transform Dashboard into Interactive Control Plane
## Reviewer: Linus Torvalds — Round 2

### Summary

This is a 9,678-line, 76-file change. For what was initially filed as "CI tests are failing because fastapi isn't found," this has ballooned into a full web dashboard rewrite with write endpoints, inline editing, persona management, run launching, artifact previews, proposals/reviews pages, and frontend test infrastructure.

The CI fix itself? Two lines in `pyproject.toml`. That part is fine. The rest is a feature dump that should have been separate PRs.

### Findings

**The Good:**

The CI fix (FR-1, FR-2, FR-3) is correct and clean:
- Adding `colonyos[ui]` to `dev` extras resolves the `ModuleNotFoundError`
- The `web-build` CI job properly runs tests then build
- Pinned action SHAs in CI — good security hygiene

The server code (`server.py`) is reasonably structured:
- Auth token generation with `secrets.token_urlsafe(32)` and `secrets.compare_digest` — correct, no timing attacks
- Path traversal protection on artifacts endpoint uses both allowlist and `is_relative_to` — defense in depth, good
- Sensitive field blocking on config writes — correct
- Rate limiting on concurrent runs with a lock — simple and effective

**The Concerning:**

1. **`dangerouslySetInnerHTML` in ArtifactPreview.tsx** — You wrote a homebrew markdown renderer that outputs raw HTML and inject it with `dangerouslySetInnerHTML`. The `renderMarkdown` function escapes `&`, `<`, `>` first, which is a reasonable mitigation, but this is a hand-rolled security-critical function. If someone manages to get content past the HTML entity escaping (and these are artifact files that could contain anything), you have an XSS vector. The server-side `sanitize_untrusted_content` is NOT applied to artifact content served via `GET /api/artifacts/{path}` — it returns raw file content. This is a real gap between FR-7 and FR-10's intent.

2. **`active_run_count` as a `dict[str, int]`** — Using `{"value": 0}` as a mutable container for an integer is a well-known Python pattern, but it's needlessly clever. Use a simple `list` or, better yet, a proper `threading.Event` or `threading.Semaphore(1)`. The current approach works but reads like someone who learned closures yesterday.

3. **No ETag / optimistic concurrency on config writes** — The PRD (Open Question 1) specifically flagged this, and "Linus recommends yes." Two browser tabs can race on PUT /api/config and silently clobber each other's changes. This is a data loss bug waiting to happen on a config file.

4. **`POST /api/runs` doesn't return `run_id`** — FR-6 says "return the new `run_id` immediately." The implementation returns `{"status": "launched"}` and a comment saying the orchestrator assigns the ID asynchronously. The frontend navigates to `/` instead of the new run. This is a functional gap — the PRD explicitly says to return the run_id and navigate to it.

5. **PersonaCard uses array index as React key** — `key={i}` in Config.tsx line 212. When you add/remove/reorder personas, React will incorrectly reuse DOM nodes. This will cause state corruption in the editable persona cards. Use a stable identifier.

6. **Layout.tsx component test** — The test file exists but I notice there's no test for the AuthTokenPrompt component verifying that it actually validates the token works (it just stores whatever you paste). A user could paste garbage and get silent 401s on every write operation.

7. **`web_dist/**` in package-data** — You're committing built JS/CSS bundles (`src/colonyos/web_dist/`) to the repo. This is a 67-line minified JS blob and a CSS file. Every frontend change will create merge conflicts in these binary-ish files. The build should happen in CI, not be committed.

### Checklist Assessment

- [x] FR-1: CI installs UI deps — `colonyos[ui]` added to dev extras
- [x] FR-2: Server tests pass in CI — deps now available
- [x] FR-3: web-build CI job added — runs npm ci, test, build
- [x] FR-4: PUT /api/config — implemented with validation
- [x] FR-5: PUT /api/config/personas — implemented with validation
- [~] FR-6: POST /api/runs — implemented but does NOT return run_id as specified
- [x] FR-7: GET /api/artifacts/{path} — implemented with path traversal protection
- [x] FR-8: Bearer token auth — generated at startup, constant-time comparison
- [x] FR-9: COLONYOS_WRITE_ENABLED flag — defaults to read-only
- [x] FR-10: Input validation — schemas validated, sensitive fields blocked
- [x] FR-11: Rate limiting — max 1 concurrent run enforced
- [x] FR-12: Config page inline editing — implemented
- [x] FR-13: Persona editing — add/remove/edit implemented
- [x] FR-14: Run launcher — implemented with confirmation dialog
- [~] FR-15: Artifact previews — implemented but XSS concern with dangerouslySetInnerHTML
- [x] FR-16: Proposals page — implemented
- [x] FR-17: Reviews page — implemented
- [x] FR-18: Auth flow — token prompt on first load, stored in localStorage
- [x] FR-19: Vitest + RTL added — test infrastructure complete
- [x] FR-20: Component tests — all existing components covered
- [x] FR-21: Page-level tests — Dashboard, RunDetail, Config tested
- [x] FR-22: API client tests — all functions tested with mocked fetch
