# Review by Linus Torvalds (Round 4)

Good. I have everything I need. Here's my review:

---

## Review — Linus Torvalds

Alright, let me look at what we actually have here.

**14 files changed, 186 insertions, 9 deletions. Zero Python code files. All 3,379 tests pass.**

This is a documentation-only change to instruction templates. There is no runtime code to review, no data structures to critique, no control flow to untangle. The entire diff is static markdown text that gets loaded by `_load_instruction()` and stuffed into LLM prompts.

### Completeness

Every single functional requirement from the PRD is implemented:

| Requirement | Status |
|---|---|
| FR-1: `base.md` Dependency Management section | ✅ Clean 5-step workflow |
| FR-2: `implement.md` positive guidance | ✅ Replaced line 52 |
| FR-3: `implement_parallel.md` new rule | ✅ Added to Rules |
| FR-4: All 6 fix-phase templates | ✅ All replaced |
| FR-5: `auto_recovery.md` install as recovery | ✅ Added |
| FR-6: `review.md` expanded checklist | ✅ Expanded |
| FR-7: Tests updated/verified | ✅ 3,379 pass, no content assertions broke |

All 28 subtasks in the task file are marked complete.

### What I actually think

This is the right kind of fix. The problem was that vague negative instructions ("don't add unnecessary dependencies") were causing LLM agents to avoid installing *anything*, which is the predictable outcome when you give an LLM an ambiguous prohibition. The fix replaces each prohibition with a clear, actionable positive instruction. That's the obvious, simple thing to do, and they did it without over-engineering it.

The `base.md` section is well-structured — manifest first, install, check exit code, commit lockfile, scope constraint. Five steps, all obvious, no cleverness. Each phase template then adds phase-specific scoping ("unrelated to the feature", "unrelated to the CI failure", "unrelated to the fix request") which is correct — the scope varies by phase.

The bonus `review_standalone.md` change is sensible consistency work — if you update the checklist in `review.md`, you'd better update it in `review_standalone.md` too, or your standalone review pipeline has weaker guardrails than your main pipeline. Good catch.

No code changed. No new abstractions. No new config surfaces. No runtime risk. This is about as low-risk as a change can be while still being useful.

### Nits

None worth blocking on. If I were being pedantic: the `base.md` section lists Rust (`cargo build`) and Go (`go mod tidy`) install commands, but this is a Python/Node project. That's fine — it's defensive documentation for polyglot repos, and it costs nothing.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/base.md]: Clean 5-step dependency management workflow. Correct structure — manifest first, install, verify, commit lockfile, scope. No unnecessary abstractions.
- [src/colonyos/instructions/implement.md]: Negative framing replaced with clear positive instruction. Scoped correctly to the feature.
- [src/colonyos/instructions/review.md]: Expanded checklist gives reviewers three concrete things to check instead of one vague item. This is the enforcement point, and it's now stronger.
- [src/colonyos/instructions/review_standalone.md]: Consistency fix — mirrors `review.md` checklist expansion. Not in the PRD but correct to include.
- [src/colonyos/instructions/auto_recovery.md]: Missing dependency recovery is a valuable addition — agents can now self-heal `ModuleNotFoundError` without burning a full fix iteration.
- [src/colonyos/instructions/ci_fix.md]: CI-specific scoping ("unrelated to the CI failure") is correct and distinct from the general fix scoping.
- [All 6 fix-phase templates]: Consistent replacement pattern. Each uses phase-appropriate scoping language.

SYNTHESIS:
This is a clean, minimal, correct fix for an LLM over-inhibition bug. The old instructions were ambiguous prohibitions that caused agents to avoid installing anything at all. The new instructions are clear, actionable, and scoped per-phase. Zero code files changed, all 3,379 tests pass, no new dependencies, no new abstractions, no runtime risk. The `base.md` section establishes a shared workflow, each phase template adds appropriate scoping, and the review checklist is the enforcement guardrail — which is exactly where enforcement belongs. Ship it.
