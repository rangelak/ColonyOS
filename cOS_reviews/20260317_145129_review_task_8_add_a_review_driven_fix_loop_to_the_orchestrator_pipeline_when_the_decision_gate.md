# Task Review: - [x] 8.0 Final integration testing and cleanup

## Review Complete: Task 8.0 — Final Integration Testing and Cleanup

**Verdict: REQUEST-CHANGES**

The consolidated review from all 7 persona subagents has been saved to `cOS_reviews/20260317_151500_review_task_8_0_final_integration.md`.

### Key Context
- The **committed branch** passes all 137 tests ✅
- The working tree has uncommitted WIP changes (a separate in-progress refactor) that are **not** part of this review

### 3 Blocking Issues

| # | Severity | Issue |
|---|----------|-------|
| 1 | **HIGH** | `orchestrator.py:695` — Fix-iteration holistic review omits `allowed_tools`, giving the review agent write/execute access (privilege escalation). One-line fix. |
| 2 | **HIGH** | `orchestrator.py:649` — Budget guard checks `remaining < per_phase` but should check `remaining < 3 * per_phase` since a fix cycle costs 3 phases (fix + review + decision). PRD FR-6 explicitly requires this. |
| 3 | **MEDIUM** | `orchestrator.py:712-724` — Decision phase failure in fix loop is not checked. If the decision agent crashes, the verdict silently defaults to UNKNOWN and the loop burns remaining iterations. |

### Additional Recommended Fixes
- Missing "Fix phase completed (cost=$X.XX)" CLI log per FR-7
- Misleading "iterations exhausted" message when a phase failure causes loop exit
- Wrap `{decision_text}` in structural delimiters in fix.md for prompt injection defense
- Add bounds validation on `max_fix_iterations` in config parsing

### What's Working Well
- All PRD functional requirements (FR-1 through FR-9) are implemented
- Test coverage is comprehensive across the key matrix
- `max_fix_iterations=0` correctly preserves fail-fast behavior
- Iteration-tagged artifact naming provides clean audit trail
- Fix instruction template is well-structured
