# Review by Andrej Karpathy (Round 1)

---

## Review Complete — Andrej Karpathy Perspective

I've thoroughly reviewed the ~7800-line change across 84 files. Here's the summary:

**VERDICT: approve**

### Key Observations

**What's done well:**
- **Triage agent design** — Using haiku with zero tools and a $0.05 budget is exactly the right trade-off: cheap classification gate before expensive pipeline runs
- **Prompt injection defense-in-depth** — Three-layer sanitization (Slack link stripping → XML tag stripping → role-anchoring preamble), plus git ref validation at point of use with strict allowlist
- **HEAD SHA verification** in thread-fix pipeline prevents operating on force-pushed branches
- **Thread safety discipline** — Consistent lock/snapshot patterns, circuit breaker + daily budget + hourly rate limiting for cost control
- **324 tests pass** with thorough coverage of edge cases including malformed JSON parsing, backwards compatibility, and fix round limits

**Recommendations for follow-up:**
1. **Add few-shot examples to triage prompt** — Classification accuracy improves dramatically with 2-3 embedded examples. This matters because a false positive triggers a $5-15 pipeline run
2. **Threshold on `TriageResult.confidence`** — The field is computed but never used for gating; add a `min_triage_confidence` config parameter
3. **Default `Phase.VERIFY` to haiku** — Test suite execution doesn't need a frontier model; saves cost on every thread-fix run
4. **Watch for state file scaling** — `SlackWatchState` is accumulating many concerns (dedup, rate limiting, daily cost, circuit breaker); will eventually need a proper store

The review artifact has been saved to `cOS_reviews/reviews/andrej_karpathy/20260319_thread_fix_review_round2.md`.