# PRD: Parallel Slack Intake — Decouple Triage from Pipeline Execution

**Date:** 2026-03-31
**Status:** Draft
**Aggregated Requests:** 2 similar requests from #C0AMQFD55HA

---

## 1. Introduction / Overview

When a Slack message arrives in ColonyOS, it currently waits for the running pipeline to release `agent_lock` before the triage LLM call can classify it. This means a user who sends a feature request while the agent is mid-pipeline may wait **minutes** before receiving a queue position — even though triage is a lightweight, stateless classification call (~2-5 seconds).

This feature decouples Slack message intake from pipeline execution so that triage runs immediately and in parallel, giving users a queue position within seconds regardless of what the agent is doing.

## 2. Goals

1. **Instant intake**: Slack messages are triaged and enqueued within seconds of arrival, regardless of pipeline state.
2. **Zero regression**: Existing thread-safety guarantees (`state_lock` for queue mutations) remain intact.
3. **Minimal change surface**: The fix is surgically scoped — remove the `agent_lock` serialization from the triage path without restructuring the worker architecture.
4. **Improved resilience**: Add bounded retry for transient triage failures instead of dropping messages.
5. **Hardened rate limiting**: Close the TOCTOU gap in hourly count tracking to prevent burst abuse.

## 3. User Stories

- **As an engineer**, when I @mention the bot with a feature request while it's mid-pipeline, I want to see my queue position within 5 seconds, not after the current pipeline phase completes.
- **As a team lead**, I want the system to acknowledge and classify every Slack request immediately so I can see the full queue state in real-time.
- **As an engineer**, if the triage LLM call fails transiently (timeout, rate limit), I want the system to retry once before giving up, rather than silently dropping my request.

## 4. Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | Remove `agent_lock` acquisition from the triage path in `_triage_and_enqueue()` at `slack_queue.py:257`. Triage LLM calls must execute without waiting for pipeline, CEO, or scoring operations to release the lock. |
| FR-2 | The `agent_lock` field on `SlackQueueEngine` should no longer be passed or used for triage. The field may remain for future use but must not gate triage. |
| FR-3 | All queue mutations (similarity matching, demand signal merging, item creation, persistence) must continue to be protected by `state_lock`. No changes to queue consistency model. |
| FR-4 | Add bounded retry (1 retry with 3-second backoff) for transient triage failures (timeouts, 5xx, 429) before falling through to the existing error handler. |
| FR-5 | Mark failed triage messages as processed with status `"triage-error"` in `watch_state` to prevent Slack redelivery loops. |
| FR-6 | Move `increment_hourly_count()` to fire at message reservation time (inside `_handle_event`) rather than after triage completion, closing the TOCTOU gap where burst messages bypass rate limits. |
| FR-7 | Existing `:eyes:` reaction timing (immediate, before triage) must not change. |
| FR-8 | Single triage worker thread architecture is preserved. No thread pool changes in V1. |

## 5. Non-Goals

- **Multiple triage workers / thread pool**: The single `slack-triage-worker` thread is sufficient for expected message volumes. Parallelism within triage is deferred.
- **Heuristic triage (no-LLM fast path)**: Keyword-based classification to skip the LLM call for obvious messages is a valuable optimization but out of scope for V1.
- **Separate triage budget pool**: Triage costs (~$0.05/call) are negligible relative to pipeline costs. A separate budget adds complexity for no practical benefit at current scale.
- **Triage cost tracking on QueueItem**: Adding a `triage_cost_usd` field is a useful observability improvement but deferred.
- **Queue maxsize tuning**: The `maxsize=64` default is adequate and not changed.

## 6. Technical Considerations

### Architecture

The current flow in `src/colonyos/slack_queue.py`:

```
Slack event → _handle_event() → :eyes: reaction → _triage_queue.put()
                                                          ↓
                                              _triage_worker_loop()
                                                          ↓
                                            _triage_and_enqueue()
                                                          ↓
                                         ┌─ agent_lock ←── BOTTLENECK
                                         │   triage_message() [LLM call]
                                         └─ state_lock
                                              similarity match → enqueue → persist
```

After this change:

```
Slack event → _handle_event() → :eyes: reaction → _triage_queue.put()
                                                          ↓
                                              _triage_worker_loop()
                                                          ↓
                                            _triage_and_enqueue()
                                                          ↓
                                              triage_message() [LLM call, NO lock]
                                                          ↓
                                              state_lock
                                                similarity match → enqueue → persist
```

### Key Files

| File | Role | Change |
|------|------|--------|
| `src/colonyos/slack_queue.py` | Triage worker, lock usage, queue insertion | Primary: remove `agent_lock` from triage path, add retry, move hourly count, mark failed triages |
| `src/colonyos/daemon.py` | Creates and passes `agent_lock` | Minor: `agent_lock` still passed but no longer gates triage |
| `tests/test_slack_queue.py` | Unit tests for SlackQueueEngine | Add/update tests for parallel triage, retry, rate-limit timing |

### Thread Safety Analysis

- **`triage_message()`** is a pure, stateless LLM classification call. It reads `repo_root` and config but mutates nothing in shared memory or on disk. Safe to call without `agent_lock`.
- **`state_lock`** already correctly guards all queue state mutations (lines 303-358). No changes needed.
- **`_pending_messages`** set prevents duplicate processing of the same Slack event. Accessed under `state_lock`.
- **Race condition (similarity matching)**: Two concurrent triage calls for semantically similar (but distinct) messages could both pass similarity matching before either appends, creating duplicate queue items instead of a merge. This is acceptable because: (a) it requires two distinct messages triaged within the same ~3-second window, (b) `_reserve_pending_message` prevents identical Slack events from racing, and (c) duplicate queue items are a cosmetic issue, not a correctness bug.

### Persona Consensus & Tensions

**Unanimous agreement (7/7 personas):**
- Remove `agent_lock` from the triage path
- "Processed" means the full `_triage_and_enqueue` flow (triage + enqueue)
- Concurrent triage LLM calls are acceptable (negligible cost vs. pipeline)
- `state_lock` is already correct and sufficient
- `:eyes:` reaction timing is already correct (before triage)
- Single triage worker is fine for V1

**Majority agreement (5-6/7):**
- Same budget pool for triage and pipeline
- Add bounded retry for transient failures

**Notable dissent:**
- **Security Engineer**: Wants separate triage budget pool, tighter maxsize (8-16), and a dedicated triage semaphore instead of removing the lock entirely. Also identified the TOCTOU rate-limit gap (FR-6) and redelivery loop risk (FR-5) — both adopted.
- **Jony Ive**: Wants separate budget pool so queue intake stays alive when pipeline budget is paused. Deferred — the existing `is_budget_exceeded` check gates at event intake, not triage time.
- **Andrej Karpathy**: Suggests heuristic triage fast-path using keyword matching (like `_heuristic_mode_decision` in `router.py:133-240`). Valuable but deferred to Non-Goals.

## 7. Success Metrics

| Metric | Target |
|--------|--------|
| Time from Slack message to queue position acknowledgment | < 10 seconds (down from minutes when pipeline is active) |
| Triage failures silently dropped | 0 (all failures either retried successfully or marked in watch_state) |
| Test coverage for parallel triage scenarios | 100% of new code paths |
| Regression in existing tests | 0 failures |

## 8. Open Questions

1. **Should `agent_lock` field be removed from `SlackQueueEngine` entirely?** It's currently optional (`None` fallback to `nullcontext`). Removing it is cleaner but is a larger interface change. Recommendation: keep the field, just stop acquiring it in `_triage_and_enqueue`.
2. **Should we add a lightweight `threading.Semaphore(1)` for triage-to-triage serialization?** Currently the single worker thread provides this implicitly. Only relevant if we later move to multiple triage workers.
3. **Is the 3-second retry backoff the right duration?** Should be long enough to survive a transient 429 but short enough that the user isn't waiting too long.
