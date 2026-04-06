# Review by Andrej Karpathy (Round 3)

---

## Review Complete — Andrej Karpathy, Round 3

**All 3,379 tests pass.** All 7 PRD functional requirements implemented across 12 instruction template files (11 specified + 1 bonus `review_standalone.md` consistency fix).

### Summary

This is a textbook prompt engineering fix. The implementation correctly resolves a systematic over-inhibition bug where vague negative instructions ("Do not add unnecessary dependencies") caused LLM agents to avoid installing anything at all — burning fix iterations on `ModuleNotFoundError` failures that had nothing to do with code quality.

The fix applies three correct patterns:
1. **Positive framing > negative prohibition** — each phase now has an explicit, actionable execution path for dependency installation
2. **Shared subroutine in `base.md`** — the 5-step workflow (manifest → install → check exit code → commit lockfile → scope) is inherited by all phases
3. **Enforcement at review, not mutation** — mutation phases are permissive with clear scoping; the review phase checklist is the actual guardrail (and it's now stronger than before)

Zero Python code files changed. The diff is entirely static instruction text. No runtime risk.

**Non-blocking v2 watch items:** lockfile commit compliance monitoring, package name hallucination, parallel install race conditions in worktrees.

VERDICT: **approve**

FINDINGS:
- [src/colonyos/instructions/base.md]: Clean 5-step dependency management workflow. Well-structured, inheritable by all phases.
- [src/colonyos/instructions/implement.md]: Negative framing correctly replaced with positive, scoped guidance.
- [src/colonyos/instructions/review.md]: Expanded checklist gives reviewers clear, unambiguous criteria.
- [src/colonyos/instructions/auto_recovery.md]: Missing dependency recovery action is a valuable addition.
- All 12 modified files: Consistent language, correct scoping per phase context.

SYNTHESIS:
This is a clean, minimal, and correct fix for an LLM over-inhibition bug. The old negative framing was causing agents to avoid installing anything at all — a classic prompt engineering failure where vague prohibitions get over-generalized by the model. The replacement applies the right patterns: positive framing with explicit mechanics, shared base logic with phase-specific scoping, and enforcement at the review layer rather than blanket prohibition at every mutation phase. Zero code files changed, all 3,379 tests pass, and the expanded review checklist ensures the guardrails are actually stronger than before. Ship it.
