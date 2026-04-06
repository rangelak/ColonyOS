# Review by Linus Torvalds (Round 2)

---

## Review Complete — Linus Torvalds, Round 2

**VERDICT: approve**

The round-1 finding (`review_standalone.md` consistency) was fixed in commit `0308f7d`. No remaining issues.

This is the right fix at the right layer. The problem was ambiguous instructions causing LLM over-inhibition — agents that *could* install dependencies but were told "don't add unnecessary dependencies" and interpreted that as "never install anything." The fix:

- **Shared base section** (`base.md`) with a 5-step deterministic workflow: manifest → install → check exit code → commit lockfile → scope constraint
- **Phase-specific scoping** in each of the 11 modified templates, tailored to context (implement vs fix vs CI fix vs recovery)
- **Review phase as guardrail** — both `review.md` and `review_standalone.md` now enforce manifest declarations, lockfile commits, and no system-level packages
- **Zero code changes** — 14 files, all markdown instruction templates

No cleverness, no new abstractions, no premature generalization. Just clear instructions replacing ambiguous ones. Ship it.

**Artifacts saved:**
- Review: `cOS_reviews/reviews/linus_torvalds/20260406_110000_round2_the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn.md`
- Decision: `cOS_reviews/decisions/20260406_110000_decision_the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn.md`

VERDICT: approve

FINDINGS:
- (none)

SYNTHESIS:
This is a textbook example of the right fix at the right layer. The problem was never about capability — agents already had Bash access. The problem was ambiguous instructions causing LLM over-inhibition. The fix replaces vague negative guidance ("don't add unnecessary dependencies") with explicit positive guidance ("here's exactly when and how to install dependencies, and here's the one thing you must never do"). The data structure is correct: shared base section for the workflow, phase-specific scoping in each template, review phase as the enforcement guardrail. No code changes, no new abstractions, no cleverness. Just clear instructions. Ship it.
