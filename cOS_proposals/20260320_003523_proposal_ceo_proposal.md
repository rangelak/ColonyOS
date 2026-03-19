Based on my comprehensive analysis of ColonyOS, I now have a clear picture of what has been built and what the most impactful next feature would be. Let me formulate my proposal:

## Proposal: PR Comment Iteration via GitHub Webhooks

### Rationale
ColonyOS can now receive fix requests via Slack threads (20260319_152207), but lacks the same capability for GitHub — the primary platform where developers actually review code. Users must manually copy PR review comments to Slack or the CLI to get fixes. Adding GitHub PR comment triggers would complete the feedback loop where it naturally occurs, dramatically improving developer workflow and reducing context-switching.

### Builds Upon
- "Slack Thread Fix Requests — Conversational PR Iteration" (20260319_152207) — same thread-fix architecture, adapted for GitHub comments
- "Unified Slack-to-Queue Autonomous Pipeline with LLM Triage" (20260319_130000) — reuses triage agent and queue infrastructure
- "Git State Pre-flight Check" (20260319_091500) — shares branch validation and PR state checks

### Feature Request
Add `colonyos watch-github` command that listens for GitHub PR review comments mentioning `@colonyos` (or a configurable bot username). When a developer comments `@colonyos please fix the null check on line 42` on a PR that ColonyOS created, the bot should:

1. **Validate the trigger**: Confirm the comment is on a PR from a `colonyos/` branch, the PR is open, and the commenter has write access to the repo.

2. **Extract context**: Parse the PR number, branch name, comment body, and any line-specific context from the GitHub API (file path, line number, diff hunk if the comment is a review comment vs. issue comment).

3. **Queue a thread-fix run**: Reuse the existing `run_thread_fix()` pipeline with the comment text as the fix prompt, enriched with line-specific context when available.

4. **Post progress back**: Reply to the original comment with a GitHub reaction (👀 when starting, ✅ or ❌ when done) and optionally a threaded comment with the run summary and cost.

**Implementation scope:**
- New `src/colonyos/github_watcher.py` module using GitHub webhooks via a lightweight Flask/FastAPI endpoint (similar pattern to Slack's Bolt SDK Socket Mode)
- Alternative: GitHub App polling mode for repos that can't receive webhooks
- New `GithubWatcherConfig` in `config.py` with `bot_username`, `allowed_repos`, `rate_limits`, `daily_budget_usd`
- New `colonyos watch-github` CLI command with `--webhook-port`, `--polling-interval`, `--max-hours`, `--max-budget` flags
- Tests for comment parsing, context extraction, and queue integration
- Documentation in README under a new "GitHub Integration" section

**Acceptance criteria:**
- `colonyos watch-github` starts and listens for events (webhook or polling mode)
- Commenting `@colonyos fix the typo in the error message` on a ColonyOS-created PR triggers a fix run
- Line-specific review comments include file path and line context in the fix prompt
- Progress reactions and summary comments appear on the original comment
- Rate limiting and daily budget caps prevent runaway costs
- Graceful degradation when GitHub API is unavailable