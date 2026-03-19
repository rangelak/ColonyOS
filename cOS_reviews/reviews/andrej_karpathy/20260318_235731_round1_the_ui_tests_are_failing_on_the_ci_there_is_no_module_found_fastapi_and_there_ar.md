# Review by Andrej Karpathy (Round 1)

Here is my review:

---

VERDICT: request-changes

FINDINGS:
- [.gitignore]: `web/package-lock.json` is gitignored but CI `web-build` job uses `npm ci` which requires it — CI will fail (FR-3 broken)
- [web/src/api.ts:105]: `fetchArtifact` uses `encodeURIComponent(path)` which encodes `/` to `%2F`, breaking the `{path:path}` FastAPI route — artifact previews (FR-15) are broken in the frontend
- [web/src/components/ArtifactPreview.tsx]: Renders raw markdown in a `<pre>` tag instead of rendered markdown as required by FR-15
- [web/src/]: No auth token prompt component exists — FR-18 requires prompting user for bearer token on first load when write mode is enabled
- [src/colonyos/server.py:288]: `POST /api/runs` returns a synthetic `run_id` (`run-{ts}-api`) that won't match the actual run ID created by the orchestrator — frontend redirect to the new run will 404
- [src/colonyos/server.py:270]: `POST /api/runs` does not enforce budget caps before launching, only passes config to orchestrator (FR-6 requires server-side enforcement)
- [web/src/__tests__/]: Missing `Layout.test.tsx` — FR-20 explicitly requires Layout component tests

SYNTHESIS:
The implementation covers impressive ground — the CI fix is structurally correct (`colonyos[ui]` in dev extras), the write API has proper security primitives (bearer token with `compare_digest`, write-enable gating, sensitive field blocking, path traversal protection), and the frontend architecture is clean with proper separation of API client, components, and pages. The test coverage is genuinely useful, not just ceremony. However, there are two blockers that will cause CI failures and runtime bugs: (1) the gitignored `package-lock.json` means `npm ci` will fail every time, and (2) the `encodeURIComponent` on artifact paths encodes slashes, which breaks the entire artifact preview feature — this is the kind of bug where the test mocks pass but the real integration fails because the mock doesn't exercise URL parsing. The missing auth token prompt UI is a significant UX gap — without it, the write features are essentially inaccessible to users who aren't comfortable with browser dev tools. The synthetic run ID mismatch in `POST /api/runs` is another integration bug that unit tests won't catch. Fix these four issues and this ships cleanly.