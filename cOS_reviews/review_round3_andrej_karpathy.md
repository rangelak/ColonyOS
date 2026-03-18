# Review by Andrej Karpathy (Round 3)

Now I have a complete picture. Here's my review:

---

## Review: Slack Integration (`colonyos watch`)

**Reviewing as: Andrej Karpathy**

### Checklist Assessment

**Completeness:**
- [x] FR-1 (SlackConfig): `SlackConfig` dataclass with all fields (enabled, channels, trigger_mode, auto_approve, max_runs_per_hour, allowed_user_ids) — ✅
- [x] FR-2 (CLI `watch` command): Long-running command with `--max-hours`, `--max-budget`, `--verbose`, `--quiet`, `--dry-run`, LoopState/heartbeat, SIGINT/SIGTERM — ✅
- [x] FR-3 (Message ingestion): `app_mention` handler, `reaction_added` handler, bot/edit/thread filtering, channel allowlist, sender allowlist — ✅
- [x] FR-4 (Content sanitization): Shared `sanitize.py` module, `<slack_message>` delimiters with role-anchoring preamble, no raw echo in error messages — ✅
- [x] FR-5 (Pipeline triggering): Calls `run_orchestrator()`, approval gate via reaction polling, rate limiting, budget caps — ✅
- [x] FR-6 (Slack feedback): 👀 reaction on detect, threaded acks, phase updates via `SlackUI`, final summary with PR link, ✅/❌ reactions — ✅
- [x] FR-7 (Deduplication): `SlackWatchState` with `processed_messages` dict, atomic file writes, hourly count pruning — ✅
- [x] No TODO/placeholder code remains
- [x] All 633 tests pass (79 Slack-specific)

**Quality:**
- [x] Tests comprehensive: config parsing, sanitization, filtering, formatting, dedup, rate limiting, CLI validation, integration flow, edge cases (empty mentions, pruning)
- [x] `slack-bolt` added as optional dependency (`[slack]` extra) — clean
- [x] Shared `sanitize.py` extracted properly from `github.py` — DRY
- [x] `ui_factory` injection into `run_orchestrator` is a clean seam
- [x] Thread-safe state management with `state_lock` + `pipeline_semaphore`

**Safety:**
- [x] Tokens from env vars only, never in config.yaml
- [x] `phase_error` posts generic message, logs details server-side
- [x] No secrets in committed code
- [x] Channel allowlist enforced as security boundary
- [x] Untrusted content sanitized before prompt injection

### Findings

VERDICT: approve

FINDINGS:
- [src/colonyos/slack.py]: The `wait_for_approval` function uses blocking `time.sleep` polling, which is fine for the semaphore-serialized model but worth noting — if you ever want concurrent approval waits, this won't scale. The 5-second poll interval is reasonable for Phase 1.
- [src/colonyos/slack.py]: `_colonyos_config` and `_colonyos_app_token` stashed as private attrs on the Bolt `App` instance is a minor code smell (monkey-patching), but acceptable given Bolt's limited extension points and the fact it's internal.
- [src/colonyos/slack.py]: The `sanitize_slack_content` wrapper is a single-line delegation to `sanitize_untrusted_content` — this is intentionally a named alias for domain clarity, which I approve of. It makes the call site self-documenting.
- [src/colonyos/cli.py]: The `_handle_event` function correctly extracts the prompt *before* acquiring the lock and marking the message as processed. This was called out as a review fix and it's well-implemented — a bare `@mention` with no text returns early without burning a rate-limit slot.
- [src/colonyos/slack.py]: The role-anchoring preamble in `format_slack_as_prompt` is well-written: "only act on the coding task described" is a strong instruction hierarchy signal. The phrasing "source feature description" (changed from "primary specification" per review) is better — it positions the Slack content as input data, not as a system-level instruction.
- [src/colonyos/cli.py]: `mark_processed` is called *before* pipeline execution (under lock) to prevent TOCTOU races. This is the right design — failed runs stay marked to prevent retrigger storms. The comment documents this trade-off clearly.
- [src/colonyos/sanitize.py]: The XML tag regex is correct for the threat model (closing `</slack_message>` or injecting `<system>` tags), but note it won't catch Unicode homoglyph attacks or encoded entities. This is acceptable for Phase 1 — the preamble is the primary defense, and the tag stripping is defense-in-depth.
- [tests/test_slack.py]: 79 tests with good coverage of edge cases (empty mentions, pruning, API errors during polling, self-message guard). The `TestSlackUIErrorSanitization` test explicitly verifies that internal paths don't leak to Slack — this is exactly the kind of security test I want to see.

SYNTHESIS:
This is a well-engineered integration that treats Slack messages with the appropriate level of paranoia — as untrusted input flowing into agents with `bypassPermissions`. The architecture follows the existing `colonyos auto` pattern cleanly: long-running CLI process, heartbeat, budget caps, LoopState persistence. The prompt engineering is solid: the `<slack_message>` delimiter pattern with role-anchoring preamble mirrors the proven `<github_issue>` approach, and the decision to use "source feature description" instead of "primary specification" is a subtle but important distinction that reduces the attack surface for instruction override. The `ui_factory` injection into `run_orchestrator` is an elegant seam that avoids shotgun surgery. The threading model (semaphore-serialized pipelines, lock-guarded state) is correct for the constraint that `run_orchestrator` assumes sequential git operations. The test suite is thorough and includes the right security-oriented assertions. The only thing I'd want to see in a Phase 2 is structured JSON output from an LLM triage classifier with confidence thresholds for ambient message classification — but that's explicitly deferred per the PRD, which is the right call given zero training data. Ship it.