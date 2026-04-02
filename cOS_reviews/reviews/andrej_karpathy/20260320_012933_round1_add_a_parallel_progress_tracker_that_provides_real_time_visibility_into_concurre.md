# Review by Andrej Karpathy (Round 1)

Now I have a complete picture. Let me write my final review:

---

## Review Summary: Parallel Progress Tracker Implementation

### PRD Requirements Checked

**FR-1: Parallel Progress Display** ✅
- Progress line format matches spec: `Reviews: R1 ✓ | R2 ⏳ (45s) | ... — 2/4 complete, $0.42`
- In-place updating via carriage return implemented
- Elapsed time shown for running reviewers

**FR-2: Cost Accumulator** ✅
- `total_cost_usd` property accumulates completed reviewer costs
- Summary includes total cost

**FR-3: Completion Events** ✅
- `on_complete: Callable[[int, PhaseResult], None] | None` parameter added
- Callback invoked via `asyncio.wait(return_when=FIRST_COMPLETED)` yielding incremental results
- Backward compatible (defaults to `None`)

**FR-4: TTY Detection and Graceful Degradation** ✅
- `sys.stderr.isatty()` check implemented in orchestrator
- Non-TTY mode produces log-style output
- `--quiet` mode skips progress tracker creation entirely

**FR-5: Input Sanitization** ✅
- `sanitize_display_text()` implemented with ANSI and control character stripping
- Persona names sanitized before storage in `ParallelProgressLine`
- Status icons hardcoded (not user-influenced)

**FR-6: Summary After Completion** ✅
- `print_summary(round_num)` outputs: `Review round 1: 2 approved, 1 request-changes (name) — $0.89 total`

### Tests ✅
- 70 new/modified tests pass (test_agent.py, test_sanitize.py, test_ui.py)
- Full test suite: 1285 passed, 1 skipped

### Code Quality

**Architecture decisions:**
- Switched from `asyncio.gather()` to `asyncio.wait(FIRST_COMPLETED)` — this is the right call for streaming callbacks. The gather approach would've forced buffering until all complete.
- Verdict extraction via regex (`VERDICT:\s*(approve|request-changes)`) — reasonable for structured output. The AI outputs are constrained by our own prompts, so this is safe.

**Potential Issues:**

1. **Non-TTY render logic flaw (minor):** The `_render_non_tty()` method iterates through reviewers in index order and breaks at the first non-pending. This works by coincidence but the logic is fragile. If `asyncio.wait()` returns multiple tasks in the done set simultaneously, the `for task in done` loop will invoke the callback multiple times, and the second call will print the wrong reviewer (it'll find the first one again).

2. **Missing `_last_completed_idx` tracking:** The comment says "Only print the last completed one (avoid reprinting)" but there's no actual tracking of which index just completed. The callback receives the index but `_render_non_tty()` doesn't use it.

3. **Thread safety documentation:** The PRD mentions threading concerns (line 119). The code is safe because callbacks run in the asyncio event loop (single-threaded), but this isn't documented. A future refactor using `asyncio.to_thread()` could break this assumption.

4. **Defaulting to "approved" on parse failure:** Line 376-377 defaults unknown verdicts to "approved". This is a reasonable UX choice (optimistic), but could mask broken review outputs. Consider logging a warning.

### From an AI Engineering Perspective

The design makes good choices:
- **Structured output reliance:** The verdict regex works because we control the review prompt that asks for `VERDICT: approve | request-changes`. Prompts are programs — the implementation correctly treats the output format as a contract.
- **Failure mode handling:** Failed reviews show `✗` icon; cost tracking handles `None` values with `or 0.0`. Edge cases considered.
- **No mid-turn estimates:** Per PRD, costs are only shown on completion. This avoids the failure mode of misleading partial token counts.

**Suggestions for iteration:**
- Add structured output schema enforcement in the review prompt (JSON with verdict field) rather than regex parsing. More reliable with modern models.
- Consider adding `on_start` callback for showing "starting R1..." in verbose mode.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/ui.py:433-458]: Non-TTY render iterates in index order, not completion order. Works by coincidence but fragile if `done` set contains multiple tasks.
- [src/colonyos/ui.py:376-377]: Defaults to "approved" on parse failure without logging a warning - could mask broken review outputs.
- [src/colonyos/ui.py:433-458]: Comment says "Only print the last completed one" but method doesn't track `_last_completed_idx` from the callback.
- [src/colonyos/agent.py:268-269]: No documentation that callback is invoked from asyncio event loop (single-threaded), despite PRD mentioning threading concerns.

SYNTHESIS:
This is a well-executed implementation that correctly prioritizes simplicity over complexity. The decision to use `asyncio.wait(FIRST_COMPLETED)` instead of wrapping results is the right architectural choice for streaming callbacks. The sanitization layer properly defends against ANSI injection in persona names. The cost accumulation only shows finalized costs (not misleading estimates). The TTY/non-TTY graceful degradation follows the spec. The non-TTY render has a minor logic flaw that works by coincidence, and there's a missing warning log for parse failures, but these are polish items that don't block shipping. The implementation achieves the PRD's stated goal: 80% of the value with 20% of the complexity.
