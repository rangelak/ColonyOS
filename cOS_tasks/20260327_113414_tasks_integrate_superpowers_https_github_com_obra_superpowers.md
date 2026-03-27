# Tasks: Integrate Superpowers Methodologies into ColonyOS

_PRD: `cOS_prds/20260327_113414_prd_integrate_superpowers_https_github_com_obra_superpowers.md`_

## Relevant Files

- `src/colonyos/instructions/implement.md` - Main implementation phase template; receives TDD invariants, verification-before-completion, and task decomposition guidance
- `src/colonyos/instructions/implement_parallel.md` - Parallel implementation template; receives TDD invariants and self-review step
- `src/colonyos/instructions/fix.md` - Fix phase template; receives systematic debugging protocol
- `src/colonyos/instructions/ci_fix.md` - CI fix phase template; receives structured debugging for CI failures
- `src/colonyos/instructions/base.md` - Base instruction template (read-only reference for consistency)
- `src/colonyos/orchestrator.py` - Orchestrator prompt assembly (read-only reference — no changes needed)
- `tests/test_orchestrator.py` - Existing orchestrator tests; add instruction content verification tests
- `tests/test_instructions.py` - New file: tests that validate instruction template quality and completeness

## Tasks

- [ ] 1.0 Add instruction template quality tests (foundation — validates all subsequent changes)
  depends_on: []
  - [ ] 1.1 Create `tests/test_instructions.py` with tests that:
    - Verify all instruction `.md` files load without errors via `_load_instruction()`
    - Verify `implement.md` contains TDD-related keywords ("failing test", "RED", "GREEN", "REFACTOR")
    - Verify `implement.md` contains verification-before-completion keywords ("verify", "PRD requirement")
    - Verify `fix.md` contains debugging protocol keywords ("reproduce", "isolate", "hypothesize")
    - Verify `ci_fix.md` contains structured debugging keywords ("reproduce", "root cause")
    - Verify `implement_parallel.md` contains TDD and self-review keywords
    - Verify no instruction file exceeds a reasonable token budget (e.g., 3000 words per file)
  - [ ] 1.2 Run tests — confirm they FAIL (RED) for the keywords not yet present in current templates

- [ ] 2.0 Add TDD behavioral invariants to `implement.md` (core improvement, independent)
  depends_on: []
  - [ ] 2.1 Add a `## Behavioral Invariants` section after the Context section and before the Process section with:
    - Hard rule: "You MUST write a failing test that demonstrates the expected behavior BEFORE writing any production code"
    - RED-GREEN-REFACTOR cycle: write test → verify it fails → write minimal code to pass → verify it passes → refactor
    - Anti-patterns: "Tests that pass immediately on first run prove nothing — they must fail first to validate they test the right thing"
    - Test quality: one behavior per test, descriptive test names that explain what is being tested
    - Exceptions: config-only changes, documentation, generated/scaffolded code
  - [ ] 2.2 Enhance "Step 4: Implement Tasks in Order" to explicitly reference the RED-GREEN-REFACTOR cycle instead of just "Write tests first"
  - [ ] 2.3 Run the instruction quality tests — confirm TDD keywords now pass (GREEN)

- [ ] 3.0 Add verification-before-completion to `implement.md` (independent, same file as 2.0 but different section)
  depends_on: [2.0]
  - [ ] 3.1 Rewrite "Step 5: Final Verification" to include:
    - Requirement-by-requirement PRD check: "Read each numbered functional requirement in the PRD. For each one, verify the implementation satisfies it. If ANY requirement is not met, go back and implement it."
    - Full test suite with zero failures required
    - Red flags check: no TODO/FIXME/HACK in new code, no commented-out code, no placeholder implementations
    - Hard gate: "Do NOT declare implementation complete until every PRD requirement has been verified against the actual code"
  - [ ] 3.2 Add task decomposition guidance: "For complex tasks, break them into small verifiable steps. Commit after each verified step."
  - [ ] 3.3 Run instruction quality tests — confirm verification keywords pass (GREEN)

- [ ] 4.0 Add TDD invariants and self-review to `implement_parallel.md` (independent of 2.0/3.0 — different file)
  depends_on: []
  - [ ] 4.1 Add a compact `## Behavioral Invariants` section (adapted for single-task context) with the same TDD rules as `implement.md` but shorter
  - [ ] 4.2 Enhance "Step 4: Write Tests First" with explicit RED-GREEN guidance: write the test, run it, see it fail, then implement
  - [ ] 4.3 Add a "Step 5.5: Self-Review" step between "Step 6: Verify" and "Step 7: Commit":
    - Re-read the task description from the task file
    - Verify every requirement of this specific task is met
    - Check for obvious issues: unused imports, debug prints, incomplete error handling
  - [ ] 4.4 Run instruction quality tests — confirm parallel implementation keywords pass

- [ ] 5.0 Add systematic debugging protocol to `fix.md` (independent — different file)
  depends_on: []
  - [ ] 5.1 Add a `## Debugging Protocol` section before "Step 2: Make Targeted Fixes" with:
    - **Reproduce**: "Before changing ANY code, reproduce the exact error. Run the failing test or trigger the reported behavior. If you cannot reproduce it, investigate why before proceeding."
    - **Isolate**: "Narrow down to the smallest failing case. What is the minimal input/state that triggers the bug?"
    - **Hypothesize**: "Form an explicit hypothesis about the root cause BEFORE changing code. Write it as a comment in your commit message."
    - **Fix**: "Make the minimal change that addresses the root cause. Do not fix symptoms."
    - **Verify**: "Confirm the original error is resolved AND run the full test suite to check for regressions."
  - [ ] 5.2 Update "Step 2: Make Targeted Fixes" to reference the debugging protocol for each finding
  - [ ] 5.3 Run instruction quality tests — confirm debugging keywords pass

- [ ] 6.0 Add structured debugging to `ci_fix.md` (independent — different file)
  depends_on: []
  - [ ] 6.1 Add a `## Debugging Protocol` section adapted for CI failures:
    - **Reproduce locally**: "Before changing code, attempt to reproduce the CI failure locally. Run the exact command that failed."
    - **Classify**: "Determine the failure type: test failure, lint error, type error, build error, timeout, flaky test"
    - **Root cause**: "Identify whether this is a real bug in the code or a CI environment issue"
    - **Fix**: "Make the minimal change that addresses the root cause"
    - **Verify locally**: "Run the same CI check locally to confirm the fix before committing"
  - [ ] 6.2 Update "Step 1: Analyze the Failures" to use the classification framework
  - [ ] 6.3 Run instruction quality tests — confirm CI debugging keywords pass

- [ ] 7.0 Final integration testing and validation (depends on all instruction changes)
  depends_on: [2.0, 3.0, 4.0, 5.0, 6.0]
  - [ ] 7.1 Run the full test suite (`pytest tests/`) to confirm no regressions
  - [ ] 7.2 Verify all 4 modified instruction files still render correctly with `_load_instruction()` and `.format()` — no broken template variables
  - [ ] 7.3 Spot-check token budget: ensure no instruction file exceeds ~2500 words (rough proxy for context window impact)
  - [ ] 7.4 Review all changes for consistency: same terminology across files, no contradictions between invariants and process steps
  - [ ] 7.5 Commit all changes with a clear message crediting superpowers as methodology inspiration
