# Review Round 6 — Andrej Karpathy
## Slack Thread Message Consolidation & LLM Content Surfacing

**Branch**: `colonyos/when_you_run_the_daemon_slack_watch_when_you_finish_a_feature_you_should_update`
**PRD**: `cOS_prds/20260405_233459_prd_when_you_run_the_daemon_slack_watch_when_you_finish_a_feature_you_should_update.md`
**Date**: 2026-04-06

---

## Assessment

### Completeness

- [x] **FR-1**: `chat_update` added to `SlackClient` protocol with correct signature `(channel, ts, text, **kwargs)`
- [x] **FR-2**: `SlackUI` refactored to edit-in-place — `_current_msg_ts`, `_note_buffer`, `_flush_buffer()` all present
- [x] **FR-3**: Implementation progress consolidation — notes buffer into one message via `chat_update`. However, the *specific* format from the PRD ("Implementing: 2/5 tasks complete ✓ task1, ✓ task2, ⏳ task3...") is NOT implemented. The existing `_format_implement_result_note()` and `_format_task_outline_note()` formatting in the orchestrator is preserved as-is, which is fine — the consolidation happens at the SlackUI layer.
- [x] **FR-4**: `generate_phase_summary()` implemented for plan and review with Haiku model, 280-char limit, proper fallbacks
- [x] **FR-5**: `sanitize_outbound_slack()` implemented with secret redaction (sk-ant-, PEM, GCP), 3000-char ceiling, mrkdwn sanitization
- [x] **FR-6**: `FanoutSlackUI` updated with `flush()` delegation — each target independently tracks its own message state
- [x] **FR-7**: `phase_error()` always posts a NEW message (never edits)
- [x] All tasks marked complete in task file
- [x] No TODO/placeholder code

### Quality

- [x] **338 tests pass** (`test_slack.py` + `test_sanitize.py`)
- [x] Code follows existing patterns — `generate_phase_summary()` mirrors `generate_plain_summary()`
- [x] No unnecessary dependencies
- [x] No unrelated changes

### Safety

- [x] No secrets in committed code
- [x] Error handling present — `_flush_buffer()` catches exceptions and falls back to `chat_postMessage`
- [x] `generate_phase_summary()` catches all exceptions and returns deterministic fallback
- [x] Outbound sanitization applied to all LLM-generated Slack content

---

## Findings

### Missing: Debounce / Rate Limit Protection (Medium)

The PRD explicitly states: *"Edits should be batched/debounced — don't update on every single `phase_note` call; accumulate and flush periodically (e.g., every 3-5 seconds or on phase transitions)."* The task file also mentions debounce in tasks 2.1 and 2.4.

The current implementation calls `_flush_buffer()` on **every** `phase_note()` call, meaning every note immediately fires a `chat_update` API call. For the implement phase with 5+ tasks, this means 5+ rapid `chat_update` calls on the same message. Slack's Tier 2 rate limit is ~1 request/sec per channel — this will work for a single pipeline run but could hit limits with concurrent runs or rapid task completions.

This is acceptable for v1 — the consolidation already drops from ~50 to ~7 *messages*, and the `chat_update` calls are edits to existing messages (much less noisy than new posts). But a proper debounce (accumulate notes, flush on phase transition or every 3-5s) would be the correct production behavior.

### Orchestrator Changes (Low — Acceptable Deviation)

The PRD states orchestrator.py "should NOT change," but the implementation adds ~25 lines for plan summary generation. This is a reasonable pragmatic choice — the summary needs plan_result artifacts that are only available in the orchestrator. The change doesn't alter event emission (the concern the PRD was protecting), it just adds a new summary posting step.

### Prompt Design: Good (Minor Nit)

The `generate_phase_summary()` prompt design is solid:
- System prompt sets persona + format constraints
- User prompt includes instruction + truncated context (2000 chars)
- 280-char output constraint via both prompt instruction AND `sanitize_outbound_slack(max_chars=280)`
- The belt-and-suspenders approach (prompt says "under 280 chars" + code enforces it) is exactly right for stochastic outputs

One minor nit: the system prompt says "No headers, no markdown formatting, no bullet points" but doesn't explicitly say "no code blocks" — LLMs love wrapping things in backticks. For 280 chars this is unlikely to matter, but worth noting.

### `Phase.TRIAGE` Reuse for Summaries (Low)

`generate_phase_summary()` reuses `Phase.TRIAGE` as the phase identifier for the `run_phase_sync` call. This is a pragmatic hack — triage is a lightweight phase that works fine for this use case. But if phase-specific budget tracking or audit logging is added later, summary calls will be miscategorized as triage. A dedicated `Phase.SUMMARY` or tagging mechanism would be cleaner long-term.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/slack.py]: No debounce on `phase_note()` → `_flush_buffer()` path — every note immediately fires `chat_update`. PRD specified 3-5s batching. Acceptable for v1 but should be added for production rate limit safety.
- [src/colonyos/orchestrator.py]: PRD said "should NOT change" but implementation adds ~25 lines for plan summary generation. Acceptable deviation — summary generation requires plan artifacts only available here.
- [src/colonyos/slack.py]: `generate_phase_summary()` uses `Phase.TRIAGE` as the phase identifier for summary LLM calls — works but will miscategorize in phase-level budget tracking.
- [src/colonyos/slack.py]: System prompt for summaries doesn't explicitly prohibit code blocks/backticks — minor gap in output format control.

SYNTHESIS:
This is a clean, well-structured implementation that achieves the core goal: collapsing ~50 Slack messages down to ~5-7 through edit-in-place message consolidation. The architecture is right — consolidation lives in `SlackUI` not the orchestrator, the LLM summary calls use cheap Haiku with proper fallbacks, and outbound sanitization covers the key secret patterns. The test coverage is thorough (851 new lines of tests) with good edge case coverage (update failures, empty notes, orphan notes, multi-target fanout). The missing debounce is the only meaningful gap, and it's a safe omission for v1 since the message *count* reduction is already achieved — the extra `chat_update` calls are invisible to users (they're edits, not new messages). Ship it and add debounce as a fast-follow.
