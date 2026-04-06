# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 4)

---

## Review Complete — Principal Systems Engineer

**All 3,379 tests pass.** 14 files changed (12 instruction templates + 2 artifacts). Zero Python code changes. Zero runtime risk.

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/base.md]: Clean 5-step dependency management workflow with correct inheritance model. Manifest-first, exit code checking, lockfile commit, system-level prohibition — all the right controls.
- [src/colonyos/instructions/implement.md]: Negative "Do not add unnecessary dependencies" correctly replaced with positive, actionable guidance including specific commands and verification step.
- [src/colonyos/instructions/implement_parallel.md]: Dependency guidance correctly scoped to `{task_id}`, preventing cross-task pollution.
- [src/colonyos/instructions/fix.md, fix_standalone.md, ci_fix.md, verify_fix.md, thread_fix.md, thread_fix_pr_review.md]: All 6 fix-phase templates consistently updated with phase-appropriate positive guidance.
- [src/colonyos/instructions/auto_recovery.md]: Missing dependency recovery action correctly scoped to `ModuleNotFoundError`/`Cannot find module` — appropriately narrow.
- [src/colonyos/instructions/review.md, review_standalone.md]: Expanded checklist gives reviewers three concrete things to verify (manifest declaration, lockfile commits, no system-level packages) instead of one vague check.

SYNTHESIS:
This is a textbook fix for an LLM over-inhibition bug. The old negative phrasing ("Do not add unnecessary dependencies") was interpreted by agents as "never install anything," causing predictable `ModuleNotFoundError` failures that burned fix iterations. The new positive phrasing tells agents exactly what to do (manifest → install → verify → commit lockfile) and scopes the prohibition to what actually matters (unrelated deps, system-level packages). The layered architecture is correct: mutation phases are permissive, the review phase is the guardrail. Zero Python code changed, zero runtime risk, all 3,379 tests pass. The bonus `review_standalone.md` update prevents a consistency bug the PRD didn't even call out. Non-blocking v2 items (install observability, parallel worktree lockfile conflicts, package name hallucination) are real but not blockers. Ship it.
