# Review — Linus Torvalds, Round 2

**Branch:** `colonyos/the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn`
**PRD:** `cOS_prds/20260406_102116_prd_the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn.md`

## Checklist

### Completeness
- [x] All functional requirements from the PRD are implemented (FR-1 through FR-7)
- [x] All 28 tasks in the task file are marked complete
- [x] No placeholder or TODO code remains

### Quality
- [x] All 3,379 tests pass
- [x] No linter errors introduced
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies added; no new dependencies at all — this is a pure instruction-template change
- [x] No unrelated changes included

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive database operations
- [x] Error handling: N/A — no code changes, only markdown instruction templates

## Analysis

14 files changed, 186 insertions, 9 deletions. All in markdown instruction templates plus the PRD/task artifacts. Zero code changes. Zero test changes.

**FR-1 (base.md):** The "Dependency Management" section is clean, structured, and actionable. Five numbered steps, each doing exactly one thing. The system-level prohibition is explicit and unambiguous. This is the right data structure for this problem — a shared base section that all phases inherit.

**FR-2 (implement.md):** Old vague prohibition replaced with a concrete workflow. Good.

**FR-3 (implement_parallel.md):** One-line addition scoped to `{task_id}`. Correct — parallel workers shouldn't install each other's dependencies.

**FR-4 (fix phases):** All six fix-phase templates updated. `ci_fix.md` correctly has slightly different wording (mentions "missing modules" and "run the install command" before "add to manifest") because the CI failure case is often about *existing* deps not being installed, not new ones. The others correctly focus on the "new dependency needed for the fix" case. Good differentiation.

**FR-5 (auto_recovery.md):** Three lines, anchored to specific error signatures (`ModuleNotFoundError`, `Cannot find module`). Not a blanket "install stuff when confused." Correct.

**FR-6 (review.md + review_standalone.md):** Both review templates now have the expanded checklist: manifest declarations, lockfile commits, no system-level packages. The round-1 consistency fix for `review_standalone.md` was the right call.

**FR-7 (tests):** No tests asserted on the old instruction template wording. Verified via grep. Nothing to update. Correct.

## Previous Finding Status

The round-1 finding (`review_standalone.md` consistency) was fixed in commit `0308f7d`. Verified in the diff — both `review.md` and `review_standalone.md` now have identical dependency checklist wording.

VERDICT: approve

FINDINGS:
- (none)

SYNTHESIS:
This is a textbook example of the right fix at the right layer. The problem was never about capability — agents already had Bash access. The problem was ambiguous instructions causing LLM over-inhibition. The fix replaces vague negative guidance ("don't add unnecessary dependencies") with explicit positive guidance ("here's exactly when and how to install dependencies, and here's the one thing you must never do"). The data structure is correct: shared base section for the workflow, phase-specific scoping in each template, review phase as the enforcement guardrail. No code changes, no new abstractions, no cleverness. Just clear instructions. Ship it.
