# Review: Andrej Karpathy — Round 1
## Fix Learn Phase — Tool Constraint Mismatch Causing 100% Failure Rate

**Branch**: `colonyos/the_learn_phase_is_failing_every_time_right_now_31f87a1c36`
**PRD**: `cOS_prds/20260401_130207_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

---

### Checklist Assessment

| Item | Status | Notes |
|------|--------|-------|
| FR-1: Available Tools section in learn.md | ✅ | Lists Read, Glob, Grep explicitly |
| FR-2: Concrete Glob patterns replace vague instructions | ✅ | `{reviews_dir}/**/*.md` pattern provided |
| FR-3: Negative constraint about disallowed tools | ✅ | "Do not attempt to use Bash, Write, Edit, Agent, or any other tool" with consequence |
| FR-4: Regression test for prompt-tool alignment | ✅ | Two tests added to TestBuildLearnPrompt |
| FR-5: Full test suite passes | ✅ | Both new tests pass, confirmed via pytest |
| No placeholder/TODO code | ✅ | Clean |
| No secrets/credentials | ✅ | N/A |
| No unrelated changes | ✅ | Only PRD, tasks, learn.md, test_orchestrator.py |

### Detailed Findings

**The diagnosis is exactly right.** This is a textbook prompt-program alignment bug. The learn agent's instructions were written for a human who'd intuitively know how to traverse a directory, but the agent is constrained to three specific tools. Prompts are programs; when you restrict the tool API, you must update the prompt to match.

**The fix is minimal and correct:**
- 11 lines added to `learn.md`: Available Tools section with tool listing, Glob pattern example, negative constraint with consequence
- 1 line changed: "Read all review artifacts recursively" → explicit Glob + Read workflow
- This is the right granularity — the prompt now programs the agent to use the tools it actually has

**The negative constraint is well-engineered.** "Do not attempt to use Bash, Write, Edit, Agent, or any other tool. They are not available and will cause a fatal error." This follows a good pattern: enumerate likely temptations explicitly, add a catch-all for unknown tools, explain the consequence. Models comply better with constraints that explain stakes vs. bare prohibitions.

**Defense in depth is now properly layered:**
- Layer 1 (enforcement): `allowed_tools=["Read", "Glob", "Grep"]` in orchestrator.py line 3510 — hard reject at CLI level
- Layer 2 (instruction): prompt tells the agent what's available — prevents the attempt entirely
- The bug was that Layer 2 was missing, so the agent kept hitting Layer 1 and burning budget on retries

**The tests are appropriately scoped:**
- `test_learn_prompt_contains_tool_constraint_language`: checks for positive mentions (Read, Glob, Grep), negative constraint language ("do not"/"must not"/"never"), and explicit Bash warning
- `test_learn_prompt_contains_glob_pattern_for_reviews`: checks for `**/*.md` pattern
- Static prompt tests — no LLM needed, which is the right level for regression guards

**Minor observations (non-blocking):**

1. Test assertions use common words (`"read" in system_lower`), but the five conditions checked collectively are specific enough to avoid false positives. Removing the Available Tools section would fail multiple assertions.

2. The catch-all "or any other tool" covers future tool additions (WebFetch, WebSearch, etc.) without requiring prompt updates.

3. The `{reviews_dir}` template variable in the Glob example gives the agent a copy-pasteable pattern rather than an abstract description — this reduces stochastic surface area in the model's tool-call generation.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/learn.md]: Correctly adds Available Tools section with consequence-based negative constraint and copy-pasteable Glob pattern — directly fixes the root cause
- [src/colonyos/instructions/learn.md]: "Will cause a fatal error" consequence framing is good prompt engineering — models internalize constraints better with explained stakes
- [tests/test_orchestrator.py]: Two regression tests are appropriately scoped as static prompt checks; collectively specific despite individually matching common words
- [src/colonyos/orchestrator.py]: Correctly untouched — enforcement layer was already correct; the bug was purely at the instruction layer

SYNTHESIS:
This is a clean, correct fix for a classic prompt-program alignment bug. When you restrict an agent's tool API, the system prompt IS the program — it must be updated to match the available API surface. The implementation is minimal (11 lines in learn.md, 25 lines of tests) and directly addresses all 5 functional requirements. The consequence-based negative constraint and concrete Glob pattern are good prompt engineering that will reliably steer the model toward the correct tool calls. No concerns — ship it.
