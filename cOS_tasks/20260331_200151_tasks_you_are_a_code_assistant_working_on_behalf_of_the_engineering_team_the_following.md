# Tasks: Replace `:eyes:` Emoji with Completion Emoji on Pipeline Finish

## Relevant Files

- `src/colonyos/slack.py` - SlackClient Protocol (line 37-59), `react_to_message()` helper (line 445). Add `reactions_remove` to Protocol and add `remove_reaction()` helper.
- `src/colonyos/cli.py` - Main run completion (line 4050-4056) and fix run completion (line 4304-4310). Add `:eyes:` removal and `:tada:` addition at both sites.
- `src/colonyos/slack_queue.py` - Reference only: where `:eyes:` is added on intake (line 212) and fix intake (line 501). No changes needed.
- `tests/test_slack.py` - `TestSlackClientProtocol` (line 1725). Update Protocol method list test. Add tests for new `remove_reaction()` helper.
- `tests/test_slack_queue.py` - Reference for MagicMock patterns used in Slack tests. May need new tests for the completion emoji swap logic.

## Tasks

- [x] 1.0 Add `reactions_remove` to SlackClient Protocol and create `remove_reaction()` helper
  depends_on: []
  - [x] 1.1 Write tests for `remove_reaction()` helper in `tests/test_slack.py`:
    - Test that `remove_reaction()` calls `client.reactions_remove` with correct args
    - Test that the Protocol now includes `reactions_remove` in its members (update existing `test_protocol_defines_required_methods`)
  - [x] 1.2 Add `reactions_remove` method signature to `SlackClient` Protocol in `src/colonyos/slack.py` (after `reactions_add` at line 51)
  - [x] 1.3 Add `remove_reaction()` function in `src/colonyos/slack.py` (after `react_to_message()` at line 456), mirroring the existing `react_to_message()` pattern but calling `client.reactions_remove()`

- [ ] 2.0 Add `:eyes:` removal and `:tada:` addition to main run completion path
  depends_on: [1.0]
  - [ ] 2.1 Write tests verifying the main completion path calls `remove_reaction("eyes")` before adding the result emoji, and adds `:tada:` on success only
  - [ ] 2.2 In `src/colonyos/cli.py` (~line 4050-4056), add a try/except block calling `remove_reaction(client, channel, thread_ts, "eyes")` before the existing `react_to_message()` call
  - [ ] 2.3 In the same block, add a try/except for `react_to_message(client, channel, thread_ts, "tada")` after the `:white_check_mark:` reaction, gated on `log.status == RunStatus.COMPLETED`

- [ ] 3.0 Add `:eyes:` removal and `:tada:` addition to fix run completion path
  depends_on: [1.0]
  - [ ] 3.1 Write tests verifying the fix completion path calls `remove_reaction("eyes")` before adding the result emoji, and adds `:tada:` on success only
  - [ ] 3.2 In `src/colonyos/cli.py` (~line 4304-4310), add the same `:eyes:` removal and `:tada:` addition pattern as task 2.0

- [ ] 4.0 Update existing tests and verify no regressions
  depends_on: [1.0, 2.0, 3.0]
  - [ ] 4.1 Update `test_protocol_defines_required_methods` in `tests/test_slack.py` to assert `reactions_remove` is in the Protocol members and update the docstring ("4 Slack methods" → "5 Slack methods")
  - [ ] 4.2 Run full test suite (`pytest tests/`) to verify zero regressions
  - [ ] 4.3 Verify the import of `remove_reaction` is added to `src/colonyos/cli.py` alongside the existing `react_to_message` import
