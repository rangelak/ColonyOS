# PRD: Replace `:eyes:` Emoji with Completion Emoji on Pipeline Finish

## Introduction/Overview

When ColonyOS processes a feature request from Slack, it adds an `:eyes:` emoji reaction to acknowledge receipt. When the pipeline completes, it adds `:white_check_mark:` (success) or `:x:` (failure) — but never removes the `:eyes:`. This leaves messages in a cluttered, ambiguous state with two emoji reactions that contradict each other (`:eyes:` = "in progress" alongside `:white_check_mark:` = "done").

This feature adds a clean state transition: on pipeline completion, remove `:eyes:` before adding the terminal status emoji, so each message has exactly one reaction reflecting its current state.

## Goals

1. **Clean state transitions**: Every completed Slack message shows exactly one of `{white_check_mark, x}` and zero `:eyes:` reactions.
2. **Consistent behavior**: Both the main run completion path and the thread-fix completion path behave identically.
3. **Resilient**: Failed emoji removal never blocks the pipeline or loses the completion signal.
4. **Minimal scope**: Ship the smallest change that solves the problem — no configuration flags, no `:tada:` in v1.

## User Stories

1. **As a developer watching Slack**, I want to scan my channel and instantly know which requests are in-progress (`:eyes:`), completed (`:white_check_mark:`), or failed (`:x:`) without seeing contradictory emoji combinations.
2. **As a team lead**, I want a clear visual signal when the bot finishes my request, so I don't wonder if it's still working on something that already finished.
3. **As an on-call engineer**, I want failed runs to show only `:x:` (not `:eyes:` + `:x:`), so I can quickly triage what needs human intervention versus what's still being processed.

## Functional Requirements

1. **FR-1**: Add `reactions_remove` method to the `SlackClient` Protocol class in `src/colonyos/slack.py` (line 38), matching the signature of `reactions_add`.
2. **FR-2**: Add a `remove_reaction()` helper function in `src/colonyos/slack.py` alongside the existing `react_to_message()` (line 445), wrapping `client.reactions_remove()`.
3. **FR-3**: On pipeline completion (success or failure), remove the `:eyes:` reaction before adding the terminal status emoji. This applies to:
   - Main run completion in `src/colonyos/cli.py` (~line 4050-4056)
   - Fix run completion in `src/colonyos/cli.py` (~line 4304-4310)
4. **FR-4**: The `:eyes:` removal must be wrapped in a try/except with `logger.debug()` level logging, matching the existing error-handling pattern for Slack API calls.
5. **FR-5**: The removal call must execute **before** the addition of the completion emoji, so that if the removal is slow or fails, the completion emoji still gets added.
6. **FR-6**: Add `:tada:` reaction alongside `:white_check_mark:` on successful completion only.
7. **FR-7**: All new functionality must have corresponding unit tests.

## Non-Goals

- **No `:tada:` configuration flag**: We add `:tada:` on success unconditionally in v1. Configuration can be added later if users want to disable it.
- **No daemon.py changes**: `daemon.py` (line 970) does not currently handle emoji reactions — it only posts summary messages. Adding emoji handling to the daemon path is a separate concern.
- **No reaction-based state machine**: We are not building a generic emoji lifecycle system. This is a targeted fix for the `:eyes:` cleanup gap.
- **No Slack OAuth scope changes**: The existing `reactions:write` scope already covers `reactions.remove`.

## Technical Considerations

### Existing Code Patterns

The codebase has a consistent pattern for Slack API calls:
```python
try:
    react_to_message(client, channel, thread_ts, emoji)
except Exception:
    logger.debug("Failed to add result reaction", exc_info=True)
```
The new `remove_reaction` call follows this exact pattern.

### SlackClient Protocol (`src/colonyos/slack.py`, line 37-59)

The `SlackClient` is a `@runtime_checkable` Protocol. Adding `reactions_remove` is safe because:
- The real `slack_sdk.WebClient` already implements `reactions_remove`
- All test mocks use `MagicMock()` which auto-satisfies any method call
- The only Protocol-checking test (`tests/test_slack.py:1728`) verifies method names in `dir()` — it needs to be updated to include `reactions_remove`

### Completion Paths

There are exactly two completion sites in `cli.py` that add emoji reactions:
1. **Line 4050-4056**: Main `QueueExecutor._process_next_item()` completion
2. **Line 4304-4310**: Fix run `_process_thread_fixes()` completion

Both follow identical structure and need identical changes.

### Error Scenarios

- **Bot already removed `:eyes:`** (e.g., user manually removed it): Slack API returns `no_reaction` error — caught by try/except, logged at debug.
- **Rate limiting**: Extremely unlikely (one extra call per multi-minute pipeline run), but handled by the same try/except.
- **Network failure on remove**: The completion emoji addition proceeds independently since it's in a separate try/except.

### Persona Consensus

All seven expert personas unanimously agreed on:
- `:eyes:` must be removed on both success AND failure
- Log at debug level on failure, never block the pipeline
- Both cli.py completion paths need the change
- No backward compatibility risk from adding `reactions_remove` to the Protocol
- Doubling API calls at completion is negligible

**Key tension**: Most personas advised against `:tada:` (calling it "emoji bloat" and "zero information"), but the user explicitly requested it. Per project rules, **user direction is highest priority**, so we include `:tada:` on success.

## Success Metrics

1. After deployment, no Slack messages should show both `:eyes:` and a completion emoji simultaneously.
2. Zero pipeline failures caused by the emoji removal logic.
3. All existing tests continue to pass with no regressions.

## Open Questions

1. **Should `:tada:` be configurable?** — Deferred to a follow-up if users request it.
2. **Should daemon.py also get emoji reaction handling?** — Out of scope; daemon doesn't currently touch reactions.
