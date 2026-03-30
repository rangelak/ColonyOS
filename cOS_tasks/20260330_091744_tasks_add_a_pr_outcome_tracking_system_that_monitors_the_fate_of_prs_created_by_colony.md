# Tasks: PR Outcome Tracking System

## Relevant Files

- `src/colonyos/outcomes.py` - New module: core outcome tracking logic (track_pr, poll_outcomes, compute_outcome_stats, format_outcome_summary)
- `tests/test_outcomes.py` - New test file: unit tests for the outcomes module
- `src/colonyos/orchestrator.py` - Modify: deliver phase integration (call track_pr after PR creation ~line 4342), CEO prompt injection (~line 1920)
- `src/colonyos/cli.py` - Modify: add `outcomes` and `outcomes poll` CLI commands
- `src/colonyos/stats.py` - Modify: add DeliveryOutcomeStats dataclass and render_delivery_outcomes renderer
- `tests/test_stats.py` - Modify: add tests for delivery outcome stats rendering
- `src/colonyos/daemon.py` - Modify: add outcome polling step in _tick() (~line 230)
- `tests/test_daemon.py` - Modify: add tests for outcome polling in daemon tick
- `src/colonyos/config.py` - Modify: add outcome_poll_interval_minutes to DaemonConfig
- `tests/test_config.py` - Modify: add tests for new daemon config field
- `src/colonyos/memory.py` - Reference: existing MemoryStore patterns, sanitization, memory.db schema
- `src/colonyos/github.py` - Reference: existing `gh` CLI subprocess patterns
- `src/colonyos/sanitize.py` - Reference: sanitize_ci_logs for untrusted PR comment text

## Tasks

- [x] 1.0 Core outcomes module — SQLite storage and tracking functions
  depends_on: []
  - [x] 1.1 Write tests for `OutcomeStore` class: test table creation, schema migration (table already exists), `track_pr()` persists a record, `get_outcomes()` returns all records, `get_open_outcomes()` returns only open records, `update_outcome()` changes status and timestamps
  - [x] 1.2 Write tests for `poll_outcomes()`: mock `gh pr view` subprocess calls, test status transitions (open→merged, open→closed), test close_context extraction and sanitization, test handling of `gh` CLI failures (log and continue), test skipping already-resolved PRs
  - [x] 1.3 Write tests for `compute_outcome_stats()`: test merge rate calculation, average time-to-merge, counts by status, empty outcomes case
  - [x] 1.4 Write tests for `format_outcome_summary()`: test compact string output, test token budget stays under ~500 tokens, test empty outcomes returns empty string
  - [x] 1.5 Implement `OutcomeStore` class in `src/colonyos/outcomes.py`: SQLite table `pr_outcomes` in `memory.db` with columns (id, run_id, pr_number, pr_url, branch_name, status, created_at, merged_at, closed_at, review_comment_count, ci_passed, labels, close_context, last_polled_at). Follow `MemoryStore._init_db` pattern for schema creation.
  - [x] 1.6 Implement `track_pr()` function: insert a new record with status='open' and current timestamp
  - [x] 1.7 Implement `poll_outcomes()` function: query all open outcomes, call `gh pr view <number> --json state,mergedAt,closedAt,reviews,comments,statusCheckRollup,labels` for each, update records. Extract close_context from last comment/review for closed PRs, sanitize with `sanitize_ci_logs`, cap at 500 chars.
  - [x] 1.8 Implement `compute_outcome_stats()` and `format_outcome_summary()`: aggregate metrics from the pr_outcomes table, format a compact CEO-injection string

- [x] 2.0 Config — add outcome_poll_interval_minutes to DaemonConfig
  depends_on: []
  - [x] 2.1 Write tests for new `outcome_poll_interval_minutes` field: test default value (30), test custom value from YAML, test validation (must be positive)
  - [x] 2.2 Add `outcome_poll_interval_minutes: int = 30` to `DaemonConfig` dataclass in `config.py`, add to DEFAULTS dict, add parsing/validation in `_parse_daemon_config`, add to `save_config` serialization

- [x] 3.0 Deliver phase integration — register PRs after creation
  depends_on: [1.0]
  - [x] 3.1 Write tests for deliver phase integration: mock `track_pr()`, verify it is called with correct args after successful deliver in `run()`, verify it is NOT called when deliver fails, verify it handles track_pr exceptions gracefully (log and continue)
  - [x] 3.2 In `orchestrator.py` `run()` function (~line 4342-4344), after `pr_url` is extracted from deliver artifacts, call `track_pr()` with the run_id, PR number (extracted via regex from pr_url), pr_url, and branch_name. Wrap in try/except to avoid blocking the pipeline on tracking failures.

- [x] 4.0 CEO prompt injection — inject outcome summary
  depends_on: [1.0]
  - [x] 4.1 Write tests for CEO prompt injection: verify outcome summary section appears in CEO prompt when outcomes exist, verify it is skipped when no outcomes, verify exception handling (format_outcome_summary failure doesn't break CEO prompt)
  - [x] 4.2 In `_build_ceo_prompt()` (~line 1920, after the prs_section block), add an `outcomes_section` block that calls `format_outcome_summary(repo_root)`, wraps it in `## PR Outcome History`, and appends to the user prompt. Follow the same try/except pattern as issues_section and prs_section.

- [x] 5.0 CLI commands — `colonyos outcomes` and `colonyos outcomes poll`
  depends_on: [1.0]
  - [x] 5.1 Write tests for CLI commands: test `outcomes` command displays a Rich table with correct columns, test `outcomes poll` calls poll_outcomes then displays table, test empty outcomes shows a helpful message, test error handling
  - [x] 5.2 Add `outcomes` command group to `cli.py`: `@app.group()` with `outcomes` name. Default command (no subcommand) shows the outcome table using Rich Table with columns: PR#, Status (colored), Branch, Age, Reviews, CI, Close Context. Use `OutcomeStore` to fetch records.
  - [x] 5.3 Add `outcomes poll` subcommand: calls `poll_outcomes(repo_root)`, then displays the updated table

- [ ] 6.0 Stats integration — Delivery Outcomes section in dashboard
  depends_on: [1.0]
  - [ ] 6.1 Write tests for stats integration: test `DeliveryOutcomeStats` dataclass, test `render_delivery_outcomes` produces expected Rich Panel output, test integration with `render_dashboard`
  - [ ] 6.2 Add `DeliveryOutcomeStats` dataclass to `stats.py` with fields: total_tracked, merged_count, closed_count, open_count, merge_rate, avg_time_to_merge_hours
  - [ ] 6.3 Add `compute_delivery_outcomes()` function that reads from `OutcomeStore` and returns `DeliveryOutcomeStats`
  - [ ] 6.4 Add `render_delivery_outcomes()` function that renders the stats as a Rich Panel, and call it from `render_dashboard()` after the parallelism section

- [ ] 7.0 Memory capture — store feedback from closed PRs as memory entries
  depends_on: [1.0]
  - [ ] 7.1 Write tests for memory capture: verify that when poll_outcomes detects open→closed transition, a MemoryEntry with category FAILURE is created with sanitized close_context, verify no memory is created for merged PRs, verify no memory for PRs closed without any reviewer comment
  - [ ] 7.2 In `poll_outcomes()`, after detecting a status change from open to closed (not merged), call `MemoryStore.add_memory()` with category=FAILURE, phase="deliver", text="PR #{number} closed without merge. Reviewer feedback: {close_context}". Use existing `MemoryStore` from `memory.py`.

- [ ] 8.0 Daemon integration — automatic outcome polling in _tick()
  depends_on: [1.0, 2.0]
  - [ ] 8.1 Write tests for daemon outcome polling: test that `_tick()` calls `_poll_pr_outcomes()` when interval elapsed, test it skips when interval not yet elapsed, test it handles exceptions gracefully (log and continue), test configurable interval from DaemonConfig
  - [ ] 8.2 Add `_last_outcome_poll_time: float = 0.0` to `Daemon.__init__`
  - [ ] 8.3 Add step 6 in `_tick()` after heartbeat: check `outcome_poll_interval_minutes`, call `_poll_pr_outcomes()` if elapsed, update timestamp. Follow the exact pattern of lines 204-208 (GitHub polling).
  - [ ] 8.4 Implement `_poll_pr_outcomes()` method: wraps `poll_outcomes(self.repo_root)` in try/except, logs warning on failure, no retry
