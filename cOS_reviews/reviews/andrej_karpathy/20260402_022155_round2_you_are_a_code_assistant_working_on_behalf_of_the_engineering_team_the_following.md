# Review: Task-Level Retry for Auto-Recovery (Round 2)

**Reviewer**: Andrej Karpathy
**Branch**: `colonyos/recovery-b69f562da7`
**PRD**: `cOS_prds/20260402_022155_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Date**: 2026-04-02

## Checklist

### Completeness
- [x] FR-1: `max_task_retries: int = 1` added to `RecoveryConfig` dataclass
- [x] FR-2: `previous_error` parameter added to `_build_single_task_implement_prompt()` with `## Previous Attempt Failed` section
- [x] FR-3: `_clean_working_tree()` helper implemented with `git checkout -- .` and `git clean -fd`
- [x] FR-4: Retry loop wraps task failure handling in `_run_sequential_implement()`
- [x] FR-5: `task_retry` recovery events logged via `_record_recovery_event()`
- [x] FR-6: `max_task_retries` parsed and validated in `_parse_recovery_config()`
- [x] All tasks marked complete
- [x] No placeholder or TODO code remains

### Quality
- [x] All 218 tests pass (22 new + 196 existing)
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies added
- [x] No unrelated changes included
- [x] Previous round findings (dead test stub, safety-net `task_results` gap) fixed

### Safety
- [x] No secrets or credentials in committed code
- [x] Error handling present for failure cases
- [x] `_clean_working_tree()` handles OSError/TimeoutExpired gracefully

## Assessment

### What's right

**The prompt design is the highest-leverage intervention.** Injecting `previous_error` into a clearly delimited `## Previous Attempt Failed` section is exactly the right pattern. The model gets a structured signal — "here's what broke, fix it" — rather than blindly retrying with the same prompt. This is how you treat prompts as programs: the retry prompt is a *different program* than the first-attempt prompt, carrying strictly more information. The truncation to `incident_char_cap` is the right call — you don't want unbounded error strings competing for context window space with the actual task specification.

**The retry loop is mechanically simple.** A `for attempt in range(max_attempts)` with `continue` on retry and `break` on success. No state machines, no retry frameworks, no exponential backoff abstractions. This is correct — you're retrying a stochastic agent, not a flaky network call. The variance comes from the model sampling, not from transient infrastructure failures. One retry with better information is worth more than ten retries with the same prompt.

**The test philosophy is correct and battle-hardened.** After two prior implementation failures at the integration test stage, the team correctly pivoted to unit tests that mock `run_phase_sync` and test deterministic logic. This is the right lesson learned. You can't write reliable integration tests for stochastic LLM outputs. What you *can* test: git cleanup gets called, error gets injected, recovery events get logged, dependents unblock when retry succeeds, dependents stay blocked when retry fails. All covered.

**The fix iteration addressed both Round 1 findings cleanly.** The dead `TestCleanWorkingTree` stub was removed. The safety-net block now uses `task_results.setdefault()` to populate the failure entry without overwriting existing data.

### Minor observations (non-blocking)

1. **`_drain_injected_context()` inside the retry loop.** On retry, if the injection provider is destructive (queue-drain semantics), the retry prompt gets empty external context while the first attempt got the full context. This is cosmetic — the injected context is supplementary, and the `previous_error` is the important new signal. But worth noting for a future iteration where you might want to cache the injected context across attempts.

2. **Recovery event records `"success": False` for the trigger, not the outcome.** The `task_retry` event logged before the retry captures `"success": False` (the *triggering* failure), not whether the retry itself succeeded. To know if the retry worked, you'd need to look at the task's final status. This is a minor naming ambiguity — the field describes "did the attempt that triggered this retry succeed" rather than "did the retry succeed." Not blocking but could confuse someone reading the logs.

3. **No hard ceiling on `max_task_retries`.** The PRD's Open Question #1 asks about this. The current implementation validates `>= 0` but has no upper bound. A misconfigured value of 50 would burn budget retrying a genuinely broken task. The per-task budget cap limits financial blast radius, but wall-clock time is unbounded. Recommend capping at 3 in a follow-up.

4. **UI label on retry is nice.** The `(retry 1)` suffix in the phase header gives users immediate visibility into retry attempts. Good touch.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py]: `_drain_injected_context()` runs inside retry loop — destructive providers yield empty context on retry (cosmetic, non-blocking)
- [src/colonyos/orchestrator.py]: `task_retry` recovery event `"success": False` describes the triggering failure, not the retry outcome — minor naming ambiguity
- [src/colonyos/config.py]: No upper-bound ceiling on `max_task_retries` — recommend capping at 3 in follow-up
- [tests/test_sequential_implement.py]: All 22 new tests are well-structured, testing deterministic retry mechanics without stochastic LLM behavior

SYNTHESIS:
This is a clean, well-scoped implementation that does the single most important thing for retry success: giving the model structured error context. The prompt design is correct — the retry prompt is a strictly more informative program than the first attempt. The mechanical simplicity of the retry loop (plain for-loop, no abstractions) is a feature, not a bug. The test suite correctly tests deterministic logic and avoids the integration test trap that killed two prior attempts. Both Round 1 findings from Linus Torvalds have been addressed. Ship it.
