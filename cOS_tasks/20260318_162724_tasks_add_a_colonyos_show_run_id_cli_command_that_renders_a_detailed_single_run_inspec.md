# Tasks: `colonyos show <run-id>` — Single-Run Inspector

## Relevant Files

- `src/colonyos/show.py` - **New file**: Data-layer and render-layer for single-run inspection (following `stats.py` pattern)
- `tests/test_show.py` - **New file**: Unit tests for all data-layer functions and render smoke tests
- `src/colonyos/cli.py` - Add `show` Click command with `--json` and `--phase` flags
- `tests/test_cli.py` - Add CLI integration tests for the `show` command (argument handling, error cases)
- `src/colonyos/stats.py` - Existing file: reuse `load_run_logs()` for loading run files
- `src/colonyos/ui.py` - Existing file: reuse `_format_duration()` for duration formatting
- `src/colonyos/config.py` - Existing file: reuse `runs_dir_path()` for locating runs directory
- `src/colonyos/models.py` - Existing file: reference `RunLog`, `PhaseResult`, `Phase`, `RunStatus` types

## Tasks

- [x] 1.0 Define data-layer dataclasses and run resolution logic in `show.py`
  - [x] 1.1 Write tests for `resolve_run_id()` — exact match, prefix match, hash suffix match, zero matches (error), multiple matches (ambiguity), path traversal rejection (`/`, `\`, `..`)
  - [x] 1.2 Write tests for `load_single_run()` — valid file loading, missing file error, corrupted JSON handling
  - [x] 1.3 Implement `RunHeader`, `PhaseTimelineEntry`, `CollapsedReviewGroup`, `ReviewSummary`, `ShowResult` dataclasses
  - [x] 1.4 Implement `resolve_run_id(runs_dir: Path, partial_id: str) -> str | list[str]` — returns single run ID or list of ambiguous matches
  - [x] 1.5 Implement `load_single_run(runs_dir: Path, run_id: str) -> dict` — loads one run JSON file

- [x] 2.0 Implement data-layer compute functions in `show.py`
  - [x] 2.1 Write tests for `compute_run_header()` — extracts metadata, truncates prompt, computes wall-clock duration
  - [x] 2.2 Write tests for `collapse_phase_timeline()` — collapses contiguous review phases into summary entries, handles fix-round boundaries, preserves non-review phases as-is
  - [x] 2.3 Write tests for `compute_review_summary()` — counts review rounds, fix iterations, per-round review counts
  - [x] 2.4 Write tests for `compute_show_result()` — integration of all compute functions, conditional sections (decision, ci_fix only present when phases exist)
  - [x] 2.5 Implement `compute_run_header(run_data: dict) -> RunHeader`
  - [x] 2.6 Implement `collapse_phase_timeline(phases: list[dict]) -> list[PhaseTimelineEntry]` — the core collapsing logic for review groups
  - [x] 2.7 Implement `compute_review_summary(phases: list[dict]) -> ReviewSummary | None`
  - [x] 2.8 Implement `compute_show_result(run_data: dict, phase_filter: str | None) -> ShowResult`

- [x] 3.0 Implement render-layer functions in `show.py`
  - [x] 3.1 Write smoke tests for all render functions (no-crash, key content assertions using captured Console)
  - [x] 3.2 Implement `render_run_header(console, header: RunHeader)` — Rich Panel with status coloring, prompt truncation, timestamps
  - [x] 3.3 Implement `render_phase_timeline(console, entries: list[PhaseTimelineEntry])` — Rich Table with collapsed review groups visually distinct
  - [x] 3.4 Implement `render_review_summary(console, summary: ReviewSummary)` — Rich Panel with round/fix counts
  - [x] 3.5 Implement `render_artifact_links(console, header: RunHeader)` — file paths and URLs
  - [x] 3.6 Implement `render_show(console, result: ShowResult)` — orchestrates all render functions, skips empty sections
  - [x] 3.7 Implement `render_phase_detail(console, entries, phase_name)` — extended detail for `--phase` flag showing session_id, model, error

- [x] 4.0 Wire `show` command into CLI
  - [x] 4.1 Write CLI integration tests: `colonyos show <full-id>` renders output, `colonyos show <prefix>` resolves correctly, `colonyos show <bad-id>` prints error, `colonyos show <ambiguous>` lists matches, `colonyos show <id> --json` outputs valid JSON, `colonyos show <id> --phase review` shows filtered detail
  - [x] 4.2 Add `show` Click command in `cli.py` with positional `run_id` argument, `--json` flag, and `--phase` option
  - [x] 4.3 Implement command body: resolve run ID, load run, compute result, render (or JSON dump)
  - [x] 4.4 Handle error paths: no runs directory, no matches, ambiguous matches — each with clear error message and non-zero exit code

- [x] 5.0 Validate and finalize
  - [x] 5.1 Run full existing test suite (`pytest`) to verify zero regressions
  - [x] 5.2 Run new tests in `test_show.py` and `test_cli.py` additions
  - [x] 5.3 Manual smoke test: `colonyos show` against actual run files in `.colonyos/runs/` to verify rendering looks correct for real data (especially the 19-phase ci-fix run)
