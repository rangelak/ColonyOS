# Staff Security Engineer — Review Round 1

**Branch:** `colonyos/add_the_option_to_listen_to_every_message_in_a_c_305511536b`
**PRD:** `cOS_prds/20260401_131917_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## Checklist

### Completeness
- [x] FR-1: `"all"` added to `_VALID_TRIGGER_MODES` in `config.py`
- [x] FR-2: `bolt_app.event("message")` bound when `trigger_mode == "all"` in `register()`
- [x] FR-3: `extract_prompt_text()` correctly dispatches between mention and passive paths
- [x] FR-4: 👀 reaction skipped for passive messages at intake, deferred to post-triage
- [x] FR-5: Dedup via `_is_pending_message` / `watch_state.is_processed` verified with tests
- [x] FR-6: Startup warning for missing `allowed_user_ids` in "all" mode
- [x] FR-7: Startup warning for missing `triage_scope` in "all" mode
- [x] FR-8: All existing `should_process_message()` filters untouched and intact
- [x] All tasks complete — no TODOs or placeholders remain
- [x] No unrelated changes

### Quality
- [x] 318 tests pass (0 failures, 0 regressions)
- [x] Code follows existing project conventions
- [x] No new dependencies added — all imports are internal (`colonyos.slack`)
- [x] Test coverage is thorough: 676+ new test lines covering prompt extraction, event binding, conditional reactions, dedup races, and end-to-end flows

### Security Assessment

**Attack surface expansion:**
- This change widens the bot's input surface from "messages explicitly directed at the bot" to "all top-level messages in configured channels." This is a meaningful security posture change.
- However, the expansion is **controlled**: the channel allowlist, sender allowlist, bot rejection, edit rejection, and thread rejection filters all remain intact in `should_process_message()`, which is completely untouched by this diff.

**Prompt injection risk:**
- In "all" mode, more untrusted user text reaches the triage LLM. This is a pre-existing concern (the triage LLM already processes arbitrary user text in mention mode), but the volume increases.
- No new sanitization is introduced for passive messages, which is correct — `extract_prompt_text()` delegates to `extract_prompt_from_mention()` for mentions and returns `text.strip()` for passive messages. The downstream `sanitize_slack_content()` in `format_slack_as_prompt()` applies equally to both paths.

**Information leakage prevention:**
- [x] Passive messages do NOT get 👀 at intake — prevents revealing the bot is listening
- [x] Queue-full warnings are suppressed for passive messages — prevents revealing the bot was monitoring
- [x] The `is_passive` flag is correctly computed via `has_bot_mention()` before any side effects

**Secrets in code:**
- [x] No secrets, credentials, API keys, or tokens in the diff
- [x] No `.env` files modified

**Access control:**
- Startup warnings (FR-6, FR-7) are advisory, not enforced. The PRD explicitly decided against hard enforcement of `allowed_user_ids` for "all" mode, which I accepted as a compromise in prior review rounds. The warnings are well-worded and actionable.

**Audit trail:**
- All message processing flows through the existing logging in `_handle_event` and `_triage_and_enqueue`. Passive messages are distinguishable via the `is_passive` flag passed through the triage queue. This is sufficient for post-incident analysis.

## Findings

- [src/colonyos/slack_queue.py]: `is_passive` flag is correctly threaded from `_handle_event` through the triage queue dict to `_triage_and_enqueue`, enabling the deferred 👀 reaction pattern. The flag defaults to `False` in the method signature, preserving backward compatibility for any other callers.
- [src/colonyos/slack.py]: `extract_prompt_text()` is a clean dispatcher — no new attack surface beyond what `extract_prompt_from_mention()` already exposes. The `has_bot_mention()` check is a simple string containment (`f"<@{bot_user_id}>" in text`), which is deterministic and not spoofable in a security-relevant way.
- [src/colonyos/daemon.py]: `_warn_all_mode_safety()` is a static method called at startup, correctly placed after engine creation but before `register()`. Warnings are logged at WARNING level, which is appropriate for operational safety advisories.
- [tests/]: 676+ new test lines with excellent coverage of security-relevant scenarios: dedup race conditions, information leakage via 👀 reactions, queue-full behavior for passive vs. mention messages.

## Verdict

VERDICT: approve

FINDINGS:
- [src/colonyos/slack_queue.py]: Passive message flow correctly suppresses all user-visible side effects (👀, queue-full warnings) until triage confirms actionability. No information leakage vectors identified.
- [src/colonyos/slack.py]: `extract_prompt_text()` does not introduce new sanitization gaps. Passive messages take a simpler path (strip only), but downstream `sanitize_slack_content()` applies uniformly.
- [src/colonyos/daemon.py]: Startup warnings are advisory. Hard enforcement of `allowed_user_ids` remains a v2 consideration per PRD consensus.
- [src/colonyos/config.py]: One-line change to add `"all"` to valid trigger modes. No config migration needed.

SYNTHESIS:
From a supply chain and least-privilege perspective, this change is well-contained. The critical security invariant — that `should_process_message()` is the single chokepoint for all access control decisions — is preserved. The function is completely untouched by this diff, and all five filters (channel allowlist, bot rejection, edit rejection, thread rejection, sender allowlist) continue to apply uniformly to both mention and passive messages. The expanded input surface does increase prompt injection volume reaching the triage LLM, but this is a pre-existing risk that scales linearly with channel activity and is properly gated by the existing controls. The implementation correctly prevents information leakage about the bot's passive monitoring through conditional 👀 reactions and suppressed queue-full warnings. The `is_passive` flag provides adequate audit trail differentiation. All 318 tests pass. Approved.
