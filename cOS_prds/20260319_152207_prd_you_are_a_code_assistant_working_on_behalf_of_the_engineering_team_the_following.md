# PRD: Slack Thread Fix Requests — Conversational PR Iteration

## Introduction/Overview

This feature enables **conversational iteration on PRs via Slack threads**. When ColonyOS completes a pipeline run triggered from Slack, users can `@mention` the bot in the same thread to request fixes on the existing PR. The bot re-launches a lightweight fix pipeline on the same branch, pushes new commits, and reports results back to the thread.

**Current state:** The bot already posts phase-by-phase updates to Slack threads via `SlackUI` (in `src/colonyos/slack.py`), including cost, phase status, branch name, and PR link in the final summary. However, `should_process_message()` (line 112-114 of `slack.py`) explicitly ignores threaded replies (`thread_ts != ts`), so there is no mechanism for follow-up interactions.

**Why it matters:** Today, after a pipeline run, the only way to iterate is to post a new top-level message or manually fix the PR. This breaks the conversational flow — the thread already contains all context about the work item. Enabling thread-based fix requests turns the Slack thread into a single source of truth for the entire lifecycle of a change.

## Goals

1. **Enable thread-based fix requests**: Users can `@mention` the bot in an existing pipeline thread to request changes on the PR
2. **Re-use existing branch/PR**: Fix runs push commits to the same branch, keeping the PR intact with its review context
3. **Lightweight pipeline**: Fix requests skip Plan and triage, running only Implement → Verify → Deliver
4. **Cost-controlled iteration**: Hard cap on fix rounds per thread (default 3) with budget enforcement
5. **Maintain security posture**: Thread replies go through the same sanitization pipeline as top-level messages

## User Stories

1. **As an engineer**, I want to reply in a pipeline thread saying "@ColonyOS fix the failing test in test_auth.py" and have the bot make the fix on the same PR, so I don't have to context-switch to a terminal or create a new request.

2. **As a team lead**, I want to see fix request costs reported in the same thread alongside the original run costs, so I can track the total cost of a change.

3. **As a security-conscious admin**, I want thread fix requests to go through the same content sanitization as top-level messages, so the attack surface is not expanded.

4. **As an engineer**, I want the bot to tell me immediately if the branch was merged/deleted when I request a fix, so I don't wait for a pipeline that will fail.

## Functional Requirements

### Thread Reply Detection

1. **FR-1**: Add a new function `should_process_thread_fix()` in `slack.py` that accepts threaded replies (`thread_ts != ts`) where the bot is `@mentioned` and the parent `thread_ts` maps to a known completed `QueueItem`
2. **FR-2**: The existing `should_process_message()` MUST remain unchanged — top-level and thread-fix are separate code paths
3. **FR-3**: Thread fix requests must respect `allowed_user_ids` from `SlackConfig`

### Thread-to-Run Mapping

4. **FR-4**: Look up the original run by scanning `QueueState.items` for a `QueueItem` where `slack_ts == event["thread_ts"]` and `status == COMPLETED`
5. **FR-5**: Add `branch_name` field to `QueueItem` (alongside existing `pr_url`, `slack_ts`, `slack_channel`) to avoid needing to load `RunLog` from disk
6. **FR-6**: Add `fix_rounds` counter field to `QueueItem` (default 0) to track thread-fix iterations

### Fix Pipeline

7. **FR-7**: Create a new `run_thread_fix()` function in `orchestrator.py` that:
   - Checks out the existing feature branch
   - Validates branch exists and PR is still open (via `validate_branch_exists` and `check_open_pr`)
   - Verifies HEAD SHA matches last known state (defense against force-push tampering)
   - Runs Implement phase with the user's fix message as the prompt, injecting original PRD/task context
   - Runs Verify phase (test suite)
   - Runs Deliver phase (push to existing branch — no new PR creation)
8. **FR-8**: Skip Plan phase entirely — the user's thread message IS the spec
9. **FR-9**: Skip triage — a threaded `@mention` reply on a known completed run is an explicit, intentional instruction

### Slack UX

10. **FR-10**: Immediately acknowledge fix requests with `:eyes:` reaction + threaded reply: ":wrench: Working on fix for `branch-name` — implementing your changes."
11. **FR-11**: Post phase updates to the same thread via existing `SlackUI`
12. **FR-12**: Post fix run summary with cost, branch, and updated PR link
13. **FR-13**: On error (branch deleted, PR merged, max rounds), post a clear, actionable message in the thread

### Cost & Safety Controls

14. **FR-14**: Add `max_fix_rounds_per_thread` to `SlackConfig` (default 3)
15. **FR-15**: Fix requests count against existing `daily_budget_usd`, `max_runs_per_hour`, and circuit breaker limits
16. **FR-16**: Fix rounds use the same `per_phase` budget cap as regular runs
17. **FR-17**: After max rounds reached, post: "Max fix rounds reached ($X.XX total). Please open a new request or iterate manually."

### Sanitization & Security

18. **FR-18**: Thread reply text MUST pass through `sanitize_slack_content()` before any processing
19. **FR-19**: Wrap fix instructions in `format_slack_as_prompt()` with role-anchoring preamble
20. **FR-20**: Add Slack link sanitizer to strip `<URL|display_text>` markup, keeping only display text (addresses attack vector identified by security review)
21. **FR-21**: Validate that `thread_ts` maps to a real completed `QueueItem` before any agent work (prevents spoofed thread targeting)

## Non-Goals

- **Thread history aggregation**: Not fetching full thread history via `conversations.replies`. The fix agent gets the original prompt (from `QueueItem.source_value`) plus the latest fix request message only.
- **Branch resurrection**: If a branch is merged or deleted, the bot will not attempt to recreate it. Users must open a new top-level request.
- **PR recreation**: Never close and recreate PRs. Always push to the existing branch.
- **Phase selection by user**: Users cannot specify which phase to re-run (e.g., "re-run just the review"). This is a potential future enhancement.
- **Cross-thread references**: Users cannot reference a PR from a different thread. The thread-to-run mapping is strictly per-thread.
- **Interactive approval for thread fixes**: Skip the approval gate for thread fix requests — the `@mention` in an existing pipeline thread is itself an approval signal.

## Technical Considerations

### Existing Infrastructure Leverage

- **`QueueItem` model** (`models.py:226`): Already has `slack_ts`, `slack_channel`, `pr_url`, `base_branch`. Needs `branch_name` and `fix_rounds` fields added.
- **`SlackUI` class** (`slack.py:265`): Already implements the phase update posting interface. Reusable as-is for fix runs.
- **`should_process_message()`** (`slack.py:84`): Must NOT be modified. New `should_process_thread_fix()` is a separate function.
- **`QueueExecutor._execute_item()`** (`cli.py:2120`): Needs a parallel method `_execute_fix_item()` for the thread-fix pipeline.
- **`orchestrator.run()`** (`orchestrator.py:1616`): Already supports `base_branch` and `resume_from`. The new `run_thread_fix()` can reuse branch validation logic.
- **`validate_branch_exists()`** (`orchestrator.py:1075`): Existing branch validation.
- **`check_open_pr()`** (`github.py`): Existing PR state check.
- **`sanitize_slack_content()`** (`slack.py:41`): Existing sanitization pipeline.

### New Instruction Template

A new `instructions/thread_fix.md` template is needed, similar to `fix.md` but scoped to user-requested changes rather than reviewer findings. It should:
- Reference the original PRD and task file for context
- Include the user's fix request as the primary instruction
- Instruct the agent to work on the existing branch
- Emphasize minimal, targeted changes

### State Management

- The `QueueItem.fix_rounds` counter is incremented when a thread-fix is enqueued and checked before execution
- Fix items are enqueued with `source_type="slack_fix"` to distinguish from fresh `"slack"` runs in metrics and logging
- The thread-fix `QueueItem` should reference the parent `QueueItem.id` via a new `parent_item_id` field for audit trail

### Concurrency

- Thread-fix requests go through the same `pipeline_semaphore` as regular runs — no parallel execution
- The `state_lock` protects `fix_rounds` increment (same pattern as existing `QueueItem` status transitions)

### Persona Consensus & Tensions

**Strong agreement (6/6 personas):**
- Push commits to existing PR, never recreate
- Fail fast on merged/deleted branches with clear message
- Sanitization must always run on thread replies
- Thread replies distinguished by `thread_ts != ts`
- Cap fix rounds (2-3)

**Agreement with security dissent (5/6):**
- Skip triage for thread fixes (Security Engineer advocates keeping triage). **Decision: Skip triage** — the cost/latency of a haiku call is small, but the UX benefit of immediate action is significant, and the `@mention` in a known pipeline thread is already a strong intent signal. Sanitization provides the security boundary.
- Skip Plan phase (Security Engineer wants artifact hash verification). **Decision: Skip Plan, add artifact verification as a fast-follow.** The `prd_sha256`/`task_sha256` suggestion is sound but not MVP-blocking.

**Thread context scope (split opinion):**
- 3 personas say latest message + original prompt only
- 2 personas say include user messages from thread
- 1 persona says full thread with token cap
- **Decision: Latest message + original prompt** (from `QueueItem.source_value`). This minimizes token waste and context confusion. Can expand later based on user feedback.

## Success Metrics

1. **Fix success rate**: % of thread-fix requests that produce a passing commit on first attempt (target: >60%)
2. **Time to fix**: Median wall-clock time from `@mention` to PR update (target: <5 minutes for simple fixes)
3. **Cost per fix round**: Average cost of a thread-fix pipeline run (target: <$3 for simple fixes)
4. **Adoption**: % of pipeline runs that receive at least one thread-fix request (measuring organic adoption)
5. **Thread-fix abandonment**: % of fix rounds that hit the max cap (indicates spec quality issues)

## Open Questions

1. **Artifact integrity**: Should we add `prd_sha256` / `task_sha256` to `RunLog` for tamper detection when skipping Plan? (Security Engineer recommendation — agreed as fast-follow, not MVP)
2. **Review phase in fix pipeline**: Should the fix pipeline include a Review phase after Implement, or go straight to Verify + Deliver? The current design skips Review for speed, but this means fix changes are not persona-reviewed. Consider making this configurable.
3. **Slack link sanitization**: The Security Engineer identified that Slack's `<URL|display_text>` format could embed malicious URLs. Should we strip these to display text only, or also log the URLs for audit?
4. **Per-thread budget tracking**: Should we track cumulative cost per thread (across all fix rounds) and enforce a per-thread budget cap separate from daily budget?
