# PRD: `colonyos queue` — Durable Multi-Item Execution Queue

**Date:** 2026-03-18
**Status:** Draft

---

## 1. Introduction / Overview

ColonyOS currently supports executing a single feature at a time (`colonyos run`) or letting the AI autonomously propose and execute features in a loop (`colonyos auto`). However, there is no way for a human to curate a list of specific features and have them executed sequentially through the full pipeline.

The `colonyos queue` command fills this gap: it lets users enqueue multiple feature prompts and/or GitHub issue references into a durable, file-backed queue, then execute them sequentially through the full Plan → Implement → Review → Decision → Deliver pipeline with aggregate budget and time tracking. Interrupted queues resume from the first pending item.

This is the user-directed counterpart to `auto`: **`auto` = AI picks what to build; `queue` = human picks what to build.**

## 2. Goals

1. **Batch execution**: Allow users to queue 2-20+ feature requests and walk away — the pipeline processes them unattended.
2. **Durability**: Queue state survives process interruption (Ctrl+C, crash, reboot). `queue start` resumes from the first pending item.
3. **Budget safety**: Aggregate cost and time caps halt the queue gracefully, consistent with the existing `auto --max-budget` / `--max-hours` patterns.
4. **Visibility**: Users can inspect queue state at any time via `queue status`, and get a comprehensive summary table at the end of a run.
5. **Fault isolation**: A failed or rejected item does not block subsequent items.

## 3. User Stories

- **As a tech lead**, I want to queue up 5 features from my sprint backlog (mix of prompts and GitHub issues) before going to lunch, and come back to 5 PRs ready for review.
- **As a solo developer**, I want to set a $50 budget cap on a queue of 8 features so I don't overspend overnight.
- **As an ops engineer**, I want to check `queue status` from another terminal to see how many items are done and how much has been spent.
- **As a user whose laptop went to sleep**, I want `queue start` to pick up where it left off without re-running completed items.

## 4. Functional Requirements

### 4.1 Queue Management Commands

| # | Requirement |
|---|-------------|
| FR-1 | `colonyos queue add "prompt1" "prompt2" --issue 42 --issue 57` enqueues items (free-text and/or issue refs) to `.colonyos/queue.json`. |
| FR-2 | Each queue entry stores: `id` (UUID), `source_type` ("prompt" or "issue"), `source_value` (text or issue number), `status` ("pending"/"running"/"completed"/"failed"/"rejected"), `run_id` (once started), `added_at` (ISO timestamp), `cost_usd`, `duration_ms`, `pr_url`. |
| FR-3 | `queue add` validates issue references at add-time via `fetch_issue()` from `src/colonyos/github.py` — fail fast on invalid refs. Store the resolved issue title for display. |
| FR-4 | `queue add` confirms the count of items added and total pending. |
| FR-5 | `colonyos queue clear` removes all items with status "pending". Running/completed/failed/rejected items are preserved. |

### 4.2 Queue Execution

| # | Requirement |
|---|-------------|
| FR-6 | `colonyos queue start` processes pending items sequentially, each via `run_orchestrator()` from `src/colonyos/orchestrator.py`. |
| FR-7 | For issue-sourced items, re-fetch the issue at execution time (to get latest comments/edits) using `fetch_issue()` + `format_issue_as_prompt()`. |
| FR-8 | On item success (pipeline completes, Decision = GO): mark "completed", record `run_id`, `cost_usd`, `duration_ms`, `pr_url`. Proceed to next item. |
| FR-9 | On item failure (pipeline error/crash): mark "failed", record error, proceed to next item. |
| FR-10 | On item rejection (Decision = NO-GO): mark "rejected", record `run_id` and cost. Proceed to next item. |
| FR-11 | Individual run budgets governed by `budget.per_run` in config (unchanged). |
| FR-12 | `--max-cost <USD>` flag: aggregate cost cap across all queued runs. Queue halts gracefully (not a failure) when exceeded. |
| FR-13 | `--max-hours <H>` flag: wall-clock time cap. Queue halts gracefully when exceeded. Reuse `_compute_elapsed_hours()` pattern from `cli.py`. |
| FR-14 | If interrupted (Ctrl+C, crash), `queue start` resumes from the first pending item. Completed/failed/rejected items are skipped. |
| FR-15 | Each queue item creates an independent branch from the default branch (not stacked). |

### 4.3 Queue Status & Summary

| # | Requirement |
|---|-------------|
| FR-16 | `colonyos queue status` renders a Rich table of all queue items showing: position, source (prompt preview or issue ref), status, cost, duration, PR URL. |
| FR-17 | End-of-queue summary table printed after `queue start` completes, showing: all items with status, cost, duration, PR URLs; plus aggregate totals (total cost, total duration, success/fail/rejected counts). |
| FR-18 | `colonyos status` (existing command) shows a one-line queue summary when a queue exists (e.g., "Queue: 2/5 completed, 1 running, $12.34 spent"). |

## 5. Non-Goals

- **Multiple named queues**: V1 supports one queue per repo. Named queues can be added later with a `--name` flag.
- **Parallel execution**: Items execute sequentially. Parallel queue processing is out of scope.
- **Stacked branches**: Each item gets an independent branch. No rebase chains.
- **Queue item reordering/editing**: Users can `clear` pending items and re-add them. No in-place edit or priority commands.
- **Remote/shared queues**: Queue state is local, gitignored, single-developer.
- **File locking for concurrent access**: V1 uses atomic writes (existing `os.replace` pattern). The queue is loaded once at `start` time; new items added concurrently are picked up on next `start` invocation.

## 6. Technical Considerations

### 6.1 Architecture: Share Infrastructure with `auto`

The `auto` command's loop infrastructure in `src/colonyos/cli.py` (lines 551-888) provides the exact patterns needed:
- **Budget/time caps**: `_compute_elapsed_hours()`, pre/post-iteration budget checks
- **State persistence**: `_save_loop_state()` atomic write via `os.replace`
- **Iteration tracking**: `LoopState` dataclass in `src/colonyos/models.py`

The `queue` command should reuse these patterns but replace the CEO prompt-generation step with dequeuing from the user-supplied list. Specifically:
- Extract a shared `_execute_pipeline_item()` helper from the existing `_run_single_iteration()` that takes a prompt string (bypassing CEO).
- Create a new `QueueState` dataclass that wraps queue-specific fields (items list, per-item status) alongside the shared budget/timing fields.

### 6.2 New Data Models (in `src/colonyos/models.py`)

```python
class QueueItemStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"

@dataclass
class QueueItem:
    id: str                          # UUID
    source_type: str                 # "prompt" or "issue"
    source_value: str                # prompt text or issue number
    status: QueueItemStatus
    added_at: str                    # ISO timestamp
    run_id: str | None = None
    cost_usd: float = 0.0
    duration_ms: int = 0
    pr_url: str | None = None
    error: str | None = None
    issue_title: str | None = None   # Cached at add-time for display

@dataclass
class QueueState:
    queue_id: str
    items: list[QueueItem]
    aggregate_cost_usd: float = 0.0
    start_time_iso: str | None = None
    status: str = "pending"          # pending/running/completed/interrupted
```

### 6.3 Persistence

- **Location**: `.colonyos/queue.json` (top-level in `.colonyos/`, not inside `runs/`)
- **Gitignore**: Add `.colonyos/queue.json` to `.gitignore` (the `runs/` glob doesn't cover this path)
- **Atomic writes**: Use the `_save_loop_state()` pattern (tempfile + `os.replace`)

### 6.4 GitHub Issue Handling

- **At add-time**: Call `fetch_issue()` from `src/colonyos/github.py` to validate existence and cache the title for display in `queue status`.
- **At execution-time**: Re-fetch via `fetch_issue()` + `format_issue_as_prompt()` to get latest content (comments may have been added since enqueue).
- **Sanitization**: Issue content goes through existing `sanitize_untrusted_content()` via `format_issue_as_prompt()` at execution time. Free-text prompts from the CLI user are first-party input and not sanitized (consistent with `colonyos run "prompt"` behavior).

### 6.5 CLI Registration

New Click group `queue` with subcommands `add`, `start`, `status`, `clear`, registered on the existing `app` group in `src/colonyos/cli.py`:

```python
@app.group()
def queue():
    """Manage the feature execution queue."""
    pass

@queue.command()
def add(...): ...

@queue.command()
def start(...): ...

@queue.command()
def status(...): ...

@queue.command()
def clear(...): ...
```

### 6.6 Key File Changes

| File | Change |
|------|--------|
| `src/colonyos/models.py` | Add `QueueItemStatus`, `QueueItem`, `QueueState` dataclasses |
| `src/colonyos/cli.py` | Add `queue` group with `add`, `start`, `status`, `clear` subcommands; update `status` command to show queue summary |
| `src/colonyos/config.py` | No changes needed (budget config already exists) |
| `src/colonyos/orchestrator.py` | No changes needed (queue calls existing `run()` function) |
| `src/colonyos/github.py` | No changes needed (existing `fetch_issue` reused) |
| `.gitignore` | Add `.colonyos/queue.json` |
| `tests/test_queue.py` | New test file for queue functionality |
| `tests/test_cli.py` | Add tests for queue CLI integration |

### 6.7 Persona Consensus & Tensions

**Strong consensus (all 7 personas agree):**
- Share infrastructure with `auto` loop; do not duplicate budget/timing logic
- Independent branches (not stacked) — unanimous
- One queue per repo (no named queues in V1) — unanimous
- Gitignored persistence — unanimous
- Distinguish "rejected" (NO-GO verdict) from "failed" (pipeline crash) — unanimous
- `colonyos status` should show a one-line queue summary — unanimous

**Key tension: Issue resolution timing**
- **Fail-fast camp** (Michael Seibel, Steve Jobs, Systems Engineer, Security Engineer): Validate at add-time, re-fetch at execution time. Best UX and catches typos immediately.
- **Lazy-fetch camp** (Jony Ive, Linus Torvalds, Karpathy): Only fetch at execution time to get freshest content.
- **Resolution**: Validate existence and cache title at add-time (fail-fast UX); re-fetch full content at execution-time (freshest data). Both camps satisfied.

**Key tension: Sanitization of free-text prompts**
- **Security Engineer**: Sanitize everything at add-time, queue decouples input from execution.
- **Steve Jobs, Linus, Karpathy**: CLI user is trusted; sanitizing their own words is unnecessary.
- **Resolution**: Free-text prompts from CLI are first-party input (consistent with `colonyos run`); issue-sourced content sanitized at execution-time via existing `format_issue_as_prompt()`. This matches the existing trust model.

**Key tension: File locking**
- **Systems Engineer, Security Engineer**: Use `fcntl.flock` for concurrent safety.
- **Everyone else**: Overkill for a single-user CLI tool.
- **Resolution**: V1 uses atomic writes only (consistent with existing `auto` loop pattern). Document the single-writer assumption. Revisit if real concurrency issues are reported.

## 7. Success Metrics

1. **Correctness**: All 8 acceptance criteria pass (see feature request).
2. **Test coverage**: Unit tests cover queue persistence (add/read/clear), resume logic, budget enforcement, status rendering, and failure isolation.
3. **Code reuse**: Queue execution reuses `run_orchestrator()` without modification. Budget/time cap logic shares patterns with `auto`.
4. **Consistency**: CLI UX matches existing ColonyOS conventions (Click options, Rich output, error handling patterns).

## 8. Open Questions

1. **Queue item retry**: Should there be a `queue retry` command to re-enqueue failed/rejected items? (Deferred to V2.)
2. **Notification on completion**: Should queue completion trigger a Slack notification if `watch` is configured? (Deferred to V2.)
3. **Maximum queue size**: Should there be a hard limit on queue items to prevent accidental runaway? (Recommend: soft warning at 20 items, no hard limit.)
4. **PR merge**: Should completed PRs be auto-merged, or is that always manual? (Current answer: manual, consistent with existing `deliver` phase behavior.)
