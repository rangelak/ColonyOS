# Principal Systems Engineer — Review Round 1

**Branch:** `colonyos/add_the_option_to_listen_to_every_message_in_a_c_305511536b`
**PRD:** `cOS_prds/20260401_131917_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## Checklist

### Completeness
- [x] FR-1: `"all"` added to `_VALID_TRIGGER_MODES` in `config.py`
- [x] FR-2: `register()` binds `message` event when `trigger_mode == "all"`
- [x] FR-3: `extract_prompt_text()` handles both mention and passive messages; `has_bot_mention()` correctly detects the split
- [x] FR-4: 👀 reaction skipped at intake for passive messages; deferred to post-triage for actionable passives
- [x] FR-5: Dedup verified with 3 dedicated tests (pending-set, processed-set, end-to-end)
- [x] FR-6: Startup warning for empty `allowed_user_ids` in "all" mode
- [x] FR-7: Startup warning for empty `triage_scope` in "all" mode
- [x] FR-8: `should_process_message()` filters unchanged — all existing guards intact

### Quality
- [x] 318 tests pass (0 failures, 0 regressions)
- [x] Code follows existing project conventions (patch patterns, engine construction helpers, test class organization)
- [x] No unnecessary dependencies added
- [x] No unrelated changes included
- [x] ~680 lines of new tests for ~50 lines of new production code — excellent ratio

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive operations
- [x] Error handling present: queue-full, reaction failures, triage errors all handled with try/except
- [x] Passive message queue-full warning correctly suppressed to avoid UX leak

## Findings

- **[src/colonyos/slack_queue.py]**: The `is_passive` flag is computed from `has_bot_mention(raw_text, ...)` which checks the raw event text. This is correct — it uses the pre-extraction text, so the detection is reliable. The flag flows cleanly from `_handle_event` through the triage queue dict to `_triage_and_enqueue`, with a safe default of `is_passive=False` for backward compatibility. Good.

- **[src/colonyos/slack_queue.py]**: The deferred 👀 reaction for passive messages (lines ~341-345 in the diff) fires after triage confirms actionable but *before* the queue item is created. If `format_slack_as_prompt()` or queue insertion subsequently fails, the user sees 👀 but gets no response. This is a minor inconsistency — the same issue already exists for mention messages (👀 fires before triage), so it's not a regression. Acceptable for v1.

- **[src/colonyos/slack_queue.py line 84]**: `bolt_app.event("message")` in `register()` — Slack's `message` event type includes subtypes like `message_changed`, `message_deleted`, `bot_message`. The existing `should_process_message()` already rejects edits and bot messages, so these subtypes are filtered. However, `message_deleted` events have no `text` field — `raw_text = event.get("text", "")` returns empty string, and `extract_prompt_text("", ...)` returns `""`, which is caught by the `if not prompt_text.strip(): return` guard. Safe by accident but worth noting.

- **[src/colonyos/daemon.py]**: `_warn_all_mode_safety` is a `@staticmethod`, which is the right call — it doesn't need instance state and is easily testable in isolation. Placement after engine creation but before `register()` is correct: warnings appear in logs before any events start flowing.

- **[tests/test_slack_queue.py]**: The integration tests (tasks 4.0, 5.0, 7.0) correctly test the triage worker thread with `triage_completed.wait(timeout=3)` followed by `_triage_queue.join()`. This is the right pattern — wait for the mock to signal completion, then ensure the queue's task_done is called. No flaky timing issues.

VERDICT: approve

FINDINGS:
- [src/colonyos/slack_queue.py]: Deferred 👀 for passive messages fires before queue item creation — if downstream fails, user sees 👀 with no follow-up. Pre-existing pattern for mentions; acceptable for v1.
- [src/colonyos/slack_queue.py]: `message` event binding receives `message_deleted` subtypes with no `text` field — safely handled by existing empty-text guard, but the resilience is implicit rather than explicit.

SYNTHESIS:
This is a well-scoped, minimal-blast-radius change that correctly activates a latent configuration path. The implementation touches exactly the right code paths with no unnecessary abstractions. From a systems reliability perspective, the key question is "what breaks at 3am?" and the answer is "nothing new" — all failure modes (queue full, triage errors, reaction failures, dedup races) are handled by existing infrastructure, and the new code correctly routes passive messages through those same paths. The conditional 👀 reaction is the most operationally important detail (silent monitoring without creepy UX), and it's implemented with the right two-phase pattern: suppress at intake, add after triage. The `is_passive` flag flows cleanly through the system without polluting the queue item schema. Test coverage is comprehensive with 680 new lines covering dedup races, end-to-end flows, and edge cases. The only thing I'd want for v2 is explicit `message_subtype` filtering in `_handle_event` rather than relying on downstream guards, but that's defense-in-depth, not a correctness issue. Ship it.
