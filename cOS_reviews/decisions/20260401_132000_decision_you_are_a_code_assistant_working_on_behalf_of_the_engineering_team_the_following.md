# Decision Gate: Fix Learn Phase — Tool Constraint Mismatch

**Branch**: `colonyos/the_learn_phase_is_failing_every_time_right_now_31f87a1c36`
**PRD**: `cOS_prds/20260401_130207_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Date**: 2026-04-01

---

```
VERDICT: GO
```

### Rationale
All four persona reviewers (Andrej Karpathy, Linus Torvalds, Principal Systems Engineer, Staff Security Engineer) approved unanimously across both review rounds with zero CRITICAL or HIGH findings. The fix is surgical and well-scoped: 12 lines added to `learn.md` (explicit tool list, concrete Glob pattern, negative constraint) and 25 lines of regression tests in `test_orchestrator.py` — exactly matching PRD requirements FR-1 through FR-5. No changes were made to enforcement code, allowed_tools, budget, or downstream consumers, consistent with the PRD's non-goals and the unanimous persona consensus.

### Unresolved Issues
_(None blocking)_

### Recommendation
Merge as-is. The non-blocking advisories (loose substring assertions in tests, extending tool-constraint patterns to other phases) are valid follow-ups but correctly out of scope for this bug fix. File a follow-up ticket for PRD Open Question #2 (adding tool-constraint sections to all phase instruction templates).

### Review Tally

| Persona | Round 1 | Round 2 | Blocking Findings |
|---|---|---|---|
| Andrej Karpathy | APPROVE | APPROVE | None |
| Linus Torvalds | APPROVE | APPROVE | None |
| Principal Systems Engineer | APPROVE | APPROVE | None |
| Staff Security Engineer | APPROVE | APPROVE | None |

### Changes Reviewed

| File | Change Summary |
|---|---|
| `src/colonyos/instructions/learn.md` | +12 lines: Available Tools section, concrete Glob pattern, negative constraint |
| `tests/test_orchestrator.py` | +25 lines: Two regression tests for tool-constraint language and Glob pattern |
| `cOS_prds/...` | PRD artifact (new file) |
| `cOS_tasks/...` | Task tracking artifact (new file) |
