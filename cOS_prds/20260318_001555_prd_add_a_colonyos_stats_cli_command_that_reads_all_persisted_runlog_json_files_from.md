# PRD: `colonyos stats` CLI Command — Aggregate Analytics Dashboard

## 1. Introduction / Overview

ColonyOS persists detailed run logs (cost, duration, phase success/failure) as JSON files in `.colonyos/runs/`, but there is no way to see aggregate analytics across runs. Users who have completed 5, 10, or 50 pipeline runs have no visibility into where their money goes, which phases fail most, or whether their review personas are well-calibrated.

The `colonyos stats` command fills this gap by reading all persisted `run-*.json` files and rendering a multi-section analytics dashboard using `rich` Tables and Panels. It answers the question every user eventually asks: *"Where did my money go, and is this pipeline working well?"*

## 2. Goals

- **Cost visibility**: Show users exactly where their budget is spent, broken down by phase (CEO, Plan, Implement, Review, Fix, Decision, Learn, Deliver).
- **Reliability insight**: Surface phase failure rates so users can identify if reviews are too strict, implement is flaky, or any phase is a bottleneck.
- **Review loop calibration**: Measure review/fix iteration counts and first-pass approval rates to help users tune their personas.
- **Trend awareness**: Show recent run success/fail patterns so users can spot regressions.
- **Graceful degradation**: Work correctly with zero runs, one run, corrupted files, and missing cost data.

## 3. User Stories

1. **As a first-time user**, after completing my first run, I type `colonyos stats` and see a simple dashboard showing my single run's cost breakdown by phase, so I understand where my $9 went.

2. **As a power user with 20+ runs**, I type `colonyos stats` and instantly see my aggregate success rate, total spend, and which phases consume the most budget, so I can decide whether to simplify my reviewer personas.

3. **As a user debugging a cost spike**, I type `colonyos stats --last 5` to compare my recent runs against historical averages and identify which phase drove the increase.

4. **As a user tuning review strictness**, I check the Review Loop Efficiency section to see that my first-pass approval rate is only 30%, indicating my reviewers may be over-indexing on style issues.

5. **As a user with an empty project**, I type `colonyos stats` and see a friendly "No runs found" message instead of a crash.

## 4. Functional Requirements

### FR-1: Run Summary Panel
- Display: total runs, completed count, failed count, success rate (%), failure rate (%), total cost (USD).
- Cost total must match `sum(run.total_cost_usd for all runs)`.

### FR-2: Cost Breakdown by Phase Table
- One row per phase that appears in the data (all `Phase` enum values: CEO, Plan, Implement, Review, Fix, Decision, Learn, Deliver).
- Columns: Phase name, Total Cost, Avg Cost/Run, % of Total Spend.
- Phases with zero occurrences are omitted from the table.
- `None` costs are excluded from sums/averages (following `RunLog.mark_finished()` convention at `models.py:101-103`).

### FR-3: Phase Failure Hotspots Table
- One row per phase showing: phase name, total executions, failure count, failure rate (%).
- Sorted by failure rate descending.
- Only phases with at least one execution are shown.

### FR-4: Review Loop Efficiency Panel
- Average number of review rounds per run (a "review round" = a contiguous block of `Phase.REVIEW` entries before a `Phase.DECISION` or `Phase.FIX`).
- First-pass approval rate: percentage of runs where the first review round led directly to approval (no Fix phase).
- Total review rounds across all runs, total fix iterations.

### FR-5: Duration Stats Table
- Average wall-clock time per phase (using `PhaseResult.duration_ms`).
- Average total run duration (from `started_at` to `finished_at`).
- Displayed in human-friendly format using the existing `_format_duration()` helper from `ui.py:183-188`.

### FR-6: Recent Trend Display
- Last 10 runs (by `started_at` timestamp) shown as a compact timeline: `✓` for completed, `✗` for failed, with cost per run.
- Respects `--last N` filter if provided.

### FR-7: Filtering Options
- `--last N`: Limit analysis to the N most recent runs (sorted by `started_at`).
- `--phase <name>`: Drill into a specific phase, showing per-run detail for that phase (cost, duration, success/fail for each run).

### FR-8: Graceful Edge Cases
- Zero runs: display "No runs found." and exit cleanly.
- Corrupted JSON files: skip with a stderr warning, continue processing remaining files (following the `status` command pattern at `cli.py:835-836`).
- `None` cost values: treat as zero for aggregation, display as "—" in detail views.
- Runs with `status=RUNNING` (in-progress): include in counts but flag as "(in progress)".

## 5. Non-Goals

- **Machine-readable output (`--json`)**: Designed for but not shipped in v1. The stats module will separate data computation from rendering so `--json` can be trivially added later.
- **Loop state analytics**: `loop_state_*.json` files are not consumed in v1. All data comes from individual `run-*.json` files.
- **Interactive drill-down**: No interactive TUI or clickable elements. This is a static dashboard.
- **Historical trend charts**: No sparklines or ASCII charts beyond the simple ✓/✗ timeline.
- **Prompt content display**: Stats does not show prompt text or session IDs. Users wanting per-run detail use `colonyos status` or read the JSON directly.

## 6. Technical Considerations

### Architecture: Separate Computation from Rendering

The `stats.py` module will be structured as two layers:
1. **Data layer**: Pure functions that load run logs, compute aggregates, and return typed dataclasses (not raw dicts). This makes the logic independently testable and prepares for future `--json` output.
2. **Rendering layer**: Functions that take the computed dataclasses and render them using `rich` Tables/Panels to stdout.

### Key Integration Points

| What | Where | How |
|------|-------|-----|
| Run log discovery | `config.runs_dir_path()` (`config.py:222`) | Reuse existing helper to find `.colonyos/runs/` |
| Run log parsing | `RunLog` / `PhaseResult` (`models.py:60-103`) | Deserialize from JSON using existing field names |
| Phase enum | `Phase` (`models.py:12-20`) | Iterate all enum values for completeness |
| Duration formatting | `_format_duration()` (`ui.py:183-188`) | Import and reuse directly |
| CLI registration | `cli.py` `app` group | Add `@app.command()` following `status` pattern |
| Error handling | `status` command (`cli.py:835-836`) | Follow `except (json.JSONDecodeError, KeyError)` pattern |

### Data Loading

Run logs are loaded by globbing `run-*.json` (excluding `loop_state_*.json`), parsing each with `json.loads()`, and sorting by `started_at` descending. This matches the pattern already used by the `status` command at `cli.py:794-797`.

### Review Round Counting Algorithm

Scan the `phases` list sequentially. A "review round" is a contiguous group of `Phase.REVIEW` entries (parallel reviewers share the same round). The round ends when a non-REVIEW phase (typically `Phase.DECISION` or `Phase.FIX`) is encountered. Count total rounds per run and check if any `Phase.FIX` appears to determine first-pass approval.

### Dependencies

No new dependencies. Uses `rich` (already in `pyproject.toml` as `rich>=13.0`) and `click` (already `click>=8.1`).

### Consistency with Existing Conventions

- Output to stdout via `click.echo` and `rich.Console()` (no `stderr=True`), matching `status` command behavior.
- `_format_duration` reused from `ui.py` (will need to be made importable if currently module-private — it's a module-level function, not class-private, so it's importable as `from colonyos.ui import _format_duration`).
- Corrupted file handling follows exact `status` command pattern.

## 7. Success Metrics

- `colonyos stats` renders all 6 dashboard sections with no errors on a project with 10+ runs.
- `colonyos stats` displays "No runs found." gracefully on a fresh project.
- Cost totals in the dashboard exactly match `sum(run.total_cost_usd)` across all loaded run logs.
- Review iteration counts correctly identify consecutive Review→Fix cycles from the `phases` list.
- `--last 5` correctly limits to the 5 most recent runs by `started_at`.
- `--phase review` shows per-run detail for review phases only.
- All new code has unit tests covering: empty dir, single run, multiple runs, mixed success/failure, null costs, corrupted files, review iteration counting, and `--last` filtering.
- All existing tests continue to pass.

## 8. Open Questions

1. **Persona agreement**: All 7 personas agree CEO phase must be included, `--json` should be designed-for but not shipped, and stdout is correct. No unresolved tension on core design.
2. **Review round vs. Review→Fix cycle**: The feature request says "Review→Fix cycles" but real data shows parallel reviews followed by a Decision (not always Fix). The implementation counts "review rounds" (contiguous blocks of Review phases) as the unit, which is more accurate.
3. **`_format_duration` visibility**: The function has a leading underscore suggesting it's private, but it's a module-level function that can be imported. Consider renaming to `format_duration` (public) in a follow-up if this pattern is reused more broadly.
4. **Security persona concern**: The security engineer flagged that session IDs and prompts should not appear in default stats output. The design already excludes them, so this is resolved.
