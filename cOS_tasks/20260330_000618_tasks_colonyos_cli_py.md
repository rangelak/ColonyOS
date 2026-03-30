# Tasks: Refactor `cli.py` into a `cli/` Package

**PRD**: `cOS_prds/20260330_000618_prd_colonyos_cli_py.md`
**Date**: 2026-03-30

---

## Relevant Files

- `src/colonyos/cli.py` - The 5603-line monolith to be decomposed (will be deleted)
- `src/colonyos/cli/__init__.py` - New package init; re-exports `app` and all public/test-facing symbols
- `src/colonyos/cli/_app.py` - Click group definition, root command, welcome banner
- `src/colonyos/cli/_helpers.py` - Shared utilities (_find_repo_root, _tui_available, _load_dotenv, etc.)
- `src/colonyos/cli/_display.py` - Rich output helpers (_print_run_summary, _print_review_summary, _print_queue_summary)
- `src/colonyos/cli/_repl.py` - REPL loop (_run_repl, _repl_command_names, _invoke_cli_command, etc.)
- `src/colonyos/cli/_routing.py` - Prompt routing (RouteOutcome, _route_prompt, _handle_routed_query, _run_direct_agent, _run_review_only_flow, _run_cleanup_loop)
- `src/colonyos/cli/_run.py` - `run` command + _resolve_latest_prd_path
- `src/colonyos/cli/_review.py` - `review` command
- `src/colonyos/cli/_auto.py` - `auto` command + loop state management (_init_or_resume_loop, _save_loop_state, etc.)
- `src/colonyos/cli/_queue.py` - `queue` group + state management (add, start, status, clear, unpause, _save_queue_state, etc.)
- `src/colonyos/cli/_watch.py` - `watch` command + QueueExecutor, _DualUI, Slack event handlers
- `src/colonyos/cli/_memory.py` - `memory` group (list, search, delete, clear, stats)
- `src/colonyos/cli/_status.py` - `status` command
- `src/colonyos/cli/_simple_commands.py` - Small commands: doctor, init, stats, show, directions, ui, tui (deprecated)
- `src/colonyos/cli/_daemon.py` - `daemon` command + run_pipeline_for_queue_item
- `src/colonyos/cli/_ci_fix.py` - `ci-fix` command
- `src/colonyos/cli/_cleanup_cmd.py` - `cleanup` group (branches, artifacts, scan)
- `src/colonyos/cli/_sweep.py` - `sweep` command
- `src/colonyos/cli/_pr_review.py` - `pr-review` command
- `src/colonyos/cli/_tui_launcher.py` - _launch_tui function (large, ~400 lines)
- `tests/test_cli.py` - Primary CLI tests (~15 private imports + ~20 `patch()` targets)
- `tests/test_queue.py` - Imports `_save_queue_state`, `_load_queue_state`, `_is_nogo_verdict`
- `tests/test_preflight.py` - Imports `_ensure_on_main`
- `tests/test_router.py` - Imports `_handle_routed_query`
- `tests/test_standalone_review.py` - Imports `_print_review_summary`, `app`
- `tests/test_slack.py` - Imports CLI helpers
- `tests/test_sweep.py` - Imports CLI helpers
- `tests/tui/test_cli_integration.py` - Imports `_NEW_CONVERSATION_SIGNAL`, `_run_direct_agent`, `_handle_tui_command`
- `tests/tui/test_auto_in_tui.py` - Imports `_handle_tui_command`, `_AUTO_COMMAND_SIGNAL`
- `tests/test_cli_package.py` - New: structural tests for the cli package (imports, module sizes, etc.)
- `src/colonyos/daemon.py` - Imports `run_pipeline_for_queue_item` from `colonyos.cli`
- `src/colonyos/__main__.py` - Imports `app` from `colonyos.cli`

## Tasks

- [x] 1.0 Create `cli/` package foundation: `_app.py` and `_helpers.py`
  depends_on: []
  - [x] 1.1 Write `tests/test_cli_package.py` with structural tests: verify `colonyos.cli.app` is importable, verify `_find_repo_root` is importable from `colonyos.cli`, verify no file in `cli/` exceeds 800 lines
  - [x] 1.2 Create `src/colonyos/cli/` directory
  - [x] 1.3 Create `_app.py`: move Click group definition (`app`), `_show_welcome()`, version option from `cli.py` lines 265-284
  - [x] 1.4 Create `_helpers.py`: move `_find_repo_root`, `_tui_available`, `_interactive_stdio`, `_load_dotenv`, `_current_branch_name`, `_announce_mode_cli`, `_dirty_recovery_help` from `cli.py` lines 65-88, 246-264, 333-380
  - [x] 1.5 Create minimal `__init__.py` that imports `app` from `_app` and helpers from `_helpers`, re-exports them
  - [x] 1.6 Verify `colonyos.cli:app` entry point works with just the foundation

- [ ] 2.0 Extract display and REPL modules
  depends_on: [1.0]
  - [ ] 2.1 Create `_display.py`: move `_print_run_summary` (lines 90-141), `_print_review_summary` (lines 1258-1298), `_print_queue_summary` (lines 1490-1608), `_format_queue_item_source` (lines 1590-1608)
  - [ ] 2.2 Create `_repl.py`: move `_run_repl` (lines 793-1005), `_repl_command_names`, `_repl_top_level_names`, `_invoke_cli_command`, `_capture_click_output`, `_capture_click_output_and_result`, `_print_repl_help`, `_tui_command_hints` (lines 286-330, 528-630, 781-792)
  - [ ] 2.3 Create `_routing.py`: move `RouteOutcome` (lines 54-62), `_route_prompt` (lines 632-724), `_handle_routed_query` (lines 725-780), `_run_direct_agent` (lines 388-466), `_run_review_only_flow` (lines 467-497), `_run_cleanup_loop` (lines 498-527)
  - [ ] 2.4 Update `__init__.py` re-exports to include `RouteOutcome`, display helpers, REPL functions
  - [ ] 2.5 Run existing test suite to verify no regressions

- [ ] 3.0 Extract core command modules: `run`, `review`, `auto`
  depends_on: [2.0]
  - [ ] 3.1 Create `_run.py`: move `run` command (lines 1075-1251) and `_resolve_latest_prd_path` (lines 359-380)
  - [ ] 3.2 Create `_review.py`: move `review` command (lines 1300-1355)
  - [ ] 3.3 Create `_auto.py`: move `auto` command (lines 1836-1964), loop state helpers: `_init_or_resume_loop`, `_compute_elapsed_hours`, `_ensure_on_main`, `_run_single_iteration`, `_save_loop_state`, `_load_latest_loop_state` (lines 1360-1831)
  - [ ] 3.4 Update `__init__.py` to import command modules (triggers @app.command registration)
  - [ ] 3.5 Update re-exports: `_compute_elapsed_hours`, `_save_loop_state`, `_load_latest_loop_state`, `_resolve_latest_prd_path`
  - [ ] 3.6 Run test suite

- [ ] 4.0 Extract queue and watch modules
  depends_on: [2.0]
  - [ ] 4.1 Create `_queue.py`: move `queue` group + all subcommands (lines 2295-2598), state helpers: `_save_queue_state`, `_load_queue_state`, `_compute_queue_elapsed_hours`, `_is_nogo_verdict`, `_extract_pr_url_from_log` (lines 1409-1608)
  - [ ] 4.2 Create `_watch.py`: move `watch` command (lines 2770-3927) including QueueExecutor, _DualUI, all nested functions/closures
  - [ ] 4.3 Update `__init__.py` re-exports and command registration
  - [ ] 4.4 Run test suite (especially `test_queue.py`, `test_cli.py`)

- [ ] 5.0 Extract remaining command modules
  depends_on: [1.0]
  - [ ] 5.1 Create `_memory.py`: move `memory` group + subcommands (lines 2133-2288)
  - [ ] 5.2 Create `_status.py`: move `status` command (lines 1969-2127)
  - [ ] 5.3 Create `_simple_commands.py`: move `doctor` (lines 1007-1033), `init` (lines 1035-1073), `stats` cmd (lines 2601-2628), `show` cmd (lines 2635-2683), `directions` (lines 2690-2763), `ui` cmd (lines 4683-4724), deprecated `tui` cmd (lines 5574-5603)
  - [ ] 5.4 Create `_daemon.py`: move `daemon` command (lines 3977-4023) and `run_pipeline_for_queue_item` (lines 3933-3969)
  - [ ] 5.5 Create `_ci_fix.py`: move `ci-fix` command (lines 4030-4181)
  - [ ] 5.6 Create `_cleanup_cmd.py`: move `cleanup` group + subcommands (lines 4183-4524)
  - [ ] 5.7 Create `_sweep.py`: move `sweep` command (lines 4530-4677)
  - [ ] 5.8 Create `_pr_review.py`: move `pr-review` command (lines 4731-5147)
  - [ ] 5.9 Create `_tui_launcher.py`: move `_launch_tui` function (lines 5148-5572) + related constants/helpers (`_NEW_CONVERSATION_SIGNAL`, `_SAFE_TUI_COMMANDS`, `_handle_tui_command`)
  - [ ] 5.10 Update `__init__.py` with all re-exports
  - [ ] 5.11 Run test suite

- [ ] 6.0 Delete `cli.py` monolith and finalize `__init__.py`
  depends_on: [3.0, 4.0, 5.0]
  - [ ] 6.1 Ensure `__init__.py` has complete re-exports matching everything `tests/test_cli.py` imports: `app`, `RouteOutcome`, `_compute_elapsed_hours`, `_launch_tui`, `_load_latest_loop_state`, `_NEW_CONVERSATION_SIGNAL`, `_SAFE_TUI_COMMANDS`, `_handle_tui_command`, `_run_direct_agent`, `_run_cleanup_loop`, `_resolve_latest_prd_path`, `_save_loop_state`, `run_pipeline_for_queue_item`
  - [ ] 6.2 Verify `src/colonyos/daemon.py` import of `run_pipeline_for_queue_item` works
  - [ ] 6.3 Delete `src/colonyos/cli.py`
  - [ ] 6.4 Add `__all__` to `__init__.py` listing the public API
  - [ ] 6.5 Run full test suite (2294+ tests must pass)

- [ ] 7.0 Update ALL test files and add structural validation
  depends_on: [6.0]
  - [ ] 7.1 Run `grep -r "from colonyos.cli import" tests/` to find every import site (~80 across 10 files)
  - [ ] 7.2 Update import paths in `tests/test_cli.py` to import from specific sub-modules (not re-exports)
  - [ ] 7.3 Update import paths in `tests/test_queue.py`, `tests/test_preflight.py`, `tests/test_router.py`, `tests/test_standalone_review.py`, `tests/test_slack.py`, `tests/test_sweep.py`
  - [ ] 7.4 Update import paths in `tests/tui/test_cli_integration.py`, `tests/tui/test_auto_in_tui.py`
  - [ ] 7.5 **CRITICAL**: Update ALL `mock.patch("colonyos.cli._foo")` targets to point at the defining module (e.g., `mock.patch("colonyos.cli._helpers._find_repo_root")`). Re-export patches silently fail to mock the real code path.
  - [ ] 7.6 Finalize `tests/test_cli_package.py`: add tests that every sub-module is importable, that `app` has all expected commands registered, that no `cli/` file exceeds 800 lines
  - [ ] 7.7 Run `colonyos --version`, `colonyos doctor`, `colonyos --help` to verify entry point
  - [ ] 7.8 Run full test suite (2294+ tests must pass)
  - [ ] 7.9 Verify `pip install -e .` and entry point still works

- [ ] 8.0 Documentation and cleanup
  depends_on: [7.0]
  - [ ] 8.1 Add a brief module docstring to each new `cli/` file explaining its purpose
  - [ ] 8.2 Ensure no commented-out code or TODO placeholders remain
  - [ ] 8.3 Run pre-commit hooks (linting, formatting) on all new files
  - [ ] 8.4 Final test suite run
