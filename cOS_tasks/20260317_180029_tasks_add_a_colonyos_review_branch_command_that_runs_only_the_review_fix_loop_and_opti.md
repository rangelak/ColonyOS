# Tasks: Standalone `colonyos review <branch>` Command

## Relevant Files

- `src/colonyos/cli.py` - Add `review` command with Click decorators, argument parsing, pre-flight checks, and summary output
- `src/colonyos/orchestrator.py` - Extract `run_review_loop()`, add standalone prompt builders, add `detect_base_branch()`, add `_build_review_run_id()`
- `src/colonyos/instructions/review_standalone.md` - New template for PRD-less persona reviews
- `src/colonyos/instructions/fix_standalone.md` - New template for PRD-less fix iterations
- `src/colonyos/instructions/decision_standalone.md` - New template for PRD-less decision gate
- `src/colonyos/models.py` - No changes needed (reuse `RunLog`, `PhaseResult`, `Phase` as-is)
- `src/colonyos/agent.py` - No changes needed (reuse `run_phase_sync`, `run_phases_parallel_sync`)
- `src/colonyos/config.py` - No changes needed (reuse `ColonyConfig`, `BudgetConfig`)
- `tests/test_cli.py` - Add tests for `review` command argument parsing, exit codes, pre-flight checks
- `tests/test_orchestrator.py` - Add tests for `run_review_loop()`, `detect_base_branch()`, standalone prompt builders, artifact naming

## Tasks

- [x] 1.0 Add standalone review instruction templates
  - [x] 1.1 Create `src/colonyos/instructions/review_standalone.md` — a review template that instructs the reviewer to assess a branch diff without a PRD. Must include: persona identity placeholders (`{reviewer_role}`, `{reviewer_expertise}`, `{reviewer_perspective}`), `{branch_name}`, `{base_branch}` context, instructions to read all changed files via `git diff {base_branch}...HEAD`, assess code quality/correctness/test coverage, and produce the same `VERDICT: approve | request-changes` + `FINDINGS:` + `SYNTHESIS:` structured output format as the existing `review.md`
  - [x] 1.2 Create `src/colonyos/instructions/fix_standalone.md` — a fix template for PRD-less fix iterations. Same structure as existing `fix.md` but replaces PRD/task references with instructions to use review findings and the branch diff as the sole specification. Placeholders: `{branch_name}`, `{base_branch}`, `{reviews_dir}`, `{findings_text}`, `{fix_iteration}`, `{max_fix_iterations}`
  - [x] 1.3 Create `src/colonyos/instructions/decision_standalone.md` — a decision gate template for PRD-less reviews. Same structure as existing `decision.md` but replaces PRD references with branch diff context. Placeholders: `{branch_name}`, `{base_branch}`, `{reviews_dir}`

- [x] 2.0 Extract review/fix/decision loop into reusable function
  - [x] 2.1 Write tests for `run_review_loop()` in `tests/test_orchestrator.py` — test that it calls `run_phases_parallel_sync` with correct reviewer prompts, respects `enable_fix=False` (skips fix loop), respects `enable_fix=True` (runs fix loop up to `max_fix_iterations`), runs the decision gate, returns the correct overall verdict, and saves review artifacts with correct filenames
  - [x] 2.2 Add `run_review_loop()` function to `src/colonyos/orchestrator.py` — extract lines ~770-920 from `run()` into a standalone function with signature: `run_review_loop(repo_root, config, branch_name, log, *, prd_rel=None, task_rel=None, enable_fix=True, artifact_prefix="", verbose=False, quiet=False) -> str` (returns "approve" or "request-changes" or "GO" or "NO-GO")
  - [x] 2.3 Refactor `orchestrator.run()` to call `run_review_loop()` instead of the inline review/fix/decision logic, ensuring all existing tests still pass

- [x] 3.0 Add standalone prompt builders
  - [x] 3.1 Write tests for `_build_persona_standalone_review_prompt()` in `tests/test_orchestrator.py` — verify it loads `review_standalone.md`, formats persona identity and branch/base placeholders, and does not reference any PRD path
  - [x] 3.2 Implement `_build_persona_standalone_review_prompt(persona, config, branch_name, base_branch)` in `orchestrator.py` — builds system+user prompts using `review_standalone.md`
  - [x] 3.3 Write tests for `_build_standalone_fix_prompt()` — verify it loads `fix_standalone.md`, formats branch/findings/iteration placeholders, and does not reference PRD/task paths
  - [x] 3.4 Implement `_build_standalone_fix_prompt(config, branch_name, base_branch, findings_text, fix_iteration)` in `orchestrator.py`
  - [x] 3.5 Write tests for `_build_standalone_decision_prompt()` — verify it loads `decision_standalone.md` and formats correctly
  - [x] 3.6 Implement `_build_standalone_decision_prompt(config, branch_name, base_branch)` in `orchestrator.py`

- [x] 4.0 Add base branch detection and pre-flight checks
  - [x] 4.1 Write tests for `detect_base_branch()` in `tests/test_orchestrator.py` — test that it returns "main" when main exists, "master" when only master exists, falls back to "HEAD~1", and respects an explicit override
  - [x] 4.2 Implement `detect_base_branch(repo_root, override=None)` in `orchestrator.py` — checks for `main`, `master`, falls back to `HEAD~1`. Uses `git rev-parse --verify` to check branch existence
  - [x] 4.3 Write tests for `validate_review_preconditions()` in `tests/test_orchestrator.py` — test branch existence check, empty diff check, and clean working tree check (when fix=True)
  - [x] 4.4 Implement `validate_review_preconditions(repo_root, branch, base_branch, fix_enabled)` in `orchestrator.py` — validates branch exists, diff is non-empty, and working tree is clean if fix is enabled. Returns error message or None

- [x] 5.0 Add review run ID generation and artifact naming
  - [x] 5.1 Write tests for `_build_review_run_id()` in `tests/test_orchestrator.py` — verify it produces IDs matching `review-YYYYMMDD_HHMMSS-{hash}` format
  - [x] 5.2 Implement `_build_review_run_id(branch_name)` in `orchestrator.py` — generates `review-{timestamp}-{hash}` run IDs
  - [x] 5.3 Write tests for standalone artifact naming — verify filenames match `review_standalone_{branch_slug}_round{N}_{persona_slug}.md` and `decision_standalone_{branch_slug}.md`
  - [x] 5.4 Implement the artifact naming logic in `run_review_loop()` — use `artifact_prefix` parameter to control whether filenames include `standalone_` prefix

- [x] 6.0 Add `review` CLI command
  - [x] 6.1 Write tests for `review` command argument parsing in `tests/test_cli.py` — test: branch argument is required, `--prd` accepts a file path, `--fix` is a boolean flag, `--base` accepts a string, `-v`/`-q` flags work, missing config shows init message
  - [x] 6.2 Write tests for `review` command exit codes in `tests/test_cli.py` — test: exit 0 when all approve, exit 1 when any request-changes, exit 1 when decision gate NO-GO, exit 1 when branch has no diff
  - [x] 6.3 Implement the `review` command in `src/colonyos/cli.py` with Click decorators:
    - `@app.command()` with `@click.argument("branch")`, `@click.option("--prd")`, `@click.option("--fix")`, `@click.option("--base")`, `@click.option("-v", "--verbose")`, `@click.option("-q", "--quiet")`
    - Load config, run pre-flight checks, create `RunLog` with review run ID
    - Call `run_review_loop()` with appropriate parameters
    - Print summary table and exit with correct code
  - [x] 6.4 Implement the review summary table using Rich — show per-persona verdict rows and overall decision. Reuse `_print_run_summary()` for cost breakdown

- [x] 7.0 Update welcome banner and status display
  - [x] 7.1 Add `review` to the welcome banner command list in `_show_welcome()` in `cli.py`
  - [x] 7.2 Verify `colonyos status` displays `review-*` run logs correctly (should work automatically since the status command globs all `*.json` files)

- [x] 8.0 Integration testing and final validation
  - [x] 8.1 Run full existing test suite to verify no regressions from the `run_review_loop()` extraction
  - [x] 8.2 Verify the refactored `orchestrator.run()` still passes all existing orchestrator tests
  - [x] 8.3 Manual smoke test: `colonyos review <branch>` on a real branch produces review artifacts in `cOS_reviews/`
