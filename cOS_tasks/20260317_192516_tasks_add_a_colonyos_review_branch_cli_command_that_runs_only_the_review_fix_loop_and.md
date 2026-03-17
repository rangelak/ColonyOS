# Tasks: Standalone `colonyos review <branch>` Command

## Relevant Files

- `src/colonyos/cli.py` - Add `review` Click command with argument/option parsing, branch validation, orchestration call, summary printing, and exit code logic
- `src/colonyos/orchestrator.py` - Add `run_standalone_review()`, `_build_standalone_review_prompt()`, `_build_standalone_fix_prompt()`, `_build_standalone_decision_prompt()`, `_get_branch_diff()`, `_validate_branch_exists()`
- `src/colonyos/instructions/review_standalone.md` - New instruction template for standalone reviews (no PRD references)
- `src/colonyos/instructions/fix_standalone.md` - New instruction template for standalone fix phase (no PRD/task file)
- `src/colonyos/instructions/decision_standalone.md` - New instruction template for standalone decision gate (no PRD)
- `src/colonyos/agent.py` - Existing `run_phases_parallel_sync()` and `run_phase_sync()` (no changes needed, just reused)
- `src/colonyos/config.py` - Existing `ColonyConfig`, `load_config()` (no changes needed)
- `src/colonyos/models.py` - Existing `Phase`, `PhaseResult`, `Persona` (no changes needed)
- `src/colonyos/naming.py` - May reuse or extend slug generation for branch names
- `tests/test_standalone_review.py` - New test file for standalone review orchestration logic
- `tests/test_cli.py` - Add tests for the `review` CLI command

## Tasks

- [x]1.0 Branch Validation and Diff Extraction Utilities
  - [x]1.1 Write tests for `_validate_branch_exists()` in `tests/test_standalone_review.py`: test with existing local branch (mocked `subprocess.run` returning branch name), test with non-existent branch (empty output), test error message suggests `git fetch`/`git checkout`, test rejection of remote-style refs like `origin/foo`
  - [x]1.2 Write tests for `_get_branch_diff()` in `tests/test_standalone_review.py`: test normal diff extraction via `git diff base...branch`, test truncation when diff exceeds 10,000 chars (verify truncation marker appended), test empty diff returns empty string, test subprocess error handling
  - [x]1.3 Implement `_validate_branch_exists(branch: str, repo_root: Path) -> tuple[bool, str]` in `orchestrator.py` — runs `git branch --list <branch>`, returns `(True, "")` if found or `(False, error_message)` if not. Detects `origin/` prefix and suggests checkout instead.
  - [x]1.4 Implement `_get_branch_diff(base: str, branch: str, repo_root: Path, max_chars: int = 10_000) -> str` in `orchestrator.py` — runs `git diff <base>...<branch>`, truncates if needed with a summary line, returns the diff text.

- [x]2.0 Standalone Review Instruction Templates
  - [x]2.1 Create `src/colonyos/instructions/review_standalone.md` — same structure as `review.md` but replaces PRD references with diff-focused instructions. Uses `{reviewer_role}`, `{reviewer_expertise}`, `{reviewer_perspective}`, `{branch_name}`, `{base_branch}`, `{diff_summary}` placeholders. Checklist focuses on quality, safety, and convention-following (not PRD completeness). Keeps the same VERDICT/FINDINGS/SYNTHESIS output format.
  - [x]2.2 Create `src/colonyos/instructions/fix_standalone.md` — adapted from `fix.md` but removes PRD/task file references. Uses `{branch_name}`, `{reviews_dir}`, `{findings_text}`, `{fix_iteration}`, `{max_fix_iterations}` placeholders. Instructs fix agent to address findings and commit on the branch.
  - [x]2.3 Create `src/colonyos/instructions/decision_standalone.md` — adapted from `decision.md` but removes PRD references. Uses `{branch_name}`, `{base_branch}`, `{reviews_dir}` placeholders. Decision criteria based on review verdicts and finding severity rather than PRD compliance.

- [x]3.0 Standalone Review Prompt Builders
  - [x]3.1 Write tests for `_build_standalone_review_prompt()` in `tests/test_standalone_review.py`: test that returned system prompt contains persona role/expertise/perspective, test that diff summary is included, test that user prompt references the branch and base, test that no PRD path appears in the output
  - [x]3.2 Write tests for `_build_standalone_fix_prompt()` in `tests/test_standalone_review.py`: test that findings text is included, test that fix iteration number is included, test that no PRD/task file paths appear
  - [x]3.3 Implement `_build_standalone_review_prompt(persona, config, branch_name, base_branch, diff_summary) -> tuple[str, str]` in `orchestrator.py` — loads `review_standalone.md`, formats with persona identity and diff context, returns (system_prompt, user_prompt)
  - [x]3.4 Implement `_build_standalone_fix_prompt(config, branch_name, findings_text, fix_iteration) -> tuple[str, str]` in `orchestrator.py` — loads `fix_standalone.md`, formats with findings and iteration info
  - [x]3.5 Implement `_build_standalone_decision_prompt(config, branch_name, base_branch) -> tuple[str, str]` in `orchestrator.py` — loads `decision_standalone.md`, formats for standalone context

- [x]4.0 Core `run_standalone_review()` Orchestration Function
  - [x]4.1 Write tests for `run_standalone_review()` in `tests/test_standalone_review.py`: test all-approve scenario returns `(True, results, cost)` with correct artifact filenames saved, test request-changes triggers fix loop when `no_fix=False`, test `no_fix=True` skips fix loop, test budget exhaustion stops review loop early, test `decide=True` runs decision gate, test summary artifact is saved with correct filename
  - [x]4.2 Write tests for parallel review execution (mocked `run_phases_parallel_sync`): verify correct number of calls made, verify each call has correct phase/tools/budget/model, verify results are processed correctly
  - [x]4.3 Implement `run_standalone_review()` in `orchestrator.py` with signature:
    ```python
    def run_standalone_review(
        branch: str,
        base: str,
        repo_root: Path,
        config: ColonyConfig,
        *,
        verbose: bool = False,
        quiet: bool = False,
        no_fix: bool = False,
        decide: bool = False,
    ) -> tuple[bool, list[PhaseResult], float]:
    ```
    Returns `(all_approved, phase_results, total_cost_usd)`.
    Implementation:
    1. Get reviewer personas via `_reviewer_personas(config)`
    2. Get diff via `_get_branch_diff(base, branch, repo_root)`
    3. Loop up to `max_fix_iterations + 1` rounds:
       a. Budget guard (same pattern as pipeline lines 986-995)
       b. Build review calls via `_build_standalone_review_prompt()` for each persona
       c. Execute via `run_phases_parallel_sync()`
       d. Save each review artifact with `review_standalone_{branch_slug}_round{N}_{persona_slug}.md`
       e. Collect findings via `_collect_review_findings()`
       f. If no findings → break (all approve)
       g. If `no_fix` → break
       h. If iteration < max_fix_iterations → run fix agent via `_build_standalone_fix_prompt()` and `run_phase_sync()`
    4. If `decide` → run decision gate
    5. Save summary artifact
    6. Return results

- [x]5.0 CLI `review` Command
  - [x]5.1 Write tests for the `review` CLI command in `tests/test_cli.py`: test missing config shows "run colonyos init" error, test invalid branch shows error with suggestion, test invalid base branch shows error, test successful review prints summary and exits 0, test failed review exits 1, test `--no-fix` flag is passed through, test `--base` flag is passed through, test `--decide` flag is passed through, test `--verbose` and `--quiet` flags
  - [x]5.2 Implement the `review` Click command in `cli.py`:
    - `@app.command()` with `@click.argument("branch")`, `@click.option("--base", default="main")`, `@click.option("--no-fix", is_flag=True)`, `@click.option("--decide", is_flag=True)`, `@click.option("-v", "--verbose", is_flag=True)`, `@click.option("-q", "--quiet", is_flag=True)`
    - Load config via `load_config(repo_root)`, error if not initialized
    - Validate branches via `_validate_branch_exists()`
    - Call `run_standalone_review()`
    - Print summary table (persona, verdict, one-line finding)
    - Print cost summary
    - `sys.exit(0)` if all approved, `sys.exit(1)` if not

- [x]6.0 Review Summary Table and Artifacts
  - [x]6.1 Write tests for `_print_review_summary()` in `tests/test_standalone_review.py`: test that each persona verdict is printed, test that cost is printed, test that decision verdict is printed when present
  - [x]6.2 Write tests for summary artifact content: verify it contains all persona verdicts, findings, and cost
  - [x]6.3 Implement `_print_review_summary()` in `cli.py` — prints a formatted table with persona name, verdict, top finding, and total cost
  - [x]6.4 Implement summary artifact generation in `run_standalone_review()` — builds and saves `review_standalone_{branch_slug}_summary.md`

- [x]7.0 Integration Testing and Edge Cases
  - [x]7.1 Write tests for exit code logic: exit 0 when all approve on first round, exit 0 when approve after fix, exit 1 when changes requested and `--no-fix`, exit 1 after fix loop exhaustion with remaining findings, exit 0 for GO decision, exit 1 for NO-GO decision
  - [x]7.2 Write tests for budget enforcement: review stops when per_run budget exhausted mid-loop, cost tracking across review and fix phases is correct
  - [x]7.3 Write tests for edge cases: no reviewer personas configured (error message), empty diff (review still runs), fix phase failure (loop stops gracefully)
  - [x]7.4 Run full existing test suite (`pytest tests/`) to verify no regressions

- [x]8.0 Export and Wiring
  - [x]8.1 Add `run_standalone_review` to the imports in `cli.py` from `orchestrator.py`
  - [x]8.2 Add new utility functions (`_validate_branch_exists`, `_get_branch_diff`, `_build_standalone_review_prompt`, `_build_standalone_fix_prompt`, `_build_standalone_decision_prompt`) to the test imports in `tests/test_standalone_review.py`
  - [x]8.3 Verify the full test suite passes with `pytest tests/ -v`
