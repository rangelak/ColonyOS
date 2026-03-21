# PRD: `colonyos pr-review` Command

## Introduction/Overview

This feature adds a new CLI command `colonyos pr-review <pr-number>` that monitors GitHub PR review comments and automatically runs lightweight fix pipelines in response. When a reviewer leaves actionable feedback on a PR, the bot triages the comment, applies the fix using the existing `run_thread_fix()` infrastructure (Implement → Verify → Deliver), and replies on the original comment thread with what was fixed and a link to the commit.

This closes the developer-reviewer feedback loop from hours/days to minutes, allowing reviewers to see fixes applied while they still have the code fresh in their minds. The feature reuses existing infrastructure from the Slack thread-fix system, extending ColonyOS's autonomous fix capabilities to the GitHub PR review workflow.

## Goals

1. **Reduce review turnaround time**: Automatically address actionable review comments within minutes of posting, eliminating the context-switch delay when developers come back to implement fixes.

2. **Maintain safety invariants**: Inherit all existing protections (HEAD SHA verification, budget caps, circuit breaker, max fix rounds) to prevent runaway costs and unsafe modifications.

3. **Maximize infrastructure reuse**: Use existing `run_thread_fix()` pipeline, triage agent, and `QueueItem` state tracking with minimal duplication.

4. **Provide clear auditability**: Track PR review fixes separately via `source_type="pr_review_fix"` for analytics, debugging, and cost attribution.

## User Stories

1. **As a reviewer**, I want to leave a comment like "add null check here" and have the bot apply the fix automatically, so I can continue reviewing without waiting for the PR author.

2. **As a PR author**, I want to run `colonyos pr-review 42 --watch` and have the bot monitor my PR for new review comments, so I don't have to manually implement trivial fixes.

3. **As a team lead**, I want visibility into how much budget is being spent on PR review fixes, so I can tune the per-PR budget cap appropriately.

4. **As a developer**, I want the bot to skip non-actionable comments (questions, "LGTM", acknowledgments), so budget isn't wasted on comments that don't require code changes.

## Functional Requirements

### Core Functionality

1. **FR-1**: The `colonyos pr-review <pr-number>` command SHALL fetch review comments from GitHub using `gh api repos/{owner}/{repo}/pulls/{pr}/comments`.

2. **FR-2**: The command SHALL filter to inline code comments only (comments with `path` and `line` fields). General review summaries and top-level PR comments are out of scope for v1.

3. **FR-3**: The command SHALL use the existing haiku-based triage agent (from `src/colonyos/slack.py`) to determine if each comment is actionable. Non-actionable comments (questions, acknowledgments, "LGTM", etc.) SHALL be skipped.

4. **FR-4**: For each actionable comment, the command SHALL invoke `run_thread_fix()` with the comment text as the fix prompt, operating on the PR's branch.

5. **FR-5**: After each successful fix commit, the command SHALL post a reply to the original comment thread using `gh api` with format: "Fixed in [`<sha>`](<commit-url>): <one-line summary>".

6. **FR-6**: After all fixes in a polling cycle, the command SHALL post a single summary comment at the PR level listing all applied fixes.

### Watch Mode

7. **FR-7**: The `--watch` flag SHALL enable continuous polling for new review comments at configurable intervals (default: 60s, configurable via `--poll-interval`).

8. **FR-8**: In watch mode, only comments posted AFTER the watch starts SHALL be processed. Pre-existing comments are ignored to avoid processing stale feedback.

9. **FR-9**: Processed comment IDs SHALL be persisted in `pr_review_state_{pr_number}.json` to deduplicate across poll cycles and restarts.

### Safety Guards

10. **FR-10**: The command SHALL verify HEAD SHA matches the PR's head before every fix attempt. If the branch has diverged (force-push, human commits), the fix SHALL be skipped with a comment explaining the mismatch.

11. **FR-11**: A per-PR cumulative budget cap (`pr_review_budget_per_pr`, default $5) SHALL halt processing when exceeded, posting a comment: "Max budget reached (${X} spent), pausing auto-fixes."

12. **FR-12**: The `max_fix_rounds_per_thread` config SHALL be reused as max fix rounds per PR. After N failed fix attempts, processing halts.

13. **FR-13**: The consecutive failure circuit breaker SHALL pause watch mode after 3 consecutive failures, resumable after cooldown.

14. **FR-14**: The command SHALL skip PRs in `merged` or `closed` state, exiting gracefully with a message.

### State Tracking

15. **FR-15**: PR review fixes SHALL use `source_type="pr_review_fix"` in `QueueItem` for analytics and cost tracking.

16. **FR-16**: Each fix SHALL store `pr_number`, `review_comment_id`, and `head_sha` for audit trails.

17. **FR-17**: Cumulative cost per PR SHALL be tracked in state and displayed in `colonyos status`.

## Non-Goals

1. **General review comments**: Top-level PR comments and review summaries ("Changes requested" without inline comments) are out of scope for v1. They lack file/line context and are too ambiguous for reliable fixes.

2. **Auto-merge on conflict**: If the bot's fix conflicts with subsequent human commits, the fix is aborted. No merge logic is implemented.

3. **@mentioning reviewers**: Replies do not @mention reviewers to avoid notification spam. Reviewers are already subscribed to the thread.

4. **Processing historical comments**: When `--watch` starts, only new comments are processed. Historical comments from before watch start are ignored.

5. **Per-reviewer rate limits**: v1 uses per-PR budget caps only. Per-reviewer limits (to prevent sockpuppet attacks) are deferred to v2.

## Technical Considerations

### Existing Infrastructure to Reuse

| Component | Location | Usage |
|-----------|----------|-------|
| `run_thread_fix()` | `src/colonyos/orchestrator.py:1690-1940` | Core fix pipeline (Implement → Verify → Deliver) |
| Triage agent | `src/colonyos/slack.py:770-860` | Haiku-based actionability classifier |
| `QueueItem` model | `src/colonyos/models.py:238-334` | State tracking with `source_type`, `fix_rounds`, `head_sha` |
| HEAD SHA verification | `src/colonyos/orchestrator.py:1810-1819` | Force-push protection |
| Watch state persistence | `src/colonyos/slack.py:596-618` | Pattern for `pr_review_state_{id}.json` |
| Sanitization | `src/colonyos/sanitize.py` | Strip XML tags from untrusted input |
| `gh api` usage | `src/colonyos/ci.py` | Pattern for GitHub API calls |

### New Components

1. **`src/colonyos/pr_review.py`**: New module for PR review comment fetching, filtering, and GitHub reply posting.

2. **`PRReviewState` dataclass**: Similar to `SlackWatchState`, tracks processed comment IDs, cumulative cost, and circuit breaker state per PR.

3. **`pr-review` CLI command**: New command in `cli.py` following the pattern of the `watch` command.

4. **`thread_fix_pr_review.md`**: Instruction template variant for PR review context (includes comment URL, reviewer username).

### API Endpoints

- `GET /repos/{owner}/{repo}/pulls/{pr}/comments` - Fetch inline review comments
- `GET /repos/{owner}/{repo}/pulls/{pr}` - Check PR state (open/closed/merged)
- `POST /repos/{owner}/{repo}/pulls/{pr}/comments` - Reply to review comment thread
- `POST /repos/{owner}/{repo}/issues/{pr}/comments` - Post summary comment

### Security Considerations

1. **Untrusted input**: PR review comments are attacker-controlled on public repos. All comment text MUST pass through `sanitize_untrusted_content()` before inclusion in prompts.

2. **HEAD SHA verification**: Mandatory before every fix to prevent applying fixes to tampered branches.

3. **Budget caps**: Per-PR caps prevent review-bombing attacks where an attacker spams comments to drain budget.

4. **Comment author validation**: Future v2 should validate that comment authors are authenticated GitHub users (not bots).

## Success Metrics

1. **Fix success rate**: % of actionable comments that result in successful fix commits (target: >80%)

2. **Triage accuracy**: % of comments correctly classified as actionable/non-actionable (target: >90%)

3. **Review turnaround reduction**: Median time from comment to fix commit (target: <5 minutes)

4. **Budget efficiency**: Average cost per successful fix (target: <$0.50)

5. **False positive rate**: % of fixes that reviewers reject or need to undo (target: <5%)

## Open Questions

1. **Batching strategy**: Should multiple comments from the same review be batched into a single fix cycle, or processed individually? Individual is simpler but may create many small commits.

2. **Comment threading**: GitHub's review comment threading model is complex (replies, suggestions, resolved threads). Should we respect "resolved" state and skip those comments?

3. **Suggestion acceptance**: GitHub has a "suggestion" feature with inline code blocks. Should the bot detect and auto-apply these instead of running the full fix pipeline?

4. **PR author check**: Should we verify the authenticated user matches the PR author before applying fixes? This prevents unauthorized auto-fixing of others' PRs.

---

## Persona Q&A Synthesis

### Areas of Agreement

All personas agreed on:
- **Inline comments only**: Start with inline code comments (have file/line context), skip general review summaries
- **New comments only in watch mode**: Don't process historical comments to avoid stale feedback
- **HEAD SHA verification mandatory**: Fail-fast if branch has diverged
- **No @mentions**: Avoid notification spam, use threaded replies only
- **Abort on conflict**: Don't attempt auto-merge
- **`source_type="pr_review_fix"`**: Use existing analytics pattern
- **Per-PR budget cap**: Essential to prevent runaway costs

### Areas of Tension

| Topic | Position A | Position B | Resolution |
|-------|------------|------------|------------|
| Per-PR budget cap value | $5 (YC, Steve, Jony) | $10 (Systems Eng) | Default $5, configurable |
| Per-reviewer limits | v2 (most) | Essential v1 (Security) | Defer to v2, note in Non-Goals |
| Complexity of budget tracking | Per-PR cap "pointless" (Linus) | Per-PR cap "mandatory" (most) | Implement per-PR cap as majority agrees |
| Summary comment | After all fixes (most) | Only on failure (Steve) | Post summary after all fixes, keep it minimal |
