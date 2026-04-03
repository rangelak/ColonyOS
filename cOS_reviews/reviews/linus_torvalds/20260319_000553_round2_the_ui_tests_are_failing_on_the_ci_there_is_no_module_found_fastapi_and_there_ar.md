# Review by Linus Torvalds (Round 2)

Here is my review:

---

VERDICT: request-changes

FINDINGS:
- [web/src/components/ArtifactPreview.tsx]: Hand-rolled markdown renderer used with `dangerouslySetInnerHTML` — artifact content from `GET /api/artifacts/{path}` is NOT sanitized server-side, creating an XSS vector. The HTML entity escaping in `renderMarkdown` is a mitigation but not a guarantee against all payloads.
- [src/colonyos/server.py]: `POST /api/runs` returns `{"status": "launched"}` instead of `{"run_id": ...}` as FR-6 requires. The frontend navigates to `/` rather than the new run's detail page. This is a functional requirements gap.
- [src/colonyos/server.py]: `active_run_count` uses `dict[str, int]` with `{"value": 0}` — use a `threading.Semaphore(1)` instead. It's the right tool for max-1-concurrent-resource and eliminates the manual lock management.
- [src/colonyos/server.py]: No ETag/optimistic concurrency on `PUT /api/config` — concurrent browser tabs will silently clobber each other's config changes. The PRD flagged this as a recommendation from me, and I still recommend it.
- [web/src/pages/Config.tsx]: `key={i}` (array index) used for PersonaCard list items. Add/remove/reorder will corrupt React component state because keys won't match the right persona.
- [src/colonyos/web_dist/]: Committed built JS/CSS bundles to the repo. These should be built in CI and packaged, not version-controlled. They'll create merge conflicts on every frontend change.
- [web/src/components/AuthTokenPrompt.tsx]: No validation that the pasted token actually works — user can paste garbage and get silent 401 errors on every subsequent write operation. Add a test-auth call after token entry.

SYNTHESIS:
The CI fix is a two-line change that's correct and should have shipped alone. Instead, it's bundled with a 9,600+ line feature dump that builds an entire interactive web control plane. The architecture is mostly sound — bearer token auth is done right, path traversal protection is defense-in-depth, sensitive fields are blocked, rate limiting is simple and correct. But there are real bugs: the `POST /api/runs` endpoint doesn't meet its own spec (no run_id returned), the artifact preview has an XSS surface from `dangerouslySetInnerHTML` on unsanitized server content, and array-index React keys will cause state corruption during persona editing. The committed `web_dist/` bundles are a maintenance headache waiting to happen. Fix the XSS issue, the missing run_id, and the React keys. The rest is minor.
