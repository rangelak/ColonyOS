# Tasks: Fix Learn Phase — Tool Constraint Mismatch

## Relevant Files

- `src/colonyos/instructions/learn.md` - System prompt template for the learn agent; missing tool constraints (PRIMARY FIX)
- `src/colonyos/orchestrator.py` - Contains `_run_learn_phase()` (line 3474), `_build_learn_prompt()` (line 2152), `_parse_learn_output()` (line 2248); no changes needed but context is important
- `src/colonyos/agent.py` - Contains `run_phase_sync()` that enforces allowed_tools; no changes needed
- `src/colonyos/learnings.py` - Parsing/appending logic for learnings ledger; no changes needed
- `tests/test_orchestrator.py` - Existing learn phase tests in `TestLearnPhaseWiring`, `TestBuildLearnPrompt`; add new regression test here
- `tests/test_learnings.py` - 21 existing tests for learnings module; no changes needed
- `.colonyos/learnings.md` - The persisted learnings ledger (read by learn agent)
- `.colonyos/config.yaml` - Contains `learnings.enabled: true` and `learnings.max_entries: 100`

## Tasks

- [x] 1.0 Add regression test for learn phase tool-constraint alignment (test-first)
  depends_on: []
  - [x] 1.1 Add test in `tests/test_orchestrator.py` that calls `_build_learn_prompt()` and asserts the system prompt contains explicit tool-constraint language (e.g., "Read, Glob, and Grep" or "Do not use Bash")
  - [x] 1.2 Add test that asserts the learn phase `allowed_tools` passed to `run_phase_sync` is exactly `["Read", "Glob", "Grep"]` (may already exist as `test_learn_phase_uses_read_only_tools` — verify and strengthen if needed)
  - [x] 1.3 Run tests to confirm the new test FAILS (proving the constraint language is missing from learn.md)

- [ ] 2.0 Fix learn.md instruction template to include tool constraints and explicit Glob patterns
  depends_on: [1.0]
  - [ ] 2.1 Add an "Available Tools" section to `src/colonyos/instructions/learn.md` listing Read, Glob, and Grep with brief descriptions
  - [ ] 2.2 Add explicit negative constraint: "Do not attempt to use Bash, Write, Edit, Agent, or any other tool"
  - [ ] 2.3 Rewrite Step 1 to use concrete Glob pattern: `Glob` with pattern `{reviews_dir}/**/*.md` for file discovery, then `Read` for each file
  - [ ] 2.4 Run the new test from 1.1 to confirm it now PASSES

- [ ] 3.0 Verify full test suite passes with no regressions
  depends_on: [2.0]
  - [ ] 3.1 Run the full pytest suite (`pytest --tb=short -q`) and confirm all tests pass (expected: 2919+ tests, 0 failures)
  - [ ] 3.2 Manually verify `_build_learn_prompt()` output includes the new tool constraints by inspecting the formatted prompt
