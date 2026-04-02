# Review by Linus Torvalds (Round 2)

Here's my review as Linus Torvalds:

---

**VERDICT: request-changes**

**FINDINGS:**
- **[src/colonyos/orchestrator.py]**: **Bug — on_failure hooks fire twice when a blocking hook fails.** `_hooks_at()` (line 4416) calls `hook_runner.run_on_failure()` when a blocking hook fails, then returns `False`. The caller then calls `_fail_pipeline()` which calls `run_on_failure()` *again* (line 4453). The recursion guard doesn't prevent this because it resets after the first call completes. Fix: remove the `run_on_failure()` call from `_hooks_at()` — let `_fail_pipeline()` be the single owner of failure hook dispatch.
- **[src/colonyos/orchestrator.py]**: `_run_hooks_at` return type `str | None | object` is meaningless — `object` subsumes everything. Either annotate honestly or use a typed sentinel.
- **[src/colonyos/hooks.py]**: `_SAFE_ENV_EXACT` safelist (5 entries) will silently scrub new env vars containing `_KEY`/`_TOKEN`. Consider logging scrubbed non-exact keys at DEBUG level for debuggability.
- **[src/colonyos/orchestrator.py]**: `_MAX_HOOK_INJECTION_BYTES` defined after the closure that references it — unusual ordering, move it before `_hooks_at()`.

**SYNTHESIS:**
The architecture is right. Standalone `HookRunner` testable in isolation with real subprocesses, clean parameter injection into the orchestrator, no mocking of 700-line functions. 771 tests pass. The previous round's findings — conditional hook placement, private attribute access, nonce-tagged delimiters, aggregate injection cap, env scrubbing precision — are all addressed correctly. One real bug remains: on_failure hooks execute twice on blocking hook failures because both `_hooks_at()` and `_fail_pipeline()` independently call `run_on_failure()`. It's a one-line fix. Fix that and this ships.

Review artifact written to `cOS_reviews/reviews/linus_torvalds/round_7_hooks_review.md`.