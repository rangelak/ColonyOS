## Proposal: Detailed Run Inspector (`colonyos show`)

### Rationale
ColonyOS has `status` for listing runs and `stats` for aggregate analytics, but there's no way to drill into a single run and understand what actually happened phase-by-phase. For an autonomous pipeline that makes dozens of decisions per run, this observability gap is critical — users need to inspect costs, review verdicts, fix iterations, and phase durations for any individual run to build trust and debug failures.

### Builds Upon
- "`colonyos stats` Aggregate Analytics Dashboard" — extends the analytics surface from aggregate to per-run detail
- "Resume Failed Runs (`--resume`)" — the resume feature already persists phase completion data in RunLog; `show` exposes this data to humans
- "Rich Streaming Terminal UI" — reuses the rich rendering infrastructure for formatted output

### Feature Request
Add a `colonyos show <run-id>` CLI command that renders a detailed single-run inspector in the terminal. Given a run ID (or partial prefix match), it reads the corresponding `run-*.json` from `.colonyos/runs/` and displays:

1. **Run header**: run ID, feature prompt (truncated), start/end timestamps, total duration, total cost, final status (success/failed/interrupted), source issue URL if applicable.

2. **Phase timeline table**: Each phase as a row showing: phase name, model used, duration, cost, status (✓/✗/skipped), and a one-line summary. Phases that were skipped (e.g., from `--resume`) should be visually distinct.

3. **Review details section** (if review phase ran): Per-persona verdicts (approve/request-changes), number of findings per persona, and how many fix iterations were needed.

4. **Decision gate section** (if decision phase ran): The GO/NO-GO verdict.

5. **CI section** (if CI fix ran): Number of CI fix attempts, final CI status.

6. **Artifact links**: File paths to the PRD, task file, review artifacts, and the GitHub PR URL.

Additional flags:
- `--json` — Output the raw RunLog JSON instead of the formatted view (for scripting/piping)
- `--phase <name>` — Show extended detail for a specific phase (full phase result including the prompt used and raw output excerpt)

The command should support fuzzy run-id matching (prefix match on the run ID string) so users don't have to type the full ID. If multiple runs match, list the matches and ask the user to be more specific.

Acceptance criteria:
- `colonyos show <full-or-partial-run-id>` renders a rich, readable single-run breakdown
- `colonyos show <id> --json` outputs valid JSON to stdout
- `colonyos show <id> --phase review` shows extended review detail
- Ambiguous prefix matches list candidates instead of crashing
- Non-existent run IDs produce a clear error message
- All new code has unit tests; existing tests still pass