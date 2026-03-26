# Tasks: `colonyos sweep` — Autonomous Codebase Quality Agent

## Relevant Files

- `src/colonyos/models.py` - Add `Phase.SWEEP` enum value
- `src/colonyos/config.py` - Add `SweepConfig` dataclass and wire into `ColonyConfig` and DEFAULTS
- `src/colonyos/instructions/sweep.md` - New instruction template for the sweep analysis agent (new file)
- `src/colonyos/orchestrator.py` - Add `run_sweep()` function and `_build_sweep_prompt()` helper
- `src/colonyos/cli.py` - Add `sweep` command with Click decorators and all flags
- `src/colonyos/cleanup.py` - Reuse `write_cleanup_log()` for audit logging; potentially expose `scan_directory()` results as context
- `src/colonyos/dag.py` - No changes needed, but sweep output must be compatible with `parse_task_file()`
- `src/colonyos/agent.py` - No changes needed; `run_phase_sync()` already supports read-only tool lists
- `tests/test_sweep.py` - New test file for sweep-specific logic (new file)
- `tests/test_orchestrator.py` - Add tests for `run_sweep()` orchestration
- `tests/test_cli.py` - Add tests for the `sweep` CLI command

## Tasks

- [x] 1.0 Add `Phase.SWEEP` enum and `SweepConfig` to core models/config
  depends_on: []
  - [x] 1.1 Write tests for `SweepConfig` parsing from YAML and defaults in `tests/test_sweep.py`
    - Test `SweepConfig` dataclass instantiation with defaults
    - Test `SweepConfig` override from YAML config dict
    - Test `ColonyConfig` correctly populates `sweep` field
    - Test `get_model(Phase.SWEEP)` returns expected model
  - [x] 1.2 Add `SWEEP = "sweep"` to the `Phase` enum in `src/colonyos/models.py`
  - [x] 1.3 Add `SweepConfig` dataclass to `src/colonyos/config.py` with fields:
    - `max_tasks: int = 5`
    - `max_files_per_task: int = 5`
    - `default_categories: list[str]` defaulting to `["bugs", "dead_code", "error_handling", "complexity", "consistency"]`
  - [x] 1.4 Add `sweep` key to `DEFAULTS` dict in `config.py` and wire `SweepConfig` into `ColonyConfig` dataclass
  - [x] 1.5 Update `_parse_config()` (or equivalent config loader) to parse the `sweep:` YAML section into `SweepConfig`

- [x] 2.0 Create the sweep analysis instruction template
  depends_on: []
  - [x] 2.1 Write tests that verify the instruction template exists and contains required sections (categories, scoring rubric, task file format, exclusions)
  - [x] 2.2 Create `src/colonyos/instructions/sweep.md` with:
    - Staff Engineer persona definition (role, expertise, perspective)
    - Analysis categories: correctness/bugs, dead code, error handling gaps, structural complexity, consistency violations, missing tests
    - Impact (1-5) and Risk (1-5) scoring rubric with clear criteria
    - Output format: standard task file format compatible with `parse_task_file()` (with `## Relevant Files`, `## Tasks`, `depends_on:` annotations)
    - Explicit exclusions: no changes to auth/security code, secrets, DB schemas, public API signatures
    - Max-tasks cap instruction (parameterized as `{max_tasks}`)
    - Optional `{scan_context}` block for pre-computed structural scan data
    - Instruction to rank tasks by `impact * risk` descending

- [x] 3.0 Implement `run_sweep()` orchestration function
  depends_on: [1.0]
  - [x] 3.1 Write tests for `run_sweep()` in `tests/test_orchestrator.py`
    - Test analysis phase runs with read-only tools `["Read", "Glob", "Grep"]`
    - Test that analysis output is parsed as a task file
    - Test dry-run mode returns findings without calling `run()`
    - Test execute mode calls `run()` with `skip_planning=True` and the generated task file
    - Test `max_tasks` is passed to the instruction template
    - Test phase result is captured with correct `Phase.SWEEP` enum
  - [x] 3.2 Add `_build_sweep_prompt()` helper in `orchestrator.py`
    - Load `instructions/base.md` and `instructions/sweep.md`
    - Inject config values: `max_tasks`, `max_files_per_task`, `default_categories`
    - Optionally inject `scan_directory()` results as structural context
    - Inject target path (or "entire codebase") scope description
    - Return `(system_prompt, user_prompt)` tuple
  - [x] 3.3 Add `run_sweep()` function in `orchestrator.py`
    - Signature: `run_sweep(repo_root, config, *, target_path=None, max_tasks=None, execute=False, plan_only=False, verbose=False, quiet=False, force=False) -> tuple[str, PhaseResult]`
    - Call `run_phase_sync(Phase.SWEEP, ...)` with read-only tools
    - Parse the analysis output to extract the task file content
    - If dry-run: return findings text and phase result
    - If execute: write task file to `cOS_tasks/`, then call `run()` with `skip_planning=True` and reference to the task file
    - If plan_only: write task file and return without calling `run()`

- [x] 4.0 Implement the `sweep` CLI command
  depends_on: [3.0]
  - [x] 4.1 Write CLI integration tests in `tests/test_cli.py`
    - Test `sweep` command registers and shows help text
    - Test `sweep` with no args runs whole-codebase analysis (dry-run)
    - Test `sweep PATH` scopes to the given path
    - Test `--execute` flag triggers pipeline execution
    - Test `--plan-only` generates task file but stops
    - Test `--max-tasks N` overrides default
    - Test `--verbose` / `--quiet` flags pass through
    - Test error handling when config is missing
  - [x] 4.2 Add the `sweep` command to `cli.py` with Click decorators
    - `@app.command()` registration (top-level, peer to `run` and `auto`)
    - Positional `path` argument (optional, default None)
    - `--execute` flag (default False)
    - `--plan-only` flag (default False)
    - `--max-tasks` option (default from config)
    - `--verbose` / `--quiet` / `--no-tui` / `--force` flags (matching existing conventions)
  - [x] 4.3 Implement the command body
    - Load config via `load_config(repo_root)`
    - Validate target path exists (if provided)
    - Call `run_sweep()` from orchestrator
    - In dry-run mode: print Rich-formatted findings table (category, file, impact, risk, score, description)
    - In execute mode: print findings, then run pipeline, then call `_print_run_summary()`
    - Persist audit log via `write_cleanup_log()` with event type `"sweep"`
    - Handle `PreflightError` consistently with existing commands

- [x] 5.0 Add dry-run report formatting and audit logging
  depends_on: [3.0]
  - [x] 5.1 Write tests for report parsing and formatting
    - Test parsing structured findings from sweep agent output
    - Test Rich table rendering with all columns (finding #, category, files, impact, risk, score, description)
    - Test JSON audit log structure matches expected schema
  - [x] 5.2 Add a `parse_sweep_findings()` utility function
    - Parse the sweep agent's markdown output into a list of structured finding objects
    - Extract: category, file paths, impact score, risk score, description
    - Sort by `impact * risk` descending
  - [x] 5.3 Add Rich table formatting for the dry-run report
    - Reuse the pattern from `cleanup_scan` (line 3833 of `cli.py`) with columns: #, Category, File(s), Impact, Risk, Score, Description
    - Color-code by composite score: red (>=16), yellow (>=9), dim (<=4)
  - [x] 5.4 Wire audit logging through `write_cleanup_log()` with event type `"sweep"`

- [x] 6.0 End-to-end integration testing
  depends_on: [4.0, 5.0]
  - [x] 6.1 Write an integration test that runs `sweep` in dry-run mode against a test fixture directory and verifies the report output
  - [x] 6.2 Write an integration test that runs `sweep --execute --plan-only` and verifies a task file is written to `cOS_tasks/`
  - [x] 6.3 Write an integration test that verifies the generated task file is parseable by `parse_task_file()` from `dag.py`
  - [x] 6.4 Verify that `Phase.SWEEP` works correctly with `get_model()`, budget config, and phase result tracking
  - [x] 6.5 Run existing test suite to confirm no regressions
