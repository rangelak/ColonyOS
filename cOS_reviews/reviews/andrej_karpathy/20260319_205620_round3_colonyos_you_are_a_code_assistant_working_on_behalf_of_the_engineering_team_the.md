# Review by Andrej Karpathy (Round 3)

Here's my review as Andrej Karpathy:

---

**VERDICT: approve**

**Key findings from my perspective (LLM systems, prompt design, autonomy):**

1. **Triage agent uses free-text JSON instead of structured output** (`slack.py:643`). The model is asked to produce JSON as plain text, then you parse it with fallbacks for markdown fences. The Claude API supports tool_use-based structured output that would eliminate this entire fragile parsing path. Prompts are programs — use the strongest enforcement the API offers.

2. **`_build_slack_ts_index` rebuilds on every event** (`slack.py:161-172`). O(N) per incoming Slack event in long-running sessions. Should be cached and invalidated on queue mutations.

3. **HEAD SHA check is local-only** (`orchestrator.py:1796`). Doesn't `git fetch` before comparing, so remote pushes between fix rounds go undetected. Acknowledged TOCTOU — honest, but worth hardening.

4. **Thread-fix prompt template could use stronger delimiters** for the user's fix request. XML tag stripping + sanitization is good, but the interpolated content sits inline in the system prompt. A creative adversary could craft content that visually mimics instruction headers.

5. **`ui_factory` typed as `object | None`** — loses all type safety. A `Protocol` or `Callable` would be better.

**What's done well:**
- Triage agent scoping (haiku, no tools, $0.05 budget) — minimal blast radius on untrusted classification
- Defense-in-depth sanitization at both ingestion and point-of-use
- Verify phase with restricted tool access before Deliver
- Circuit breaker + daily budget caps + audit logging
- `auto_approve` config warnings with empty `allowed_user_ids` detection
- Schema versioning on `QueueItem` for forward compatibility
- 1249 tests passing with comprehensive coverage of new features

**Bottom line:** Ship it. The autonomy expansion is well-guarded. Migrate triage to structured output next.
