# Review: Handle 529 Overloaded Errors with Retry — Round 2

**Reviewer**: Andrej Karpathy
**Date**: 2026-03-29
**Branch**: `colonyos/the_following_github_issue_is_the_source_feature_description_treat_it_as_the_pri`
**Tests**: 440 passed, 0 failed

## Checklist

### Completeness
- [x] FR-1: `_friendly_error()` detects "overloaded", "529", "503" patterns
- [x] FR-2: `_is_transient_error()` checks structured `status_code` first, regex fallback second
- [x] FR-3: `run_phase()` wraps query in retry loop with from-scratch restart
- [x] FR-4: Defaults: `max_attempts=3`, `base_delay=10.0`, `max_delay=120.0`, full jitter
- [x] FR-5: `RetryConfig` dataclass in `config.py`, nested under `ColonyConfig.retry`
- [x] FR-6: Optional `fallback_model` activates after retries exhausted
- [x] FR-7: Fallback hard-blocked on `_SAFETY_CRITICAL_PHASES` (review, decision, fix)
- [x] FR-8: Retry messages via `ui.on_text_delta()` or `_log()`
- [x] FR-9: `RetryInfo` frozen dataclass on `PhaseResult`, serialized in run logs
- [x] FR-10: Parallel phases retry independently (each has own `run_phase()` call)

### Quality
- [x] All 440 tests pass
- [x] Code follows existing conventions (`RetryConfig` mirrors `CIFixConfig`/`RecoveryConfig`)
- [x] No unnecessary dependencies (only `random`, `re` from stdlib)
- [x] `.colonyos/daemon_state.json` added to `.gitignore` (prior round finding fixed)
- [x] `_TRANSIENT_PATTERNS` hoisted to module-level constant (prior round finding fixed)
- [x] Word-boundary regexes prevent false positives (prior round finding fixed)
- [x] `RetryInfo` is frozen dataclass (prior round finding fixed)

### Safety
- [x] No secrets or credentials
- [x] Config validation: `max_attempts >= 1`, delays non-negative, model allowlist
- [x] Warning log for `max_attempts > 10`
- [x] Error messages use `_friendly_error()` — no raw API responses leaked

## Findings

### Minor (non-blocking)

1. **[src/colonyos/agent.py:264-268]: `_is_transient_error(exc)` called 3x on same exception.**
   Lines 264, 266, and 268 all call `_is_transient_error(exc)` — the function does regex matching on each call. Should extract to `is_transient = _is_transient_error(exc)` once. This is a hot path during error handling but not a correctness issue, just wasteful.

2. **[src/colonyos/agent.py:248]: `resume` kwarg leaks into retry attempts.**
   If `run_phase()` is called with `resume="some-session-id"` and the first attempt 529s, the retry will try to resume the same session. For the default case (`resume=None`) this is fine. For the explicit resume case, retrying with the same session ID is arguably correct (the session didn't consume), but it's worth a code comment clarifying intent. The PRD says "restart from scratch, not resume" — if that's literal, `resume` should be cleared to `None` on retry.

3. **[src/colonyos/config.py:22]: `_SAFETY_CRITICAL_PHASES` uses raw strings instead of `Phase.XXX.value`.**
   `frozenset({"review", "decision", "fix"})` — if someone renames a Phase enum value, this silently breaks. Using `frozenset({Phase.REVIEW.value, Phase.DECISION.value, Phase.FIX.value})` would create a compile-time coupling. However, importing `Phase` into `config.py` could create a circular dependency (`config.py` ← `models.py` ← `config.py`), so the raw strings may be intentional. Worth a comment.

4. **[src/colonyos/agent.py:94]: `_friendly_error()` uses substring match for "529" while `_is_transient_error()` uses word-boundary regex.**
   `_friendly_error()` checks `if "overloaded" in lower or "529" in lower` — this is the old-style substring matching that the regex patterns in `_is_transient_error()` were introduced to fix. Not a correctness bug (this just changes the human-readable message, not retry behavior), but inconsistent. The `_friendly_error()` path still has the false-positive risk, though the impact is only cosmetic.

5. **[src/colonyos/agent.py:235-321]: The two-pass fallback loop uses `for/else` with `continue`/`break` control flow that's hard to follow.**
   The `else` clause on the inner `for` loop (line 321) plus the two `continue` statements is correct but requires careful reading. This is the kind of control flow that's easy to break during future edits. The `_run_phase_attempt()` extraction from round 1 helped a lot, but the outer loop logic itself could benefit from a comment block explaining the `for/else` semantics.

## Synthesis

This is a well-executed transport-level retry layer. The architecture is right: retry lives inside `run_phase()`, invisible to the orchestrator's recovery system — 529s resolve transparently while the heavyweight nuke/diagnostic recovery only fires for genuine logic failures. This is exactly the right level of abstraction.

The error detection strategy is principled: structured `status_code` attribute first, word-boundary regex fallback second, with a clear code comment acknowledging the SDK workaround. The backoff follows AWS full jitter (`random.uniform(0, min(base * 2^(attempt-1), max_delay))`) — textbook. The `RetryInfo` frozen dataclass flowing into `PhaseResult` and serialized into run logs gives good post-hoc observability.

The fallback-as-two-pass-loop is elegant: same retry logic runs for both primary and fallback model with no code duplication. The safety-critical phase guard is a hard block, not a soft warning — correct for phases where model quality directly affects code safety.

All prior round findings (daemon_state.json, transient patterns allocation, word-boundary regexes, RetryInfo typing) have been addressed. The remaining findings are polish — repeated function calls, a potential resume-kwarg semantic question, raw strings vs enum values, and control flow readability. None are blockers.

Test coverage is thorough: 747 new lines covering transient detection (including false-positive guards), retry exhaustion, permanent error no-retry, fallback with safety-critical blocking, backoff range verification, and config validation. The 440-test suite passes clean.

**The implementation correctly treats prompts and error classification as programs that need rigor** — the structured-first, regex-fallback error detection, the frozen dataclass for retry metadata, and the explicit safety-critical phase guard all reflect engineering discipline appropriate for a system that runs autonomously with real money on the line.
