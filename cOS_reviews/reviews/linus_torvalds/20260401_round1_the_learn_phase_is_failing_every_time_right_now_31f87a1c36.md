# Review: Fix Learn Phase Tool Constraint Mismatch
**Reviewer**: Linus Torvalds
**Round**: 1
**Branch**: `colonyos/the_learn_phase_is_failing_every_time_right_now_31f87a1c36`

## Assessment

This is exactly the kind of fix I like to see: a clear root cause, a minimal surgical change, and a regression test that would catch it if someone breaks it again. Four files changed, two of which are the PRD/tasks artifacts (not code), leaving exactly two functional changes — `learn.md` and `test_orchestrator.py`.

### What's Right

1. **Root cause correctly identified**: The agent was told "read recursively" without being told which tools it has. It naturally reached for Bash and Agent, both disallowed. The fix tells it exactly what it can use, with concrete patterns. Simple.

2. **The fix is in the right place**: They didn't touch `agent.py`, didn't expand `allowed_tools`, didn't add retry logic or error handling. They fixed the instructions. The prompt was wrong, so they fixed the prompt. This is the correct level of abstraction.

3. **The learn.md change is tight**: 12 lines added. An "Available Tools" section with the three tools, a concrete Glob pattern example, and a negative constraint. No fluff, no over-engineering.

4. **Test is specific and useful**: `test_learn_prompt_contains_tool_constraint_language` checks for both positive (Read, Glob, Grep mentioned) and negative constraints (Bash warning). `test_learn_prompt_contains_glob_pattern_for_reviews` ensures the concrete pattern survives. These are the right things to test.

5. **No unrelated changes**: The diff is clean. No formatting churn, no dependency changes, no scope creep.

### Minor Notes (Non-blocking)

1. The test checks for `"do not" in system_lower or "must not" in system_lower or "never" in system_lower` — this is fine but slightly fragile. If someone rewrites to "You cannot use..." it would pass the Bash check but fail the negative-constraint check. Acceptable for a regression test though — the point is to catch accidental removal, not to be grammar-proof.

2. The `{reviews_dir}` template variable in the Glob example is good — it means the agent gets the actual path, not a placeholder. Verified this is how `_build_learn_prompt()` works via the existing test.

3. Four commits for what is effectively a two-file change is a bit chatty, but that's the pipeline's process, not a code quality issue.

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/learn.md]: Clean, minimal fix. Adds tool constraints and concrete Glob patterns. 12 lines, all necessary.
- [tests/test_orchestrator.py]: Two targeted regression tests that verify both positive tool mention and negative constraint language. 25 lines, well-structured.
- [cOS_prds/...]: PRD correctly scopes the fix and documents what NOT to change. Good.
- [cOS_tasks/...]: All tasks marked complete. No TODOs remaining.

SYNTHESIS:
This is a textbook bug fix. The problem was a prompt that said "do the thing" without saying "with these specific tools." The agent guessed wrong, crashed, and burned the budget on retries. The fix adds 12 lines to the instruction template — explicit tool list, concrete Glob pattern, negative constraint — and 25 lines of regression tests. No architectural changes, no dependency additions, no scope creep. The learn phase was 100% broken; this should bring it to near-100% working. Ship it.
