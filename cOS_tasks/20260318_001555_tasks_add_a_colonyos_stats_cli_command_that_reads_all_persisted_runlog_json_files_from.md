# Tasks: `colonyos stats` CLI Command

## Relevant Files

- `src/colonyos/stats.py` - New module: data loading, aggregation logic, dataclasses for computed stats, and rich rendering functions
- `tests/test_stats.py` - New test module: unit tests for all stats computation and edge cases
- `src/colonyos/cli.py` - Add `stats` command to Click app group (import stats module, wire up options)
- `src/colonyos/models.py` - Existing RunLog, PhaseResult, Phase definitions (read-only reference, no changes expected)
- `src/colonyos/config.py` - Existing `runs_dir_path()` helper used for run log discovery
- `src/colonyos/ui.py` - Existing `_format_duration()` helper to reuse for duration display
- `tests/test_cli.py` - Add CLI-level tests for the `stats` command (Click runner invocations)

## Tasks

- [x] 1.0 Define stats data models (dataclasses for computed aggregates)
  - [x] 1.1 Write tests for stats dataclasses: `RunSummary`, `PhaseCostRow`, `PhaseFailureRow`, `ReviewLoopStats`, `DurationRow`, `RecentRunEntry`, `StatsResult` (the top-level container). Test default values and basic construction.
  - [x] 1.2 Implement dataclasses in `src/colonyos/stats.py`. `StatsResult` holds all computed sections as fields. All fields should be JSON-serializable types (for future `--json` support).

- [x] 2.0 Implement run log loading and filtering
  - [x] 2.1 Write tests for `load_run_logs(runs_dir: Path) -> list[dict]`: empty dir returns `[]`, single file returns one dict, corrupted JSON file is skipped (returns warning message), `loop_state_*.json` files are excluded, files sorted by `started_at` descending.
  - [x] 2.2 Write tests for `filter_runs(runs: list[dict], last: int | None, phase: str | None) -> list[dict]`: `--last 5` returns only 5 most recent, `--last` larger than run count returns all, `None` returns all.
  - [x] 2.3 Implement `load_run_logs()` in `stats.py`: glob `run-*.json`, parse each with `json.loads()`, skip corrupted files with stderr warning (following `cli.py:835-836` pattern), sort by `started_at` descending.
  - [x] 2.4 Implement `filter_runs()` in `stats.py`: apply `--last N` slicing.

- [x] 3.0 Implement aggregate computation functions
  - [x] 3.1 Write tests for `compute_run_summary(runs) -> RunSummary`: total runs, completed/failed counts, success/failure rates, total cost. Test with zero runs, one completed, one failed, mixed runs, and runs with `None` costs.
  - [x] 3.2 Write tests for `compute_cost_breakdown(runs) -> list[PhaseCostRow]`: per-phase total cost, avg cost, % of total. Test with single phase, multiple phases, `None` cost values excluded, phases with zero occurrences omitted.
  - [x] 3.3 Write tests for `compute_failure_hotspots(runs) -> list[PhaseFailureRow]`: per-phase execution count, failure count, failure rate. Sorted by failure rate descending. Test with all-success, all-failure, mixed.
  - [x] 3.4 Write tests for `compute_review_loop_stats(runs) -> ReviewLoopStats`: review round counting (contiguous blocks of `Phase.REVIEW`), first-pass approval rate (runs with no Fix phase), fix iteration count. Test with: no reviews, single review round with approval, multiple review-fix cycles, parallel reviews (4 review entries = 1 round).
  - [x] 3.5 Write tests for `compute_duration_stats(runs) -> list[DurationRow]`: avg duration per phase, avg total run duration. Test with `duration_ms=0`, single run, multiple runs.
  - [x] 3.6 Write tests for `compute_recent_trend(runs, count=10) -> list[RecentRunEntry]`: last N runs with status and cost. Test with fewer than 10 runs, exactly 10, more than 10.
  - [x] 3.7 Implement all `compute_*` functions in `stats.py`.
  - [x] 3.8 Implement top-level `compute_stats(runs, phase_filter) -> StatsResult` that calls all compute functions and returns the assembled result.

- [x] 4.0 Implement rich dashboard rendering
  - [x] 4.1 Write tests for rendering functions: verify they don't crash on empty/minimal `StatsResult` inputs and produce non-empty output. Use `rich.Console(file=StringIO())` to capture output.
  - [x] 4.2 Implement `render_run_summary(console, summary: RunSummary)` — Rich Panel with total runs, success rate, total cost.
  - [x] 4.3 Implement `render_cost_breakdown(console, rows: list[PhaseCostRow])` — Rich Table with Phase, Total Cost, Avg Cost/Run, % of Total columns.
  - [x] 4.4 Implement `render_failure_hotspots(console, rows: list[PhaseFailureRow])` — Rich Table with Phase, Executions, Failures, Failure Rate columns.
  - [x] 4.5 Implement `render_review_loop_stats(console, stats: ReviewLoopStats)` — Rich Panel with avg rounds, first-pass rate, totals.
  - [x] 4.6 Implement `render_duration_stats(console, rows: list[DurationRow])` — Rich Table using `_format_duration()` from `ui.py`.
  - [x] 4.7 Implement `render_recent_trend(console, entries: list[RecentRunEntry])` — Compact `✓`/`✗` timeline with per-run cost.
  - [x] 4.8 Implement `render_phase_detail(console, runs, phase_name)` — Per-run detail table for `--phase` filter, showing run_id, cost, duration, success for the specified phase only.
  - [x] 4.9 Implement `render_dashboard(console, result: StatsResult)` — Orchestrates all render functions in sequence.

- [x] 5.0 Wire up CLI command
  - [x] 5.1 Write CLI tests in `tests/test_cli.py`: invoke `stats` with Click test runner on empty dir (expect "No runs found"), on dir with one run file, with `--last 3` flag, with `--phase review` flag. Verify exit code 0 and expected output substrings.
  - [x] 5.2 Add `stats` command to `cli.py`: `@app.command()` with `--last` (int, optional) and `--phase` (str, optional) options. Import `stats` module, call `load_run_logs()`, `filter_runs()`, `compute_stats()`, `render_dashboard()`. Handle empty runs with "No runs found." message.

- [x] 6.0 Integration testing and polish
  - [x] 6.1 Run full test suite (`pytest`) to verify no regressions in existing tests.
  - [x] 6.2 Manual smoke test: run `colonyos stats` on the actual `.colonyos/runs/` directory in this repo and verify the dashboard renders correctly with real data.
  - [x] 6.3 Verify cost totals in dashboard match `sum(total_cost_usd)` from raw JSON files.
  - [x] 6.4 Verify `--last 5` correctly limits to 5 most recent runs.
