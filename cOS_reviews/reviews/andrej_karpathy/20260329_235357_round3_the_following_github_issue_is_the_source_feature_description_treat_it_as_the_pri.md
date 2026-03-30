# Review by Andrej Karpathy (Round 3)

Now I have a comprehensive view of the implementation. Let me write the review.

---

## Review — Andrej Karpathy (Round 3)

I've reviewed the full diff (1,872 lines added across 12 files), read the PRD, and verified that all 234 tests pass across `test_agent.py`, `test_config.py`, and `test_models.py`.

### Completeness Assessment

All 10 functional requirements are implemented:

| FR | Status | Notes |
|----|--------|-------|
| FR-1 | ✅ | `_friendly_error()` detects overloaded/529/503 via `_TRANSIENT_PATTERNS` regex |
| FR-2 | ✅ | `_is_transient_error()` checks `status_code` first, regex fallback second |
| FR-3 | ✅ | `run_phase()` wraps query in retry loop with restart-from-scratch |
| FR-4 | ✅ | Defaults: `max_attempts=3`, `base_delay=10.0`, `max_delay=120.0`, full jitter |
| FR-5 | ✅ | `RetryConfig` dataclass nested under `ColonyConfig.retry` |
| FR-6 | ✅ | `fallback_model` with two-pass retry structure |
| FR-7 | ✅ | Hard-blocked on `_SAFETY_CRITICAL_PHASES` using `Phase.XXX.value` |
| FR-8 | ✅ | Logs via `ui.on_text_delta()` or `_log()` with clear messages |
| FR-9 | ✅ | `RetryInfo` frozen dataclass on `PhaseResult`, serialized to RunLog |
| FR-10 | ✅ | Parallel phases retry independently via per-`run_phase()` loop |

### Architecture Assessment (Karpathy perspective)

The core design decision is correct and well-executed: **retry lives inside `run_phase()`, below the orchestrator's recovery system**. This is the right layer. 529 is a transport error, not a reasoning failure. The orchestrator should never see it, and it doesn't. The refactoring of `run_phase()` into `_run_phase_attempt()` + retry loop is clean — the attempt function handles streaming and exception capture, the outer function handles retry policy.

The two-pass structure for fallback (`passes: list[tuple[str | None, int]]`) is elegant. Each pass gets its own `max_attempts` budget, so the total can be `2 * max_attempts`. This is clearly documented in the docstring and tested.

The `_is_transient_error()` function correctly prioritizes structured attributes over string matching — this is the right hierarchy. The word-boundary regex patterns (`\b529\b`, `\b503\b`) are a good improvement over substring matching that could false-positive on port numbers or file paths. Tests explicitly verify that `localhost:5290` and `/error_503_report.txt` don't trigger false matches.

### Remaining Findings

All previous HIGH and MEDIUM findings from rounds 1-2 have been addressed:
- ✅ `resume` cleared to `None` after first transient error (tested by `test_resume_cleared_after_transient_error`)
- ✅ `_is_transient_error()` extracted to local `is_transient` boolean, called once
- ✅ `_SAFETY_CRITICAL_PHASES` uses `Phase.XXX.value` instead of raw strings
- ✅ `_friendly_error()` uses `_TRANSIENT_PATTERNS` regex instead of bare substring

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py:2441]: `RetryInfo(**p["retry_info"])` trusts run log JSON without field validation — a corrupted/tampered JSON could inject unexpected kwargs. LOW risk since this only reads local files written by the same process.
- [src/colonyos/agent.py:235-321]: The two-pass `for` loop with `break` to advance passes and `continue` for retries is correct but has high cognitive load for a function that's ~90 lines. A comment block at the top of the loop explaining the control flow would help future maintainers. This is style, not correctness.
- [src/colonyos/orchestrator.py]: `retry_config=config.retry` is threaded through 20+ call sites. This works but is mechanical plumbing. A future refactor could pass `config` directly or use a context variable. Acknowledged as tech debt, not a blocker.
- [tests/test_agent.py:659-669]: `test_529_substring_in_filepath_not_overloaded` has a comment explaining that standalone "529" in "line 529 of" *does* match, but the test doesn't actually assert anything about the result. The test body ends without an assertion. This is a documentation test, not a behavioral test — it's fine but could confuse future readers.

SYNTHESIS:
This is a well-executed transport-level retry layer that treats error classification with appropriate rigor. The key architectural decisions — retry below the orchestrator, structured attributes before string matching, safety-critical phase guard for fallback, restart-from-scratch semantics — are all correct. The implementation handles the LLM-specific concerns well: the `resume` session ID is properly cleared after transient errors (the session is dead, so passing it to a retry would be a subtle bug), and the fallback model guard correctly prevents quality-sensitive phases from downgrading to a weaker model. The test coverage is thorough — 55 new tests covering transient vs permanent classification, retry exhaustion, backoff ranges, fallback transitions, safety-critical blocking, UI logging, and resume clearing. All 234 tests pass. The remaining findings are LOW-severity polish items. Approved.