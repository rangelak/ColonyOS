# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

I've completed my review. Now let me write out my findings:

---

## Review Summary - Principal Systems Engineer Perspective

### PRD Requirements Analysis

**FR-1: Parallel Progress Display** ✅
- Implemented `ParallelProgressLine` class with compact status display
- Format matches spec: `Reviews: R1 ✓ | R2 ✓ | R3 ⏳ (45s) | R4 ⏳ (32s) — 2/4 complete, $0.42`
- Updates in-place with elapsed time for pending reviewers

**FR-2: Cost Accumulator** ✅
- `total_cost_usd` property tracks running total across completed reviewers
- Cost is finalized per-reviewer (not mid-turn estimates)
- Summary includes total cost

**FR-3: Completion Events** ✅
- `run_phases_parallel()` now accepts `on_complete` callback
- Signature matches spec: `Callable[[int, PhaseResult], None]`
- Backward compatible - callback defaults to `None`

**FR-4: TTY Detection and Graceful Degradation** ✅
- Auto-enables progress display when `sys.stderr.isatty()` is `True`
- Non-TTY mode produces log lines per completion
- `--quiet` mode skips progress tracker creation entirely

**FR-5: Input Sanitization** ✅
- `sanitize_display_text()` function added to sanitize.py
- Strips ANSI escape sequences and control characters
- Preserves Unicode (emoji, box drawing chars)
- Status icons are hardcoded, not user-controlled

**FR-6: Summary After Completion** ✅
- `print_summary(round_num)` produces formatted verdict summary
- Lists reviewers who requested changes by name

### Reliability/Observability Issues Identified

**Issue 1: Non-TTY render logic is buggy**
In `_render_non_tty()`, the method iterates through reviewers in index order and prints the first non-pending one, then breaks. This is incorrect behavior when:
1. Reviewer 0 completes → prints R0 ✓
2. Reviewer 2 completes → iterates, finds R0 (already complete), prints R0 AGAIN

This will cause duplicate log lines in non-TTY (CI) environments. The method should track which specific index was just updated in this callback invocation, not iterate to find the "first non-pending".

**Impact**: CI logs will have duplicated/incorrect completion messages. In a 4-reviewer scenario, the first completer would be printed 4 times.

**Issue 2: No stderr write atomicity guarantee**
The PRD mentions thread-safety concerns: "use a simple mutex or ensure all stderr writes are atomic single-line prints". The implementation uses Rich's `Console.print()` but doesn't implement any locking. When streaming output from parallel reviewers interleaves with progress updates, there's a risk of garbled output.

The callback is invoked from the async event loop (not threads), but `PhaseUI` instances may stream output concurrently while the progress line is being rendered. Rich's Console has an internal lock, so this is likely safe, but it's not explicitly tested.

**Issue 3: Exception handling in callback**
If the `on_complete` callback throws an exception (e.g., from `_extract_review_verdict` on malformed text), it would bubble up through `asyncio.wait()` and could fail the entire parallel execution. The callback invocation should be wrapped in try/except.

```python
if on_complete is not None:
    try:
        on_complete(idx, result)
    except Exception:
        logging.exception("Progress callback failed for index %d", idx)
```

**Issue 4: Elapsed time refresh strategy**
The PRD's open question #1 asks about refresh rate. The implementation shows elapsed time only when another reviewer completes (correct per PRD proposal), but the elapsed time calculation uses `time.monotonic() - self._start_time` which is the total elapsed since tracker creation, not per-reviewer elapsed time. This might be confusing if one reviewer started late.

### Code Quality

- All 1285 tests pass
- No TODO/FIXME markers in implementation
- No secrets/credentials in code (existing patterns are for sanitization, not leakage)
- Comprehensive test coverage for new functionality (27 new tests)
- Docstrings present for public classes/functions
- Type hints used consistently

### Backward Compatibility ✅
- `run_phases_parallel_sync()` accepts optional callback, existing callers unchanged
- New `ParallelProgressLine` class is opt-in, not modifying existing `PhaseUI`

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/ui.py:433-458]: Non-TTY rendering bug - iterates by index and prints first non-pending reviewer, causing duplicate log lines when multiple reviewers complete. Should track the specific index from `on_reviewer_complete()` and only print that one.
- [src/colonyos/agent.py:268-269]: Missing exception handling around callback invocation - if `on_complete` throws, it fails the entire parallel execution rather than logging and continuing
- [src/colonyos/ui.py]: No explicit test for concurrent output interleaving - while Rich Console has internal locking, the interaction between streaming PhaseUI output and progress line updates under load isn't tested

SYNTHESIS:
This is a solid implementation that addresses the core PRD requirements with appropriate simplicity. The callback-based architecture preserves backward compatibility and the asyncio.wait() pattern correctly yields incremental results. However, there's a functional bug in the non-TTY rendering path that will produce incorrect CI logs - when reviewer completions arrive out of order, the log output will be duplicated or incorrect. This is a reliability concern for the CI use case explicitly called out in the PRD (User Story #3: "I want the progress tracker to emit clean, parseable output...so my logs remain readable"). Additionally, the lack of exception handling around callback invocation creates a blast radius concern - a rendering bug could kill an entire review run. These issues should be fixed before shipping.
