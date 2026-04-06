# Linus Torvalds — Round 1 Review
# Enable Dependency Installation in Pipeline Agents

**Branch:** `colonyos/the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn`
**PRD:** `cOS_prds/20260406_102116_prd_the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn.md`

---

## Review Checklist

### Completeness
- [x] All functional requirements from the PRD are implemented (FR-1 through FR-6 verified)
- [x] All tasks in the task file are marked complete (5/5 parent tasks, all subtasks)
- [x] No placeholder or TODO code remains

### Quality
- [x] All tests pass (3379 passed)
- [x] No linter errors introduced (no Python code changed)
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies added; no manifest or lockfile changes (this is a text-only change)
- [x] No unrelated changes included

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive database operations
- [x] Error handling: N/A (instruction templates only)

---

## Findings

### Minor Issue: `review_standalone.md` not updated
`review_standalone.md` line 21 still reads `"No unnecessary dependencies added"` — the old, weaker wording. `review.md` was correctly updated to the expanded checklist item per FR-6. The PRD only specified `review.md`, so the implementation is *technically correct per the spec*, but there's now an inconsistency between the two review templates. The standalone review is used for `colonyos review-branch` — arguably the place where dependency review matters most, since those are ad-hoc reviews of existing work.

This is a PRD gap, not an implementation bug. Note it for a follow-up.

### Observation: FR-7 (Update tests) — no test changes needed
FR-7 says "Ensure any tests that validate instruction template content are updated." The implementation verified no tests assert on the old wording, so no test changes were required. This is correct — you don't write tests for the sake of writing tests.

### The `base.md` section is well-structured
The numbered workflow (manifest first → install → check exit code → commit lockfile → no unrelated deps) is the right data structure for this problem. It's a checklist, not prose. LLM agents parse numbered lists better than paragraphs. The `**Prohibited**` block at the end is clear and unambiguous.

### Consistency across phase templates
Each phase template's replacement is appropriately scoped to its context:
- Implement phases: "when a feature requires" / "unrelated to the feature"
- Fix phases: "if resolving a finding requires" / "unrelated to the review findings"
- CI fix: "if resolving a CI failure requires" / "unrelated to the CI failure"
- Thread fix: "if the fix request requires" / "unrelated to the fix request"

This is good. Each phase tells the agent exactly what "related" means in its context.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/review_standalone.md]: Still has old wording "No unnecessary dependencies added" — inconsistent with updated review.md. PRD gap, not implementation bug. Should be a fast follow-up.
- [src/colonyos/instructions/base.md]: Dependency Management section is clean, well-structured as a numbered checklist. System-level prohibition is clear.
- [src/colonyos/instructions/implement.md]: Replacement is correct and properly scoped.
- [src/colonyos/instructions/implement_parallel.md]: Added rule correctly appended to Rules section with task_id scoping.
- [src/colonyos/instructions/fix.md, fix_standalone.md, ci_fix.md, verify_fix.md, thread_fix.md, thread_fix_pr_review.md]: All six fix-phase templates correctly updated with context-appropriate wording.
- [src/colonyos/instructions/auto_recovery.md]: Missing dependency recovery action correctly added.
- [src/colonyos/instructions/review.md]: Checklist item correctly expanded to cover manifest declarations, lockfile commits, and system-level prohibition.

SYNTHESIS:
This is a clean, boring, correct change. Which is exactly what it should be. The problem was clear (ambiguous negative guidance → agents refuse to install dependencies → pipeline failures), the diagnosis was correct (instruction templates, not infrastructure), and the fix is proportional (11 text file edits, zero code changes, zero new abstractions). The base.md section provides the canonical workflow as a numbered checklist — the right format for LLM consumption. Each phase template's replacement is scoped to its specific context rather than copy-pasting identical text everywhere. 3379 tests pass, no Python code touched, no new dependencies. The only nit is review_standalone.md being missed, but that's a gap in the PRD spec, not in the implementation. The implementation did exactly what was asked, nothing more. Ship it.
