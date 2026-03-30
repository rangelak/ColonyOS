Based on my analysis of the project's 30+ shipped features, architecture, strategic directions, and the absence of open PRs, here is my proposal:

---

## Proposal: Run Outcome Scoring & Feedback Loop

### Rationale
ColonyOS generates massive amounts of data across runs (costs, review findings, learnings, memories, CEO proposals) but never closes the loop — it doesn't know which runs produced merged PRs, which review findings were real vs. false positives, or which CEO proposals were valuable. Adding outcome tracking and scoring creates the first genuine self-improvement feedback loop, turning accumulated data into actionable intelligence that compounds across runs.

### Builds Upon
- "Persistent Memory System" — outcome scores become quality-weighted metadata on memories, prioritizing high-signal entries during injection
- "Cross-Run Learnings System" — learnings from successful runs get amplified; learnings from failed runs get demoted
- "`colonyos stats` Aggregate Analytics Dashboard" — new outcome metrics section showing merge rates, proposal quality, and review accuracy

### Inspired By
RuFlo's Q-Learning routing approach — the idea that an autonomous system should use outcome signals to improve its own decision-making over time, not just log what happened.

### Feature Request
Build a **Run Outcome Tracker** that monitors the fate of PRs created by ColonyOS and feeds quality scores back into the memory and learnings systems.

**Outcome Collection:**
- Add a `colonyos outcomes sync` CLI command that scans all past run logs, finds associated PRs (via `RunLog.pr_url`), and checks their current GitHub status (merged, closed, open, CI passing/failing) using the `gh` CLI.
- Store outcomes in a new `outcomes` table in the existing `memory.db` SQLite database with fields: `run_id`, `pr_number`, `pr_status` (merged/closed/open), `time_to_merge`, `ci_status`, `review_comments_count`, `outcome_score` (0.0-1.0 computed score).
- The daemon's existing scheduler should run outcome sync periodically (e.g., every 6 hours) when in daemon mode.

**Scoring Algorithm:**
- Compute a 0.0–1.0 `outcome_score` per run based on: PR merged (0.5 weight), CI green (0.2), time-to-merge under 24h (0.15), fewer than 3 human review comments needed (0.15).
- Score is simple and deterministic — no ML, just weighted heuristics stored in config as `outcome_weights` in `config.yaml`.

**Feedback Integration:**
- Tag existing memory entries with `outcome_score` from their originating run. During memory injection (`memory.py`), boost relevance ranking for memories from high-scoring runs (score > 0.7) and demote memories from low-scoring runs (score < 0.3).
- Tag learnings entries with outcome scores. In `learnings.py`, when injecting learnings into implement/fix prompts, sort by outcome score so high-quality learnings appear first and low-quality ones are truncated first when hitting token limits.
- In `ceo.md` prompt injection, include a brief "quality report" showing the CEO's historical proposal-to-merge rate so it can calibrate ambition and scope.

**Stats Integration:**
- Add an "Outcomes" section to `colonyos stats` output showing: total runs with tracked outcomes, merge rate percentage, average outcome score, best/worst performing phases, and CEO proposal success rate.
- Add `--outcomes` flag to `colonyos show <run-id>` to display the outcome score and its component breakdown for a specific run.

**Acceptance Criteria:**
1. `colonyos outcomes sync` fetches PR statuses for all past runs and persists scores to SQLite
2. Memory injection ranks entries by outcome score as a secondary sort factor
3. Learnings injection prioritizes entries from high-scoring runs
4. `colonyos stats` shows an Outcomes section with merge rate and average score
5. `colonyos show <run-id> --outcomes` displays per-run outcome breakdown
6. Daemon mode periodically syncs outcomes when configured
7. All new code has unit tests; existing tests still pass