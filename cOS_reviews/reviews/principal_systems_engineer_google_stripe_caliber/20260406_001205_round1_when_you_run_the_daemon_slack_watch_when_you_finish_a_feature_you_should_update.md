# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

Now I have a comprehensive picture. Let me write the review output.

---

## Review: Principal Systems Engineer (Google/Stripe caliber)

I've reviewed all 7 files changed across 6 commits on branch `colonyos/when_you_run_the_daemon_slack_watch_when_you_finish_a_feature_you_should_update`. All 338 tests pass. The core architecture is well-designed — edit-in-place via `chat_update`, fallback to `chat_postMessage`, error isolation, and independent `FanoutSlackUI` targets are all solid. However, I found two issues that will cause problems in production.

### Issue 1: No debounce on `chat_update` — will hit Slack rate limits

The PRD explicitly calls out: *"Edits should be batched/debounced — don't update on every single `phase_note` call; accumulate and flush periodically (e.g., every 3-5 seconds or on phase transitions)"* (§6, Slack API considerations). Task 2.4 specifies *"with debounce — flush on phase transitions or every ~5 seconds"*.

The implementation calls `chat_update` on **every** `phase_note()` call with zero debounce:

```python
def phase_note(self, text: str) -> None:
    note = text.strip()
    if not note:
        return
    self._note_buffer.append(note)
    self._flush_buffer()  # ← immediate chat_update, no batching
```

During the implement phase, the orchestrator fires 15-30 `slack_note` calls for task progress. These will all hit `chat_update` in rapid succession. Slack's Tier 2 rate limit is ~1 request/sec per channel. At 3am when a pipeline is running across multiple merged requests via `FanoutSlackUI`, you're multiplying this by the number of targets. This will result in `429 Too Many Requests` errors, triggering fallback to `chat_postMessage`, which **defeats the entire purpose of the feature** (message consolidation degrades to the old behavior under load).

### Issue 2: Outbound sanitization gap on `phase_note` → `chat_update` path

FR-5 states: *"All LLM-generated content posted to Slack must pass through secret-redaction sanitization."* The `generate_phase_summary()` output is correctly sanitized. But the **majority of Slack content** flows through `phase_note()` → `_flush_buffer()` → `chat_update`, and this path has **no** `sanitize_outbound_slack()` call.

Content flowing through this unsanitized path includes: task outlines (formatted from LLM plan output), per-task implement results (LLM-generated), review findings and verdicts (LLM-generated), and decision text. Any of these could contain leaked secrets from the LLM context. The sanitization should be applied in `_flush_buffer()` before the `chat_update` call.

### Minor findings

- **`except Exception: pass`** in orchestrator (L4803, L5058) silently swallows failures with no logging. The `generate_phase_summary` function already has its own try/except with `logger.debug`. The orchestrator wrapper adds a second layer of silent swallowing. If the import itself fails (e.g., circular import regression), you'd never know. At minimum, add `logger.debug("plan summary failed", exc_info=True)`.

- **Plan `phase_complete` was never called before** — the diff adds `plan_ui.phase_complete()` inside the `if plan_ui is not None:` block (L4804-4808), but the original code never called `phase_complete` for the plan phase. This is a behavioral change — likely correct and intentional, but worth a comment.

- **`Phase.TRIAGE` reuse for summary generation** — `generate_phase_summary` routes through `run_phase_sync(Phase.TRIAGE, ...)` for both plan and review summaries. Cost and telemetry will be attributed to TRIAGE rather than the actual phase, muddying cost breakdowns.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/slack.py L755-756]: `phase_note()` calls `_flush_buffer()` on every invocation with no debounce — will hit Slack Tier 2 rate limits (~1/sec) during implement phase (15-30 rapid calls). PRD §6 and task 2.4 explicitly require debouncing.
- [src/colonyos/slack.py L671-699]: `_flush_buffer()` posts LLM-generated content to Slack without calling `sanitize_outbound_slack()` — violates FR-5 ("All LLM-generated content posted to Slack must pass through secret-redaction sanitization"). Only `generate_phase_summary` output is sanitized; raw orchestrator notes are not.
- [src/colonyos/orchestrator.py L4803]: Bare `except Exception: pass` silently swallows all failures including import errors. At minimum log at debug level for observability.
- [src/colonyos/orchestrator.py L4804-4808]: `plan_ui.phase_complete()` is a new behavioral addition — plan phase previously never signaled UI completion. Likely intentional but undocumented.
- [src/colonyos/slack.py L1156]: `Phase.TRIAGE` is reused for summary generation, misattributing cost to triage rather than the actual phase being summarized.

SYNTHESIS:
The edit-in-place architecture is fundamentally sound — `_compose_message` / `_flush_buffer` with fallback, independent `FanoutSlackUI` state, and error isolation are all well-engineered. Test coverage is excellent (338 pass, comprehensive E2E and fanout scenarios). However, the missing debounce is a production reliability gap that will cause the feature to degrade under real workloads — exactly the kind of thing that works perfectly in tests but fails at 3am. The outbound sanitization gap on the primary content path (`phase_note` → `_flush_buffer`) is a security concern given that most Slack content is LLM-generated. Both issues are straightforward to fix: add a timestamp-based debounce in `_flush_buffer` (flush if >3s since last update OR on phase transitions), and apply `sanitize_outbound_slack` to the composed body in `_flush_buffer` before posting.
