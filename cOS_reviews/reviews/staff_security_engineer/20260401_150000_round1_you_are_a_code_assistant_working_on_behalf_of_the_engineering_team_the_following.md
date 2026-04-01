# Staff Security Engineer — Review Round 1

**Branch**: `colonyos/add_the_option_to_listen_to_every_message_in_a_c_305511536b`
**PRD**: `cOS_prds/20260401_131917_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Date**: 2026-04-01

## Checklist

### Completeness
- [x] FR-1: `"all"` added to `_VALID_TRIGGER_MODES` in config.py
- [x] FR-2: `message` event bound in `register()` when `trigger_mode == "all"`
- [x] FR-3: `extract_prompt_text()` handles both mention and passive messages
- [x] FR-4: 👀 reaction suppressed for passive messages; deferred to post-triage
- [x] FR-5: Dedup verified with 3 tests (pending race, processed race, end-to-end)
- [x] FR-6: Startup warning logged when `trigger_mode: "all"` and `allowed_user_ids` empty
- [x] FR-7: Startup warning logged when `trigger_mode: "all"` and `triage_scope` empty
- [x] FR-8: `should_process_message()` unchanged — all 5 filters apply uniformly

### Quality
- [x] All 318 tests pass (0 failures)
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies added
- [x] No unrelated changes included
- [x] ~45 lines of production code, ~680 lines of tests — excellent coverage ratio

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive operations
- [x] Error handling present for all failure cases (reaction failures, queue full)

## Security Analysis

### Attack Surface Assessment

**Expanded input surface**: The primary security impact of this change is that in `trigger_mode: "all"`, every message in configured channels reaches the triage LLM. This increases the prompt injection attack surface — an attacker who can post messages in a monitored channel can now inject prompts without @mentioning the bot.

**Mitigating controls** (all pre-existing, all preserved by this diff):
1. **Channel allowlist** (`config.channels`) — limits which channels are monitored
2. **Bot message rejection** — prevents self-triggering loops
3. **Edit rejection** — prevents re-triggering via message edits
4. **Thread rejection** — only top-level messages, reducing noise
5. **Sender allowlist** (`allowed_user_ids`) — optional per-user gating
6. **Triage LLM** — classifies messages as actionable/not before execution

The critical invariant is that `should_process_message()` is the single chokepoint for all access control, and **this function is completely untouched by the diff**. No filters are bypassed for passive messages.

### Information Leakage Prevention

The implementation correctly prevents the bot from revealing its passive listening:

1. **No 👀 on passive intake** — `is_passive` flag suppresses immediate reaction (line 215-219 of slack_queue.py)
2. **No queue-full warning for passive messages** — if the triage queue is full, the message is silently dropped rather than posting a warning that would reveal the bot was listening (line 237-245)
3. **Post-triage 👀 only if actionable** — the bot only reveals awareness of a message after triage confirms it's actionable (line 344-347)

This is the correct "invisible until relevant" behavior per PRD Goal 3.

### `is_passive` Flag Security

The `is_passive` boolean is derived from a deterministic check (`not has_bot_mention(raw_text, self.bot_user_id)`) — there is no user-controllable way to force `is_passive=False` for a passive message or vice versa. The flag flows as metadata through the triage queue and does not affect classification logic, only UX behavior (reaction timing and warning suppression).

### `allowed_user_ids` Enforcement

Per PRD consensus, `allowed_user_ids` remains advisory (warning at startup) rather than mandatory in "all" mode. The security argument for hard enforcement was noted and deferred to v2. The warning implementation in `_warn_all_mode_safety()` is a reasonable compromise — operators are informed but not blocked.

### `message_subtype` Filtering

The `message` event type in Slack carries a `subtype` field for various message types (bot_message, message_changed, channel_join, etc.). The existing `should_process_message()` handles `bot_message` and `message_changed` subtypes. Other subtypes (e.g., `channel_join`, `channel_leave`, `file_share`) would pass through to triage, where the LLM would correctly classify them as non-actionable. Adding explicit subtype filtering would be defense-in-depth but is not a blocking concern for v1 — the triage LLM is the designed filter for these cases.

## Findings

VERDICT: approve

FINDINGS:
- [src/colonyos/slack_queue.py]: `is_passive` derived from deterministic `has_bot_mention()` check — no user-controllable bypass vector. Clean metadata propagation through triage pipeline.
- [src/colonyos/slack_queue.py]: Queue-full warning correctly suppressed for passive messages — prevents information leakage about passive listening. Test coverage confirms this.
- [src/colonyos/slack.py]: `extract_prompt_text()` delegates to existing `extract_prompt_from_mention()` for mention messages, uses `text.strip()` for passive. Downstream `sanitize_slack_content()` applies uniformly regardless of path.
- [src/colonyos/slack.py]: `should_process_message()` is completely unchanged — all 5 access control filters (channel allowlist, bot rejection, edit rejection, thread rejection, sender allowlist) apply uniformly to both mention and passive messages.
- [src/colonyos/daemon.py]: Startup warnings are advisory only. Hard enforcement of `allowed_user_ids` in "all" mode deferred to v2 per PRD consensus — acceptable given channel allowlist and triage LLM provide defense-in-depth.
- [src/colonyos/config.py]: Single-line change adds `"all"` to valid trigger modes. No config migration needed — `trigger_mode` defaults to `"mention"`.

SYNTHESIS:
From a supply chain security and least-privilege perspective, this is a well-contained change. The critical security invariant — that `should_process_message()` is the single, untouched chokepoint for all access control decisions — is preserved. The expanded input surface (all channel messages reaching triage) increases prompt injection volume, but this is gated by pre-existing controls: channel allowlist, sender allowlist, and the triage LLM. The `is_passive` flag is correctly implemented as deterministic, non-user-controllable metadata that governs only UX behavior (reaction timing, warning suppression), not security decisions. Information leakage is properly prevented through conditional 👀 reactions and suppressed queue-full warnings for passive messages. All 318 tests pass with 0 regressions, including dedicated tests for the queue-full privacy leak scenario and dual-event dedup races. No secrets in committed code. Approved.
