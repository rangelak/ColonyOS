# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 2)

## Review Complete — Principal Systems Engineer

**VERDICT: request-changes**

### Summary

The implementation is well-architected — retry sits correctly below the orchestrator's recovery system, backoff uses industry-standard full jitter, error detection is principled (structured attributes first, word-boundary regex fallback), and test coverage is strong (440 tests pass, 747 new test lines). All 10 functional requirements are implemented. The `RetryConfig` follows existing codebase conventions cleanly, and all 22 `run_phase` call sites in the orchestrator are plumbed correctly.

### Critical Finding

**`resume` session ID leaks into retry attempts** (`agent.py:248`): After a 529 error, the retry loop re-passes the original `resume` kwarg to `ClaudeAgentOptions`. But the PRD explicitly says "retry restarts the phase from scratch (not resume)." This creates a latent bug in exactly the scenario where retry matters most — daemon overnight runs with orchestrator recovery that then hit API overload. The fix is one line: only pass `resume` on the first attempt.

### Other Findings

| Severity | File | Issue |
|----------|------|-------|
| MEDIUM | `agent.py:264-268` | `_is_transient_error(exc)` called 3x on same exception — extract to local var |
| MEDIUM | `config.py:22` | `_SAFETY_CRITICAL_PHASES` uses raw strings instead of `Phase` enum values |
| MEDIUM | `agent.py:97` | `_friendly_error` uses plain substring matching while `_is_transient_error` uses word-boundary regex — inconsistent |
| LOW | `agent.py:~325` | `for/else/continue` pattern needs explanatory comment |
| LOW | `tests/test_agent.py` | No test for `resume` + retry interaction |

The full review artifact is at `cOS_reviews/reviews/principal_systems_engineer/20260329_235900_round1_handle_529_overloaded_errors_with_retry.md`.