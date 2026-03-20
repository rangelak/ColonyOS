# Tasks: GitHub PR Review Comment Response Integration

## Relevant Files

### Existing Files to Modify

- `src/colonyos/cli.py` - Add `pr-respond` command and `--github` flag to `watch` command
- `src/colonyos/config.py` - Add `GitHubWatchConfig` dataclass and parsing logic
- `src/colonyos/models.py` - Add `source_type: "pr_comment"` and `comment_ids` field to QueueItem
- `src/colonyos/orchestrator.py` - Add `run_pr_comment_fix()` wrapper function
- `src/colonyos/sanitize.py` - Ensure `sanitize_untrusted_content()` handles PR comment edge cases

### New Files to Create

- `src/colonyos/pr_comments.py` - PR comment fetching, parsing, grouping, reply posting
- `src/colonyos/instructions/pr_comment_fix.md` - Instruction template for PR comment fix agent
- `tests/test_pr_comments.py` - Unit tests for PR comment processing module
- `tests/test_pr_respond_cli.py` - Integration tests for CLI command

### Existing Files for Reference

- `src/colonyos/ci.py` - Reference for `gh api` patterns, PR check fetching
- `src/colonyos/slack.py` - Reference for watch state, rate limiting, allowlist patterns
- `src/colonyos/github.py` - Reference for existing GitHub API helpers

## Tasks

- [x] 1.0 Add `GitHubWatchConfig` to configuration system
  - [x] 1.1 Write tests for `GitHubWatchConfig` parsing in `tests/test_config.py`
    - Test parsing with all fields present
    - Test parsing with defaults
    - Test validation errors (invalid poll_interval, negative rate limits)
    - Test empty `allowed_comment_authors` behavior
  - [x] 1.2 Add `GitHubWatchConfig` dataclass to `src/colonyos/config.py`
    - Fields: `enabled`, `poll_interval_seconds`, `auto_respond`, `max_responses_per_pr_per_hour`, `budget_per_response`, `allowed_comment_authors`, `skip_bot_comments`, `comment_response_marker`
    - Add to `ColonyConfig` as `github_watch: GitHubWatchConfig`
  - [x] 1.3 Implement `_parse_github_watch_config()` function in `config.py`
    - Validate `poll_interval_seconds >= 10`
    - Validate `max_responses_per_pr_per_hour >= 1`
    - Validate `budget_per_response > 0`
  - [x] 1.4 Update `save_config()` to persist `github_watch` section

- [x] 2.0 Extend `QueueItem` model for PR comment tracking
  - [x] 2.1 Write tests for new `QueueItem` fields in `tests/test_models.py`
    - Test serialization/deserialization with `source_type: "pr_comment"`
    - Test `comment_ids` field (list of integers)
    - Test backward compatibility with schema version bump
  - [x] 2.2 Add `comment_ids: list[int] | None` field to `QueueItem` in `models.py`
  - [x] 2.3 Bump `SCHEMA_VERSION` to 3 and update `to_dict()`/`from_dict()`
  - [x] 2.4 Update `_format_queue_item_source()` in `cli.py` to handle `source_type: "pr_comment"`

- [x] 3.0 Create PR comment processing module (`pr_comments.py`)
  - [x] 3.1 Write tests for PR comment fetching in `tests/test_pr_comments.py`
    - Test `fetch_pr_comments()` with mock `gh api` response
    - Test filtering of bot comments
    - Test filtering of already-addressed comments (marker detection)
    - Test error handling for API failures
  - [x] 3.2 Implement `fetch_pr_comments(pr_number: int) -> list[ReviewComment]`
    - Call `gh api repos/:owner/:repo/pulls/:number/comments`
    - Parse into `ReviewComment` dataclass with: `id`, `body`, `path`, `line`, `user_login`, `user_type`, `created_at`
    - Filter out bot comments if `skip_bot_comments=True`
  - [x] 3.3 Write tests for comment grouping logic
    - Test grouping adjacent comments (within 10 lines, same file)
    - Test no grouping across files
    - Test edge cases (single comment, no comments)
  - [x] 3.4 Implement `group_comments(comments: list[ReviewComment]) -> list[CommentGroup]`
    - Sort by `(path, line)`
    - Group consecutive comments within 10 lines of each other
    - Return `CommentGroup` with file path, line range, and list of comment IDs
  - [x] 3.5 Write tests for allowlist checking
    - Test explicit allowlist match
    - Test org membership fallback (mock `gh api`)
    - Test rejection of non-allowed users
  - [x] 3.6 Implement `is_allowed_commenter(user_login: str, config: GitHubWatchConfig) -> bool`
    - Check `allowed_comment_authors` list first
    - Fall back to org membership check via `gh api repos/:owner/:repo/collaborators/:user`
  - [x] 3.7 Write tests for reply posting
    - Test successful reply with marker
    - Test error handling for API failures
  - [x] 3.8 Implement `post_comment_reply(comment_id: int, body: str) -> bool`
    - Call `gh api repos/:owner/:repo/pulls/comments/:id/replies -X POST`
    - Prepend `comment_response_marker` to body
  - [x] 3.9 Write tests for "unaddressed" detection
    - Test comment with no replies is unaddressed
    - Test comment with ColonyOS marker reply is addressed
    - Test comment with human reply is still unaddressed
  - [x] 3.10 Implement `filter_unaddressed_comments(comments: list[ReviewComment]) -> list[ReviewComment]`
    - Fetch replies for each comment via `gh api`
    - Filter out comments that have replies containing the marker

- [x] 4.0 Create PR comment fix instruction template
  - [x] 4.1 Write `src/colonyos/instructions/pr_comment_fix.md`
    - Include placeholders for: `{{comment_text}}`, `{{file_path}}`, `{{line_range}}`, `{{pr_description}}`, `{{prd_context}}`
    - Instructions for understanding review feedback as code change requests
    - Guidance on making minimal, targeted changes
    - Instructions for writing concise commit messages

- [x] 5.0 Implement `run_pr_comment_fix()` orchestrator function
  - [x] 5.1 Write tests for PR comment fix flow in `tests/test_orchestrator.py`
    - Test successful fix with commit and reply
    - Test fix failure with error reply
    - Test HEAD SHA validation
    - Test budget cap enforcement
  - [x] 5.2 Implement `run_pr_comment_fix()` in `orchestrator.py`
    - Validate PR is on `colonyos/` branch
    - Fetch and validate HEAD SHA
    - Build prompt from comment group using instruction template
    - Call `run_thread_fix()` with `skip_pr_creation=True`
    - Post success/failure replies to each comment in group
  - [x] 5.3 Implement `_build_pr_comment_fix_prompt()` helper
    - Sanitize comment text with `sanitize_untrusted_content()`
    - Inject PRD/task context if original run log available
    - Format using instruction template

- [x] 6.0 Add `colonyos pr-respond` CLI command
  - [x] 6.1 Write tests for CLI command in `tests/test_pr_respond_cli.py`
    - Test basic invocation with PR number
    - Test `--dry-run` flag outputs without changes
    - Test `--comment-id` single comment targeting
    - Test branch validation error
    - Test no unaddressed comments case
  - [x] 6.2 Add `@app.command()` for `pr-respond` in `cli.py`
    - Arguments: `pr_number: int`
    - Options: `--dry-run`, `--comment-id <id>`, `-v/--verbose`, `-q/--quiet`
  - [x] 6.3 Implement command logic
    - Fetch PR metadata and validate branch prefix
    - Fetch and filter unaddressed comments
    - Group comments
    - For each group: run `run_pr_comment_fix()`
    - Display summary of addressed comments
  - [x] 6.4 Add rate limit checking per-PR
    - Load/create rate limit state from `.colonyos/runs/pr_respond_state.json`
    - Check `max_responses_per_pr_per_hour` before processing
    - Update state after successful response

- [x] 7.0 Extend `colonyos watch` with `--github` flag
  - [x] 7.1 Write tests for GitHub watch mode in `tests/test_cli.py`
    - Test watch startup with `--github` flag
    - Test polling loop detects new comments
    - Test rate limiting across multiple PRs
    - Test graceful shutdown
  - [x] 7.2 Add `GitHubWatchState` dataclass (mirror `SlackWatchState` pattern)
    - Fields: `watch_id`, `last_poll_at`, `pr_response_counts`, `aggregate_cost_usd`
    - Implement `to_dict()`/`from_dict()` for persistence
  - [x] 7.3 Add `--github` flag to `watch` command in `cli.py`
    - Can be combined with `--slack` for unified watch
  - [x] 7.4 Implement GitHub polling loop in watch command
    - List open PRs on `colonyos/` branches
    - For each PR: fetch unaddressed comments
    - Queue new comments for processing
    - Sleep for `poll_interval_seconds`
  - [x] 7.5 Implement ColonyOS PR detection
    - Check branch prefix matches config
    - Optionally check PR body for ColonyOS marker
  - [x] 7.6 Persist GitHub watch state to `.colonyos/runs/github_watch_state_<id>.json`

- [x] 8.0 Integration and documentation
  - [x] 8.1 Add `pr-respond` to CLI help output
  - [x] 8.2 Update `colonyos status` to show GitHub watch sessions
  - [x] 8.3 Test end-to-end flow: create PR, add comment, run `pr-respond`, verify reply
  - [x] 8.4 Update README with `pr-respond` usage examples (if documentation updates are requested)
