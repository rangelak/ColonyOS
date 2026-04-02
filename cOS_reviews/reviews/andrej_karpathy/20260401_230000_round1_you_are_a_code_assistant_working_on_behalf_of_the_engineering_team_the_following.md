# Review: Pre-Delivery Test Verification Phase — Round 1
**Reviewer**: Andrej Karpathy
**Branch**: `colonyos/when_you_should_run_the_cli_tests_before_deliver_4c1d93388a`

## Review Checklist

### Completeness
- [x] FR-1: Verify phase inserted between Learn and Deliver in `_run_pipeline()`
- [x] FR-2: Verify-fix loop with bounded retries (up to `max_verify_fix_attempts`)
- [x] FR-3: Hard-block delivery on persistent failure via `_fail_run_log()`
- [x] FR-4: Budget guard before each verify/fix iteration
- [x] FR-5: `VerifyConfig` dataclass, `PhasesConfig.verify`, DEFAULTS wired correctly
- [x] FR-6: `verify.md` and `verify_fix.md` instruction templates created
- [x] FR-7: `_compute_next_phase()` and `_SKIP_MAP` updated for verify
- [x] FR-8: Heartbeat touched, UI phase header displayed
- [x] FR-9: Thread-fix flow unchanged (confirmed no changes to that code)
- [x] All 6 task groups marked complete
- [x] No TODO/FIXME/placeholder code in new changes

### Quality
- [x] All 474 tests pass (0 failures)
- [x] No linter errors observed
- [x] Code follows existing project conventions (budget guard pattern, `_append_phase`, `_capture_phase_memory`, `_make_ui`)
- [x] No unnecessary dependencies added
- [x] No unrelated changes included

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive database operations
- [x] Error handling present (budget exhaustion, fix agent failure, config validation with `max_fix_attempts < 1`)

---

## Findings

### Critical: `_verify_detected_failures()` is a fragile heuristic classifier

**[src/colonyos/orchestrator.py]**: The `_verify_detected_failures()` function (lines 1700–1732) uses substring matching on the verify agent's natural language output to determine pass/fail. This is the most important function in the entire feature — it's the decision boundary between "open a PR" and "block delivery" — and it's implemented as a bag-of-words classifier with no structured output.

Specific failure modes:

1. **"error" matches "0 errors"**: If pytest outputs `"42 passed, 0 errors"`, the function finds "error" in `failure_patterns` and returns `True` (tests failed). This is a **false positive that blocks delivery on a clean test run**.

2. **"passed" is too generic**: The pass pattern `"passed"` will match any output containing that word, even mid-sentence descriptions of past failures. The priority logic (check pass first, then verify no failure words) partially mitigates this, but it's order-dependent and brittle.

3. **No structured output contract**: The verify agent's instruction template (`verify.md`) tells it to "report results" in natural language. There is no structured output format (e.g., `RESULT: PASS` / `RESULT: FAIL`) that the parser can reliably key on. This is the fundamental issue — we're treating a stochastic LLM output as a deterministic signal.

**Recommendation**: Add a structured output directive to `verify.md` (e.g., "End your response with exactly `VERIFY_RESULT: PASS` or `VERIFY_RESULT: FAIL`") and update `_verify_detected_failures()` to look for that sentinel first, falling back to the heuristic only if the sentinel is missing. This is the same pattern used for `_extract_verdict()` with `VERDICT: GO/NO-GO` — it already works well in this codebase.

### Minor: No default model override for verify phase

**[src/colonyos/orchestrator.py]**: The PRD (Technical Considerations → Model Selection) specifies that the verify agent should default to haiku since it's a read-only test runner that doesn't require frontier reasoning. The implementation uses `config.get_model(Phase.VERIFY)` which falls back to the global default model (typically opus). There's no `phase_models` default that maps `verify → haiku`.

This isn't a correctness issue — the pipeline works — but it means every verify run burns opus tokens on `pytest --tb=short -q`, which directly contradicts Goal 3 ("Minimal budget impact") and the persona consensus on model selection.

### Minor: Verify-fix reuses `Phase.FIX` enum

**[src/colonyos/orchestrator.py]**: The fix agent within the verify-fix loop uses `Phase.FIX` rather than a dedicated `Phase.VERIFY_FIX` enum. This means run logs cannot distinguish between review-fix iterations and verify-fix iterations. The PRD doesn't explicitly require a separate enum, and reusing `Phase.FIX` correctly inherits safety-critical phase protections, so this is acceptable for v1. Worth noting for future observability.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/orchestrator.py]: `_verify_detected_failures()` uses fragile substring matching — "error" matches "0 errors" causing false delivery blocks on clean runs. Add a structured output sentinel (e.g., `VERIFY_RESULT: PASS/FAIL`) to `verify.md` and parse that first, matching the `_extract_verdict()` pattern already used for decision gates.
- [src/colonyos/instructions/verify.md]: Missing structured output directive — the template asks for natural language reporting but provides no machine-parseable sentinel for the orchestrator to key on.
- [src/colonyos/orchestrator.py]: No default `phase_models` mapping for verify → haiku, contradicting PRD Goal 3 and Technical Considerations on model selection.

SYNTHESIS:
This is a solid, well-tested implementation that correctly follows existing codebase patterns. The verify-fix loop, budget guards, resume logic, and config integration are all done right. The test suite is comprehensive (552 new lines in `test_verify_phase.py` alone) and all 474 tests pass. However, there's one design flaw that I consider blocking: the function that decides whether to open a PR or block delivery is parsing free-form LLM output with substring matching. This is exactly the kind of place where you need structured output — the LLM is generating a program output that drives a control flow decision. The fix is small (add a sentinel to the prompt template, regex-match it first) and matches the `_extract_verdict()` pattern already in the codebase. The model selection issue is minor but worth fixing for cost reasons. Overall, this is 95% of the way there — just needs the structured output contract to be reliable in production.
