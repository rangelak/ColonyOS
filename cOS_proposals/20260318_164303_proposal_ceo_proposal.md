## Proposal: Multi-Prompt Batch Queue (`colonyos queue`)

### Rationale
ColonyOS currently offers two modes: single-feature `run` (one prompt, one PR) and autonomous `auto` (CEO picks features). There's no middle ground — users who know exactly which 5 features or issues they want built have no way to queue them up and walk away. A batch queue command would turn ColonyOS from a one-at-a-time tool into a "queue your sprint backlog and go to sleep" pipeline, dramatically increasing throughput for teams with clear backlogs.

### Builds Upon
- "Autonomous CEO Stage (`colonyos auto`)" — reuses the sequential loop execution and aggregate budget enforcement pattern
- "GitHub Issue Integration" — queue items can be issue references (`#42`) or free-text prompts
- "`colonyos stats` Aggregate Analytics Dashboard" — queue completion summaries reuse stats computation for cost/duration rollups

### Feature Request
Add a `colonyos queue` command that accepts multiple feature prompts and/or GitHub issue references, persists them as a durable queue, and executes them sequentially through the full pipeline (Plan → Implement → Verify → Review → Decision → Deliver) with aggregate budget tracking.

**CLI interface:**
- `colonyos queue add "Add dark mode support" "Refactor auth module" --issue 42 --issue 57` — enqueue multiple items (mix of free-text prompts and issue numbers)
- `colonyos queue start` — begin processing the queue sequentially; respects existing `budget.per_run` and `budget.max_total_usd` caps across all queued items
- `colonyos queue status` — show queue state: pending/running/completed/failed items with cost and duration per item
- `colonyos queue clear` — remove all pending (unstarted) items from the queue

**Queue persistence:**
- Queue state stored in `.colonyos/queue.json` — a list of queue entries each with: id, source (prompt or issue ref), status (pending/running/completed/failed), run_id (once started), added_at timestamp
- If the process is interrupted (Ctrl+C, crash), `colonyos queue start` resumes from the first pending item — already-completed items are skipped (analogous to `--resume` but at the queue level)

**Budget enforcement:**
- `colonyos queue start --max-cost 50.00` — aggregate cost cap across all queued runs; stops the queue (without failing) when the cap is reached
- `colonyos queue start --max-hours 8` — time-based cap (reuse the pattern from `auto --max-hours`)
- Individual run budgets still governed by `budget.per_run` in config

**Execution behavior:**
- Each queue item runs through the full existing `orchestrator.run()` pipeline — no new phase logic needed
- On item failure: log the failure, mark item as failed, continue to next item (don't abort the whole queue)
- On item success: mark complete, record run_id for cross-reference, proceed to next
- Print a queue summary table at the end showing all items with status, cost, duration, and PR URLs

**Acceptance criteria:**
1. `colonyos queue add` persists items to `.colonyos/queue.json` and confirms count
2. `colonyos queue start` processes items sequentially, each producing a PR via the standard pipeline
3. Interrupted queues resume from the correct item on re-run
4. `colonyos queue status` renders a Rich table of all queue items with their state
5. Aggregate budget caps (`--max-cost`, `--max-hours`) halt the queue gracefully when exceeded
6. Failed items don't block subsequent items — the queue continues
7. End-of-queue summary shows total cost, duration, success/fail counts, and PR links
8. Unit tests cover queue persistence, resume logic, budget enforcement, and status rendering