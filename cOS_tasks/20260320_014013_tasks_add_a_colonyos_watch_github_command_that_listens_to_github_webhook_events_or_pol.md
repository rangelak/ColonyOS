# Tasks: GitHub Watch Command for PR Review Auto-Fixes

## Relevant Files

### Existing Files to Modify
- `src/colonyos/config.py` - Add `GitHubWatchConfig` dataclass with new config fields
- `src/colonyos/cli.py` - Add `watch-github` CLI command (~100 lines)
- `src/colonyos/models.py` - Add `source_type="github_review"` handling (minimal change)
- `src/colonyos/orchestrator.py` - May need minor adjustments for GitHub-sourced fix prompts

### Existing Files to Reference (Read-Only Patterns)
- `src/colonyos/slack.py` - Reference `SlackWatchState`, `check_rate_limit()`, `is_valid_git_ref()` patterns
- `src/colonyos/sanitize.py` - Reuse `sanitize_untrusted_content()` for review comments
- `src/colonyos/github.py` - Reference `gh` CLI subprocess patterns
- `src/colonyos/ci.py` - Reference `check_pr_author_mismatch()` security pattern
- `src/colonyos/instructions/thread_fix.md` - Template for fix prompts

### New Files to Create
- `src/colonyos/github_watcher.py` - Core watcher logic (~400-500 lines)
- `tests/test_github_watcher.py` - Unit tests for watcher module (~300-400 lines)

### Test Files
- `tests/test_github_watcher.py` - New test file for watcher module
- `tests/test_config.py` - Add tests for `GitHubWatchConfig` parsing
- `tests/test_cli.py` - Add tests for `watch-github` CLI command

---

## Tasks

- [x] 1.0 Add GitHubWatchConfig to configuration system
  - [x] 1.1 Write tests for `GitHubWatchConfig` parsing in `tests/test_config.py`
    - Test defaults when no `github_watch` section present
    - Test parsing all fields from YAML
    - Test invalid `trigger_mode` validation
    - Test roundtrip save/load
  - [x] 1.2 Add `GitHubWatchConfig` dataclass to `src/colonyos/config.py`
    - Fields: `enabled`, `trigger_mode`, `max_fix_rounds_per_pr`, `max_fix_cost_per_pr_usd`, `poll_interval_seconds`, `allowed_reviewers`
    - Default values matching PRD (enabled=false, trigger_mode="review_request_changes", rounds=3, cost=10.0, poll=60, reviewers=[])
  - [x] 1.3 Update `ColonyConfig` to include `github_watch: GitHubWatchConfig` field
  - [x] 1.4 Update `load_config()` and `save_config()` to handle `github_watch` section

- [x] 2.0 Create GitHubWatchState for persistent state tracking
  - [x] 2.1 Write tests for `GitHubWatchState` serialization in `tests/test_github_watcher.py`
    - Test `to_dict()` / `from_dict()` roundtrip
    - Test `is_event_processed()` / `mark_event_processed()` deduplication
    - Test `get_pr_cost()` / `add_pr_cost()` per-PR cost tracking
    - Test hourly count pruning
  - [x] 2.2 Create `GitHubWatchState` dataclass in `src/colonyos/github_watcher.py`
    - Mirror `SlackWatchState` pattern from `slack.py:513-593`
    - Add `processed_events: dict[str, str]` (event_id → run_id)
    - Add `pr_fix_costs: dict[int, float]` (pr_number → cumulative cost)
    - Add `pr_fix_rounds: dict[int, int]` (pr_number → round count)
  - [x] 2.3 Implement `save_watch_state()` and `load_watch_state()` functions
    - Use atomic write pattern from `slack.py:596-627`
    - Save to `cOS_runs/github_watch_state_{watch_id}.json`

- [x] 3.0 Implement GitHub API polling and event detection
  - [x] 3.1 Write tests for PR review event detection
    - Test filtering by `state == "changes_requested"`
    - Test filtering by `colonyos/*` branch prefix
    - Test deduplication (same event_id not processed twice)
    - Test allowed_reviewers filtering
  - [x] 3.2 Create `fetch_pr_reviews()` function in `src/colonyos/github_watcher.py`
    - Use `gh api` to fetch reviews for ColonyOS branches
    - Parse JSON response into structured dataclass
    - Validate branch names with `is_valid_git_ref()` pattern
  - [x] 3.3 Create `filter_actionable_reviews()` function
    - Filter to `state == "changes_requested"` only
    - Filter to `colonyos/*` branches
    - Check against `allowed_reviewers` allowlist
    - Deduplicate against `processed_events` in state
  - [x] 3.4 Create `extract_review_context()` function
    - Fetch review comments with file path / line number context via `gh api`
    - Format as structured fix prompt (JSON schema per PRD)

- [x] 4.0 Implement fix prompt formatting and sanitization
  - [x] 4.1 Write tests for review comment sanitization
    - Test XML tag stripping from comment bodies
    - Test handling of Markdown code blocks
    - Test branch name quoting for subprocess safety
  - [x] 4.2 Create `sanitize_review_comment()` function
    - Call `sanitize_untrusted_content()` from `sanitize.py`
    - Additional handling for GitHub-specific Markdown
  - [x] 4.3 Create `format_github_fix_prompt()` function
    - Format multiple review comments into single fix prompt
    - Include file path, line range, reviewer, feedback, severity
    - Add security preamble (same pattern as `thread_fix.md`)
  - [x] 4.4 Create `format_github_fix_prompt_from_template()` using instruction template
    - Create `src/colonyos/instructions/github_fix.md` template
    - Mirror `thread_fix.md` structure with GitHub-specific context

- [x] 5.0 Integrate with existing fix pipeline
  - [x] 5.1 Write tests for QueueItem creation with `source_type="github_review"`
    - Test all required fields populated
    - Test fix_rounds tracking per PR
  - [x] 5.2 Create `create_github_fix_queue_item()` function
    - Populate `QueueItem` with PR number, branch, review ID, reviewer
    - Set `source_type="github_review"`
    - Check current `pr_fix_rounds` against `max_fix_rounds_per_pr`
  - [x] 5.3 Implement per-PR cost cap checking
    - Read current PR cost from `GitHubWatchState.pr_fix_costs`
    - Compare against `max_fix_cost_per_pr_usd`
    - Return rejection reason if limit exceeded
  - [x] 5.4 Call `run_thread_fix()` from `orchestrator.py` with GitHub context
    - Pass formatted fix prompt
    - Handle return value and update state with cost/outcome

- [x] 6.0 Implement GitHub comment posting
  - [x] 6.1 Write tests for GitHub comment formatting
    - Test start comment format
    - Test completion comment format
    - Test limit-exceeded comment format
  - [x] 6.2 Create `post_pr_comment()` function
    - Use `gh pr comment` CLI command
    - Handle errors gracefully (don't fail pipeline on comment failure)
  - [x] 6.3 Create `format_fix_start_comment()` function
    - Include reviewer username, fix round number
  - [x] 6.4 Create `format_fix_complete_comment()` function
    - Include commit SHA, cost, link to re-review
  - [x] 6.5 Create `format_fix_limit_comment()` function
    - Explain which limit was hit (rounds vs cost)
    - Suggest manual intervention

- [x] 7.0 Implement main watch loop and CLI command
  - [x] 7.1 Write tests for watch loop behavior
    - Test polling interval timing
    - Test graceful shutdown on SIGINT
    - Test dry-run mode (no actual fixes)
  - [x] 7.2 Create `run_github_watch()` main loop function
    - Poll at configured interval
    - Process detected events sequentially
    - Update state after each event
    - Handle rate limiting / circuit breaker
  - [x] 7.3 Add `watch-github` command to `cli.py`
    - Options: `--poll-interval`, `--dry-run`, `--watch-id`
    - Load config, validate prerequisites
    - Start main loop
  - [x] 7.4 Implement signal handling for graceful shutdown
    - Handle SIGINT/SIGTERM
    - Save state before exit
    - Post "watcher shutting down" status if mid-fix

- [x] 8.0 Rate limiting and circuit breaker integration
  - [x] 8.1 Write tests for rate limit checking
    - Test hourly limit enforcement
    - Test daily budget enforcement
    - Test circuit breaker pause/resume
  - [x] 8.2 Integrate with existing `check_rate_limit()` pattern
    - Extract shared rate limit logic if needed
    - Or call `slack.py` functions directly
  - [x] 8.3 Implement consecutive failure tracking
    - Increment on pipeline errors
    - Pause queue after 3 consecutive failures
    - Post comment explaining pause
  - [x] 8.4 Implement shared budget pool with Slack watcher
    - Read/write same daily budget tracking
    - Prevent circumventing limits via alternate channel

---

## Implementation Notes

### Testing Strategy
- All new code requires unit tests BEFORE implementation (test-first)
- Mock `gh` CLI subprocess calls in tests
- Use `tmp_path` fixture for state file tests
- Integration tests should use a real (test) GitHub repo if available

### Code Structure Guidelines
- Keep `github_watcher.py` focused on GitHub-specific logic
- Reuse existing patterns from `slack.py` where possible
- Don't duplicate rate limiting / circuit breaker logic — extract to shared module if needed
- Follow existing error handling patterns (return errors, don't raise)

### Security Checklist
- [x] All review comment bodies pass through `sanitize_untrusted_content()`
- [x] Branch names validated with `is_valid_git_ref()` before use in subprocess
- [x] `allowed_reviewers` enforced when configured
- [x] HEAD SHA verified before checkout (reuse existing pattern)
- [x] Event IDs deduplicated to prevent replay attacks

### Dependencies
- No new Python dependencies required
- Relies on existing `gh` CLI (already a prerequisite)
- Uses existing `claude-agent-sdk` for fix pipeline
