# Tasks: `colonyos cleanup` — Codebase Hygiene & Structural Analysis

## Relevant Files

- `src/colonyos/cleanup.py` - **New** — Core cleanup logic: branch pruning, artifact cleanup, static scan functions
- `src/colonyos/cli.py` - Add `cleanup` Click command group with `branches`, `artifacts`, `scan` subcommands
- `src/colonyos/config.py` - Add `CleanupConfig` dataclass; wire into `ColonyConfig` with defaults
- `src/colonyos/models.py` - Reference for existing patterns (`Phase`, `RunLog`, `PreflightResult`)
- `src/colonyos/github.py` - Reuse `check_open_pr()` for safe branch deletion
- `src/colonyos/doctor.py` - Reference for standalone module pattern (similar architecture)
- `src/colonyos/agent.py` - Reuse `run_phase()` for AI scan (`--ai` flag)
- `src/colonyos/ui.py` - Reference for Rich formatting patterns
- `src/colonyos/instructions/cleanup_scan.md` - **New** — AI scan instruction template
- `tests/test_cleanup.py` - **New** — Comprehensive tests for all cleanup functionality
- `tests/test_cli.py` - Add integration tests for `cleanup` CLI commands
- `tests/conftest.py` - Add shared fixtures for cleanup tests (temp repos with branches)

## Tasks

- [x] 1.0 Add `CleanupConfig` to configuration system
  - [x] 1.1 Write tests for `CleanupConfig` parsing, defaults, and config.yaml round-tripping in `tests/test_cleanup.py`
  - [x] 1.2 Create `CleanupConfig` dataclass in `src/colonyos/config.py` with fields: `branch_retention_days` (int, default 0), `artifact_retention_days` (int, default 30), `scan_max_lines` (int, default 500), `scan_max_functions` (int, default 20)
  - [x] 1.3 Add `cleanup: CleanupConfig` field to `ColonyConfig` dataclass
  - [x] 1.4 Wire `CleanupConfig` parsing into `load_config()` with fallback to defaults

- [x] 2.0 Implement branch cleanup module (`cleanup.py`)
  - [x] 2.1 Write tests for branch discovery: `list_merged_branches()` should return branches merged into main, filtered by prefix, excluding current branch and main
  - [x] 2.2 Write tests for branch safety checks: branches with open PRs are excluded, current branch is excluded, main/master is excluded
  - [x] 2.3 Write tests for branch deletion: local delete via `git branch -d`, remote delete via `git push --delete origin`, error handling for failed deletions
  - [x] 2.4 Implement `list_merged_branches(repo_root, prefix, include_all)` — runs `git branch --merged` and filters results
  - [x] 2.5 Implement `check_branch_safety(branch, repo_root)` — validates branch is not current, not main, has no open PR (using `github.py`)
  - [x] 2.6 Implement `delete_branches(branches, repo_root, include_remote, execute)` — dry-run by default, deletes when `execute=True`, returns structured result
  - [x] 2.7 Implement `_get_branch_metadata(branch, repo_root)` — returns last commit date and author for display

- [x] 3.0 Implement artifact cleanup in `cleanup.py`
  - [x] 3.1 Write tests for artifact discovery: `list_stale_artifacts(runs_dir, retention_days)` finds old completed runs, skips RUNNING runs
  - [x] 3.2 Write tests for artifact deletion: removes directories, calculates reclaimed space, handles permission errors
  - [x] 3.3 Implement `list_stale_artifacts(runs_dir, retention_days)` — scans `.colonyos/runs/` for old `RunLog` JSON files, parses timestamps, filters by retention
  - [x] 3.4 Implement `delete_artifacts(artifacts, execute)` — dry-run by default, deletes directories when `execute=True`, returns summary with bytes reclaimed

- [x] 4.0 Implement structural scan in `cleanup.py`
  - [x] 4.1 Write tests for static file analysis: `scan_file_complexity(path)` returns line count, function count; `scan_directory(root, thresholds)` returns flagged files
  - [x] 4.2 Write tests for threshold filtering: files under threshold are excluded, files over threshold are categorized (large/very-large/massive)
  - [x] 4.3 Implement `scan_file_complexity(path)` — counts lines and functions (using regex for `def `, `function `, `class `, etc. based on file extension)
  - [x] 4.4 Implement `scan_directory(root, max_lines, max_functions, exclude_patterns)` — walks source tree, skips `.git`, `node_modules`, `__pycache__`, returns sorted list of flagged files
  - [x] 4.5 Implement complexity categorization: large (1-2x threshold), very-large (2-3x), massive (3x+)

- [x] 5.0 Create AI scan instruction template
  - [x] 5.1 Create `src/colonyos/instructions/cleanup_scan.md` following the pattern of existing instruction files (`plan.md`, `review.md`)
  - [x] 5.2 Include explicit constraints: no file modifications, no commits, output structured markdown report, forbidden from touching auth/sanitization/security files
  - [x] 5.3 Include scoring rubric: each finding should have impact (1-5) and risk (1-5) scores
  - [x] 5.4 Define output format: markdown report with sections for dead code, naming issues, architectural suggestions, and a prioritized action list

- [x] 6.0 Add CLI commands to `cli.py`
  - [x] 6.1 Write CLI integration tests in `tests/test_cli.py` for: `cleanup` (shows help), `cleanup branches` (dry-run output), `cleanup branches --execute`, `cleanup artifacts`, `cleanup scan`
  - [x] 6.2 Add `@app.group() cleanup` command group
  - [x] 6.3 Add `cleanup branches` subcommand with options: `--execute`, `--include-remote`, `--all-branches`, `--prefix TEXT`
  - [x] 6.4 Add `cleanup artifacts` subcommand with options: `--execute`, `--retention-days INT`
  - [x] 6.5 Add `cleanup scan` subcommand with options: `--max-lines INT`, `--max-functions INT`, `--ai`, `--refactor FILE`
  - [x] 6.6 Implement Rich-formatted output tables for all subcommands (consistent with `_print_run_summary` pattern)
  - [x] 6.7 Implement audit logging: write cleanup results to `.colonyos/runs/cleanup_<timestamp>.json`

- [x] 7.0 Implement `--refactor` delegation to existing pipeline
  - [x] 7.1 Write tests for prompt synthesis: given a file path and scan results, generates a focused refactoring prompt
  - [x] 7.2 Implement `synthesize_refactor_prompt(file_path, scan_results)` — creates a prompt like "Refactor src/foo.py: split the 800-line file into focused modules, reduce function complexity"
  - [x] 7.3 Wire `cleanup scan --refactor FILE` to call `run_orchestrator()` with the synthesized prompt, inheriting all config (budget, phases, model, personas)

- [x] 8.0 Documentation and integration testing
  - [x] 8.1 Add `cleanup` section to `.colonyos/config.yaml` defaults in `config.py` DEFAULTS dict
  - [x] 8.2 Write end-to-end test: create a temp repo with merged branches and large files, run `cleanup branches --execute` and `cleanup scan`, verify correct output
  - [x] 8.3 Verify all existing tests still pass (no regressions from config changes)
  - [x] 8.4 Update CHANGELOG.md with the new cleanup command
