# PRD: Slack Thread Message Consolidation & LLM Content Surfacing

**Date**: 2026-04-05
**Status**: Draft
**Author**: ColonyOS Planning Agent

---

## 1. Introduction/Overview

When ColonyOS runs in daemon mode watching Slack (`colonyos daemon slack watch`), it processes feature requests through a full pipeline (plan → implement → review → decision → fix → verify → learn). Currently, each pipeline run produces **~50 Slack messages per thread** — phase headers, per-task progress notes, phase completions, task outlines, and result summaries across 7 phases. This creates overwhelming noise that trains users to ignore the thread entirely, including the final summary that actually matters.

This feature consolidates Slack thread output to **~5 messages per run** by:
1. Using Slack's `chat_update` API to edit messages in-place instead of posting new ones
2. Posting concise LLM-generated summaries of meaningful phases (plan, review, final result) instead of raw status labels
3. Collapsing per-task progress into a single updating message per phase

The reaction flow (`:eyes:` → `:white_check_mark:` + `:tada:`) is already implemented correctly in `cli.py` L3696-3712 and L3968-3983 and requires no changes.

## 2. Goals

1. **Reduce Slack thread messages from ~50 to ≤7** for a full pipeline run
2. **Surface LLM-generated content** — plan summaries, review verdicts, and completion summaries — as rich threaded replies instead of just phase status labels
3. **Preserve observability** — errors always get their own message, and the terminal UI / run logs remain verbose
4. **Maintain security** — sanitize all LLM-generated content for secrets before posting to Slack

## 3. User Stories

**US-1**: As a developer watching a Slack channel, I want to see a concise thread with ~5 messages telling me what the agent planned, what it built, whether the review passed, and a link to the PR — not 50 granular status updates.

**US-2**: As a non-technical stakeholder, I want the Slack thread to contain meaningful LLM-generated summaries (e.g., "Adding a retry mechanism to the payment handler with exponential backoff") instead of opaque status labels ("Plan is ready (45s)").

**US-3**: As a developer, I want implementation progress shown as a single updating message ("Implementing: 3/5 tasks complete") instead of 30+ individual task messages.

**US-4**: As a developer, when the agent finishes, I want to see `:white_check_mark:` + `:tada:` reactions on my original message and a final summary with PR link, cost, and what was done.

## 4. Functional Requirements

### FR-1: Add `chat_update` to SlackClient protocol
- Add `chat_update(channel, ts, text, **kwargs)` method to the `SlackClient` protocol in `slack.py` L38-59
- This enables editing existing messages in-place instead of posting new ones

### FR-2: Refactor SlackUI to use edit-in-place pattern
- `SlackUI` (slack.py L620-720) currently posts a new message for every `phase_header`, `phase_note`, `phase_complete`, and `slack_note` call
- Refactor to:
  - `phase_header()` → posts one message, stores its `ts` as `_current_msg_ts`
  - `phase_note()` → appends content to the current phase message via `chat_update` (buffered, not per-call)
  - `phase_complete()` → final `chat_update` to the current phase message with completion status
- Net effect: **one message per phase** instead of 3-10+ per phase

### FR-3: Collapse implementation progress into a single updating message
- The implement phase currently generates the most messages via `slack_note` calls in `orchestrator.py` L4809, L4834, L4868
- Replace individual task progress messages with a single message that gets edited: "Implementing: 2/5 tasks complete ✓ task1, ✓ task2, ⏳ task3..."
- Cap visible tasks at 6 with "+N more" overflow (matches existing `_SLACK_MAX_SHOWN_TASKS`)

### FR-4: Generate concise Slack-specific summaries per meaningful phase
- After plan phase: post a 2-3 sentence summary of what will be done + task count
- After review phase: post verdict ("Approved" / "Changes requested") + top finding
- At completion: already uses `generate_plain_summary()` — keep this
- Use the existing `generate_plain_summary()` pattern (slack.py L1044) as template for per-phase summaries
- Use a cheap model call (Haiku-class, ~$0.001) with a strict character limit ("respond in under 280 characters")

### FR-5: Apply outbound secret sanitization
- All LLM-generated content posted to Slack must pass through secret-redaction sanitization
- Leverage `sanitize_ci_logs()` from `sanitize.py` for secret pattern matching
- Enforce a 3,000-character ceiling on any single LLM-generated Slack post
- Add patterns for `sk-ant-`, PEM headers, GCP service account fragments

### FR-6: Propagate edit-in-place through FanoutSlackUI
- `FanoutSlackUI` (slack.py L725-770) mirrors updates to multiple threads (merged requests)
- Must propagate the new edit-in-place behavior — each target tracks its own `_current_msg_ts`

### FR-7: Keep error messages as distinct posts
- `phase_error()` must always post a **new** message (not edit the phase message) so errors are never hidden inside an update
- This ensures failures are immediately visible in the thread

## 5. Non-Goals

- **Changing the reaction flow** — `:eyes:` → `:white_check_mark:` + `:tada:` is already implemented correctly
- **Adding a verbose/concise config toggle** — concise is the new default; the terminal TUI and run logs provide verbose output for debugging (all 7 personas agreed: no toggle)
- **Modifying the terminal UI** — `PhaseUI` / `NullUI` in `ui.py` and `DaemonMonitorEventUI` in `daemon/_ui.py` remain verbose for developers
- **Changing orchestrator event emission** — the orchestrator keeps emitting fine-grained events for logs and TUI; only `SlackUI` changes how it renders them
- **Reducing triage/acknowledgment messages** — the initial triage acknowledgment and queue position message stay as-is

## 6. Technical Considerations

### Architecture: SlackUI consolidation, not orchestrator changes

All 7 personas agreed: the consolidation logic belongs in `SlackUI`, not in the orchestrator. The orchestrator should keep emitting fine-grained events (`phase_note`, `slack_note`) for the terminal UI and disk logs. `SlackUI` buffers and consolidates internally, using `chat_update` instead of `chat_postMessage`.

### Key files to modify

| File | What changes |
|------|-------------|
| `src/colonyos/slack.py` L38-59 | Add `chat_update` to `SlackClient` protocol |
| `src/colonyos/slack.py` L620-720 | Refactor `SlackUI` to edit-in-place |
| `src/colonyos/slack.py` L725-770 | Update `FanoutSlackUI` for new pattern |
| `src/colonyos/slack.py` ~L1044 | Add per-phase summary generation (reuse `generate_plain_summary` pattern) |
| `src/colonyos/sanitize.py` | Add `sanitize_outbound_slack()` + additional secret patterns |
| `tests/test_slack.py` | Update/add tests for new SlackUI behavior |
| `tests/test_slack_queue.py` | Verify no regressions in triage/enqueue flow |

### Files that should NOT change

| File | Why |
|------|-----|
| `src/colonyos/orchestrator.py` | Keeps emitting fine-grained events; SlackUI handles consolidation |
| `src/colonyos/cli.py` L3696-3712 | Reaction flow already correct |
| `src/colonyos/ui.py` | Terminal UI stays verbose |
| `src/colonyos/daemon/_ui.py` | CombinedUI forwards to SlackUI; delegation unchanged |

### Slack API considerations

- `chat_update` shares the same Tier 2 rate limit (~1/sec per channel) as `chat_postMessage`
- Edits should be batched/debounced — don't update on every single `phase_note` call; accumulate and flush periodically (e.g., every 3-5 seconds or on phase transitions)
- Slack message max: 40,000 chars — enforce a 3,000-char ceiling for safety

### Message flow: before vs. after

**Before (~50 messages):**
```
:eyes: reaction
Acknowledgment message
:memo: Working on the plan
Plan task outline (8 bullets)
:memo: Plan is ready (45s)
:hammer_and_wrench: Writing the code
Task outline (5 tasks)
Task 1.0 result...
Task 2.0 result...
Task 3.0 result...
Task 4.0 result...
Task 5.0 result...
Implement results summary
:hammer_and_wrench: Code is written (120s)
:mag: Reviewing the changes
Review findings...
Review verdict...
:mag: Review is done (30s)
:scales: Making the final call
Decision...
:scales: Decision made (5s)
:wrench: Fixing issues from review
Fix task outline...
Fix results...
:wrench: Fixes applied (45s)
:white_check_mark: Running final checks
:white_check_mark: Checks passed (10s)
:bulb: Extracting lessons learned
:bulb: Lessons recorded (5s)
Final summary
(repeat for fix rounds...)
```

**After (~5-7 messages):**
```
:eyes: reaction
Acknowledgment: "Got it — adding retry logic to payment handler. Queued #3 of 4."
Plan: "Planning to modify 3 files: add exponential backoff to PaymentClient.retry(), update config schema, add integration test. 5 implementation tasks."
Implement: "Implementing: 5/5 tasks complete ✓" (single message, edited 5 times)
Review: "Review passed — all 3 reviewers approved. Minor suggestion: add jitter to backoff (non-blocking)."
Final: "✅ Pipeline completed — PR #142 ready for merge. Branch: colonyos/add-retry-logic. Cost: $0.45"
:white_check_mark: + :tada: reactions
```

### Security: Outbound sanitization (per Staff Security Engineer)

The current `sanitize_for_slack()` and `sanitize_untrusted_content()` handle *inbound* injection (mrkdwn formatting, @mentions). They do NOT handle *outbound* secret leakage from LLM outputs. A new `sanitize_outbound_slack()` function must compose:
1. Secret pattern redaction (extend `SECRET_PATTERNS` in `sanitize.py`)
2. Character length cap (3,000 chars)
3. Existing `sanitize_for_slack()` for mrkdwn safety

## 7. Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Messages per Slack thread (full run) | ~50 | ≤7 |
| Messages per Slack thread (implement phase) | ~15-30 | 1 (edited in-place) |
| LLM content in thread | Status labels only | Plan summary + review verdict + final summary |
| User reaction to thread | Mute/ignore | Read and engage |

## 8. Open Questions

1. **Debounce interval**: How frequently should `phase_note` edits be flushed? Every 3s? 5s? On phase transitions only?
2. **Summary model**: Should per-phase summaries use the same model as the phase, or always use a cheap model (Haiku)?
3. **Edit failure fallback**: If `chat_update` fails (e.g., message too old), should we fall back to posting a new message?
4. **Thread-fix rounds**: When a user requests a fix in the thread, should the fix round also use the consolidated format?

## Persona Synthesis

### Areas of unanimous agreement (7/7):
- **Reactions are done** — no changes needed to `:eyes:` → `:white_check_mark:` + `:tada:`
- **No config toggle** — concise is the only mode for Slack; verbose lives in TUI/logs
- **Consolidation in SlackUI** — orchestrator keeps emitting events; SlackUI handles rendering
- **Edit-in-place** — use `chat_update` instead of posting new messages
- **5-7 messages target** — down from ~50
- **High priority** — noisy Slack threads are a retention/adoption problem

### Areas of tension:
- **Per-phase message count**: Systems Engineer suggested 7 (one per phase), while most others said 5 (only meaningful phases get messages). **Resolution**: 5-7 depending on whether fix rounds are needed.
- **Separate LLM call for summaries**: Karpathy strongly favors it (cheap Haiku call, better quality). Linus and Systems Engineer prefer deterministic formatting. **Resolution**: Use a cheap LLM call for plan and review summaries; use deterministic formatting for implement progress.
- **`slack_note` indirection**: Linus calls it "pointless" and wants it removed. Others don't mention it. **Resolution**: Keep `slack_note` as a public method (it's part of the UI protocol) but internally it feeds the same buffer as `phase_note`.
