# Review by Linus Torvalds (Round 1)

---

## Review Summary — Linus Torvalds

**968 Python tests pass. 48 frontend tests pass.** All PRD requirements are addressed. The code is clean, well-structured, and security is handled properly (timing-safe token comparison, defense-in-depth path traversal, sensitive field blocking).

**However, there's a real bug that blocks approval:**

**`web/src/api.ts:105`** — `fetchArtifact` uses `encodeURIComponent(path)` which encodes forward slashes (`/` → `%2F`). The FastAPI endpoint expects literal slashes via `{path:path}`. This means **every artifact preview in the UI is broken** — PRD previews, review content, proposals — all dead on arrival. One-line fix: remove `encodeURIComponent`.

**Minor issue:** The `POST /api/runs` endpoint returns a generated `run_id` that won't match the actual run ID created by the orchestrator, so the client navigates to a run page that won't resolve until the polling picks up the real run under a different ID.

VERDICT: request-changes

FINDINGS:
- [web/src/api.ts:105]: `encodeURIComponent(path)` encodes slashes, breaking all artifact fetches since FastAPI `{path:path}` expects literal slashes. ArtifactPreview component is non-functional.
- [src/colonyos/server.py:276]: Generated `run_id` returned to client won't match the actual run_id created by `run_orchestrator()` — client navigates to a non-existent run.
- [src/colonyos/server.py:88]: `active_run_count = [0]` mutable-list-in-closure is functional but unnecessarily obscure.

SYNTHESIS:
This is a solid piece of work overall — 968 tests pass, the architecture is clean, security is handled correctly (timing-safe token comparison, defense-in-depth path traversal, sensitive field blocking, write mode gating). The CI fix is correct and minimal. The frontend code is straightforward React without over-abstraction. However, there's a real bug: `encodeURIComponent` on artifact paths encodes the forward slashes, which means the entire artifact preview feature — one of the PRD's key deliverables — is broken. That's a one-line fix but it needs to happen before this ships. The run_id mismatch on POST /api/runs is a design wart that should be noted for follow-up. Fix the `fetchArtifact` URL encoding and this is ready to merge.
