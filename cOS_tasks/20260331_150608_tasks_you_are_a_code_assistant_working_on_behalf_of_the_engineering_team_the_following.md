# Tasks: Parallel Slack Intake — Decouple Triage from Pipeline Execution

**PRD:** `cOS_prds/20260331_150608_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## Relevant Files

- `src/colonyos/slack_queue.py` - Primary change target: `SlackQueueEngine._triage_and_enqueue()` (line 234), `_handle_event()`, triage worker loop
- `tests/test_slack_queue.py` - Unit tests for SlackQueueEngine, triage worker, queue operations
- `src/colonyos/daemon.py` - Creates `_agent_lock` (line 325), passes to SlackQueueEngine (line 1689); verify no behavioral change needed
- `src/colonyos/slack.py` - `triage_message()` function (line 922), `increment_hourly_count()`, `check_rate_limit()`
- `src/colonyos/models.py` - QueueItem/QueueState data models; no changes expected but reference for watch_state schema

## Tasks

- [x] 1.0 Remove `agent_lock` from triage path (core fix)
  depends_on: []
  - [x] 1.1 Write tests: Add test that verifies `_triage_and_enqueue()` does NOT acquire `agent_lock` — e.g., test that triage completes successfully while `agent_lock` is held by another thread (simulating a running pipeline). Also add test that triage completes when `agent_lock is None`.
  - [x] 1.2 In `slack_queue.py:257`, remove the `with self.agent_lock or nullcontext():` wrapper around the `triage_message()` call. The `triage_message()` call and its surrounding try/except should execute at the same indentation level as the rest of `_triage_and_enqueue()`, without any lock acquisition.
  - [x] 1.3 Verify existing tests pass — specifically all `test_slack_queue.py` tests and any tests that mock or reference `agent_lock`.

- [x] 2.0 Add bounded retry for transient triage failures
  depends_on: [1.0]
  - [x] 2.1 Write tests: (a) Test that a transient failure (simulated timeout/API error) on first attempt succeeds on retry. (b) Test that retry checks `shutdown_event` between attempts. (c) Test that after max retries, the existing error handler runs (warning posted to Slack). (d) Test that non-transient errors (e.g., ValueError) skip retry and fail immediately.
  - [x] 2.2 In `_triage_and_enqueue()`, wrap the `triage_message()` call in a retry loop: max 1 retry, 3-second backoff between attempts, with `shutdown_event.is_set()` check before retry. Only retry on `Exception` subclasses that indicate transient failure (timeout, connection error, HTTP 429/5xx). Let other exceptions propagate to the existing error handler.
  - [x] 2.3 Import `time` module if not already imported for the `time.sleep(3)` backoff.

- [x] 3.0 Mark failed triages as processed in watch_state (prevent redelivery loops)
  depends_on: [1.0]
  - [x] 3.1 Write tests: (a) Test that when triage fails (after retries), `watch_state.mark_processed(channel, ts, "triage-error")` is called. (b) Test that a message previously marked `"triage-error"` is rejected by `_handle_event()` via the existing `is_processed` check.
  - [x] 3.2 In `_triage_and_enqueue()`, in the `except Exception` block (after the retry logic from task 2.0), add `with self.state_lock: self.watch_state.mark_processed(channel, ts, "triage-error"); self.persist_watch_state()` before the `return` statement. This ensures Slack redeliveries of the same message are rejected.

- [ ] 4.0 Move `increment_hourly_count` to message reservation time (close TOCTOU gap)
  depends_on: [1.0]
  - [ ] 4.1 Write tests: (a) Test that `increment_hourly_count` is called during `_handle_event()` (at reservation time) rather than during `_triage_and_enqueue()`. (b) Test that `check_rate_limit` correctly rejects messages when hourly count is incremented eagerly. (c) Test that a message that fails triage does NOT decrement the hourly count (fail-closed behavior).
  - [ ] 4.2 In `_handle_event()`, after `_reserve_pending_message()` and inside the `state_lock` block, add `increment_hourly_count(self.watch_state)`. Remove the `increment_hourly_count(self.watch_state)` call from `_triage_and_enqueue()` (currently at line 355 inside the `state_lock` block).
  - [ ] 4.3 Verify that `check_rate_limit()` (called at line 186 of `_handle_event`) reads the same `watch_state` field that `increment_hourly_count` writes, ensuring the eager increment is visible to subsequent rate-limit checks.

- [ ] 5.0 Integration verification and cleanup
  depends_on: [1.0, 2.0, 3.0, 4.0]
  - [ ] 5.1 Write integration test: simulate a full flow where `agent_lock` is held (pipeline running), a Slack event arrives, and verify: (a) `:eyes:` reaction fires immediately, (b) triage completes without blocking on `agent_lock`, (c) queue item is created with correct position, (d) acknowledgment is posted to Slack.
  - [ ] 5.2 Run the full test suite (`pytest tests/`) and confirm zero regressions.
  - [ ] 5.3 Review `daemon.py` line 1689 where `agent_lock` is passed to `SlackQueueEngine` — add a code comment explaining that the lock is no longer used for triage serialization (kept for potential future use). Alternatively, stop passing it if no other code in `SlackQueueEngine` uses it.
  - [ ] 5.4 Update any docstrings in `SlackQueueEngine` or `_triage_and_enqueue` that reference `agent_lock` serialization behavior.
