# Review by Linus Torvalds (Round 1)

All tests pass, but there's a clear bug in the non-TTY code path. The test `test_render_non_tty_mode_produces_log_lines` doesn't catch this bug because it only completes one reviewer.

Now I have enough information to write my review.

---

## Review as Linus Torvalds

Alright, let me look at this code with the scrutiny it deserves.

**The Good:**

1. **Data structures first**: The `run_phases_parallel()` refactor from `asyncio.gather()` to `asyncio.wait()` with `FIRST_COMPLETED` is correct. You need incremental results, so you use incremental waiting. The task-to-index mapping is clean.

2. **Callback interface**: Simple, obvious. `Callable[[int, PhaseResult], None]`. No over-engineering.

3. **Sanitization**: The `sanitize_display_text()` function does one thing and does it right. Two regex passes, strip, done. The regex patterns are correct for ANSI escapes and control characters. Good that it preserves Unicode.

4. **Tests are reasonable**: 70 new tests covering the callback mechanics, sanitization edge cases, and progress tracking. They actually test behavior, not implementation details.

**The Bad:**

1. **Bug in `_render_non_tty()`**: This code is broken. Look at lines 433-458:
   ```python
   for idx, _ in self._reviewers:
       state = self._states[idx]
       if state["status"] != "pending":
           # ...print the state...
           break  # BUG: always prints first non-pending, not the just-completed one
   ```
   This iterates in *reviewer order*, not *completion order*. It prints the first non-pending reviewer it finds, which will be the first one that ever completed. So if R0 completes first, every subsequent completion will re-print R0's status. The comment says "Only print the last completed one (avoid reprinting)" but the code does the exact opposite.

   The fix is trivial: track which reviewer just completed (you already know - it's the `index` passed to `on_reviewer_complete`) and print only that one. Don't iterate.

2. **The `_states` dict is stringly-typed garbage**:
   ```python
   self._states: dict[int, dict[str, object]] = {}
   ```
   You're storing `{"status": str, "cost_usd": float, "duration_ms": int}` but you declared it as `dict[str, object]`. Then you cast everywhere: `float(state["cost_usd"])`, `int(state["duration_ms"])`. This is Python, not JavaScript. Use a dataclass or a named tuple. Or at minimum, a TypedDict.

3. **Console access via `globals()`**: Line 327:
   ```python
   self._console = console or globals()["console"]
   ```
   What the hell is this? You're reaching into the module's global namespace at runtime instead of just importing the module-level `console` variable directly. This is fragile. If someone renames `console` to `_console`, this breaks at runtime, not import time.

**Verdict on Completeness:**

Looking at the PRD requirements:

- FR-1 (Progress Display): ✓ Implemented, format matches spec
- FR-2 (Cost Accumulator): ✓ `total_cost_usd` property, shown in output
- FR-3 (Completion Events): ✓ `on_complete` callback added to `run_phases_parallel`
- FR-4 (TTY Detection): ✓ `sys.stderr.isatty()` check, different rendering paths
- FR-5 (Input Sanitization): ✓ `sanitize_display_text()` implemented and used
- FR-6 (Summary After Completion): ✓ `print_summary()` called after parallel execution

The features are there, but there's a functional bug in the non-TTY path.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/ui.py:433-458]: Bug in `_render_non_tty()` - iterates in reviewer order and prints first non-pending, not the just-completed reviewer. Will re-print the same completed reviewer on every subsequent completion. Fix: track which reviewer just completed and print only that one.
- [src/colonyos/ui.py:336]: `_states` typed as `dict[str, object]` forces explicit casts everywhere. Should use a dataclass or TypedDict for `{status: str, cost_usd: float, duration_ms: int}`.
- [src/colonyos/ui.py:327]: `globals()["console"]` is fragile - use direct import reference instead of runtime global lookup.

SYNTHESIS:
The implementation is architecturally sound. The parallel execution callback design is clean - `asyncio.wait()` with `FIRST_COMPLETED` is the right primitive when you need incremental notification. The sanitization code is correct and well-tested. However, there's a functional bug in the non-TTY rendering path that will cause duplicate log lines for the same reviewer instead of logging each completion once. This is a must-fix before merge. The typing issues and `globals()` hack are minor - they're code smells, not correctness bugs - but they indicate hasty implementation. Fix the non-TTY bug, and this is ready.