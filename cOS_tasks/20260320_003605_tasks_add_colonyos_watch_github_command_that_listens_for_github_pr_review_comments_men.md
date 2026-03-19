# Tasks: `colonyos watch-github` — GitHub PR Review Comment Watcher

**Generated:** 2026-03-20T00:36:05Z
**PRD:** `cOS_prds/20260320_003605_prd_add_colonyos_watch_github_command_that_listens_for_github_pr_review_comments_men.md`

---

## Relevant Files

### Existing files to modify
- `src/colonyos/config.py` - Add `GithubWatcherConfig` dataclass and parser (mirrors `SlackConfig` at lines 93-108)
- `src/colonyos/cli.py` - Add `watch-github` command (mirror `watch` command pattern)
- `src/colonyos/models.py` - Document `source_type="github_review"` in `QueueItem` docstring
- `src/colonyos/sanitize.py` - Add `sanitize_github_comment()` function (reuse existing patterns)
- `tests/test_config.py` - Add tests for `GithubWatcherConfig` parsing and validation

### New files to create
- `src/colonyos/github_watcher.py` - Main watcher module: polling, filtering, context extraction, state management
- `tests/test_github_watcher.py` - Unit tests for all watcher functionality
- `src/colonyos/instructions/github_fix.md` - Instruction template for GitHub-triggered fixes (optional, may reuse `thread_fix.md`)

### Reference files (read-only, for pattern reuse)
- `src/colonyos/slack.py` - `SlackWatchState`, `should_process_message()`, `format_slack_as_prompt()`, `SlackUI` patterns
- `src/colonyos/github.py` - `gh` CLI usage, `check_open_pr()`, sanitization imports
- `src/colonyos/orchestrator.py` - `run_thread_fix()`, `_build_thread_fix_prompt()`, `validate_branch_exists()`

---

## Tasks

- [x] 1.0 Add `GithubWatcherConfig` to configuration system
  - [x] 1.1 Write tests in `tests/test_config.py` for `GithubWatcherConfig` parsing — cover `enabled`, `bot_username`, `max_runs_per_hour`, `daily_budget_usd`, `polling_interval_seconds`, `max_consecutive_failures`, `circuit_breaker_cooldown_minutes` fields; test validation errors for invalid values
  - [x] 1.2 Add `GithubWatcherConfig` dataclass to `src/colonyos/config.py` mirroring `SlackConfig` structure (lines 93-108)
  - [x] 1.3 Add `_parse_github_watcher_config()` function with validation (mirror `_parse_slack_config()` at lines 174-235)
  - [x] 1.4 Add `github: GithubWatcherConfig` field to `ColonyConfig` dataclass
  - [x] 1.5 Update `load_config()` to parse `github` section from YAML
  - [x] 1.6 Update `save_config()` to serialize `github` section when non-default

- [x] 2.0 Create GitHub comment sanitization and formatting utilities
  - [x] 2.1 Write tests in `tests/test_sanitize.py` for `sanitize_github_comment()` — test XML tag stripping, character limits, edge cases
  - [x] 2.2 Add `sanitize_github_comment(text: str) -> str` to `src/colonyos/sanitize.py` — reuse `sanitize_untrusted_content()` with 2000 char cap
  - [x] 2.3 Write tests for `format_github_comment_as_prompt()` — verify role-anchoring preamble, delimiter wrapping, context fields
  - [x] 2.4 Add `format_github_comment_as_prompt()` to `src/colonyos/github_watcher.py` — include PR number, file path, line number, diff hunk, sanitized comment

- [x] 3.0 Implement `GithubWatchState` deduplication and rate limiting
  - [x] 3.1 Write tests in `tests/test_github_watcher.py` for `GithubWatchState` — test `is_processed()`, `mark_processed()`, `check_rate_limit()`, `reset_daily_cost_if_needed()`, serialization/deserialization
  - [x] 3.2 Create `GithubWatchState` dataclass in `src/colonyos/github_watcher.py` mirroring `SlackWatchState` (lines 513-593 of `slack.py`)
  - [x] 3.3 Implement `save_github_watch_state()` and `load_github_watch_state()` with atomic temp+rename pattern
  - [x] 3.4 Implement `check_rate_limit()` and `increment_hourly_count()` functions

- [x] 4.0 Implement GitHub API polling and filtering
  - [x] 4.1 Write tests for `fetch_open_prs()` — mock `gh` CLI, test pagination, error handling
  - [x] 4.2 Implement `fetch_open_prs(repo_root: Path) -> list[dict]` using `gh api repos/:owner/:repo/pulls?state=open`
  - [x] 4.3 Write tests for `fetch_pr_comments()` — mock `gh` CLI, test filtering by timestamp
  - [x] 4.4 Implement `fetch_pr_comments(pr_number: int, repo_root: Path, since: str | None) -> list[PRComment]`
  - [x] 4.5 Write tests for `should_process_comment()` — test branch prefix, PR state, bot mention, write access, dedup
  - [x] 4.6 Implement `should_process_comment(comment: PRComment, config: GithubWatcherConfig, state: GithubWatchState) -> bool`

- [x] 5.0 Implement write-access verification with caching
  - [x] 5.1 Write tests for `check_write_access()` — mock `gh` CLI, test caching, permission levels, 404 handling
  - [x] 5.2 Implement `check_write_access(username: str, repo_root: Path, cache: dict) -> bool` with 5-minute TTL
  - [x] 5.3 Add `PermissionCache` dataclass to store `{username: (level, expires_at)}`

- [x] 6.0 Implement context extraction for review comments
  - [x] 6.1 Write tests for `extract_fix_context()` — test line-specific vs general comments, diff hunk parsing
  - [x] 6.2 Implement `GithubFixContext` dataclass with `pr_number`, `pr_title`, `branch_name`, `file_path`, `line_number`, `side`, `diff_hunk`, `comment_body`, `author`, `head_sha`
  - [x] 6.3 Implement `extract_fix_context(comment: PRComment, pr: dict) -> GithubFixContext`

- [x] 7.0 Implement GitHub reaction and comment posting
  - [x] 7.1 Write tests for `add_reaction()` — mock `gh` CLI, test emoji encoding
  - [x] 7.2 Implement `add_reaction(comment_id: int, emoji: str, repo_root: Path)` using `gh api` POST
  - [x] 7.3 Write tests for `post_summary_comment()` — test formatting, optional flag
  - [x] 7.4 Implement `post_summary_comment(pr_number: int, body: str, repo_root: Path)` for success summaries

- [x] 8.0 Implement queue integration
  - [x] 8.1 Write tests for `create_github_queue_item()` — verify `source_type`, `branch_name`, `head_sha` fields
  - [x] 8.2 Implement `create_github_queue_item(context: GithubFixContext, config: ColonyConfig) -> QueueItem` with `source_type="github_review"`
  - [x] 8.3 Update `QueueItem` docstring in `src/colonyos/models.py` to document `github_review` source type
  - [x] 8.4 Verify `QueueExecutor._execute_fix_item()` handles `github_review` source type (should work as-is)

- [x] 9.0 Implement main polling loop
  - [x] 9.1 Write tests for `GitHubWatcher` class — test poll cycle, state persistence, graceful shutdown
  - [x] 9.2 Implement `GitHubWatcher` class with `start()`, `stop()`, `_poll_cycle()` methods
  - [x] 9.3 Implement circuit breaker logic (pause after `max_consecutive_failures`, resume after cooldown)
  - [x] 9.4 Implement budget tracking (`daily_cost_usd` accumulation, limit enforcement)
  - [x] 9.5 Implement graceful shutdown on SIGINT/SIGTERM (persist state, restore branch)

- [x] 10.0 Add `watch-github` CLI command
  - [x] 10.1 Write tests in `tests/test_cli.py` for `watch-github` command — test option parsing, config loading, dry-run mode
  - [x] 10.2 Add `watch-github` command to `src/colonyos/cli.py` with `--polling-interval`, `--max-hours`, `--max-budget`, `--dry-run`, `-v`, `-q` options
  - [x] 10.3 Wire command to `GitHubWatcher.start()` with config overrides from CLI flags
  - [x] 10.4 Add `watch-github` to welcome banner command list (dynamic generation at lines 165-171)

- [x] 11.0 Documentation and integration testing
  - [x] 11.1 Add "GitHub Integration" section to `README.md` (mirror "Slack Integration" section at lines 399-477)
  - [x] 11.2 Document `github:` config section in Configuration Reference
  - [x] 11.3 Add `watch-github` to CLI Reference table
  - [x] 11.4 Write integration test simulating full poll → queue → fix → reaction cycle (mocked `gh` CLI)

---

## Implementation Notes

### Pattern reuse checklist
- [x] Copy `SlackWatchState` structure → `GithubWatchState`
- [x] Copy `should_process_message()` logic → `should_process_comment()`
- [x] Copy `format_slack_as_prompt()` → `format_github_comment_as_prompt()`
- [ ] Copy `SlackUI.phase_header/phase_complete` → `GithubUI` (or reuse via reactions only)
- [ ] Copy `check_rate_limit()` / `increment_hourly_count()` → same names, different state object

### Security checklist
- [ ] All comment text passes through `sanitize_untrusted_content()` before prompt injection
- [ ] Branch names validated via `is_valid_git_ref()` before any git operations
- [ ] Write access verified before queuing any fix
- [ ] No detailed error messages in GitHub comments (log server-side only)
- [ ] HEAD SHA captured at queue time and verified at execution time (force-push defense)

### Testing checklist
- [ ] All `gh` CLI calls mocked via `subprocess` patching
- [ ] Rate limit edge cases (exactly at limit, over limit, hour rollover)
- [ ] Circuit breaker transitions (healthy → tripped → cooldown → healthy)
- [ ] Malformed API responses (missing fields, unexpected types)
- [ ] Concurrent comment handling (multiple comments same poll cycle)
