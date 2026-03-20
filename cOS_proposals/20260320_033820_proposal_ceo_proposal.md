Now I have a comprehensive understanding of ColonyOS. Let me analyze the project and propose the next feature.

## Proposal: PR Merge Auto-Close Issue Loop

### Rationale
ColonyOS already creates PRs that reference GitHub issues with `Closes #N` syntax, but there's no visibility into what happens after the PR is created. Teams need to know when their triggered features actually ship to production. Completing this feedback loop — from Slack request through PR merge and back to Slack — would make ColonyOS feel like a complete teammate rather than a fire-and-forget tool.

### Builds Upon
- "GitHub Issue Integration" — which added `--issue` flag and `Closes #N` in PR bodies
- "Slack Thread Fix Requests — Conversational PR Iteration" — which established threaded Slack replies for status updates
- "Unified Slack-to-Queue Autonomous Pipeline with LLM Triage" — which created the watcher infrastructure

### Feature Request
Add a **PR lifecycle watcher** that monitors merged PRs and posts completion notifications back to the originating Slack thread. When a ColonyOS-created PR is merged:

1. **Detect merge events**: The existing `colonyos watch` process should poll for merged PRs that ColonyOS created (tracked via `RunLog.pr_url` and `QueueItem.pr_url` fields already present in the data model). Use `gh pr view --json state,mergedAt` or webhook if feasible.

2. **Post merge notification**: When a merge is detected, post a threaded Slack reply to the original request thread (using `slack_ts` and `slack_channel` already stored on `QueueItem`) with a celebratory message like "🎉 PR #42 merged! Your feature 'Add health check endpoint' is now live."

3. **Close the loop in run logs**: Add a `merged_at` timestamp field to `RunLog` and update the run log JSON when a merge is detected, so `colonyos stats` can show time-to-merge metrics.

4. **Configuration**: Add `slack.notify_on_merge: true/false` (default true) to `.colonyos/config.yaml` so teams can opt out if they find it noisy.

The implementation should:
- Run as a background polling task within `colonyos watch` (not a separate command)
- Check for merged PRs every 5 minutes (configurable via `slack.merge_poll_interval_sec`)
- Only check PRs from the last 7 days to bound the query scope
- Handle rate limits gracefully (GitHub API has 5000 req/hour for authenticated users)

This creates a satisfying closed-loop experience: request feature in Slack → see progress updates → get notified when it ships.