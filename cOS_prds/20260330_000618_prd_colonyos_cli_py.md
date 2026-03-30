# PRD: Refactor `cli.py` into a `cli/` Package

**Date**: 2026-03-30
**Status**: Draft
**Author**: ColonyOS Plan Phase

---

## 1. Introduction / Overview

`src/colonyos/cli.py` has grown to **5,603 lines** — a monolithic file containing 15+ Click commands, a full REPL, TUI launcher, Slack watch loop with a nested `QueueExecutor` class, queue/loop state management, display helpers, and dozens of private functions. Every new feature adds more surface area to this single file, making it harder to navigate, test, and maintain.

This PRD proposes splitting `cli.py` into a well-organized `cli/` package with focused sub-modules, each under 500 lines, while preserving the public entry point (`colonyos.cli:app`) and all existing behavior.

## 2. Goals

| # | Goal | Measurable Target |
|---|------|-------------------|
| G1 | **Reduce cognitive load** | No single file in `cli/` exceeds ~600 lines |
| G2 | **Preserve all behavior** | 100% of existing CLI tests pass without modification to test logic (only import paths change) |
| G3 | **Maintain entry point** | `colonyos.cli:app` continues to work (pyproject.toml unchanged) |
| G4 | **Improve test isolation** | Each sub-module is independently testable; new test files mirror module structure |
| G5 | **Zero runtime regressions** | All 2294+ tests pass; no new import errors in any code path |

## 3. User Stories

1. **As a contributor**, I want to find the `watch` command logic without scrolling through 5600 lines, so I can understand and modify Slack integration quickly.
2. **As a contributor**, I want to add a new CLI command by creating a focused file in `cli/`, not by appending to a 5600-line monolith.
3. **As a test author**, I want to test queue state management without importing the entire CLI surface and mocking unrelated subsystems.
4. **As a CI pipeline**, I want import-time to remain fast so `colonyos --help` stays sub-second.

## 4. Functional Requirements

### FR-1: Package Structure
Convert `src/colonyos/cli.py` into `src/colonyos/cli/__init__.py` + sub-modules:

```
src/colonyos/cli/
├── __init__.py          # Re-exports `app`, public helpers; preserves `colonyos.cli:app`
├── _app.py              # Click group definition, root command, version, welcome banner
├── _helpers.py          # Shared utilities: _find_repo_root, _tui_available, _interactive_stdio, _load_dotenv, _current_branch_name, _announce_mode_cli, _dirty_recovery_help
├── _display.py          # Rich output: _print_run_summary, _print_review_summary, _print_queue_summary, _format_queue_item_source
├── _repl.py             # REPL loop: _run_repl, _repl_command_names, _invoke_cli_command, _capture_click_output, _print_repl_help
├── _routing.py          # Prompt routing: _route_prompt, _handle_routed_query, RouteOutcome, _run_direct_agent, _run_review_only_flow, _run_cleanup_loop
├── _run.py              # `run` command + its helpers: _resolve_latest_prd_path
├── _review.py           # `review` command
├── _auto.py             # `auto` command + loop state: _init_or_resume_loop, _compute_elapsed_hours, _ensure_on_main, _run_single_iteration, _save_loop_state, _load_latest_loop_state
├── _queue.py            # `queue` group + state: add, start, status, clear, unpause, _save_queue_state, _load_queue_state, _compute_queue_elapsed_hours, _is_nogo_verdict, _extract_pr_url_from_log
├── _watch.py            # `watch` command + QueueExecutor, _DualUI, event handlers (~800 lines → largest module, but cohesive)
├── _memory.py           # `memory` group: list, search, delete, clear, stats
├── _status.py           # `status` command
├── _stats_cmd.py        # `stats` command (wraps colonyos.stats)
├── _show_cmd.py         # `show` command (wraps colonyos.show)
├── _directions.py       # `directions` command
├── _doctor.py           # `doctor` command
├── _init_cmd.py         # `init` command
├── _daemon.py           # `daemon` command + run_pipeline_for_queue_item
├── _ci_fix.py           # `ci-fix` command
├── _cleanup_cmd.py      # `cleanup` group: branches, artifacts, scan
├── _sweep.py            # `sweep` command
├── _ui_cmd.py           # `ui` command (web dashboard launcher)
├── _pr_review.py        # `pr-review` command
├── _tui_launcher.py     # _launch_tui + `tui` command
```

### FR-2: Public API Preservation
`src/colonyos/cli/__init__.py` must re-export:
- `app` — the Click group (entry point)
- `RouteOutcome` — used in tests
- All private helpers currently imported by `tests/test_cli.py`: `_compute_elapsed_hours`, `_launch_tui`, `_load_latest_loop_state`, `_NEW_CONVERSATION_SIGNAL`, `_SAFE_TUI_COMMANDS`, `_handle_tui_command`, `_run_direct_agent`, `_run_cleanup_loop`, `_resolve_latest_prd_path`, `_save_loop_state`
- `run_pipeline_for_queue_item` — used by `colonyos.daemon`

### FR-3: Command Registration
Each sub-module defines its Click commands/groups. `__init__.py` imports them to trigger `@app.command()` / `@app.group()` registration. The `app` Click group is defined in `_app.py` and imported first.

### FR-4: Lazy Imports Preserved
All existing lazy imports (e.g., `from rich.console import Console` inside function bodies, `from colonyos.slack import ...` inside `watch()`) must remain lazy to keep `colonyos --help` fast and avoid requiring optional dependencies at import time.

### FR-5: Test Migration
Update `tests/test_cli.py` imports to use the re-exports from `colonyos.cli` (no change needed if `__init__.py` re-exports everything). If any tests import from deeper paths, add deprecation-free re-exports.

### FR-6: Cross-Module References
Where sub-modules need shared state or helpers, they import from `_helpers.py`, `_display.py`, or `_app.py` (for the `app` group). Circular imports are avoided by:
- Defining `app` in `_app.py`
- Having command modules import `app` from `_app.py`
- Having `__init__.py` import command modules after importing `_app`

## 5. Non-Goals

- **Behavior changes**: No new features, no bug fixes, no UX changes. Pure structural refactor.
- **Config/model changes**: No changes to `config.py`, `models.py`, `orchestrator.py`, or any non-CLI module.
- **Test rewrite**: Test logic stays the same; only import paths are updated if re-exports aren't sufficient.
- **Click group restructuring**: The command hierarchy (top-level commands, `memory` subgroup, `queue` subgroup, `cleanup` subgroup) stays identical.
- **Performance optimization**: Not trying to speed anything up, just preserve current import-time behavior.

## 6. Technical Considerations

### 6.1 Entry Point
`pyproject.toml` defines `colonyos = "colonyos.cli:app"`. The `__init__.py` must export `app` so this continues to work without any pyproject.toml changes.

### 6.2 Circular Import Prevention
The main risk is circular imports. Strategy:
1. `_app.py` defines `app = click.group(...)` with zero colonyos imports
2. `_helpers.py` imports from `colonyos.config`, `colonyos.models` (no CLI imports)
3. Command modules import `app` from `._app` and helpers from `._helpers`
4. `__init__.py` imports `app` from `._app` first, then imports all command modules

### 6.3 The `watch` Command
At ~800 lines with nested classes (`QueueExecutor`, `_DualUI`) and closures, `watch()` is the largest single command. It should remain as one module (`_watch.py`) because:
- The `QueueExecutor` class captures variables from the enclosing `watch()` scope
- Splitting it would require significant refactoring of the closure-based architecture
- It's cohesive — all code serves the Slack watch loop

### 6.4 Shared State
Several functions are used across commands:
- `_find_repo_root()` — used by nearly every command
- `_save_queue_state()` / `_load_queue_state()` — used by `queue`, `watch`
- `_save_loop_state()` / `_load_latest_loop_state()` — used by `auto`
- Display helpers — used by `run`, `review`, `status`, `queue`

These go into `_helpers.py` (utilities), `_queue.py` (queue state), `_auto.py` (loop state), `_display.py` (Rich output).

### 6.5 Existing Module References
Other modules import from `colonyos.cli`:
- `colonyos.daemon` imports `run_pipeline_for_queue_item` from `colonyos.cli`
- `tests/test_cli.py` imports many private helpers

All must continue working via `__init__.py` re-exports.

### 6.6 Files Affected
- **Deleted**: `src/colonyos/cli.py`
- **Created**: `src/colonyos/cli/__init__.py` + ~22 sub-modules
- **Modified**: Multiple test files that import from `colonyos.cli`:
  - `tests/test_cli.py` — ~15 private symbol imports + ~20 `patch()` targets
  - `tests/test_queue.py` — imports `_save_queue_state`, `_load_queue_state`, `_is_nogo_verdict`
  - `tests/test_preflight.py` — imports `_ensure_on_main`
  - `tests/test_router.py` — imports `_handle_routed_query`
  - `tests/test_standalone_review.py` — imports `_print_review_summary`, `app`
  - `tests/test_slack.py` — imports CLI helpers
  - `tests/test_sweep.py` — imports CLI helpers
  - `tests/tui/test_cli_integration.py` — imports `_NEW_CONVERSATION_SIGNAL`, `_run_direct_agent`, `_handle_tui_command`
  - `tests/tui/test_auto_in_tui.py` — imports `_handle_tui_command`, `_AUTO_COMMAND_SIGNAL`
- **Modified**: `src/colonyos/__main__.py` — imports `app` (should work via `__init__.py` re-export)
- **Unchanged**: `pyproject.toml`, all other `src/colonyos/*.py` modules

## 7. Persona Synthesis (All 7 Complete)

### Areas of Unanimous Agreement
- **`cli/` package is the right approach** — all 7 personas reject "extract helpers" as a half-measure that leaves a 3000-line file with the same problem
- **`app` must remain the single public API** — `colonyos.cli:app` entry point is the only contract with users; everything else is internal
- **Lazy imports must be preserved and expanded** — optional deps (textual, slack-bolt, fastapi, rich) must stay function-scoped; Linus adds "but don't lazy-load your own 200-line modules — that's premature optimization"
- **Single atomic PR, zero behavioral changes** — unanimous that the refactor must be purely structural with no bug fixes or features mixed in; rollback = `git revert`
- **`watch` command deserves its own isolated module** — Security Engineer emphasizes trust boundary isolation (Slack credentials, threading); all agree it should not share a module with queue CRUD

### Areas of Strong Majority (5-6 of 7)
- **Update test imports directly** (Jobs, Seibel, Linus, Systems Eng, Security, Karpathy) rather than relying on re-exports as a permanent crutch. Systems Engineer adds the critical insight: `mock.patch()` targets must point at the defining module, not re-exports, or mocks silently stop working.
- **Merge state persistence into consuming modules** (Jobs, Linus, Systems Eng) — loop state belongs in `_auto.py`, queue state in `_queue.py`, not a separate `_state.py`. Counter: Ive and Karpathy prefer a dedicated `state.py`. **Decision**: merge into consuming modules (simpler, follows cohesion).
- **7-12 modules, not 22** (Seibel, Linus, Jobs, Karpathy) — merge trivially small commands into `_simple_commands.py`. **Decision**: adopted.

### Areas of Tension
- **Re-exports strategy**: Ive advocates re-exports first, migrate tests in second pass ("80 import sites atomically is error-prone"). Majority disagrees — "re-exports create two valid paths and nobody knows the canonical one." **Decision**: provide re-exports in `__init__.py` for safety, but update test imports and `patch()` targets in the same PR.
- **`RouteOutcome` location**: Systems Engineer suggests moving it to `models.py` since it's a dataclass. Others keep it with routing. **Decision**: keep in `_routing.py` — it's CLI-specific and used only by routing logic.
- **Karpathy's pluggability vision**: "Separate modules enable a future plugin system." All others: "Out of scope. Ship the refactor, don't design for hypotheticals." **Decision**: noted as future work.
- **Security Engineer's two-commit strategy**: Create `cli/` package first, delete old `cli.py` second, enabling targeted revert. Others prefer single atomic commit. **Decision**: single commit for simplicity; full test suite is the safety net.

## 8. Success Metrics

| Metric | Target |
|--------|--------|
| All existing tests pass | 2294+ tests green |
| No file in `cli/` exceeds 800 lines | Verified by CI lint check |
| `colonyos --help` latency unchanged | < 500ms (same as before) |
| `colonyos.cli:app` entry point works | Verified by `pip install -e . && colonyos --version` |
| Zero import errors across all code paths | Verified by running every CLI command |

## 9. Open Questions

1. **Should `_watch.py` be further decomposed?** At ~800 lines it's the largest module, but the nested class/closure architecture makes splitting risky. Recommend leaving it as-is for v1.
2. **Should we add `__all__` to `__init__.py`?** Helps document the public API but adds maintenance burden. Recommend yes.
3. **Should trivially small command modules be merged?** Linus's point is valid — `_doctor.py` at 30 lines and `_ui_cmd.py` at 40 lines could be merged. Recommend creating `_simple_commands.py` for commands under ~80 lines.
