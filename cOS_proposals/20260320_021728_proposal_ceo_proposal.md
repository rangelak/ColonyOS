Now I have a comprehensive understanding of the ColonyOS project. Let me analyze what's been built and identify the highest-impact next feature.

Based on my analysis of the project:

**Current State:**
- ColonyOS is a mature autonomous AI pipeline with a rich feature set
- It has: CEO autonomous mode, multi-persona reviews, Slack integration, web dashboard, queue system, CI fix capabilities, cleanup commands, stats/analytics, and more
- The pipeline flow is: CEO → Plan → Implement → Verify → Review/Fix → Decision → Deliver → Learn

**Key Gaps I Identified:**

1. **No PR Review Integration** - When a PR is opened by ColonyOS (or manually), there's no way to have ColonyOS review it or respond to GitHub PR comments. The Slack thread fix feature exists but there's no GitHub-native PR iteration.

2. **No GitHub Actions Integration** - ColonyOS can't be triggered from GitHub Actions as a workflow step (e.g., on PR open, on issue creation).

3. **No Metrics/Telemetry Dashboard** - While `colonyos stats` exists, there's no persistent telemetry or success rate tracking over time.

4. **No Multi-Repo Support** - Each repo needs its own initialization; no way to manage a fleet of ColonyOS-enabled repos.

5. **No PR Comment Response** - When reviewers comment on PRs created by ColonyOS, there's no automated way to address their feedback.

The most impactful feature that builds directly on existing work and fills a significant gap is **GitHub PR Review Comment Response** - allowing ColonyOS to automatically respond to and fix issues raised in PR review comments, similar to the Slack thread fix feature but native to GitHub.

## Proposal: GitHub PR Comment Review Response

### Rationale
ColonyOS creates PRs automatically but currently has no way to iterate on them based on GitHub reviewer feedback. The Slack thread fix feature (20260319_152207) proves the value of conversational iteration, but GitHub is where most code review happens. This feature completes the feedback loop, allowing teams to use ColonyOS PRs in standard GitHub review workflows.

### Builds Upon
- "Slack Thread Fix Requests — Conversational PR Iteration" (thread fix pattern, lightweight fix pipeline)
- "Git State Pre-flight Check" (PR detection, branch validation)
- "`colonyos ci-fix` Command & CI-Aware Deliver Phase" (PR-aware fix patterns)

### Feature Request
Add a `colonyos pr-respond <pr-number>` command and integrate with `colonyos watch` to monitor GitHub PR review comments and automatically address reviewer feedback.

**CLI Command:**
- `colonyos pr-respond <pr-number>` — Fetch unaddressed review comments from a PR, run a fix agent to address them, push commits, and reply to each comment with what was done
- `colonyos pr-respond <pr-number> --dry-run` — Show what would be addressed without making changes
- `colonyos pr-respond <pr-number> --comment-id <id>` — Address a specific review comment only

**GitHub Watch Mode (extension of existing watch):**
- `colonyos watch --github` — Poll for new review comments on open ColonyOS PRs
- Auto-detect PRs created by ColonyOS (via branch prefix or PR body marker)
- When a new review comment is detected, run the fix pipeline and respond

**Comment Processing:**
- Fetch review comments via `gh api` (threaded conversations, inline comments, review summaries)
- Filter to unaddressed comments (no ColonyOS reply yet)
- Group related comments (same file/line range) for batched fixes
- Sanitize comment content (reuse existing `sanitize.py` patterns)

**Fix Pipeline:**
- Reuse the thread-fix pattern: Implement → Verify → Deliver (push only, no new PR)
- Build context from: the comment text, file path, line range, original PR description
- Inject relevant PRD/task file context if available from original run log

**Response Flow:**
- After successful fix: reply to each addressed comment with a summary of changes
- After failed fix: reply with explanation and suggest manual review
- Use GitHub's review comment reply API to keep conversations threaded

**Configuration:**
```yaml
github_watch:
  enabled: false
  poll_interval_seconds: 60
  auto_respond: false          # require explicit trigger vs auto-fix
  comment_response_template: "..."
  max_comments_per_batch: 5
```

**Safety Guards:**
- Only process PRs on `colonyos/` branches (or configurable prefix)
- Rate limit: max N responses per hour per PR
- Budget cap per response round
- Skip comments from bot accounts (avoid infinite loops)
- Require comment to be from allowlisted users or org members

**Output:**
- Each response round creates a run log entry with `source_type: "github_comment"`
- Track which comments were addressed in QueueItem metadata
- Log PR URLs and comment IDs for audit trail