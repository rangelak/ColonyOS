# Linus Torvalds — Round 7 Review: Slack Thread Consolidation

**Branch**: `colonyos/when_you_run_the_daemon_slack_watch_when_you_finish_a_feature_you_should_update`
**PRD**: `cOS_prds/20260405_233459_prd_when_you_run_the_daemon_slack_watch_when_you_finish_a_feature_you_should_update.md`
**Date**: 2026-04-06

---

## Assessment

The code is correct. The data structures are simple and obvious. That's what matters.

### What's right

The core change is dead simple: `SlackUI` accumulates notes in `_note_buffer`, composes them with the phase header, and uses `chat_update` to edit one message instead of spamming fifty. The state is three fields: `_current_msg_ts`, `_phase_header_text`, `_note_buffer`. You can look at those three fields and understand everything the class does. That's good design.

`_flush_buffer` is a single function that handles the compose → sanitize → update → fallback path. It's ~25 lines. It does one thing. `_compose_message` is 5 lines. `phase_header` posts and captures the `ts`. `phase_complete` calls `_flush_buffer(force=True)` and resets. `phase_note` appends and calls `_flush_buffer()`. That's the entire edit-in-place mechanism. No inheritance hierarchy, no strategy pattern, no abstraction astronautics.

`sanitize_outbound_slack` is three steps in a pipeline: redact → truncate → escape. Correct order (you redact before truncating so you don't truncate mid-redaction). Simple function, good docstring.

The debounce is timestamp-based with a `force` flag. Crude but effective — no threads, no timers, no async machinery. `phase_complete` and `flush()` bypass it. That's the right design for something that just needs to not hammer an API.

### What's wrong

**The orchestrator got touched.** The PRD explicitly said `orchestrator.py` should NOT change. The changes are pragmatically necessary — someone has to call `generate_phase_summary` and feed the result back to the UI — but let's not pretend it matches the PRD spec. The PRD was wrong to say the orchestrator wouldn't need changes, and the implementation correctly ignored bad advice. I'm fine with it, but I'm noting it.

**`Phase.TRIAGE` reuse for summary calls.** `generate_phase_summary` calls `run_phase_sync(Phase.TRIAGE, ...)` because it needs *some* phase enum. This means phase-level cost tracking will attribute summary costs to TRIAGE instead of to the actual phase being summarized. It's a minor accounting bug, not a correctness issue, but it'll confuse someone eventually.

**`plan_ui.phase_complete()` is outside the try/except.** Look at orchestrator.py L4792-4808:

```python
if plan_ui is not None:
    try:
        ...
        plan_ui.slack_note(plan_summary)
    except Exception:
        logger.debug(...)
    plan_ui.phase_complete(...)  # <-- outside try
```

If `plan_ui.phase_complete()` throws, it's unhandled. This is fine in practice (SlackUI methods don't throw for Slack errors, they're caught internally), but it's inconsistent with the defensive pattern used everywhere else. Either everything is inside the try or nothing is.

### Checklist

- [x] **FR-1**: `chat_update` added to `SlackClient` protocol — correct signature, keyword-only args
- [x] **FR-2**: SlackUI refactored to edit-in-place — one message per phase, notes buffered
- [x] **FR-3**: Implementation progress collapses into single updating message — notes accumulate in `_note_buffer`
- [x] **FR-4**: `generate_phase_summary` for plan and review phases — Haiku-class call, 280-char limit, deterministic fallbacks
- [x] **FR-5**: `sanitize_outbound_slack` applied in `_flush_buffer` — both update and fallback paths
- [x] **FR-6**: `FanoutSlackUI.flush()` propagates to all targets — each target tracks independent state
- [x] **FR-7**: `phase_error()` always posts new message — unchanged, correct
- [x] **Tests pass**: 344 tests, 0 failures
- [x] **No TODOs/placeholders**: clean
- [x] **No secrets in committed code**: verified
- [x] **Debounce**: 3-second window, force-flush on phase_complete and explicit flush()
- [x] **Bare except blocks replaced**: now `logger.debug(..., exc_info=True)`

### Test coverage

968 new lines in `test_slack.py`, 107 in `test_sanitize.py`. Tests cover:
- Edit-in-place lifecycle (header → notes → complete)
- Debounce behavior (rapid notes, force flush)
- Outbound sanitization (secrets in notes, in phase_complete, in fallback)
- FanoutSlackUI independent state tracking
- `generate_phase_summary` success, failure, fallback, secret redaction, truncation
- E2E pipeline simulation asserting ≤7 postMessage calls

That's thorough. The tests actually test the data flow, not just mock invocations.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py]: PRD said "don't touch orchestrator.py" but changes were pragmatically necessary for wiring phase summaries — correct decision to deviate
- [src/colonyos/orchestrator.py L4804]: `plan_ui.phase_complete()` sits outside the try/except block — inconsistent defensive pattern (non-blocking)
- [src/colonyos/slack.py L1170]: `Phase.TRIAGE` reused for summary LLM calls will miscategorize costs in phase-level budget tracking (non-blocking)
- [src/colonyos/sanitize.py L39-40]: `sk-ant-api03-\S+` overlaps with existing `sk-\w+` pattern — redundant but harmless, the more specific pattern provides better coverage for the `-api03-` variant

SYNTHESIS:
This is clean, simple code that does exactly what it says. The data structures tell the story: a note buffer, a message timestamp, a header string. The edit-in-place pattern reduces ~50 Slack messages to ~7 without any architectural complexity. The debounce is crude and correct. The sanitization pipeline is ordered properly. The test coverage is genuinely comprehensive. The orchestrator changes deviate from the PRD's "don't touch" guidance, but the PRD was wrong — someone has to wire the summary generation, and the orchestrator is where the phase artifacts live. Ship it.
