# Task Review: - [x] 3.0 Create fix instruction template

## Review Complete: Task 3.0 — Create Fix Instruction Template

### Consolidated Verdict: ✅ APPROVE (6/7 approve, 1 request-changes)

The review has been saved to `cOS_reviews/20260317_review_task3_fix_instruction_template.md`.

### Summary

The `src/colonyos/instructions/fix.md` template **fully satisfies FR-3**. All seven persona reviewers confirmed that every bullet point in the PRD requirement is addressed:

| Requirement | Status |
|---|---|
| Read review artifacts in `{reviews_dir}` | ✅ |
| Read decision artifact with "Unresolved Issues" | ✅ (inline via `{decision_text}`) |
| Understand specific findings | ✅ |
| Targeted fixes on `{branch_name}` (incremental commits) | ✅ |
| Run tests to verify no regressions | ✅ |
| Update task file | ✅ |

### Key Strengths
- **Structurally consistent** with existing templates (`implement.md`, `review.md`) — same Context/Process/Rules pattern
- **Hybrid approach** correctly implemented: decision text embedded inline for immediate agent action, `{reviews_dir}` referenced for deeper context
- **Well-scoped rules** prevent the fix agent from wandering into unrelated refactoring
- All 7 placeholder variables align exactly with `_build_fix_prompt()` call site

### One Actionable Item
The **Staff Security Engineer** flagged a **format-string injection risk**: `{decision_text}` is untrusted agent output passed through Python's `str.format()`. If it contains literal curly braces (code snippets, JSON), the call could crash. This is a bug in the **calling code** (`_build_fix_prompt()` in `orchestrator.py`), not in the template itself — it should be addressed as part of **Task 4.0** when implementing `_build_fix_prompt()`.