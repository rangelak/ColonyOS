# Tasks: `colonyos queue` — Durable Multi-Item Execution Queue

**PRD:** `cOS_prds/20260318_164532_prd_add_a_colonyos_queue_command_that_accepts_multiple_feature_prompts_and_or_github.md`

---

## Relevant Files

- `src/colonyos/models.py` - Add `QueueItemStatus`, `QueueItem`, `QueueState` dataclasses with serialization
- `src/colonyos/cli.py` - Add `queue` Click group with `add`, `start`, `status`, `clear` subcommands; update existing `status` command
- `src/colonyos/orchestrator.py` - No changes expected (queue calls existing `run()`)
- `src/colonyos/config.py` - `runs_dir_path()` reused for atomic write helpers; no changes expected
- `src/colonyos/github.py` - Reused for `fetch_issue()` at add-time validation and execution-time fetch; no changes expected
- `src/colonyos/sanitize.py` - Reused for issue content sanitization via `format_issue_as_prompt()`; no changes expected
- `.gitignore` - Add `.colonyos/queue.json` entry
- `tests/test_queue.py` - **New file**: Unit tests for queue data models, persistence, resume logic, budget enforcement
- `tests/test_cli.py` - Add integration tests for queue CLI commands

## Tasks

- [x] 1.0 Add queue data models to `src/colonyos/models.py`
  - [x] 1.1 Write tests for `QueueItemStatus`, `QueueItem`, and `QueueState` dataclasses in `tests/test_queue.py` — cover `to_dict()` / `from_dict()` round-trip serialization, status enum parsing, and default values
  - [x] 1.2 Implement `QueueItemStatus` enum with values: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `REJECTED`
  - [x] 1.3 Implement `QueueItem` dataclass with fields: `id`, `source_type`, `source_value`, `status`, `added_at`, `run_id`, `cost_usd`, `duration_ms`, `pr_url`, `error`, `issue_title`; include `to_dict()` and `from_dict()` methods
  - [x] 1.4 Implement `QueueState` dataclass with fields: `queue_id`, `items`, `aggregate_cost_usd`, `start_time_iso`, `status`; include `to_dict()` and `from_dict()` methods

- [x] 2.0 Implement queue persistence layer (save/load/atomic writes)
  - [x] 2.1 Write tests for `_save_queue_state()` and `_load_queue_state()` in `tests/test_queue.py` — cover: writing to non-existent directory, round-trip read/write, loading when no file exists (returns empty state), crash safety (atomic rename)
  - [x] 2.2 Implement `_save_queue_state(repo_root, state)` in `src/colonyos/cli.py` using the atomic tempfile + `os.replace` pattern from `_save_loop_state()` (line 555), writing to `.colonyos/queue.json`
  - [x] 2.3 Implement `_load_queue_state(repo_root)` that reads `.colonyos/queue.json` or returns `None` if absent
  - [x] 2.4 Add `.colonyos/queue.json` to `.gitignore`

- [x] 3.0 Implement `colonyos queue add` command
  - [x] 3.1 Write tests for the `add` command in `tests/test_queue.py` — cover: adding free-text prompts, adding issue refs (mock `fetch_issue`), mixed prompts + issues, appending to existing queue, validation of empty input
  - [x] 3.2 Register `queue` Click group on the `app` group in `src/colonyos/cli.py`
  - [x] 3.3 Implement `queue add` subcommand: accept positional args (prompts) and `--issue` option (multiple), validate issue refs via `fetch_issue()`, create `QueueItem` entries with status PENDING, persist to queue state, print confirmation with count

- [x] 4.0 Implement `colonyos queue start` command (core execution loop)
  - [x] 4.1 Write tests for the queue execution loop in `tests/test_queue.py` — cover: processing pending items sequentially (mock `run_orchestrator`), skipping completed/failed/rejected items on resume, marking items as completed/failed/rejected based on pipeline result, aggregate cost accumulation
  - [x] 4.2 Implement `queue start` subcommand with `--max-cost` and `--max-hours` options
  - [x] 4.3 Implement the execution loop: iterate over pending items, for each: mark running → call `run_orchestrator()` → inspect `RunLog.status` and decision verdict → mark completed/failed/rejected → update cost/duration/pr_url → persist state after each item
  - [x] 4.4 Implement budget and time cap enforcement: check aggregate cost against `--max-cost` and elapsed time against `--max-hours` before each item; halt gracefully when exceeded
  - [x] 4.5 Implement issue re-fetch at execution time: for issue-sourced items, call `fetch_issue()` + `format_issue_as_prompt()` to get latest content before passing to orchestrator
  - [x] 4.6 Handle SIGINT/crash gracefully: current item stays "running" (or revert to "pending"), persist state before exit so next `start` resumes correctly

- [x] 5.0 Implement `colonyos queue status` command
  - [x] 5.1 Write tests for status rendering in `tests/test_queue.py` — cover: empty queue, mixed statuses, prompt truncation, issue title display
  - [x] 5.2 Implement `queue status` subcommand: load queue state, render a Rich table with columns (Position, Source, Status, Cost, Duration, PR URL), show aggregate totals row

- [x] 6.0 Implement `colonyos queue clear` command
  - [x] 6.1 Write tests for clear in `tests/test_queue.py` — cover: clearing pending items, preserving non-pending items, clearing an empty queue
  - [x] 6.2 Implement `queue clear` subcommand: filter out PENDING items from queue state, persist, print count of removed items

- [x] 7.0 Implement end-of-queue summary and integrate with `colonyos status`
  - [x] 7.1 Write tests for summary table rendering and `status` command queue integration in `tests/test_queue.py`
  - [x] 7.2 Implement `_print_queue_summary(state)` helper: Rich table showing all items with status, cost, duration, PR URLs; aggregate row with total cost, total duration, success/fail/rejected counts
  - [x] 7.3 Call `_print_queue_summary()` at the end of `queue start` after all items processed (or budget/time cap hit)
  - [x] 7.4 Update existing `status` command (line 896 of `cli.py`) to check for `.colonyos/queue.json` and print a one-line summary (e.g., "Queue: 3/5 completed, $12.34 spent")

- [x] 8.0 End-to-end integration and edge-case tests
  - [x] 8.1 Write integration test: add items → start (with mocked orchestrator) → verify queue.json state → verify summary output
  - [x] 8.2 Write test: interrupted queue resumes correctly (add 3 items, mark first as completed, start → should skip first, process second)
  - [x] 8.3 Write test: budget cap halts queue mid-execution (set --max-cost low, verify remaining items stay pending)
  - [x] 8.4 Write test: failed item does not block subsequent items (mock orchestrator to fail on item 2, verify item 3 still runs)
  - [x] 8.5 Write test: rejected item (NO-GO verdict) marked as rejected, not failed, and queue continues
