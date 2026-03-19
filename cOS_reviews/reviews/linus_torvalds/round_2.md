# Review: Fix CI Test Failures & Transform Dashboard into Interactive Control Plane
## Reviewer: Linus Torvalds — Round 2

### Test Results
- **Python**: 968 passed in 4.46s
- **Frontend (Vitest)**: 48 passed (8 test files)
- **No TODOs/FIXMEs** in shipped code

### Checklist

| Item | Status | Notes |
|------|--------|-------|
| All PRD functional requirements implemented | PASS | FR-1 through FR-22 all addressed |
| All tasks marked complete | PASS | 8/8 task groups complete |
| No placeholder/TODO code | PASS | Clean |
| All tests pass | PASS | 968 Python + 48 frontend |
| No linter errors introduced | PASS | |
| Code follows project conventions | PASS | Consistent with existing patterns |
| No unnecessary dependencies | PASS | FastAPI/uvicorn remain optional |
| No unrelated changes | PASS | Only relevant changes |
| No secrets in code | PASS | Token generated at runtime |
| Error handling present | PASS | All endpoints handle failures |
| Path traversal protection | PASS | Defense-in-depth |

### Bug Found

**`fetchArtifact` URL encoding breaks artifact paths** (`web/src/api.ts` line 105):
```typescript
return fetchJSON<ArtifactResult>(`/artifacts/${encodeURIComponent(path)}`);
```
`encodeURIComponent("cOS_prds/test.md")` produces `cOS_prds%2Ftest.md`. The FastAPI endpoint uses `{path:path}` which expects literal slashes. This means **all artifact previews will fail** — the `ArtifactPreview` component is dead code in practice.

Fix: use `path` directly (slashes are valid in URL paths) or encode only individual segments:
```typescript
return fetchJSON<ArtifactResult>(`/artifacts/${path}`);
```

### Minor Issues (non-blocking)

1. **`launch_run` run_id mismatch** (`server.py` line 276): The endpoint generates a `run_id` and returns it, but the background thread calls `run_orchestrator()` which generates its own `run_id`. The client navigates to a run that doesn't exist yet — and when the real run appears, it has a different ID. The polling will eventually show the run, but the UX is confusing.

2. **`active_run_count = [0]` pattern** (`server.py` line 88): Works but is an ugly hack. A simple class or `threading.local()` would be clearer.

3. **No ETag/optimistic concurrency on PUT /api/config**: The PRD's open question #1 recommended this. Two browser tabs can stomp each other's config edits. Not blocking for v1 but should be addressed.

VERDICT: request-changes

FINDINGS:
- [web/src/api.ts:105]: `encodeURIComponent(path)` encodes slashes, breaking all artifact fetches since FastAPI `{path:path}` expects literal slashes. ArtifactPreview component is non-functional.
- [src/colonyos/server.py:276]: Generated `run_id` returned to client won't match the actual run_id created by `run_orchestrator()` — client navigates to a non-existent run.
- [src/colonyos/server.py:88]: `active_run_count = [0]` mutable-list-in-closure is functional but unnecessarily obscure.

SYNTHESIS:
This is a solid piece of work overall — 968 tests pass, the architecture is clean, security is handled correctly (timing-safe token comparison, defense-in-depth path traversal, sensitive field blocking, write mode gating). The CI fix is correct and minimal. The frontend code is straightforward React without over-abstraction. However, there's a real bug: `encodeURIComponent` on artifact paths encodes the forward slashes, which means the entire artifact preview feature — one of the PRD's key deliverables — is broken. That's a one-line fix but it needs to happen before this ships. The run_id mismatch on POST /api/runs is a design wart that should be noted for follow-up. Fix the `fetchArtifact` URL encoding and this is ready to merge.
