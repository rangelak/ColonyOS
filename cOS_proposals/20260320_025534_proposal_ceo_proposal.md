Now I have a comprehensive understanding of ColonyOS. Let me analyze the development history and propose the most impactful next feature.

## Proposal: PR Review Comments Integration

### Rationale
ColonyOS has robust Slack thread-fix capability (conversational iteration on PRs) but lacks the same functionality for GitHub PR review comments — the most common workflow for code review feedback. Developers expect to leave inline comments on PRs and have the AI address them, just like they can with Slack threads. This is a natural extension that meets developers where they already work.

### Builds Upon
- "Slack Thread Fix Requests — Conversational PR Iteration" (20260319_152207) — extends the thread-fix pattern to GitHub's native review surface
- "Git State Pre-flight Check" (20260319_091500) — reuses branch validation and HEAD SHA verification for safe PR iteration
- "GitHub Issue Integration" (20260318_000500) — extends GitHub API usage patterns already in place

### Feature Request
Add a `colonyos pr-review <pr-number>` command that monitors GitHub PR review comments and runs lightweight fix pipelines in response. The command should:

1. **Fetch PR review comments** — Use `gh api` to retrieve review comments, including inline code comments and general review feedback, from a specific PR.

2. **Filter actionable comments** — Apply the existing haiku-based triage agent (from the Slack triage system) to evaluate which comments contain actionable fix requests vs. questions, acknowledgments, or completed items. Only queue actionable comments.

3. **Run thread-fix pipeline** — For each actionable comment batch, run the existing `run_thread_fix()` pipeline (Implement → Verify → Deliver) on the PR's branch, using the comment text as the fix prompt.

4. **Reply on GitHub** — After each fix commit, post a reply to the original PR comment thread indicating what was fixed and linking to the commit. Use `gh api` or `gh pr comment`.

5. **Watch mode** — Support a `--watch` flag that polls for new review comments at configurable intervals (default: 60s) and processes them continuously, similar to `colonyos watch` for Slack.

6. **Safety guards** — Inherit existing protections: HEAD SHA verification (refuse to fix if branch was force-pushed since last run), per-run budget caps, consecutive failure circuit breaker, and max fix rounds per PR.

7. **PR state awareness** — Skip comments on merged/closed PRs. If the PR is marked "Changes requested," process all outstanding review comments as a batch.

**Acceptance criteria:**
- `colonyos pr-review 42` fetches and addresses review comments on PR #42
- `colonyos pr-review 42 --watch` continuously monitors for new comments
- Fix commits include a message like "Address review feedback from @username"
- GitHub reply comments are posted linking to the fix commit
- Existing `run_thread_fix()` infrastructure is reused with minimal duplication
- Triage agent filters out non-actionable comments (questions, "LGTM", etc.)