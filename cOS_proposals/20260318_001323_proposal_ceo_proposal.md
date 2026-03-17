## Proposal: Run Analytics & Performance Dashboard

### Rationale
ColonyOS collects detailed per-phase cost, duration, and success/failure data in every RunLog, but there's no way to analyze this data in aggregate. Users running autonomous loops have no visibility into where their budget is going, which phases fail most, or whether the review/fix loop is converging. A `colonyos stats` command that mines existing run logs would give users actionable insights to tune their configuration and maximize ROI.

### Builds Upon
- "Rich Streaming Terminal UI" (extends the rich-based display layer with new visualizations)
- "Cross-Run Learnings System" (similarly mines past run data for actionable insights)
- "Developer Onboarding & Long-Running Autonomous Loops" (loop users are the primary audience needing aggregate analytics)

### Feature Request
Add a `colonyos stats` CLI command that reads all persisted RunLog JSON files from `.colonyos/runs/` and renders an aggregate analytics dashboard using `rich` tables and panels. The dashboard should include:

1. **Run Summary** — Total runs, success rate, failure rate, total cost spent across all runs.

2. **Cost Breakdown by Phase** — A table showing each phase (Plan, Implement, Review, Fix, Decision, Learn, Deliver) with: total cost, average cost per run, percentage of total spend. This tells users where their money goes.

3. **Phase Failure Hotspots** — Which phases fail most often, with counts and failure rates. Helps users identify if reviews are too strict, if implement is flaky, etc.

4. **Review Loop Efficiency** — Average number of review/fix iterations before approval. First-pass approval rate. This measures whether personas are well-calibrated.

5. **Duration Stats** — Average wall-clock time per phase and per full run. Helps users estimate how long loops will take.

6. **Recent Trend** — Last 10 runs shown as a compact success/fail timeline (e.g., `✓ ✓ ✗ ✓ ✓ ✓ ✗ ✓ ✓ ✓`) with cost per run.

7. **Filtering** — Optional `--last N` flag to limit analysis to the N most recent runs, and `--phase <name>` to drill into a specific phase.

Implementation approach:
- Create `src/colonyos/stats.py` with functions to load all run logs, compute aggregates, and return structured data objects (dataclasses, not raw dicts).
- Add `stats` command to `cli.py` that calls the stats module and renders with `rich` Tables and Panels.
- Add `tests/test_stats.py` with unit tests covering: empty runs dir, single run, multiple runs with mixed success/failure, phase cost aggregation, review iteration counting, and the `--last` filter.

Acceptance criteria:
- `colonyos stats` renders a multi-section dashboard to the terminal with no errors, even when zero runs exist (shows "No runs found" gracefully).
- Cost totals match the sum of individual RunLog `total_cost_usd` fields.
- Review loop iteration count is correctly extracted from RunLog phase lists (counting consecutive Review→Fix cycles).
- `--last 5` correctly limits analysis to the 5 most recent runs by timestamp.
- All new code has unit tests; existing tests still pass.