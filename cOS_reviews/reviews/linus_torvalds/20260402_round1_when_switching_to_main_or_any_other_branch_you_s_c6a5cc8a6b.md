# Review: Auto-Pull Latest on Branch Switch
**Reviewer**: Linus Torvalds
**Round**: 1
**Branch**: `colonyos/when_switching_to_main_or_any_other_branch_you_s_c6a5cc8a6b`

## Checklist

### Completeness
- [x] FR-1: `pull_branch()` helper in `recovery.py` — implemented, uses `_git()`, checks upstream first
- [x] FR-2: `restore_to_branch()` calls `pull_branch()` after checkout, failure logged as warning
- [x] FR-3: Orchestrator base-branch checkout pulls, failure raises `PreflightError`
- [x] FR-4: Preflight replaces fetch+warn with actual pull
- [x] FR-5: All pull calls gated by offline flag
- [x] FR-6: Thread-fix checkout does NOT pull (verified by source inspection test)
- [x] FR-7: `_ensure_on_main()` refactored to use shared `pull_branch()` helper
- [x] FR-8: Upstream check via `git rev-parse --abbrev-ref @{upstream}` before pull
- [x] FR-9: Structured logging for success/failure with branch name

### Quality
- [x] All tests pass (512 passed)
- [x] No linter errors introduced
- [x] Code follows existing project conventions (`_git()` helper, return tuples)
- [x] No unnecessary dependencies added
- [x] No unrelated changes included

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive operations — `--ff-only` fails safely on divergence
- [x] Error handling present for all failure cases

## Findings

VERDICT: approve

FINDINGS:
- [src/colonyos/recovery.py]: `pull_branch()` is clean — 34 lines, does exactly one thing, return type is honest about the three possible outcomes (success, no-upstream, failure). The upstream check before pull is the right call — avoids a confusing error message on branches with no tracking ref.
- [src/colonyos/recovery.py]: The `branch_result` call to get the branch name for logging is an extra subprocess spawn on every pull. It's fine — this runs at most 3 times per pipeline run, not in a hot path. If it ever matters, the upstream result already contains the remote branch name, but premature optimization is the root of all evil.
- [src/colonyos/recovery.py]: `restore_to_branch()` wraps the pull call in a bare `except Exception` — normally I'd scream about this, but it's explicitly part of the never-raises contract. The `exc_info=True` on the warning log means we can still debug it. Acceptable.
- [src/colonyos/orchestrator.py]: Preflight pull replaces ~25 lines of fetch+rev-list+count logic with 5 lines calling the shared helper. The old code was doing fetch, then counting behind commits, then warning. The new code just pulls and either succeeds or warns. Simpler. Better.
- [src/colonyos/orchestrator.py]: Base-branch checkout hard-fails on pull failure — this is correct. Starting from a stale base is the exact bug this feature exists to fix. If the pull fails, you want to know NOW, not after 20 minutes of wasted pipeline time.
- [src/colonyos/cli.py]: `_ensure_on_main()` refactored cleanly — removed 13 lines of inline subprocess handling, replaced with 4 lines using the shared helper. Added `offline` parameter that was previously missing. The checkout still uses raw `subprocess.run` (not `_git()`), which is slightly inconsistent, but that's pre-existing code and not part of this change.
- [tests/test_orchestrator.py]: Some tests use `inspect.getsource()` to verify source-level properties (e.g., "if not offline:" appears in the source). This is fragile — any refactor that changes variable names or structure breaks these tests without changing behavior. However, it's a pragmatic choice given the difficulty of testing the full `run()` orchestrator path end-to-end. I'll let it slide for now.
- [tests/test_pull_branch_integration.py]: Good coverage of the cross-cutting concerns — daemon restore, orchestrator preflight, orchestrator base-branch, thread-fix exclusion, offline mode across all paths. The `TestSharedPullHelper` class that checks both cli and orchestrator import the same `pull_branch` function is a nice touch.

SYNTHESIS:
This is a well-executed, focused change. The data structure — `tuple[bool, str | None]` with three states (success, no-upstream, failure) — drives the control flow naturally at every call site. The implementation touches exactly three pipeline entry points as the PRD specified, adds no unnecessary abstraction, and the test coverage is thorough (208 new test lines for 131 new source lines). The code removed is more complex than the code added, which is always a good sign. The only real nit is the `inspect.getsource()` test pattern in the orchestrator tests — it's testing implementation rather than behavior — but given the complexity of mocking the full `run()` path, it's a reasonable trade-off. Ship it.
