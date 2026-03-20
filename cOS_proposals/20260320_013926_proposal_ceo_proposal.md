Now I have a comprehensive understanding of ColonyOS. Let me analyze the changelog and current state to propose the most impactful next feature.

Based on my analysis:

## Current State Summary

ColonyOS is a mature autonomous agent pipeline with:
- **Full pipeline**: CEO → Plan → Implement → Verify → Review/Fix → Decision → Deliver → Learn
- **Multiple input sources**: CLI prompts, GitHub issues, Slack mentions with thread-fix iteration
- **Execution modes**: Single runs, autonomous loops, queue-based execution
- **Monitoring**: Web dashboard, `colonyos stats`, `colonyos show`, `colonyos status`
- **Maintenance**: Branch/artifact cleanup, AI-powered structural scan

## Key Gaps I Identified

Looking at the changelog and current capabilities:

1. **No GitHub PR Review Integration** — The pipeline can create PRs, but doesn't respond to GitHub PR review comments. When someone leaves a review comment on a ColonyOS-created PR, there's no way to automatically address it like there is with Slack threads.

2. **No webhook-based triggers** — The Slack watcher uses Socket Mode (polling), but there's no GitHub webhook integration for PR events, issue comments, or push events.

3. **No pipeline metrics/observability** — While `colonyos stats` shows aggregate analytics, there's no OpenTelemetry/metrics export for integration with monitoring systems.

4. **No multi-repo orchestration** — Each ColonyOS instance is tied to a single repository.

5. **No PR review comment iteration** — Similar to Slack thread fixes, but for GitHub PR reviews.

## Proposal

Given the recent addition of "Slack Thread Fix Requests — Conversational PR Iteration", the most logical and high-impact next feature is **GitHub PR Review Comment Iteration** — the same conversational iteration pattern, but for GitHub instead of Slack.

---

## Proposal: GitHub PR Review Comment Fix Requests

### Rationale
ColonyOS creates PRs and receives review comments from human reviewers, but currently has no way to respond to those comments automatically. Users must copy/paste review feedback back into Slack or the CLI. Adding GitHub PR review iteration creates a complete feedback loop: ColonyOS creates a PR, humans leave review comments, ColonyOS addresses them — all within GitHub's native workflow.

### Builds Upon
- "Slack Thread Fix Requests — Conversational PR Iteration" — same architectural pattern (lightweight fix pipeline, branch name tracking, fix round limits)
- "Unified Slack-to-Queue Autonomous Pipeline with LLM Triage" — queue-based execution model, triage patterns
- "Git State Pre-flight Check" — branch validation, HEAD SHA verification for force-push defense

### Feature Request
Add a `colonyos watch-github` command that listens to GitHub webhook events (or polls the GitHub API) for PR review comments on ColonyOS-created PRs. When a reviewer requests changes or leaves actionable comments (e.g., `@colonyos fix this`, or any comment on a PR created by ColonyOS with `pending` status), the system should:

1. **Detect actionable review events**: Listen for `pull_request_review` (with `request_changes` action) and `issue_comment`/`pull_request_review_comment` events on PRs where the branch matches `colonyos/*`.

2. **Extract fix context**: Parse the review comments to build a fix prompt. Include the file path, line number context, and reviewer's feedback.

3. **Run the thread-fix pipeline**: Reuse the existing `run_thread_fix()` lightweight pipeline (Implement → Verify → Deliver) on the existing branch.

4. **Post status updates**: Leave a GitHub comment on the PR indicating that fixes are being applied, then update when complete.

5. **Respect fix round limits**: Track fix rounds per PR (similar to `QueueItem.fix_rounds`) and refuse further fixes after hitting `max_fix_rounds_per_pr` (configurable, default 3).

**Configuration** (in `.colonyos/config.yaml`):
```yaml
github_watch:
  enabled: true
  trigger_mode: review_request_changes  # or "mention", "all_comments"
  max_fix_rounds_per_pr: 3
  auto_approve: false  # require explicit @colonyos mention
```

**CLI**:
- `colonyos watch-github` — long-running process (or webhook server) that monitors PR events
- `colonyos watch-github --port 8080` — run as webhook endpoint for GitHub webhook integration
- `colonyos watch-github --poll` — poll mode using GitHub API (no webhook server)

**Acceptance criteria**:
- When a reviewer clicks "Request changes" on a ColonyOS PR, the watcher detects it within 60 seconds (poll mode) or immediately (webhook mode)
- The fix pipeline runs, commits are pushed to the existing branch, and the PR is updated
- A GitHub comment is posted acknowledging the fix request and another when complete
- Fix round tracking prevents infinite loops (respects `max_fix_rounds_per_pr`)
- Works with both GitHub.com and GitHub Enterprise (configurable base URL)