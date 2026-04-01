# Review — Linus Torvalds (Round 1)

**Branch**: `colonyos/the_learn_phase_is_failing_every_time_right_now_31f87a1c36`
**PRD**: `cOS_prds/20260401_130207_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## Checklist

### Completeness
- [x] All functional requirements from the PRD are implemented (FR-1 through FR-5)
- [x] All tasks in the task file are marked complete
- [x] No placeholder or TODO code remains

### Quality
- [x] All tests pass (18/18 learn-related, full suite verified)
- [x] No linter errors introduced
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies added
- [x] No unrelated changes included

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive database operations without safeguards
- [x] Error handling is present for failure cases

## Assessment

The diff is 12 lines of instruction changes in `learn.md` and 25 lines of regression tests. That's it. This is exactly the right size for a bug fix.

The root cause was trivially stupid: the prompt said "read all review artifacts recursively" without telling the agent which tools it had. The agent guessed `Bash` and `Agent`, both forbidden, and crashed every single time. The fix says "here are your three tools, here's a copy-pasteable Glob pattern, don't touch anything else or you'll crash." Simple, obvious, correct.

The negative constraint ("will cause a fatal error") is good prompt engineering — it gives the model a reason to comply rather than just a prohibition. The concrete `{reviews_dir}/**/*.md` Glob pattern is better than any abstract description could be.

The tests are minimal and targeted. They check that the prompt mentions the allowed tools, contains a negative constraint, and includes a concrete Glob pattern. They don't over-specify — they catch the regression that matters without being brittle.

No changes to `orchestrator.py`, `agent.py`, or `learnings.py`. No expanded privileges. No scope creep. The allowed_tools enforcement at the CLI level remains untouched as a hard backstop.

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/learn.md]: 12 lines added — tool list, Glob pattern, negative constraint. All necessary, nothing superfluous.
- [tests/test_orchestrator.py]: 25 lines of regression tests. Appropriately scoped as static prompt checks.
- [cOS_tasks/...]: All tasks marked complete. No TODOs remaining.
- No unrelated changes, no secrets, no dependency additions.

SYNTHESIS:
This is the simplest possible fix for a 100% failure rate. The problem was a prompt that told the agent what to do but not how to do it within its tool constraints. The fix adds 12 lines to the prompt template and 25 lines of regression tests. No architectural changes, no privilege escalation, no scope creep. The data structures (allowed_tools, learnings format) are unchanged. Ship it.
