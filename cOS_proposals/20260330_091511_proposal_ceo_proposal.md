## Proposal: PR Outcome Tracking & Feedback Loop

### Rationale
ColonyOS delivers PRs autonomously but is completely blind to what happens after delivery — it never learns whether PRs get merged, closed with feedback, or ignored. This means the CEO, planner, and memory system operate without the most critical signal: *did the work actually land?* Closing this feedback loop is the single highest-leverage improvement for autonomous quality because it turns the system from "generate and forget" into "generate, measure, and improve."

### Builds Upon
- "Persistent Memory System" — outcome data stored and injected via existing memory infrastructure
- "Daemon Mode: Fully Autonomous 24/7 Engineering Agent" — daemon can poll outcomes during idle periods
- "`colonyos stats` Aggregate Analytics Dashboard" — outcome metrics surface in the existing stats view

### Inspired By
RuFlo's self-learning swarm (Q-Learning routing that improves based on task outcomes) and Paperclip's governance model (tracking whether autonomous decisions lead to good results). The pattern is: you can't improve what you don't measure.

### Feature Request
Add a PR outcome tracking system that monitors the fate of PRs created by ColonyOS and feeds results back into future pipeline decisions.

**Core module (`src/colonyos/outcomes.py`):**
- `track_pr(run_id, pr_number, pr_url)` — called by the deliver phase after PR creation, persists a tracking record to `.colonyos/outcomes.json` (append-only JSON lines file)
- `poll_outcomes()` — queries GitHub API for all tracked PRs, updates their status (open/merged/closed), captures: time-to-merge, number of review comments received, whether CI passed, labels added
- `compute_outcome_stats()` — returns aggregate metrics: merge rate, average time-to-merge, most common close reasons, streak data

**Integration points:**
1. **Deliver phase** — after successful PR creation, call `track_pr()` to register the PR for monitoring
2. **CEO prompt injection** — inject a summary like "Your last 10 PRs: 7 merged (avg 2.1h to merge), 2 still open, 1 closed (reviewer noted: 'too large')" so the CEO can calibrate proposal scope and ambition
3. **Daemon idle task** — `poll_outcomes()` runs periodically (e.g., every 30 minutes) during daemon idle time, updating statuses
4. **`colonyos stats`** — new "Delivery Outcomes" section showing merge rate, avg time-to-merge, and a mini-table of recent PR fates
5. **Memory capture** — when a PR is closed without merge, extract the close reason / last reviewer comment and store it as a memory so future plans avoid the same mistakes

**CLI additions:**
- `colonyos outcomes` — show a table of all tracked PRs with their current status, age, and review comment count
- `colonyos outcomes poll` — manually trigger a status refresh for all tracked PRs

**Acceptance criteria:**
- Deliver phase automatically registers every created PR for tracking
- `colonyos outcomes` displays a formatted table of tracked PRs with statuses
- `colonyos outcomes poll` refreshes all PR statuses from GitHub
- `colonyos stats` includes a "Delivery Outcomes" section with merge rate and time-to-merge
- CEO prompt includes outcome summary when tracked PRs exist
- Closed-without-merge PRs generate a memory entry with the reason/feedback
- Daemon mode polls outcomes on a configurable interval
- All new code has unit tests; existing tests still pass