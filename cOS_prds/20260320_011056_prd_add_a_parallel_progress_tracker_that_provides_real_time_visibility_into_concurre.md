# PRD: Parallel Progress Tracker

## Introduction/Overview

The Parallel Progress Tracker provides real-time visibility into concurrent operations across the ColonyOS pipeline, specifically during the review phase where multiple AI personas run in parallel. When users run `colonyos run "feature"` with multiple reviewer personas, they currently see interleaved output with colored prefixes (`R1`, `R2`, etc.) but have no clear at-a-glance summary of which reviewers are still running vs. completed.

This feature adds a lightweight progress display that shows reviewer status without disrupting the existing streaming output that users rely on for debugging.

## Goals

1. **Visibility**: Show real-time status of parallel reviewers (running/approved/request-changes/failed) without requiring users to scroll back through interleaved output
2. **Cost Transparency**: Display running cost totals during the review phase, not just after completion
3. **Simplicity**: Augment the existing streaming UI rather than replacing it—preserve debugging visibility
4. **Robustness**: Degrade gracefully in non-TTY environments (CI pipelines, redirected output)
5. **Minimal Complexity**: Avoid over-engineering terminal cursor management that introduces fragility

## User Stories

1. **As a developer running parallel reviews**, I want to see at-a-glance which reviewers are still running and which have completed, so I can estimate how long the phase will take.

2. **As a budget-conscious user**, I want to see the accumulated cost across all reviewers during the review phase, so I can Ctrl+C if costs are tracking higher than expected.

3. **As a CI pipeline operator**, I want the progress tracker to emit clean, parseable output without ANSI escape sequences, so my logs remain readable.

4. **As a debugger investigating a stuck review**, I want to see elapsed time per reviewer, so I can identify if one reviewer is taking significantly longer than others.

## Functional Requirements

### FR-1: Parallel Progress Display
- Display a compact summary line showing reviewer completion status during parallel reviews
- Format: `Reviews: R1 ✓ | R2 ✓ | R3 ⏳ (45s) | R4 ⏳ (32s) — 2/4 complete, $0.42`
- Update in-place (single line rewrite) when a reviewer completes
- Show elapsed time only for running reviewers (provides "is it stuck?" signal)

### FR-2: Cost Accumulator
- Display running total of completed reviewer costs in the progress line
- Update the total when each reviewer completes (not mid-turn estimates)
- Show final phase cost in the existing `phase_complete()` output

### FR-3: Completion Events
- Modify `run_phases_parallel_sync()` to accept an optional `on_complete` callback
- Callback signature: `Callable[[int, PhaseResult], None]` where `int` is the reviewer index
- Preserve backward compatibility: callback defaults to `None`, existing callers unchanged

### FR-4: TTY Detection and Graceful Degradation
- Auto-enable progress display when `sys.stderr.isatty()` is `True`
- When non-TTY: emit one log line per completion (`R1 complete (approved) $0.12 in 23s`)
- `--quiet` mode disables progress display entirely (existing behavior)
- `--verbose` mode shows progress display + full streaming output (coexist)

### FR-5: Input Sanitization
- Sanitize persona role names before display to strip ANSI escape sequences and control characters
- Add `sanitize_display_text()` function to `sanitize.py`
- Validate persona roles during config load to warn on suspicious characters

### FR-6: Summary After Completion
- After all reviewers complete, print a one-line verdict summary before proceeding to decision gate
- Format: `Review round 1: 2 approved, 1 request-changes (Linus Torvalds) — $0.89 total`

## Non-Goals

1. **Live-updating table/grid UI**: Per persona feedback (Steve Jobs, Linus Torvalds), a persistent multi-row grid with Rich's `Live` context adds complexity without proportional benefit. The single-line progress indicator achieves 80% of the value with 20% of the complexity.

2. **Real-time token counts**: Token-based cost estimates mid-turn are misleading; we only show finalized costs after each reviewer completes.

3. **Progress tracking for plan phase**: The persona Q&A during planning is fast (seconds, not minutes). Scope is review phase only.

4. **Aggregate progress bar**: A horizontal bar filling from 0-100% adds visual noise without information. The "2/4 complete" text conveys the same information more precisely.

5. **Per-reviewer detailed metrics**: Model name, token counts, etc. are available in the `colonyos show` command for post-run inspection.

## Technical Considerations

### Existing Architecture

The codebase has clear separation of concerns:
- `src/colonyos/agent.py`: `run_phases_parallel_sync()` uses `asyncio.gather()` for parallel execution
- `src/colonyos/orchestrator.py`: Review loop at lines 2266-2365 constructs parallel review calls
- `src/colonyos/ui.py`: `PhaseUI` handles streaming output with per-reviewer prefixes (`R1`, `R2`)

### Proposed Changes

1. **`agent.py`**: Add `on_complete` callback parameter to `run_phases_parallel()`:
   ```python
   async def run_phases_parallel(
       calls: list[dict],
       on_complete: Callable[[int, PhaseResult], None] | None = None,
   ) -> list[PhaseResult]:
   ```
   Use `asyncio.as_completed()` to yield results incrementally instead of waiting for all.

2. **`ui.py`**: Add `ParallelProgressLine` class:
   ```python
   class ParallelProgressLine:
       def __init__(self, reviewers: list[str], is_tty: bool):
           ...
       def on_reviewer_complete(self, index: int, result: PhaseResult) -> None:
           ...
       def render(self) -> None:
           ...
   ```

3. **`orchestrator.py`**: Instantiate `ParallelProgressLine` before calling `run_phases_parallel_sync()`, pass `on_complete=tracker.on_reviewer_complete`.

4. **`sanitize.py`**: Add `sanitize_display_text()` function:
   ```python
   _ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
   _CONTROL_CHARS_RE = re.compile(r'[\x00-\x1f\x7f-\x9f]')

   def sanitize_display_text(text: str) -> str:
       text = _ANSI_ESCAPE_RE.sub('', text)
       text = _CONTROL_CHARS_RE.sub('', text)
       return text.strip()
   ```

### Concurrency Considerations

- The `on_complete` callback is invoked from the async event loop, not a separate thread
- `ParallelProgressLine` must be thread-safe if used with the existing `PhaseUI` streaming (both write to stderr)
- Use a simple mutex or ensure all stderr writes are atomic single-line prints

### Backward Compatibility

- All new parameters are optional with sensible defaults
- Existing callers of `run_phases_parallel_sync()` continue to work unchanged
- `--quiet` and `--verbose` behavior preserved; `--progress` flag is optional (auto-detected from TTY)

## Persona Synthesis

### Areas of Agreement

| Topic | Consensus |
|-------|-----------|
| **Simplicity** | All personas agree: avoid Rich `Live` tables, prefer lightweight single-line updates |
| **Cost visibility** | Show finalized costs only, not mid-turn estimates |
| **TTY detection** | Essential for CI compatibility; auto-disable fancy output in non-TTY |
| **Security** | Sanitize persona names before display to prevent ANSI injection |

### Areas of Tension

| Topic | Tension | Resolution |
|-------|---------|------------|
| **Build vs. wait** | YC Partner says "wait for user demand"; Jony Ive wants design excellence | Ship minimal version (FR-1, FR-3, FR-4) now; iterate based on feedback |
| **Visible vs. invisible** | Steve Jobs wants "invisible until anomaly"; Systems Engineer wants observability | Default to visible progress line; add timeout indicator for anomalies |
| **Streaming interleave** | Linus warns about stderr corruption; Andrej wants tool stream preserved | Single-line rewrite doesn't interleave with multi-line streaming output |

## Success Metrics

1. **Adoption**: >50% of interactive runs use the progress display (measured via heartbeat telemetry)
2. **User satisfaction**: No regression in "ease of use" if user surveys are conducted
3. **Reliability**: Zero reports of terminal corruption or garbled output in first 30 days
4. **Performance**: <5ms overhead per progress update (measured via profiling)

## Open Questions

1. **Refresh rate**: Should the elapsed time for running reviewers update every second, or only when another reviewer completes? (Proposed: only on completion events, to minimize redraws)

2. **Failure handling**: When a reviewer fails mid-review, should we show `R2 ✗ (error)` and continue, or halt all reviewers? (Current behavior: let others complete, aggregate results)

3. **Verbose + progress**: When both `--verbose` and progress are active, should the progress line appear above or below the streaming output? (Proposed: below, as a "status bar")

## Related Files

- `src/colonyos/agent.py` — Parallel execution primitives (lines 232-240)
- `src/colonyos/orchestrator.py` — Review loop (lines 2266-2365)
- `src/colonyos/ui.py` — Terminal UI and `PhaseUI` class (lines 55-268)
- `src/colonyos/sanitize.py` — Input sanitization utilities
- `src/colonyos/models.py` — `PhaseResult`, `Persona` dataclasses
- `tests/test_orchestrator.py` — Existing orchestrator tests
