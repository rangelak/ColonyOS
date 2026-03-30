# PRD: PR Outcome Tracking System

## 1. Introduction/Overview

ColonyOS currently operates as an open-loop system: it creates PRs and never learns whether they were merged, rejected, or required significant rework. This feature closes the feedback loop by tracking the fate of every PR ColonyOS creates, feeding outcome data back into the CEO prompt, memory system, and analytics dashboard so the pipeline gets smarter over time.

Without outcome tracking, the CEO agent has no signal about which types of proposals produce mergeable work versus which get rejected. The system keeps repeating the same classes of mistakes — proposing features that are too large, generating code that fails review patterns, or duplicating approaches that were already rejected.

## 2. Goals

1. **Close the feedback loop**: Every PR created by ColonyOS is tracked from creation through merge/close, with outcomes fed back into future pipeline decisions.
2. **Improve merge rate over time**: By surfacing rejection patterns in the CEO prompt and memory system, the pipeline should progressively produce higher-quality, more-mergeable PRs.
3. **Operator visibility**: Provide clear CLI commands (`colonyos outcomes`, `colonyos stats`) that show PR outcome data so operators can assess pipeline effectiveness.
4. **Zero new dependencies**: Follow the project's existing convention of using `gh` CLI for GitHub interactions and SQLite for structured persistence.

## 3. User Stories

- **As a ColonyOS operator**, I want to run `colonyos outcomes` to see a table of all PRs created by ColonyOS with their current status (open/merged/closed), age, and review comment count, so I can quickly assess pipeline effectiveness.
- **As a ColonyOS operator**, I want to run `colonyos outcomes poll` to manually refresh PR statuses from GitHub, so I can get up-to-date information on demand.
- **As a ColonyOS operator**, I want `colonyos stats` to include a "Delivery Outcomes" section showing merge rate and average time-to-merge, so I have a complete picture of pipeline performance.
- **As the CEO agent**, I want to see a summary of recent PR outcomes (merge rate, common rejection reasons) in my prompt context, so I can calibrate proposal scope and ambition based on what actually gets merged.
- **As a daemon user**, I want PR outcomes to be polled automatically on a configurable interval, so the system stays up-to-date without manual intervention.

## 4. Functional Requirements

### FR-1: Core outcomes module (`src/colonyos/outcomes.py`)

1. **FR-1.1**: `track_pr(repo_root, run_id, pr_number, pr_url, branch_name)` — persists a new outcome record to the `pr_outcomes` table in `.colonyos/memory.db` with status `open`, timestamps, and run metadata.
2. **FR-1.2**: `poll_outcomes(repo_root)` — queries GitHub via `gh pr view` for all tracked PRs with status `open`, updates their status (`open`/`merged`/`closed`), captures: `merged_at`/`closed_at` timestamps, review comment count, CI pass/fail, and labels.
3. **FR-1.3**: `compute_outcome_stats(repo_root)` — returns aggregate metrics: merge rate, average time-to-merge, common close reasons, total tracked PRs, and recent PR fates.
4. **FR-1.4**: `format_outcome_summary(repo_root)` — returns a compact string suitable for CEO prompt injection (capped at ~500 tokens), e.g., "Your last 10 PRs: 7 merged (avg 2.1h to merge), 2 still open, 1 closed (reviewer noted: 'too large')".
5. **FR-1.5**: When a PR is closed without merge, extract the last reviewer comment / closing comment via `gh pr view --json comments,reviews`, sanitize it with `sanitize_ci_logs`, cap at 500 characters, and store as `close_context`.

### FR-2: Storage (SQLite in `memory.db`)

6. **FR-2.1**: Add a `pr_outcomes` table to `memory.db` with columns: `id`, `run_id`, `pr_number`, `pr_url`, `branch_name`, `status` (open/merged/closed), `created_at`, `merged_at`, `closed_at`, `review_comment_count`, `ci_passed`, `labels`, `close_context`, `last_polled_at`.
7. **FR-2.2**: Schema migration: detect whether `pr_outcomes` table exists on `OutcomeStore` initialization; create it if missing (same pattern as `MemoryStore._init_db`).
8. **FR-2.3**: Use the same `memory.db` SQLite database as the existing `MemoryStore` — no separate files.

### FR-3: Deliver phase integration

9. **FR-3.1**: After successful PR creation in the `run()` function (orchestrator.py line ~4342-4344), call `track_pr()` to register the PR for outcome tracking.
10. **FR-3.2**: Also register PRs created via `run_thread_fix()` when a new PR is created (not when pushing to an existing branch).

### FR-4: CEO prompt injection

11. **FR-4.1**: In `_build_ceo_prompt()` (orchestrator.py line 1818), inject the outcome summary from `format_outcome_summary()` as a new `## PR Outcome History` section, placed after the open PRs section.
12. **FR-4.2**: Injection is non-blocking: if outcome data is unavailable, skip silently (same try/except pattern as issues and PRs sections).

### FR-5: CLI commands

13. **FR-5.1**: `colonyos outcomes` — display a Rich table of all tracked PRs showing: PR number, status (with color), branch name, age, review comments, CI status, and close context (truncated).
14. **FR-5.2**: `colonyos outcomes poll` — manually trigger `poll_outcomes()`, then display the updated table.

### FR-6: Stats integration

15. **FR-6.1**: Add a `DeliveryOutcomeStats` dataclass to `stats.py` with fields: `total_tracked`, `merged_count`, `closed_count`, `open_count`, `merge_rate`, `avg_time_to_merge_hours`.
16. **FR-6.2**: Add a `render_delivery_outcomes()` function to render it as a Rich Panel in the stats dashboard.
17. **FR-6.3**: Call from `render_dashboard()` after the parallelism section.

### FR-7: Memory capture for closed PRs

18. **FR-7.1**: When `poll_outcomes()` detects a PR transition from `open` to `closed` (without merge), create a `MemoryEntry` with category `FAILURE` containing the close context (sanitized reviewer feedback).
19. **FR-7.2**: Memory text format: `"PR #{number} closed without merge. Reviewer feedback: {close_context}"`.

### FR-8: Daemon integration

20. **FR-8.1**: Add `outcome_poll_interval_minutes: int = 30` to `DaemonConfig`.
21. **FR-8.2**: Add `_last_outcome_poll_time: float = 0.0` to `Daemon.__init__`.
22. **FR-8.3**: Add step 6 in `_tick()` following the exact pattern of GitHub issue polling (lines 204-208): check time elapsed, call `_poll_pr_outcomes()`, update timestamp.
23. **FR-8.4**: `_poll_pr_outcomes()` wraps `poll_outcomes()` in try/except, logs warnings on failure, and continues (same resilience pattern as `_poll_github_issues`).

## 5. Non-Goals

- **Cross-repo aggregation**: Outcomes are per-repository only. A global dashboard across repos is a future concern.
- **NLP classification of close reasons**: Store raw reviewer feedback and let the LLM interpret it. No structured taxonomy of rejection reasons.
- **Time-to-first-review tracking**: V1 tracks only creation time and merge/close time. Additional timestamp granularity is a V2 enhancement.
- **Direct GitHub API calls**: All interactions use the `gh` CLI, consistent with the existing codebase.
- **Retry logic for failed polls**: Failed polls log a warning and skip to the next interval. The next scheduled poll is the implicit retry.
- **Outcome-based automated behavior changes**: V1 injects data into prompts for the LLM to reason about. Automated rules (e.g., "reduce scope if merge rate < 50%") are out of scope.

## 6. Technical Considerations

### Storage architecture
All personas unanimously agreed: use the existing `memory.db` SQLite database rather than the proposed `outcomes.json` JSONL file. The project already has SQLite with FTS5, schema versioning, and atomic writes via `MemoryStore`. Adding a third storage format would create a split-brain problem. A new `pr_outcomes` table in `memory.db` gives ACID transactions, indexed queries, and integration with existing pruning patterns.

### GitHub interaction pattern
Use `gh pr view <number> --json state,mergedAt,closedAt,reviews,comments,statusCheckRollup,labels` via `subprocess.run`, consistent with every function in `github.py`. The `doctor.py` preflight already validates `gh` is installed and authenticated. No new Python dependencies needed.

### Sanitization
PR review comments are untrusted input. All comment text must pass through `sanitize_ci_logs()` from `sanitize.py` (which chains XML tag stripping with secret-pattern redaction) before storage. This matches what `MemoryStore.add_memory()` already does. Additionally, cap individual review comments at 500 characters to prevent memory budget abuse.

### CEO prompt budget
Outcome summary is pre-computed as a compact string (~30-50 tokens), not raw data. This follows the pattern of `load_learnings_for_injection` which caps at 20 entries. The CEO prompt is already heavy (changelog, issues, PRs, directions, learnings), so outcome context must be tightly budgeted.

### Daemon threading model
Outcome polling runs inline in `_tick()` as a time-gated check, exactly like GitHub issue polling, CEO scheduling, cleanup, and heartbeats. No new threads. The daemon architecture is explicitly "single process, multiple threads, one pipeline at a time" and outcome polling is a lightweight `gh` CLI call.

### Key files to modify
- `src/colonyos/outcomes.py` — new module (core tracking logic)
- `src/colonyos/orchestrator.py` — deliver phase integration (line ~4342), CEO prompt injection (line ~1920)
- `src/colonyos/cli.py` — new `outcomes` command group
- `src/colonyos/stats.py` — new `DeliveryOutcomeStats` dataclass and renderer
- `src/colonyos/daemon.py` — outcome polling in `_tick()` (line ~230)
- `src/colonyos/config.py` — `outcome_poll_interval_minutes` in `DaemonConfig`
- `src/colonyos/memory.py` — potentially reuse `MemoryStore` connection or add `OutcomeStore` that shares `memory.db`
- `tests/test_outcomes.py` — new test file for the outcomes module

### Persona consensus and tensions

**Strong consensus (all 7 personas agree):**
- Use SQLite (`memory.db`), not JSONL files
- Use `gh` CLI, not direct API calls
- Per-repository scoping, not global
- Pre-compute compact summaries for CEO injection
- Follow existing error handling patterns (log and continue)
- Schedule in `_tick()`, not a separate thread

**Minor tension:**
- **Time-to-first-review**: Jony Ive and the Security Engineer advocate tracking it; Michael Seibel, Steve Jobs, and Karpathy say skip it for V1. **Decision**: Skip for V1 — store creation and merge/close timestamps only. The raw timestamps are enough for the LLM to reason about if needed.
- **Daemon threading**: The Security Engineer suggested a separate daemon thread; all other personas recommended inline in `_tick()`. **Decision**: Inline in `_tick()` — outcome polling is a sub-second operation that doesn't warrant its own thread.

## 7. Success Metrics

1. **Feature completeness**: All 8 functional requirement groups are implemented with passing tests.
2. **Merge rate visibility**: `colonyos stats` shows a "Delivery Outcomes" panel with merge rate and average time-to-merge.
3. **CEO calibration**: CEO prompt includes outcome summary when tracked PRs exist. Manual inspection confirms the summary is concise and actionable.
4. **Memory learning**: Closed-without-merge PRs generate a memory entry that appears in subsequent plan/implement phase memory injection.
5. **Zero regressions**: All existing tests continue to pass.
6. **Zero new dependencies**: Only uses `gh` CLI, SQLite, and existing Python standard library.

## 8. Open Questions

1. **Pruning strategy**: Should old outcome records be pruned after N days/entries, or kept indefinitely? The memory system has FIFO pruning at `max_entries=500`. Outcomes could follow a similar pattern but may warrant longer retention.
2. **Multiple PRs per run**: If a run creates multiple PRs (e.g., via recovery), should each be tracked independently? Current design tracks each PR separately, linked by `run_id`.
3. **Stale PR handling**: Should PRs that have been open for more than N days be flagged in the outcomes table or CEO prompt? This could help the operator notice abandoned PRs.
