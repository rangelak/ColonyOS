# PRD: Unified Slack-to-Queue Autonomous Pipeline

**Date:** 2026-03-19
**Status:** Draft

---

## 1. Introduction / Overview

ColonyOS already has two parallel systems for processing work: a **Slack watcher** (`colonyos watch`) that listens for messages and runs the pipeline inline, and a **queue system** (`colonyos queue`) that processes pre-loaded items sequentially. This feature unifies them into a single end-to-end flow: **listen → triage → queue → execute → report**.

The key missing piece is an **LLM-based triage agent** that sits between Slack message intake and queue insertion, answering the question: *"Is this something I need to work on?"* Additionally, the system needs **smart branch targeting** so that when work depends on an in-flight feature, the PR targets that feature branch instead of `main`.

This transforms ColonyOS from a tool you invoke into an **always-on autonomous coding agent** that monitors a Slack channel (e.g., `#bugs`), autonomously triages incoming messages, queues actionable work, and ships PRs — all with appropriate budget controls and human approval gates.

## 2. Goals

1. **Unify watch + queue** into a single `colonyos watch` command that uses `QueueState` as its backing store instead of running pipelines inline.
2. **Add LLM-based triage** between message intake and queue insertion — a cheap haiku call that outputs a structured accept/skip decision with rationale.
3. **Support explicit branch targeting** — users can specify `base:colonyos/feature-x` in their Slack message to target a feature branch instead of `main`.
4. **Maintain all existing safety controls** — approval gates, budget caps, rate limits, deduplication, content sanitization.
5. **Add daily budget cap** for always-on operation beyond the existing per-run and aggregate caps.

## 3. User Stories

**US-1: Bug channel monitoring**
As a team lead, I add ColonyOS to my `#bugs` channel. When an engineer posts "the CSV export is broken — it truncates at 1000 rows," the bot triages it, posts a summary to the thread ("I can fix this — truncation bug in CSV export. React 👍 to approve."), and upon approval, queues the work, executes the full pipeline, and posts the PR link back to the thread.

**US-2: Feature branch dependency**
As a developer, I post "the new auth middleware breaks session refresh — build on top of colonyos/add-auth-middleware" in `#bugs`. The bot triages, recognizes the explicit base branch, and creates a PR targeting `colonyos/add-auth-middleware` instead of `main`.

**US-3: Intelligent filtering**
As a team member, I post "anyone else's VPN broken today?" in `#bugs`. The triage agent recognizes this is not an actionable code change for the project and silently skips it (optionally posting a brief "Skipping — not an actionable code change" in the thread).

**US-4: Budget-safe always-on operation**
As an ops engineer, I configure `daily_budget_usd: 50.0` and `max_runs_per_hour: 3`. The bot runs 24/7, processing bugs as they come in, but never exceeds $50/day or 3 runs/hour regardless of channel activity.

**US-5: Queue visibility**
As a developer, I post a bug to `#bugs` and the bot replies "Added to queue, position 3 of 5." I can also run `colonyos queue status` to see all items regardless of whether they came from Slack or CLI.

## 4. Functional Requirements

### Triage Agent
- **FR-1:** Add a new triage phase that runs a lightweight LLM call (haiku model) on each incoming Slack message after structural filtering passes.
- **FR-2:** The triage agent receives: the message text (sanitized), `project.name`, `project.description`, `project.stack`, `vision`, and a configurable `triage_scope` string from `SlackConfig`.
- **FR-3:** The triage agent outputs structured JSON: `{"actionable": bool, "confidence": float, "summary": str, "base_branch": str|null, "reasoning": str}`.
- **FR-4:** The triage agent must have **no tool access** — it is a single-turn text-in/JSON-out call, not a full agent session. This minimizes cost and prompt injection blast radius.
- **FR-5:** Add a `triage_scope` field to `SlackConfig` (e.g., `"Bug reports and small fixes for our Python backend; not infrastructure or deployment"`).

### Watch → Queue Unification
- **FR-6:** Modify the `watch` command to insert triaged items into `QueueState` (with `source_type="slack"`) instead of spawning pipeline threads directly.
- **FR-7:** Add a queue executor loop running in a separate thread within the `watch` command that drains `QueueState` items sequentially (reusing the existing `pipeline_semaphore`).
- **FR-8:** Add `source_type="slack"` to the `QueueItem` model alongside the existing `"prompt"` and `"issue"` types.
- **FR-9:** Store the originating Slack message timestamp (`slack_ts`) and channel on `QueueItem` so the executor can post threaded replies via `SlackUI`.
- **FR-10:** `colonyos queue status` must show all items regardless of source (Slack or CLI).

### Branch Targeting
- **FR-11:** Add an optional `base_branch` field to `QueueItem`.
- **FR-12:** The triage agent extracts `base_branch` from explicit user syntax (e.g., `base:colonyos/feature-x` or `build on top of colonyos/feature-x`).
- **FR-13:** When `base_branch` is specified, the orchestrator checks out that branch before pipeline execution and sets the PR target accordingly.
- **FR-14:** Validate that the specified `base_branch` exists (locally or on remote) before accepting the item. If invalid, post a message and skip.

### Budget & Rate Limits
- **FR-15:** Add `daily_budget_usd` field to `SlackConfig` with a required explicit value (no dangerous default).
- **FR-16:** Track daily spend in `SlackWatchState` and reset the counter at midnight UTC.
- **FR-17:** Add `max_queue_depth` to `SlackConfig` (default 20) to prevent unbounded queue growth from channel floods.

### Feedback & Error Handling
- **FR-18:** Post a triage acknowledgment to the message thread: "I can fix this — [summary]. React 👍 to approve." (when approval required) or "Adding to queue, position N of M." (when auto-approved).
- **FR-19:** When triage skips a message, optionally post a brief explanation to the thread (controlled by a `triage_verbose` config flag, default `false`).
- **FR-20:** Failed queue items are marked `FAILED`, a failure message is posted to the originating Slack thread, and the queue continues to the next item. No auto-retry.
- **FR-21:** Add `max_consecutive_failures` config (default 3) — if N items fail in a row, pause the queue and notify the channel.

## 5. Non-Goals

- **Priority queuing** — FIFO is sufficient for v1. Priority can be added later without data model changes.
- **Automatic dependency detection** — The system will not analyze code overlap to infer branch dependencies. Users must declare them explicitly.
- **Parallel pipeline execution** — The semaphore stays at 1. Parallelism requires isolated worktrees, which is a separate architectural change.
- **Batching related bugs** — Each item is processed independently. Semantic grouping is a separate feature.
- **Image/screenshot analysis** — Triage operates on message text only.
- **Auto-retry on failure** — Failed items stay failed until a human re-queues them.

## 6. Technical Considerations

### Existing Code to Modify

| File | Change |
|------|--------|
| `src/colonyos/slack.py` | Add `triage_message()` function; update `format_slack_as_prompt()` for triage context |
| `src/colonyos/cli.py` | Refactor `watch` command to use `QueueState` backing; add queue executor thread; wire triage into `_handle_event` |
| `src/colonyos/config.py` | Add `triage_scope`, `daily_budget_usd`, `max_queue_depth`, `triage_verbose`, `max_consecutive_failures` to `SlackConfig` |
| `src/colonyos/models.py` | Add `base_branch`, `slack_ts`, `slack_channel`, `source_type="slack"` to `QueueItem`; add `daily_cost_usd`, `daily_cost_reset_date` to `SlackWatchState`; add `pr_url` field to `RunLog` |
| `src/colonyos/orchestrator.py` | Accept `base_branch` parameter; modify preflight to check out specified branch; set PR target |

### Architecture Decision: Triage Agent

All 7 expert personas unanimously agreed: the triage must be LLM-based, not regex. The triage call uses the **haiku model** (fractions of a cent per call) with **no tool access** — a single-turn structured output call. This keeps costs near-zero while providing semantic understanding that regex cannot achieve.

The security engineer specifically noted that the triage agent should NOT use `bypassPermissions` mode — it needs zero tool access since it only evaluates text and returns JSON.

### Architecture Decision: Unify Watch + Queue

All personas agreed: do not create a third flow. The `watch` command already handles Slack listening, filtering, rate limiting, budget caps, and shutdown. The `queue` system provides sequential execution with persistence and crash recovery. Unifying them means:
- Slack events → triage → `QueueItem` insertion (producer)
- Queue executor thread → drain items → run pipeline (consumer)
- Single `QueueState` backing store for both Slack and CLI sources

### Architecture Decision: Branch Targeting

All personas agreed: explicit declaration only. Users specify `base:branch-name` in the Slack message. The triage agent extracts it as a structured field. Auto-detection is a research problem, not an engineering one.

### Existing Patterns to Reuse
- `should_process_message()` — structural filtering (already handles bot/thread/edit/channel guards)
- `wait_for_approval()` — thumbsup polling (already production-ready)
- `post_run_summary()` — threaded reply with PR URL (already built)
- `SlackUI` — per-phase progress posting (already implements `PhaseUI` interface)
- `QueueState` / `QueueItem` — persistent queue with crash recovery (already handles RUNNING→PENDING recovery on restart)
- `format_slack_as_prompt()` — sanitization with role-anchoring preamble (already handles prompt injection defense)

### Dependencies
- `slack-bolt[socket-mode]` — already an optional dependency
- `claude-agent-sdk` — already a core dependency
- No new external dependencies required

## 7. Success Metrics

| Metric | Target |
|--------|--------|
| Triage accuracy | >90% correct accept/skip decisions on a sample of 50 real Slack messages |
| End-to-end latency | Triage decision within 5 seconds of message receipt |
| Queue throughput | Process ≥3 items/hour at default rate limit |
| False positive rate | <10% of triaged items result in NO-GO at decision gate |
| Budget adherence | Never exceeds daily_budget_usd by more than one per_run cap |
| Crash recovery | After process restart, no items are lost (RUNNING items recover to PENDING) |

## 8. Open Questions

1. **Triage skip visibility**: Should the bot post a reason when it skips a message? The Karpathy persona favors transparency; others worry about noise. Current design: off by default (`triage_verbose: false`), configurable.
2. **Per-channel auto_approve**: The current `auto_approve` is global. Should it become per-channel? (e.g., auto-approve in `#bugs` but require approval in `#feature-requests`). Deferred to v2.
3. **`pr_url` on RunLog**: The existing code uses `getattr(log, "pr_url", None)` suggesting it's not a declared field. This should be fixed regardless of this feature — flagged by multiple personas.
4. **Confidence threshold for auto-approve**: Should high-confidence triage (>0.9) bypass the approval gate? Deferred to v2 — default requires human approval for all items.
5. **Daily budget reset timezone**: Currently specified as midnight UTC. Should this be configurable? Probably not worth the complexity.
