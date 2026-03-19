# Tasks: Slack Thread Fix Requests — Conversational PR Iteration

## Relevant Files

- `src/colonyos/models.py` - Add `branch_name`, `fix_rounds`, `parent_item_id` fields to `QueueItem`; add `source_type="slack_fix"`
- `tests/test_models.py` - Tests for QueueItem serialization with new fields (backwards compat)
- `src/colonyos/slack.py` - Add `should_process_thread_fix()`, `format_fix_acknowledgment()`, Slack link sanitizer
- `tests/test_slack.py` - Tests for thread fix detection, acknowledgment formatting, link sanitization
- `src/colonyos/config.py` - Add `max_fix_rounds_per_thread` to `SlackConfig`
- `tests/test_config.py` - Tests for new config field parsing and defaults
- `src/colonyos/orchestrator.py` - Add `run_thread_fix()` function for lightweight fix pipeline
- `tests/test_orchestrator.py` - Tests for thread fix orchestration, branch validation, phase skipping
- `src/colonyos/cli.py` - Update `watch()` event handler to route thread replies; add `QueueExecutor._execute_fix_item()`
- `tests/test_cli.py` - Tests for thread fix CLI integration
- `src/colonyos/instructions/thread_fix.md` - New instruction template for thread-initiated fixes
- `src/colonyos/sanitize.py` - Add Slack link markup stripping (`<URL|text>` → `text`)
- `tests/test_sanitize.py` - Tests for Slack link sanitization
- `src/colonyos/github.py` - May need `get_pr_state()` helper for merged/closed check

## Tasks

- [x] 1.0 Extend data models for thread-fix support
  - [x] 1.1 Write tests for `QueueItem` with new fields (`branch_name: str | None`, `fix_rounds: int`, `parent_item_id: str | None`) in `tests/test_models.py` — verify serialization, deserialization, and backwards compatibility with existing queue JSON that lacks these fields
  - [x] 1.2 Add `branch_name`, `fix_rounds`, and `parent_item_id` fields to `QueueItem` in `models.py` with defaults (`None`, `0`, `None`) for backwards compat
  - [x] 1.3 Update `QueueExecutor._execute_item()` in `cli.py` to persist `branch_name` on the `QueueItem` after `run_orchestrator()` returns (from `RunLog.branch_name`)

- [x] 2.0 Add `max_fix_rounds_per_thread` config
  - [x] 2.1 Write tests in `tests/test_config.py` for `SlackConfig.max_fix_rounds_per_thread` — verify default (3), YAML parsing, and bounds validation
  - [x] 2.2 Add `max_fix_rounds_per_thread: int = 3` to `SlackConfig` dataclass in `config.py`

- [x] 3.0 Implement thread-fix detection in Slack module
  - [x] 3.1 Write tests in `tests/test_slack.py` for `should_process_thread_fix()` — cover: valid thread fix (thread_ts != ts, bot mentioned, parent maps to completed run), rejection cases (no mention, unknown thread, bot's own message, non-completed parent, user not in allowlist)
  - [x] 3.2 Implement `should_process_thread_fix(event, config, bot_user_id, queue_state)` in `slack.py` — check thread_ts != ts, bot @mention present, parent thread_ts matches a completed QueueItem's slack_ts, sender passes allowlist
  - [x] 3.3 Write tests for `format_fix_acknowledgment(branch_name)` and `format_fix_round_limit(total_cost)` in `tests/test_slack.py`
  - [x] 3.4 Implement `format_fix_acknowledgment()` and `format_fix_round_limit()` formatting helpers in `slack.py`
  - [x] 3.5 Write tests for Slack link sanitizer (`strip_slack_links`) that converts `<https://evil.com|click here>` to `click here` and handles edge cases (bare URLs, malformed markup)
  - [x] 3.6 Implement `strip_slack_links(text)` in `sanitize.py` and integrate into `sanitize_slack_content()` pipeline

- [x] 4.0 Create thread-fix instruction template
  - [x] 4.1 Create `src/colonyos/instructions/thread_fix.md` with placeholders: `{branch_name}`, `{prd_path}`, `{task_path}`, `{fix_request}`, `{original_prompt}` — instruct the agent to check out the branch, make targeted changes per the fix request, write/update tests, and commit

- [x] 5.0 Implement thread-fix orchestrator pipeline
  - [x] 5.1 Write tests in `tests/test_orchestrator.py` for `run_thread_fix()` — mock branch validation, PR state check, phase execution; cover success path, branch-deleted path, PR-merged path, and HEAD SHA mismatch
  - [x] 5.2 Implement `run_thread_fix(fix_prompt, *, branch_name, pr_url, original_prompt, prd_rel, task_rel, repo_root, config, ui_factory)` in `orchestrator.py`:
    - Validate branch exists via `validate_branch_exists()`
    - Validate PR is open via `check_open_pr()`
    - Check out the existing branch
    - Run Implement phase with thread_fix instruction template
    - Run Verify phase (test suite) if `verification.verify_command` is configured
    - Run Deliver phase (push to existing branch, skip PR creation since PR already exists)
    - Return `RunLog` with phase results and cost
  - [x] 5.3 Add `_build_thread_fix_prompt()` helper in `orchestrator.py` that loads the `thread_fix.md` template, fills placeholders, and wraps the user's fix request in the sanitized `<slack_message>` format

- [x] 6.0 Wire thread-fix into watch command event handler
  - [x] 6.1 Write integration tests in `tests/test_cli.py` (or `tests/test_slack.py`) for the full thread-fix flow: mock Slack event with thread_ts → detect as fix → lookup parent QueueItem → enqueue → execute → post results
  - [x] 6.2 Update `_handle_event()` in `cli.py` watch command to:
    - After `should_process_message()` returns False, call `should_process_thread_fix()` for events with `thread_ts != ts`
    - Look up parent `QueueItem` by matching `thread_ts` to `slack_ts` in `queue_state.items`
    - Check `fix_rounds < max_fix_rounds_per_thread`; if exceeded, post limit message and return
    - Check branch exists and PR is open before enqueuing
    - Create a new `QueueItem` with `source_type="slack_fix"`, `parent_item_id=parent.id`, `base_branch=parent.branch_name`
    - Increment `fix_rounds` on the parent `QueueItem`
    - Post `:eyes:` reaction and fix acknowledgment to thread
  - [x] 6.3 Implement `QueueExecutor._execute_fix_item()` — similar to `_execute_item()` but calls `run_thread_fix()` instead of `run_orchestrator()`, passing branch_name, pr_url, original_prompt from the parent QueueItem
  - [x] 6.4 Update `QueueExecutor.run()` main loop to detect `source_type == "slack_fix"` items and route to `_execute_fix_item()`

- [x] 7.0 End-to-end testing and edge cases
  - [x] 7.1 Write test for fix request on merged PR — verify bot posts "PR already merged" and does not launch pipeline
  - [x] 7.2 Write test for fix request on deleted branch — verify bot posts "Branch no longer exists" and does not launch pipeline
  - [x] 7.3 Write test for fix round limit — verify bot posts limit message after `max_fix_rounds_per_thread` rounds
  - [x] 7.4 Write test for concurrent fix request while another is running — verify queuing behavior (waits for semaphore)
  - [x] 7.5 Write test for fix request from non-allowlisted user — verify rejection
  - [x] 7.6 Write test for backwards compatibility — existing queue.json without new fields loads correctly

- [x] 8.0 Documentation and observability
  - [x] 8.1 Update CHANGELOG.md with thread-fix feature entry
  - [x] 8.2 Add `source_type="slack_fix"` to stats/show rendering so fix runs are distinguished in `colonyos stats` and `colonyos show` output
  - [x] 8.3 Add logging at key decision points: thread-fix detection, parent lookup, branch validation, fix round check, pipeline launch, completion
