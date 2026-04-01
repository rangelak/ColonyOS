# Staff Security Engineer — Review Round 1

**Branch:** `colonyos/add_the_option_to_listen_to_every_message_in_a_c_305511536b`
**PRD:** `cOS_prds/20260401_131917_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## Checklist Assessment

### Completeness
- [x] FR-1: `"all"` added to `_VALID_TRIGGER_MODES` in `config.py`
- [x] FR-2: `bolt_app.event("message")` bound in `register()` when `trigger_mode == "all"`
- [x] FR-3: `extract_prompt_text()` + `has_bot_mention()` handle both mention and passive paths
- [x] FR-4: 👀 reaction skipped for passive messages at intake; deferred to post-triage
- [x] FR-5: Dedup verified with 3 tests (pending-set path, processed-set path, end-to-end)
- [x] FR-6: Startup warning when `allowed_user_ids` empty
- [x] FR-7: Startup warning when `triage_scope` empty
- [x] FR-8: `should_process_message()` unchanged — all existing filters still apply
- [x] All 7 tasks marked complete
- [x] No placeholder or TODO code remains

### Quality
- [x] All 316 tests pass (test_slack.py, test_slack_queue.py, test_daemon.py)
- [x] No linter errors introduced
- [x] Code follows existing conventions (same patch structure, same test patterns)
- [x] No new dependencies added
- [x] No unrelated changes — diff is tightly scoped

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive operations
- [x] Error handling present (try/except around `react_to_message`, `queue.Full` handling)

## Security-Specific Findings

### 1. Attack Surface Expansion — Acceptable with Existing Guards ✅

Activating `trigger_mode: "all"` increases the attack surface: any message in a configured channel now reaches the triage LLM. However, the existing defense layers remain intact:

- **Channel allowlist** (`config.channels`): Only configured channels are monitored
- **Bot rejection** (`bot_id`, `subtype == "bot_message"`): Bot messages dropped
- **Sender allowlist** (`allowed_user_ids`): When configured, restricts who can trigger
- **Thread rejection**: Only top-level messages processed
- **Edit rejection**: Message edits ignored
- **Self-message guard**: Bot's own messages dropped

The implementation correctly does **not** bypass any of these filters. `should_process_message()` is completely unchanged.

### 2. Startup Warnings — Appropriate Severity ✅

FR-6 and FR-7 are implemented as warnings, not hard errors. The PRD explicitly chose warning over enforcement after persona debate. From a security perspective, I'd prefer `allowed_user_ids` to be mandatory in "all" mode, but:

- Private channels where all members are trusted is a valid use case
- The warning is clear and actionable ("Consider restricting allowed_user_ids")
- Operators have agency to accept the risk

This is a reasonable compromise for v1.

### 3. Prompt Injection Surface — Pre-existing, Not Worsened ⚠️

The `extract_prompt_text()` function for passive messages returns `text.strip()` — raw user text goes to the triage LLM and eventually the pipeline. This is the same trust level as `extract_prompt_from_mention()` which also passes user-supplied text after stripping the mention prefix. The sanitization surface is unchanged.

However, in "all" mode, the volume of untrusted input reaching the triage LLM increases. This is a **pre-existing** concern (triage already handles arbitrary user input in mention mode) amplified by broader exposure. Noted but not a blocker.

### 4. 👀 Reaction Timing — Correct Information Leak Prevention ✅

The implementation correctly skips 👀 for passive messages until triage confirms actionable. This prevents information leakage — users don't learn the bot is watching if it doesn't act. The bot stays invisible for non-actionable messages.

### 5. Dedup Correctness — Critical for "All" Mode ✅

Dual-event delivery dedup is the most security-critical aspect: without it, a single @mention in "all" mode would trigger two pipeline runs, doubling budget spend. Three dedup test scenarios cover:
- Pending-set dedup (both events arrive before triage)
- Processed-set dedup (first event completes before second arrives)
- End-to-end (single QueueItem created)

The existing `_is_pending_message` and `watch_state.is_processed` mechanisms handle this correctly.

### 6. No Rate Limit Amplification ✅

The PRD explicitly defers separate rate limits. Existing `max_runs_per_hour` and `daily_budget_usd` apply uniformly. The `check_rate_limit()` call in `_handle_event` is unchanged and fires before triage queuing, preventing budget exhaustion from chatty channels.

### 7. `_triage_and_enqueue` Signature — `is_passive` Default ✅

The `is_passive: bool = False` default means existing callers (if any) maintain backward-compatible behavior. New callers pass the flag explicitly via the triage queue dict.

## VERDICT: approve

FINDINGS:
- [src/colonyos/slack.py]: `extract_prompt_text()` passes raw user text to triage — same trust level as existing `extract_prompt_from_mention()`, but broader exposure in "all" mode. Pre-existing concern, not introduced by this change.
- [src/colonyos/daemon.py]: Startup warnings are appropriate severity. Hard enforcement of `allowed_user_ids` deferred per PRD consensus — acceptable for v1.
- [src/colonyos/slack_queue.py]: All existing security filters in `should_process_message()` remain intact and unchanged. Dedup logic correctly prevents double-processing.

SYNTHESIS:
This is a clean, minimal implementation that correctly activates an existing but unwired configuration path. From a security perspective, the key question was whether expanding the event surface from @mentions to all messages would bypass existing access controls — it does not. The channel allowlist, sender allowlist, bot rejection, and thread rejection filters all still apply before any message reaches the triage LLM. The dedup infrastructure correctly prevents dual-event delivery from doubling budget spend. The conditional 👀 reaction prevents information leakage about the bot's presence. The startup warnings for missing `allowed_user_ids` and `triage_scope` are a reasonable v1 compromise between security and operator flexibility. The only amplified risk is prompt injection volume — more untrusted messages reach the triage LLM — but this is a pre-existing concern that applies equally to mention-mode messages and is properly gated by the triage LLM's classification. Approved.
