# Tasks: Enable Dependency Installation in Pipeline Agents

## Relevant Files

- `src/colonyos/instructions/base.md` - Base instructions inherited by all phases; add Dependency Management section
- `src/colonyos/instructions/implement.md` - Implement phase; replace "Do not add unnecessary dependencies" with positive guidance
- `src/colonyos/instructions/implement_parallel.md` - Parallel implement phase; add dependency guidance to Rules section
- `src/colonyos/instructions/fix.md` - Fix phase; replace ambiguous dependency restriction
- `src/colonyos/instructions/fix_standalone.md` - Standalone fix phase; replace ambiguous dependency restriction
- `src/colonyos/instructions/ci_fix.md` - CI fix phase; replace ambiguous dependency restriction
- `src/colonyos/instructions/verify_fix.md` - Verify fix phase; replace ambiguous dependency restriction
- `src/colonyos/instructions/thread_fix.md` - Thread fix phase; replace ambiguous dependency restriction
- `src/colonyos/instructions/thread_fix_pr_review.md` - PR review fix phase; replace ambiguous dependency restriction
- `src/colonyos/instructions/auto_recovery.md` - Auto recovery phase; add install as valid recovery action
- `src/colonyos/instructions/review.md` - Review phase; expand dependency checklist item
- `tests/test_orchestrator.py` - Orchestrator tests; verify instruction loading still works
- `tests/test_sweep.py` - Sweep tests; may reference instruction content

## Tasks

- [x] 1.0 Add Dependency Management section to base instructions
  depends_on: []
  - [x] 1.1 Verify no existing tests assert on `base.md` content that would break (search tests for "base.md" references and "unnecessary dependencies" string matches)
  - [x] 1.2 Add a new "## Dependency Management" section to `src/colonyos/instructions/base.md` after the "Quality Standards" section, covering: when to install, manifest-first workflow, canonical install commands (uv sync, npm install), prohibition on system-level packages (brew/apt), and exit code checking
  - [x] 1.3 Run the full test suite to confirm no regressions

- [x] 2.0 Update implement phase instructions
  depends_on: [1.0]
  - [x] 2.1 In `src/colonyos/instructions/implement.md`, replace "Do not add unnecessary dependencies" (line 52) with positive guidance: "When a feature requires a new dependency, add it to the appropriate manifest file (e.g., `pyproject.toml`, `package.json`) and run the project's install command (e.g., `uv sync`, `npm install`). Verify the import works before proceeding. Do not add dependencies unrelated to the feature."
  - [x] 2.2 In `src/colonyos/instructions/implement_parallel.md`, add a dependency installation rule to the Rules section: "If your task requires a new dependency, add it to the manifest file and run the install command. Do not add dependencies unrelated to task {task_id}."
  - [x] 2.3 Run the full test suite to confirm no regressions

- [x] 3.0 Update fix-phase instruction templates
  depends_on: [1.0]
  - [x] 3.1 In `src/colonyos/instructions/fix.md`, replace "Do not introduce new dependencies unless absolutely necessary to resolve a finding" (line 56) with: "If resolving a finding requires a new dependency or if existing dependencies are not installed, add it to the manifest file and run the install command. Do not add dependencies unrelated to the review findings."
  - [x] 3.2 In `src/colonyos/instructions/fix_standalone.md`, apply the same replacement (line 53)
  - [x] 3.3 In `src/colonyos/instructions/ci_fix.md`, replace the dependency line (line 55) with: "If resolving a CI failure requires installing dependencies (e.g., missing modules), run the project's install command. If a new dependency is genuinely needed, add it to the manifest file first. Do not add dependencies unrelated to the CI failure."
  - [x] 3.4 In `src/colonyos/instructions/verify_fix.md`, replace the dependency line (line 68) with: "If fixing a failure requires installing missing dependencies, run the project's install command. Do not add new dependencies unless the fix genuinely requires one."
  - [x] 3.5 In `src/colonyos/instructions/thread_fix.md`, replace the dependency line (line 71) with: "If the fix request requires a new dependency, add it to the manifest file and run the install command. Do not add dependencies unrelated to the fix request."
  - [x] 3.6 In `src/colonyos/instructions/thread_fix_pr_review.md`, apply the same replacement pattern (line 76)
  - [x] 3.7 Run the full test suite to confirm no regressions

- [ ] 4.0 Update recovery and review instructions
  depends_on: [1.0]
  - [ ] 4.1 In `src/colonyos/instructions/auto_recovery.md`, add a bullet to the Rules section: "If the failure is caused by a missing dependency (e.g., ModuleNotFoundError, Cannot find module), running the project's install command (e.g., `uv sync`, `npm install`) is a valid minimum recovery action."
  - [ ] 4.2 In `src/colonyos/instructions/review.md`, expand "No unnecessary dependencies added" checklist item to: "No unnecessary dependencies added; any new dependencies are declared in manifest files with lockfile changes committed; no system-level packages installed"
  - [ ] 4.3 Run the full test suite to confirm no regressions

- [ ] 5.0 Final integration verification
  depends_on: [2.0, 3.0, 4.0]
  - [ ] 5.1 Run the full test suite (`pytest`) to confirm all tests pass
  - [ ] 5.2 Run linter (`ruff check .`) and type checker (`basedpyright`) to confirm no issues
  - [ ] 5.3 Verify all modified instruction files load correctly by checking `_load_instruction()` works for each modified template name
  - [ ] 5.4 Review all changes for consistency — ensure the dependency guidance language is coherent across all templates and the base instructions are not contradicted by phase-specific instructions
