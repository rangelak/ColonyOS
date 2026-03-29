# Principal Systems Engineer Review — Handle 529 Overloaded Errors with Retry

**Reviewer**: Principal Systems Engineer (Google/Stripe caliber)
**Branch**: `colonyos/the_following_github_issue_is_the_source_feature_description_treat_it_as_the_pri`
**Round**: 1
**Date**: 2026-03-29

---

## Checklist

### Completeness
- [x] FR-1: `_friendly_error()` detects "overloaded"/"529"/"503" patterns
- [x] FR-2: `_is_transient_error()` checks structured `status_code` first, regex fallback second
- [x] FR-3: `run_phase()` wraps query in retry loop with restart-from-scratch semantics
- [x] FR-4: Default config: `max_attempts=3`, `base_delay=10.0`, `max_delay=120.0`, full jitter
- [x] FR-5: `RetryConfig` dataclass in `config.py`, nested under `ColonyConfig`
- [x] FR-6: Optional `fallback_model` activates after retries exhausted
- [x] FR-7: Fallback hard-blocked for safety-critical phases (`review`, `decision`, `fix`)
- [x] FR-8: Retry attempts logged via `ui.on_text_delta()` or `_log()`
- [x] FR-9: `PhaseResult.retry_info` (typed `RetryInfo` dataclass) with attempts, transient_errors, fallback_model_used, total_retry_delay_seconds
- [x] FR-10: Parallel phases retry independently (no cross-phase coordination)
- [x] All tasks marked complete
- [x] No placeholder/TODO code (one design-note comment about SDK structured errors is appropriate)

### Quality
- [x] 440 tests pass (zero regressions)
- [x] Code follows existing project conventions (`RetryConfig` mirrors `CIFixConfig`/`RecoveryConfig` pattern)
- [x] No unnecessary dependencies (`random`, `re` are stdlib)
- [x] README updated with config documentation
- [x] `.colonyos/daemon_state.json` added to `.gitignore` (prior review finding fixed)

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive operations without safeguards
- [x] Input validation: `max_attempts >= 1`, delays non-negative, fallback model validated against `VALID_MODELS`
- [x] Warning logged for `max_attempts > 10`
- [x] `RetryInfo` is frozen dataclass (immutable after creation)

---

## Findings

### HIGH — `resume` kwarg leaks into retry attempts

- **[src/colonyos/agent.py:248]**: The `resume` session ID is passed to `ClaudeAgentOptions` on *every* retry attempt. After a 529, no `ResultMessage` was received, so no new `session_id` exists. If `resume` was passed by the caller (orchestrator recovery), the retry will attempt to resume a session that was already interrupted by a server-side 529. The PRD explicitly states: "Retry restarts the phase from scratch (not resume)." On retry attempts (attempt > 1), `resume` should be set to `None`.

  **Impact**: On the happy path this is unlikely to bite — `resume` is rarely non-None when a 529 hits. But when the orchestrator resumes a run that then hits a 529, the retry could fail with an invalid session error, defeating the entire purpose. This is the kind of bug that surfaces at 3am during an overnight daemon run.

  **Fix**: `**({"resume": resume, "continue_conversation": True} if resume and overall_attempt == 1 else {})`

### MEDIUM — `_is_transient_error()` called 3x on same exception in hot path

- **[src/colonyos/agent.py:264-268]**: When an error occurs, `_is_transient_error(exc)` is evaluated at line 264, then again at line 266, then again at line 268. These are regex evaluations on potentially large exception strings. Extract to a local boolean:
  ```python
  is_transient = _is_transient_error(exc)
  if not is_transient or attempt == pass_max:
      transient_errors += 1 if is_transient else 0
      if is_transient and pass_idx < len(passes) - 1:
  ```

### MEDIUM — `_SAFETY_CRITICAL_PHASES` uses raw strings instead of `Phase` enum values

- **[src/colonyos/config.py:22]**: `frozenset({"review", "decision", "fix"})` — if anyone renames a `Phase` enum member's `.value`, this silently stops matching. Should be `frozenset({Phase.REVIEW.value, Phase.DECISION.value, Phase.FIX.value})`. This is a config.py file so it can't easily import from models.py (circular import risk), but the coupling should at least be documented with a comment or validated at import time.

### MEDIUM — `_friendly_error` for 529 uses plain `in` while `_is_transient_error` uses word-boundary regex

- **[src/colonyos/agent.py:97]**: `if "overloaded" in lower or "529" in lower:` — this is the same broad substring matching that was fixed in `_is_transient_error()` with `\b529\b`. The inconsistency means `_friendly_error` could produce "API is temporarily overloaded (529). Will retry..." for non-529 errors containing the substring "529". Not critical since `_friendly_error` is just a display function, but it's confusing to have two detection strategies.

### LOW — Double `continue` pattern at end of retry loop is hard to reason about

- **[src/colonyos/agent.py:~325-330]**: The `for/else/continue/continue` pattern is technically correct but requires readers to understand Python's for/else semantics (which most engineers don't use frequently). A comment explaining the control flow would help the next on-call engineer debugging at 3am.

### LOW — No test for `resume` + retry interaction

- **[tests/test_agent.py]**: 747 lines of excellent test coverage, but no test verifies behavior when `resume` is non-None and a 529 occurs. Given the HIGH finding above, this is exactly the scenario that needs a regression test.

### OBSERVATION — Backoff implementation is correct

The full jitter formula `random.uniform(0, min(base * 2^(attempt-1), max_delay))` matches the AWS architecture blog recommendation. The `asyncio.sleep(delay)` correctly yields to the event loop. In parallel execution, each phase's backoff is independent, which provides natural decorrelation without explicit thundering-herd mitigation. This is the right design for the typical 3-4 concurrent phases.

### OBSERVATION — Retry-below-recovery architecture is well-layered

The decision to place retry inside `run_phase()` rather than at the orchestrator level is correct. The orchestrator's `_attempt_phase_recovery()` and `_run_nuke_recovery()` are expensive (diagnostic agents, git operations). A 529 should never trigger those. The retry loop is invisible to the orchestrator, which is exactly the right abstraction boundary.

### OBSERVATION — `retry_config` plumbing is thorough

All 22 `run_phase`/`run_phase_sync` call sites in `orchestrator.py` pass `retry_config=config.retry`. The serialization/deserialization in `_save_run_log`/`_load_run_log` correctly handles `RetryInfo`. No call sites were missed.

---

## Synthesis

This is a well-architected feature that correctly identifies the abstraction boundary for transport-level retry (inside `run_phase()`, below the orchestrator's recovery system). The error detection is principled — structured attributes first, word-boundary regex fallback second. The backoff follows industry-standard full jitter. The `RetryConfig` follows existing codebase conventions. Test coverage is strong at 747 new lines.

The one finding I'd want addressed before merge is the **`resume` kwarg leak** — it's a latent bug that will surface specifically during the highest-value use case (daemon overnight runs with orchestrator recovery hitting API overload). The fix is a one-line change. The `_is_transient_error` triple-call is a code quality issue worth fixing but not a blocker.

Overall: solid systems engineering, correct failure-mode thinking, good observability via `RetryInfo`. Ship it after fixing the `resume` leak.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/agent.py:248]: HIGH — `resume` session ID leaks into retry attempts; after 529, retry should start from scratch with `resume=None`, not re-use a stale session
- [src/colonyos/agent.py:264-268]: MEDIUM — `_is_transient_error(exc)` called 3x on same exception; extract to local var
- [src/colonyos/config.py:22]: MEDIUM — `_SAFETY_CRITICAL_PHASES` uses raw strings instead of Phase enum values; fragile coupling
- [src/colonyos/agent.py:97]: MEDIUM — `_friendly_error` uses plain substring matching for "529" while `_is_transient_error` uses word-boundary regex; inconsistent detection
- [src/colonyos/agent.py:~325-330]: LOW — for/else/continue/continue pattern needs explanatory comment
- [tests/test_agent.py]: LOW — No test for resume + retry interaction

SYNTHESIS:
Well-layered transport-level retry that correctly sits below the orchestrator's recovery system. Architecture, backoff algorithm, error detection, config patterns, and test coverage are all strong. The `resume` kwarg leak is the critical finding — it creates a latent failure mode specifically in daemon/recovery scenarios where retry matters most. One-line fix, but it needs a fix and a regression test before merge. The triple `_is_transient_error` call and raw-string safety-critical phases are code quality issues worth addressing but not blockers.
