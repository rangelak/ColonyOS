# Staff Security Engineer — Round 1 Review
## Fix Learn Phase — Tool Constraint Mismatch Causing 100% Failure Rate

**Branch**: `colonyos/the_learn_phase_is_failing_every_time_right_now_31f87a1c36`
**PRD**: `cOS_prds/20260401_130207_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Date**: 2026-04-01

---

### Checklist Assessment

#### Completeness
- [x] **FR-1**: `learn.md` now has an "Available Tools" section listing Read, Glob, Grep — verified in lines 5-13
- [x] **FR-2**: Vague "Read all review artifacts recursively" replaced with concrete `Glob` + `Read` steps — verified in line 24
- [x] **FR-3**: Explicit negative constraint present: "Do not attempt to use Bash, Write, Edit, Agent, or any other tool" — verified in line 13
- [x] **FR-4**: Two new tests in `tests/test_orchestrator.py`: `test_learn_prompt_contains_tool_constraint_language` and `test_learn_prompt_contains_glob_pattern_for_reviews` — both assert prompt content and tool restrictions
- [x] **FR-5**: All 18 learn-related tests pass; task file reports 2921 tests, 0 failures

#### Quality
- [x] All tests pass (verified: 18 passed in 1.31s)
- [x] No linter errors introduced (pure markdown + simple string asserts)
- [x] Code follows existing project conventions (test class placement, assertion style match adjacent tests)
- [x] No dependencies added
- [x] No unrelated changes — diff is surgically scoped to 4 files (PRD, tasks, learn.md, test_orchestrator.py)

#### Safety — Security-Focused Assessment
- [x] No secrets or credentials in committed code
- [x] No destructive operations
- [x] Error handling: failure chain is unchanged; the fix addresses root cause, not symptom

---

### Security-Specific Findings

**1. Least privilege is preserved (GOOD)**
The `allowed_tools=["Read", "Glob", "Grep"]` enforcement at orchestrator.py:3510 is unchanged. The fix operates entirely within the instruction layer, not the enforcement layer. This is the correct approach — prompt alignment with enforcement, not relaxation of enforcement.

**2. Defense in depth: instructions + enforcement (GOOD)**
The learn agent now has two layers of tool restriction:
- **Layer 1 (enforcement)**: `run_phase_sync()` passes `allowed_tools` to the Claude CLI, which rejects disallowed tool calls at the API level.
- **Layer 2 (instruction)**: `learn.md` explicitly tells the agent what it can and cannot use, reducing the chance of hitting Layer 1 enforcement (which causes crashes/budget waste).

This is proper defense-in-depth. The instructions prevent the agent from *trying* disallowed tools; the enforcement prevents execution *if* the agent tries anyway.

**3. No privilege escalation vectors introduced (GOOD)**
The diff does not expand `allowed_tools`, does not modify `agent.py` enforcement logic, does not change budget caps, and does not alter the learn phase's write permissions. The learn agent remains strictly read-only.

**4. Template injection surface — pre-existing, not a regression (ADVISORY)**
The `{reviews_dir}` and `{learnings_path}` template variables in `learn.md` are populated by `_build_learn_prompt()` from `config.reviews_dir` and filesystem paths. These are operator-controlled config values, not user input. No new injection vectors introduced by this change.

**5. Negative constraint could be more comprehensive (MINOR)**
The negative constraint lists "Bash, Write, Edit, Agent" but doesn't mention `WebFetch`, `WebSearch`, `NotebookEdit`, or other tools that might exist in the tool registry. The current list covers the tools the agent was actually reaching for (Bash, Agent), so it's practically sufficient. The catch-all "or any other tool" phrase provides adequate coverage.

**6. Test assertions are structurally sound but could be tighter (MINOR)**
The test `test_learn_prompt_contains_tool_constraint_language` checks for substrings like "read", "glob", "grep" in the lowercased prompt. These are common English words that might match incidentally. However, the combination of all assertions together (including the "bash" and "do not" checks) makes false-positive passes extremely unlikely. Acceptable for a regression test.

---

### Verdict

This is a clean, minimal, correctly-scoped fix. The implementation:
- Fixes the root cause (prompt-tool mismatch) without weakening enforcement
- Maintains the principle of least privilege for the learn phase
- Adds defense-in-depth by aligning instructions with tool restrictions
- Introduces no new attack surface, no secrets, no privilege escalation
- Has regression tests that will catch future prompt-tool misalignment

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/learn.md]: Correctly adds tool constraints and negative constraints; no security issues
- [src/colonyos/instructions/learn.md]: Template variables ({reviews_dir}, {learnings_path}) are operator-controlled — no injection risk (pre-existing pattern)
- [tests/test_orchestrator.py]: Two new regression tests adequately cover prompt-tool alignment; substring matching is sufficient given combined assertions
- [src/colonyos/orchestrator.py]: allowed_tools enforcement at line 3510 is unchanged and correctly restricts to Read/Glob/Grep only

SYNTHESIS:
From a security perspective, this is an exemplary fix. The root cause was a prompt-program mismatch causing the agent to attempt unauthorized tool use, and the fix addresses this at the instruction layer without relaxing any enforcement. The learn phase remains strictly read-only with a hard-coded tool allowlist enforced at the CLI level. The negative constraint in learn.md provides defense-in-depth by preventing the agent from even attempting disallowed tools, reducing both crash risk and budget waste from tool-rejection retry loops. No secrets, no privilege escalation, no new attack surface. The only advisory note is that the negative constraint's explicit tool list ("Bash, Write, Edit, Agent") could enumerate more tool names, but the "or any other tool" catch-all provides adequate coverage. Approve without reservations.
