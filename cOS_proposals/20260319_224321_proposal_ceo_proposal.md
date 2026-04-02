## Proposal: GitHub PR Auto-Review Watcher

### Rationale
ColonyOS currently only generates outbound work (building features, opening PRs) but has no way to automatically review *incoming* PRs from human developers. The multi-persona review system and standalone `review` command already exist — wiring them to a GitHub event listener would make ColonyOS useful for the entire team, turning it from a "feature builder" into a full-cycle engineering teammate that also catches bugs and enforces standards on every PR.

### Builds Upon
- "Standalone `colonyos review <branch>` command" — provides the core review/fix/decision logic to reuse
- "Unified Slack-to-Queue Autonomous Pipeline with LLM Triage" — establishes the long-running watcher + triage + queue pattern
- "Review/fix loop redesign: per-persona parallel reviews + fix agent" — provides the parallel persona review infrastructure

### Feature Request
Add a `colonyos watch-prs` command that polls for new and updated pull requests on the current repository (using `gh pr list` / `gh api`) and automatically runs the multi-persona review pipeline against each one, posting structured review comments back to the PR on GitHub.

**Core behavior:**
- Long-running CLI command (like `colonyos watch`) that polls GitHub every N seconds (configurable, default 60s) for PRs matching configurable filters (labels, author exclusions, draft status, base branch).
- On detecting a new or updated PR (new commits pushed), runs the existing standalone review pipeline (`run_review_standalone`) against the PR's head branch.
- Posts a single, consolidated GitHub PR review comment (via `gh api`) containing each persona's findings, verdict, and the overall decision gate result. Uses GitHub's review API to submit as "APPROVE", "REQUEST_CHANGES", or "COMMENT" based on the decision gate.
- Maintains a local ledger (`.colonyos/pr-reviews.json`) tracking which PRs and commit SHAs have been reviewed, to avoid duplicate reviews. Re-reviews only when new commits are pushed.
- Skips PRs opened by ColonyOS itself (branches matching the configured `branch_prefix`).

**Configuration (in `.colonyos/config.yaml` under `pr_review:`):**
- `enabled: bool` — toggle
- `poll_interval_seconds: int` — default 60
- `auto_approve: bool` — whether to submit GitHub "APPROVE" reviews or always use "COMMENT"
- `label_filter: list[str]` — only review PRs with these labels (empty = all PRs)
- `exclude_authors: list[str]` — skip PRs from these GitHub usernames
- `exclude_drafts: bool` — skip draft PRs (default true)
- `max_reviews_per_hour: int` — rate limit (default 5)
- `budget_per_review_usd: float` — cost cap per review (default from existing `budget.per_run`)

**CLI flags:**
- `--dry-run` — detect PRs but don't run reviews or post comments
- `--max-hours N` — auto-stop after N hours
- `--max-budget N` — aggregate budget cap
- `--once` — review all current PRs once and exit (no polling loop)
- `--pr N` — review a single specific PR number and exit

**GitHub comment format:**
A structured markdown comment with collapsible sections per persona (using `<details>` tags), a summary table of verdicts, and the overall GO/NO-GO decision. Include a footer identifying ColonyOS as the reviewer.

**Acceptance criteria:**
1. `colonyos watch-prs` starts polling GitHub for open PRs and logs detected PRs
2. New PRs trigger the multi-persona review pipeline and post a structured review comment to the PR
3. PRs with new commits since last review are re-reviewed; already-reviewed PRs at the same SHA are skipped
4. Self-opened PRs (matching `branch_prefix`) are excluded by default
5. Rate limiting and budget caps are enforced
6. `--dry-run` mode logs what would be reviewed without taking action
7. `--pr N` mode reviews a single PR and exits
8. Configuration is parsed from `config.yaml` with sensible defaults
9. Unit tests cover: PR detection, dedup ledger, comment formatting, rate limiting, config parsing, and the `--once`/`--pr` modes
