Now I have a comprehensive understanding of the project. Here's my proposal:

---

## Proposal: Cross-Run Learnings Ledger

### Rationale
ColonyOS's core thesis is "compounding returns" — each shipped PR should make the next run better. But today, runs are stateless: the CEO reads past proposals to avoid duplication, yet the implement and review/fix phases learn nothing from prior runs. The same review findings recur across runs (test name typos, missing docstrings, stale artifacts), and the fix agent re-discovers the same patterns every time. A lightweight learnings ledger that captures key takeaways after each run and injects them as context into future phases would deliver on the project's central promise of self-improvement, reduce repeated review churn, and improve first-pass implementation quality — all within a single, well-scoped PR.

### Feature Request
Add a cross-run learnings system that automatically extracts patterns from review findings after each completed run, appends them to a persistent `.colonyos/learnings.md` file, and injects those learnings as context into future implement and fix phases. This creates a genuine feedback loop where each run makes subsequent runs better.

**Specific requirements:**

1. **New `Phase.LEARN` enum value**: Add a `LEARN` phase to the `Phase` enum in `models.py` so the learnings extraction step is tracked in the run log with its own cost entry.

2. **Learnings extraction agent**: After the decision gate (regardless of GO/NO-GO outcome), run a short Claude agent session that reads all review artifacts from the current run and produces structured learnings. Create a new instruction template `src/colonyos/instructions/learn.md` that instructs the agent to: read the review artifacts, identify recurring patterns, extract 3-5 concise actionable takeaways (e.g., "Always add docstrings to public functions", "Run `pytest` before committing", "Use `^test:` regex for Makefile targets"), and output them in a structured markdown format with categories (code-quality, testing, architecture, security, style).

3. **Learnings ledger file**: Maintain a `.colonyos/learnings.md` file that accumulates learnings across runs. Each run appends a section with the run ID, date, feature summary, and the extracted takeaways. Cap the file at 100 entries (oldest entries are pruned) to prevent unbounded growth. The file format should be simple markdown with `## Run: <run-id>` headers.

4. **Deduplication**: Before appending new learnings, the extraction agent should read the existing ledger and avoid adding duplicate or near-duplicate entries. The instruction template should explicitly tell the agent to check for redundancy and only add genuinely new insights.

5. **Context injection into implement phase**: Modify `_build_implement_prompt()` in `orchestrator.py` to read `.colonyos/learnings.md` (if it exists) and append a "Learnings from past runs" section to the implement prompt. Truncate to the most recent 20 entries (roughly 2000 chars) to avoid bloating the context window.

6. **Context injection into fix phase**: Similarly, modify `_build_fix_prompt()` to include relevant learnings from the ledger, so the fix agent can proactively address patterns that reviewers typically flag.

7. **Config options**: Add a `learnings:` section to config with `enabled: bool` (default: `true`) and `max_entries: int` (default: `100`). When `enabled` is false, skip the learn phase entirely (backward compatible).

8. **Pipeline integration**: Wire the learn phase into `orchestrator.run()` after the decision gate and before the deliver phase. The flow becomes: Plan → Implement → Verify → Review/Fix → Decision → **Learn** → Deliver. The learn phase should not block delivery — if it fails, log a warning and continue to deliver.

9. **`colonyos status` integration**: Show the learnings count in status output, e.g., "Learnings ledger: 23 entries". This gives users visibility into the accumulated knowledge base.

10. **Non-blocking failure**: The learn phase must never cause a pipeline failure. If the agent session errors out or exceeds budget, log a warning and proceed to deliver. Use a conservative budget (e.g., $0.50 or half of `per_phase`).

11. **Tests**: Add unit tests for: learnings file parsing and appending, entry cap enforcement (pruning oldest), context injection into implement prompt, context injection into fix prompt, config parsing (enabled/max_entries), non-blocking failure behavior, and integration with the orchestrator pipeline flow.

**Acceptance criteria:**
- After each completed run, a `LEARN` phase extracts takeaways from review artifacts
- Takeaways are appended to `.colonyos/learnings.md` with run ID and date
- Future implement phases include relevant past learnings in their prompt
- Future fix phases include relevant past learnings in their prompt
- The ledger is capped at `max_entries` (default 100) with oldest entries pruned
- When `learnings.enabled` is false, the learn phase is skipped entirely
- Learn phase failure does not block delivery (non-blocking, warning-only)
- `colonyos status` shows the learnings entry count
- All existing tests continue to pass
- New tests cover file I/O, deduplication, cap enforcement, context injection, config parsing, and failure handling