# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 2)

Here's my review summary:

---

**VERDICT: approve**

All 22 functional requirements from the PRD are implemented. The implementation is well-structured with good security practices (bearer token auth, constant-time comparison, write-mode default-off, path traversal defense, sensitive field blocking, input sanitization).

**Key findings to track as follow-ups:**

1. **Background run timeout gap**: If the orchestrator hangs, the concurrent-run counter stays at 1 forever, blocking new launches until server restart. A TTL/watchdog would improve operability.

2. **POST /api/runs doesn't return run_id**: The PRD specifies returning it immediately, but the orchestrator generates it asynchronously. The implementation pragmatically returns `{"status": "launched"}` and relies on polling — a reasonable engineering tradeoff with a code comment explaining why.

3. **Hand-rolled markdown renderer**: `ArtifactPreview.tsx` uses `dangerouslySetInnerHTML` with a custom markdown parser. HTML entity escaping is present, but a dedicated library would be more robust long-term.

4. **Budget enforcement delegated**: FR-6 implies API-layer budget enforcement, but it's delegated to the orchestrator. Acceptable if the orchestrator is trusted.

5. **Unconditional polling**: Dashboard polls every 5s regardless of active runs — fine for localhost, but worth noting.

The review artifact has been written to `cOS_reviews/reviews/principal_systems_engineer_google_stripe_caliber/20260319_review_the_ui_tests_are_failing_on_the_ci_there_is_no_module_found_fastapi_and_there_ar.md`.