# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

Now I have everything I need for a thorough review. Let me write it up.

---

## Review: Fix Learn Phase — Tool Constraint Mismatch

**Reviewing as: Principal Systems Engineer (Google/Stripe caliber)**

### Completeness Assessment

| Requirement | Status | Evidence |
|---|---|---|
| **FR-1**: `learn.md` "Available Tools" section | ✅ | Lines 5-13 of learn.md — explicit section listing Read, Glob, Grep |
| **FR-2**: Concrete Glob patterns replace vague instructions | ✅ | Line 24: `Glob` with pattern `{reviews_dir}/**/*.md` + Read for each file |
| **FR-3**: Negative constraint about disallowed tools | ✅ | Line 13: "Do not attempt to use Bash, Write, Edit, Agent, or any other tool." |
| **FR-4**: Regression tests in test_orchestrator.py | ✅ | Two new tests: `test_learn_prompt_contains_tool_constraint_language` and `test_learn_prompt_contains_glob_pattern_for_reviews` |
| **FR-5**: Full test suite passes | ✅ | Task file confirms 2921 passed, 0 failures; I confirmed 18/18 learn tests pass |
| All tasks marked complete | ✅ | All tasks in task file are `[x]` |
| No placeholder/TODO code | ✅ | Clean implementation, no TODOs |

### Quality Assessment

**Tests**: The regression tests are well-structured and have good assertion messages. They test the right thing: the *rendered prompt* that the agent actually sees, not just config values. The `test_learn_prompt_contains_tool_constraint_language` test checks both positive constraints (all three allowed tools mentioned) and negative constraints ("do not" + "bash"). The `test_learn_prompt_contains_glob_pattern_for_reviews` test checks for the concrete pattern `**/*.md`.

**One minor test robustness concern**: The assertion `"read" in system_lower` is quite loose — "read" appears naturally in English text ("read review artifacts"). It would be stronger to assert something like `"read, glob, and grep"` or `"available tools"` as a phrase. However, since the test combines multiple assertions (read + glob + grep + negative constraint + bash), the *conjunction* of all five is specific enough that a false pass is unlikely. Non-blocking.

**Prompt quality**: The learn.md changes are surgical and correct. The "Available Tools" section is positioned prominently before the process steps (good — agent will see constraints before receiving instructions). The negative constraint includes the consequence ("will cause a fatal error"), which is excellent for LLM compliance. The Glob pattern example uses the template variable `{reviews_dir}` correctly.

**No unrelated changes**: The diff is exactly 4 files — PRD, task file, learn.md, and test_orchestrator.py. The PRD and task file are planning artifacts (expected). The two code changes are precisely scoped.

### Safety Assessment

- ✅ No secrets or credentials
- ✅ No destructive operations
- ✅ Error handling: the fix prevents errors rather than adding catch blocks (correct approach — fix the cause)
- ✅ No dependency changes
- ✅ The `allowed_tools` enforcement in agent.py remains untouched (defense-in-depth preserved)

### Systems Engineering Perspective

**What happens at 3am?** The learn phase was previously a guaranteed crash. Now it has clear instructions that align with its tool sandbox. If a future prompt editor accidentally references `Bash` in learn.md, the regression test catches it before merge. This is the right defense.

**Blast radius**: Zero. The change is purely to an instruction template for a read-only extraction phase. Even if the learn phase somehow produces garbage output, `_parse_learn_output()` regex validation and `append_learnings()` deduplication are untouched safety nets.

**Observability**: The task file documents the test-first methodology (test failed first, then passed after fix). The commit history tells a clean story: test-first → fix → verification.

**One thing I'd want for V2** (non-blocking): The PRD's Open Question #2 is correct — every phase instruction template should declare its available tools. The learn phase was the canary; the same class of bug could exist in other phases with restricted tool sets. But that's a separate ticket.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/learn.md]: Clean, well-positioned "Available Tools" section with both positive (three tools listed) and negative ("Do not attempt to use Bash, Write, Edit, Agent") constraints. Consequence language ("will cause a fatal error") improves LLM compliance.
- [src/colonyos/instructions/learn.md]: Step 1 correctly replaced vague "Read all review artifacts recursively" with concrete `Glob` + `Read` workflow using template variable `{reviews_dir}/**/*.md`.
- [tests/test_orchestrator.py]: Two regression tests verify the rendered prompt contains tool-constraint language and concrete Glob patterns. Tests are well-documented with docstrings explaining the regression they prevent.
- [tests/test_orchestrator.py]: Minor: `"read" in system_lower` assertion is loose (matches natural English), but the conjunction of all five assertions makes false positives unlikely. Non-blocking.

SYNTHESIS:
This is a textbook minimal fix for a 100% failure-rate bug. The root cause analysis is precise (prompt-program mismatch), the fix is surgical (two files, zero logic changes), and the regression test catches the exact class of error that caused the failure. From a systems reliability perspective, the change moves the learn phase from "guaranteed crash" to "well-constrained read-only agent" with no blast radius to other phases. The defense-in-depth is preserved: the agent.py tool enforcement remains untouched as a backstop, while the prompt now prevents the agent from ever hitting that backstop. The only forward-looking concern is PRD Open Question #2 — other restricted phases may have the same latent bug — but that's correctly scoped as a separate ticket. Ship it.
