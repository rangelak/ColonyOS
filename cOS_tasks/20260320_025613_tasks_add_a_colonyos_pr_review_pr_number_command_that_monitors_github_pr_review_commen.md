# Tasks: `colonyos pr-review` Command

## Relevant Files

### Files to Modify

- `src/colonyos/cli.py` - Add `pr-review` command with `--watch` and `--poll-interval` options
- `src/colonyos/models.py` - Add `"pr_review_fix"` to `source_type` documentation, potentially add `review_comment_id` field to `QueueItem`
- `src/colonyos/config.py` - Add `PRReviewConfig` dataclass with `pr_review_budget_per_pr` and related settings

### Files to Create

- `src/colonyos/pr_review.py` - New module for PR review comment fetching, filtering, state management, and GitHub reply posting
- `src/colonyos/instructions/thread_fix_pr_review.md` - Instruction template variant for PR review context
- `tests/test_pr_review.py` - Unit tests for PR review module

### Files to Reference (Read-Only Patterns)

- `src/colonyos/orchestrator.py` - `run_thread_fix()` implementation (lines 1690-1940), HEAD SHA verification (lines 1810-1819)
- `src/colonyos/slack.py` - `SlackWatchState` dataclass (lines 504-620), triage agent `triage_message()` (lines 770-860), `should_process_thread_fix()` (lines 201-252)
- `src/colonyos/ci.py` - `gh api` usage patterns (lines 61-108, 126-160)
- `src/colonyos/sanitize.py` - `sanitize_untrusted_content()` for input sanitization
- `tests/test_slack.py` - Test patterns for watch state, triage parsing, thread-fix detection

---

## Tasks

- [x] 1.0 Create `PRReviewState` dataclass and persistence
  - [x] 1.1 Write tests for `PRReviewState.to_dict()`, `from_dict()`, processed comment deduplication
  - [x] 1.2 Create `src/colonyos/pr_review.py` with `PRReviewState` dataclass mirroring `SlackWatchState` pattern
  - [x] 1.3 Implement `save_pr_review_state()` and `load_pr_review_state()` functions with atomic writes
  - [x] 1.4 Add `processed_comment_ids: dict[str, str]` for comment_id → run_id mapping
  - [x] 1.5 Add `cumulative_cost_usd`, `fix_rounds`, `consecutive_failures`, `queue_paused` fields

- [x] 2.0 Implement GitHub PR review comment fetching
  - [x] 2.1 Write tests for `fetch_pr_review_comments()` with mock `gh api` responses
  - [x] 2.2 Implement `fetch_pr_review_comments(pr_number, repo_root)` using `gh api repos/{owner}/{repo}/pulls/{pr}/comments`
  - [x] 2.3 Implement `fetch_pr_state(pr_number, repo_root)` to check open/closed/merged status
  - [x] 2.4 Filter to inline comments only (those with `path` and `line` fields)
  - [x] 2.5 Parse `created_at` timestamps for incremental processing

- [x] 3.0 Implement comment triage and actionability classification
  - [x] 3.1 Write tests for `triage_pr_review_comment()` with various comment types
  - [x] 3.2 Adapt existing `triage_message()` from slack.py to work with PR review comment format
  - [x] 3.3 Implement `triage_pr_review_comment(comment_body, file_path, line_number, repo_root)` wrapper
  - [x] 3.4 Add sanitization of comment body via `sanitize_untrusted_content()` before triage
  - [x] 3.5 Return `TriageResult` with `actionable`, `confidence`, `summary`, `reasoning` fields

- [x] 4.0 Implement GitHub reply posting
  - [x] 4.1 Write tests for `post_pr_review_reply()` with mock `gh api` calls
  - [x] 4.2 Implement `post_pr_review_reply(pr_number, comment_id, message, repo_root)` for comment thread replies
  - [x] 4.3 Implement `post_pr_summary_comment(pr_number, message, repo_root)` for PR-level summaries
  - [x] 4.4 Format reply messages: "Fixed in [`{sha}`]({commit_url}): {summary}"
  - [x] 4.5 Format summary messages: "Applied fixes for N review comments. Commits: ..."

- [x] 5.0 Add `PRReviewConfig` to configuration
  - [x] 5.1 Write tests for `PRReviewConfig` parsing from YAML
  - [x] 5.2 Add `PRReviewConfig` dataclass to `src/colonyos/config.py` with fields:
    - `pr_review_budget_per_pr: float = 5.0`
    - `max_fix_rounds_per_pr: int = 3`
    - `poll_interval_seconds: int = 60`
    - `circuit_breaker_threshold: int = 3`
    - `circuit_breaker_cooldown_minutes: int = 15`
  - [x] 5.3 Update `ColonyConfig` to include optional `pr_review: PRReviewConfig` field
  - [x] 5.4 Update `load_config()` and `save_config()` to handle PR review config

- [x] 6.0 Create instruction template for PR review fixes
  - [x] 6.1 Create `src/colonyos/instructions/thread_fix_pr_review.md` based on `thread_fix.md`
  - [x] 6.2 Add security note about untrusted PR review comment input
  - [x] 6.3 Include placeholders for `{comment_body}`, `{file_path}`, `{line_number}`, `{reviewer_username}`, `{comment_url}`
  - [x] 6.4 Ensure commit message format includes "Address review feedback from @{username}"

- [x] 7.0 Implement core `pr-review` CLI command
  - [x] 7.1 Write integration tests for `pr-review` command invocation
  - [x] 7.2 Add `@app.command()` for `pr-review` in `cli.py` with arguments:
    - `pr_number: int` (required positional)
    - `--watch: bool` flag
    - `--poll-interval: int` (default from config)
    - `--max-cost: float` (override per-PR budget)
    - `-v/--verbose`, `-q/--quiet` flags
  - [x] 7.3 Implement single-run mode: fetch comments, triage, fix actionable ones, post replies
  - [x] 7.4 Verify PR is open before processing (exit gracefully if merged/closed)
  - [x] 7.5 Integrate with existing `run_thread_fix()` for fix execution

- [x] 8.0 Implement watch mode loop
  - [x] 8.1 Write tests for watch mode polling and deduplication
  - [x] 8.2 Implement polling loop with configurable interval
  - [x] 8.3 Track `watch_started_at` timestamp to filter to new comments only
  - [x] 8.4 Persist `PRReviewState` after each poll cycle
  - [x] 8.5 Handle graceful shutdown on SIGINT/SIGTERM

- [x] 9.0 Implement safety guards
  - [x] 9.1 Write tests for HEAD SHA verification, budget cap, circuit breaker
  - [x] 9.2 Add HEAD SHA verification before each fix (fetch PR head SHA via `gh api`, compare to local)
  - [x] 9.3 Implement per-PR cumulative budget cap with halt and comment posting
  - [x] 9.4 Implement max fix rounds per PR limit
  - [x] 9.5 Implement consecutive failure circuit breaker (pause queue, post warning)
  - [x] 9.6 Add conflict detection on push failure (post comment, skip fix)

- [x] 10.0 Add `source_type="pr_review_fix"` state tracking
  - [x] 10.1 Write tests for QueueItem creation with PR review metadata
  - [x] 10.2 Update `QueueItem` usage in `run_thread_fix()` call to pass `source_type="pr_review_fix"`
  - [x] 10.3 Add `review_comment_id: str | None` field to `QueueItem` (bump `SCHEMA_VERSION`)
  - [x] 10.4 Store `pr_number` in `QueueItem.source_value` for analytics
  - [x] 10.5 Update `colonyos status` to show PR review fix summaries

- [x] 11.0 Documentation and polish
  - [x] 11.1 Add `pr-review` command to CLI help text
  - [x] 11.2 Update README with PR review workflow example
  - [x] 11.3 Add config example for `pr_review` section in `.colonyos/config.yaml`
  - [x] 11.4 Run full test suite and fix any regressions
