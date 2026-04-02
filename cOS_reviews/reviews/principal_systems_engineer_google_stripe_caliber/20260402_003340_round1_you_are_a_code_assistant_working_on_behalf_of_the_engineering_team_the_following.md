# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

Now I have a complete picture. Let me write the review.

---

## Review: Principal Systems Engineer Perspective

### Checklist Assessment

**Completeness:**
- [x] FR-1: `pull_branch()` helper in `recovery.py` — ✅ Implemented with upstream check, `--ff-only`, structured return
- [x] FR-2: `restore_to_branch()` calls `pull_branch()` after checkout — ✅ Warn-and-continue, never-raises preserved
- [x] FR-3: Base-branch checkout in orchestrator hard-fails — ✅ Raises `PreflightError`
- [x] FR-4: Preflight replaces fetch+warn with pull — ✅ Clean replacement
- [x] FR-5: All pulls gated by offline flag — ✅ Three gates: `if not offline` in orchestrator (×2), `if offline: return` in CLI
- [x] FR-6: Thread-fix does NOT pull — ✅ Verified by source inspection test
- [x] FR-7: `_ensure_on_main()` refactored to shared helper — ✅ Clean delegation
- [x] FR-8: Upstream check before pull — ✅ `rev-parse --abbrev-ref @{upstream}`
- [x] FR-9: Structured logging — ✅ `_LOGGER.info` on success, `_LOGGER.warning` on failure with branch name

**Quality:**
- [x] All 35 new + 40 existing preflight tests pass (0 failures)
- [x] Code follows existing project conventions (`_git()` helper, `_LOGGER` pattern)
- [x] No unnecessary dependencies added
- [x] No unrelated changes

**Safety:**
- [x] No secrets or credentials
- [x] No destructive operations — `--ff-only` fails safely on diverged state
- [x] Error handling present for all failure cases

### Findings

- **[src/colonyos/recovery.py:170-222]**: `_LOGGER` is defined at line 222 but referenced inside `pull_branch()` at lines 194/199/202. This works in Python (module-level name resolution is deferred to call-time), but it's a readability hazard — a reader sees `_LOGGER.warning(msg)` and has to scroll past 30 lines to find where it's defined. The existing codebase has this pattern already (other functions above line 222 also use `_LOGGER`), so this is pre-existing tech debt, not introduced by this PR.

- **[src/colonyos/recovery.py:180-182]**: The upstream check uses a hardcoded `timeout=10` while the main pull uses the configurable `timeout` parameter. This is correct (the metadata query should be fast) but undocumented. Minor nit.

- **[src/colonyos/orchestrator.py:394-405]**: The preflight now calls `pull_branch()` which pulls *the current branch* (whatever is checked out), not specifically `main`. The old code explicitly fetched `origin main`. This is actually more correct — the preflight runs on whatever branch is current — but worth noting the semantic shift. The `main_behind_count` variable name is now slightly misleading since we're pulling the current branch, not necessarily main.

- **[tests/test_orchestrator.py:395-419]**: Two tests use `inspect.getsource()` to verify code structure by string matching. This is fragile — a whitespace change or variable rename breaks these tests without any behavioral change. However, given the difficulty of exercising the full `run()` function in unit tests (it has many dependencies), this is a pragmatic tradeoff. The behavioral test at line 374 (`test_base_branch_pull_fails_raises_preflight_error`) provides the actual contract test.

- **[src/colonyos/recovery.py:383-385]**: The bare `except Exception` catch around `pull_branch()` in `restore_to_branch()` is defensive and correct — it preserves the never-raises contract. The `exc_info=True` on the warning log is exactly right for debugging at 3am.

- **[src/colonyos/orchestrator.py:4201-4209]**: The pull happens *after* checkout but *before* preflight. This ordering is correct: preflight validates the state we'll actually work from. If pull changes something (e.g., a new file appears), preflight will see the true state.

- **[src/colonyos/cli.py:1956-1961]**: When `pull_branch()` returns `(False, None)` (no upstream), the condition `not success and error` is `False`, so no warning is emitted. This is correct — no upstream means no pull needed.

### Synthesis

This is a clean, well-scoped implementation that hits all nine functional requirements with appropriate failure semantics at each call site. The key architectural decision — different failure modes per call site (hard-fail at base-branch checkout, warn-and-continue at daemon restore and preflight) — is correct and well-tested. The `pull_branch()` helper has a good return-type design: the `(bool, Optional[str])` tuple cleanly distinguishes "success", "no upstream" (skip), and "failure with reason", letting each caller decide its own policy.

The test coverage is thorough: 35 new tests covering success, failure, timeout, no-upstream, offline-skip, and the critical negative case (thread-fix must NOT pull). The `inspect.getsource()` tests are a minor smell but acceptable given the testing constraints. The never-raises contract on `restore_to_branch()` is properly preserved with a defensive `except Exception` + `exc_info=True` logging — exactly what you want when debugging a stuck daemon at 3am.

No race conditions introduced: pulls happen at entry points before any concurrent work begins. The `--ff-only` flag is the right choice — it fails explicitly on diverged state rather than silently discarding local commits. The offline gating is consistent across all three entry points.

VERDICT: approve

FINDINGS:
- [src/colonyos/recovery.py:222]: `_LOGGER` defined after `pull_branch()` — works but harms readability (pre-existing pattern, not introduced here)
- [src/colonyos/orchestrator.py:399]: `main_behind_count` variable name is now slightly misleading since pull targets the current branch, not necessarily main
- [tests/test_orchestrator.py:395-419]: Two tests use `inspect.getsource()` string matching — fragile to refactoring but pragmatic given constraints
- [src/colonyos/recovery.py:180]: Hardcoded `timeout=10` for upstream check is undocumented but reasonable

SYNTHESIS:
Solid, minimal-blast-radius implementation that adds auto-pull at exactly the three right pipeline entry points while preserving critical safety invariants (thread-fix SHA integrity, never-raises daemon contract, offline mode). The shared `pull_branch()` helper has clean error semantics, the failure modes are appropriate per call site, and test coverage is comprehensive. The code is production-ready. Ship it.