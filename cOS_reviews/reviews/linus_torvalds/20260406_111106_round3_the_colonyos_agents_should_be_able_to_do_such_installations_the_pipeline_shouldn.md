# Review by Linus Torvalds (Round 3)

All 3,379 tests pass. Now let me write the review.

---

I've reviewed the full diff (14 files, +186/-9 lines), the PRD, the task list, and verified all 3,379 tests pass. Here's my review as Linus Torvalds:

---

Right. This is the kind of change I actually like reviewing — small, obvious, and boring. Let me be clear about what this is: it's a text-only change to instruction templates. Zero code. Zero logic. The diff is 11 markdown files getting their dependency wording updated. There is nothing clever here, and that's exactly what makes it correct.

The core insight is right: telling an LLM "Do not add unnecessary dependencies" is like telling a junior developer "don't break anything" — it paralyzes them. Replacing that with "here's exactly when and how to install things" is the obvious fix. The data structure here is the 5-step workflow in `base.md`, and every phase template now references that same mental model. Good.

**What's done well:**

1. The `base.md` section is clean — manifest-first, install, check exit code, commit lockfile, scope to task. Five steps, no bullshit.
2. Each phase template got exactly one line replaced — no unnecessary rewriting of surrounding context. Minimal diff, easy to review.
3. `review.md` and `review_standalone.md` are the enforcement layer — they now explicitly check for manifest declarations, lockfile commits, and system-level package prohibition. This is the right architecture: permissive mutation, strict review.
4. `auto_recovery.md` got the missing-dependency recovery action. Good — `ModuleNotFoundError` is the exact failure pattern they're targeting.
5. `review_standalone.md` was updated too, even though the PRD didn't mention it. That's attention to detail, not scope creep.

**What I'd nitpick:**

The `verify_fix.md` wording is slightly inconsistent with the others: "Do not add new dependencies unless the fix genuinely requires one" vs the more structured "add it to the manifest file and run the install command" pattern in `fix.md`. It's not wrong — `verify_fix` is a narrower phase — but the inconsistency in phrasing across templates is the kind of thing that will drift further over time. Not blocking.

FR-7 says "Update tests" but there were no test changes. That's actually fine here — I checked, and no tests assert on the old wording. The task file correctly documented that they verified this (task 1.1). The PRD was being cautious; the implementation correctly determined no test changes were needed.

No secrets, no code changes, no dependency additions, no orchestrator changes. Clean.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/verify_fix.md]: Wording pattern ("Do not add new dependencies unless...") is slightly inconsistent with the structured "add to manifest and run install" pattern used in fix.md, fix_standalone.md, thread_fix.md. Non-blocking — verify_fix is intentionally narrower in scope.
- [tests/]: No test changes despite FR-7 requesting them. Correct decision — no tests asserted on old wording. Task 1.1 explicitly verified this.

SYNTHESIS:
This is a textbook prompt-engineering fix: 11 markdown files, zero code, minimal diff surface. The old negative framing ("do not add unnecessary dependencies") was causing LLM agents to avoid all dependency installation, burning fix iterations on `ModuleNotFoundError`. The replacement is a clean 5-step workflow in `base.md` inherited by all phases, with phase-specific scoping that correctly anchors permission to each phase's objective. The review phase is the enforcement layer, not blanket prohibition. All 3,379 tests pass, no regressions, no scope creep. Ship it.
