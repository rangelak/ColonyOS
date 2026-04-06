# Review by Andrej Karpathy (Round 1)

---

## Review Complete — Andrej Karpathy, Round 1

**3,379 tests pass.** All 28 tasks complete. All 7 PRD functional requirements implemented.

### The Core Insight

This change treats prompts as programs — which is exactly right. The root cause was a classic LLM over-inhibition bug: "Do not add unnecessary dependencies" was being interpreted as "never install anything, ever." The fix applies the correct prompt engineering pattern:

1. **Positive > Negative framing** — Replace vague prohibitions with explicit, actionable permission + scope boundaries
2. **Structured workflow** — The base.md 5-step procedure (manifest → install → check → commit → scope) gives agents a deterministic path instead of relying on judgment
3. **Scope anchoring per phase** — Each template ties dependency scope to its purpose ("unrelated to the feature" / "unrelated to the CI failure" / etc.)
4. **Enforcement at the right layer** — Mutation phases are permissive; the review phase is the guardrail

### One Minor Gap

`review_standalone.md` still has the old "No unnecessary dependencies added" without the expanded checklist. Technically out of PRD scope (FR-6 only mentions `review.md`), but worth a fast-follow to keep both review paths consistent.

---

**VERDICT: approve** — ship it.

Review artifact saved to: `cOS_reviews/reviews/andrej_karpathy/20260406_105248_round1_the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn.md`
