# Staff Security Engineer Review — Task-Level Retry for Auto-Recovery

**Branch**: `colonyos/recovery-b69f562da7`
**PRD**: `cOS_prds/20260402_022155_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Date**: 2026-04-02

## Checklist Assessment

### Completeness
- [x] **FR-1**: `max_task_retries: int = 1` added to `RecoveryConfig` dataclass and `DEFAULTS`
- [x] **FR-2**: `previous_error` parameter added to `_build_single_task_implement_prompt()` with truncation to `incident_char_cap`
- [x] **FR-3**: `_clean_working_tree()` helper implemented with `git checkout -- .` and `git clean -fd`
- [x] **FR-4**: Retry loop wraps task failure handling in `_run_sequential_implement()` with proper cascade
- [x] **FR-5**: Recovery events logged with `kind="task_retry"` including `task_id`, `attempt`, `error`, `success`
- [x] **FR-6**: `max_task_retries` parsed and validated in `_parse_recovery_config()` with non-negative floor
- [x] All tasks appear implemented — no placeholder or TODO code

### Quality
- [x] All 218 tests pass (including 22 new tests)
- [x] Code follows existing project conventions (same patterns as `max_phase_retries` validation, same `_record_recovery_event` call pattern)
- [x] No unnecessary dependencies added
- [x] No unrelated changes included
- [x] Existing tests updated correctly to set `max_task_retries=0` to preserve original behavior semantics

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive database operations
- [x] Error handling present — `_clean_working_tree` catches `OSError` and `TimeoutExpired` without raising

## Security-Specific Findings

### Error Message Injection into Prompts (Low-Medium Risk)

**[src/colonyos/orchestrator.py:733-740]**: Error messages from a failed task are injected directly into the retry prompt. The only sanitization is truncation to `incident_char_cap` (4000 chars). If a malicious instruction template or poisoned dependency causes a crafted error message, it could inject adversarial instructions into the retry prompt.

**Mitigations already present**:
- Truncation to 4000 chars bounds the attack surface
- The error is placed inside a fenced code block (`` ``` ``) which provides some semantic framing
- The error originates from `run_phase_sync` which is already a trusted execution boundary

**Assessment**: Acceptable for v1. The PRD explicitly acknowledged this tension and chose truncation over full sanitization. The error string comes from the same execution sandbox the agent already controls, so the incremental attack surface is minimal. Future hardening could add `sanitize_untrusted_content()` to the error string.

### `git checkout -- .` and `git clean -fd` (Accepted Risk)

**[src/colonyos/orchestrator.py:335-358]**: `_clean_working_tree()` runs destructive git commands. This is the correct approach per the PRD — successful tasks are already committed, so there's nothing to lose. The 30-second timeout prevents hangs.

**Positive**: The helper logs warnings on failure rather than silently swallowing errors, and it does NOT raise — preventing a cleanup failure from cascading into an unhandled exception during recovery.

### No Upper Bound on `max_task_retries` (Low Risk)

**[src/colonyos/config.py:790-793]**: Validation only checks `>= 0`, with no ceiling. The PRD's Open Question #1 flagged this — I recommended capping at 2. A misconfigured `max_task_retries=100` would burn budget on a genuinely broken task. However, the per-task budget cap limits the financial blast radius, and this matches the existing pattern for `max_phase_retries` which also has no ceiling.

### Recovery Event Logging (Good)

**[src/colonyos/orchestrator.py:954-962, 1061-1069]**: Task retry events are logged in both the exception path and the normal failure path with consistent field structure. This gives full observability — critical for auditing what the agent did during recovery.

### Safety Net for Untracked State (Good)

**[src/colonyos/orchestrator.py:1082-1084]**: The `if not task_succeeded and task_id not in failed` safety net after the retry loop exit catches edge cases where the loop might exit without properly categorizing the task. Defensive programming done right.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py:733-740]: Error messages injected into retry prompts are truncated but not sanitized via `sanitize_untrusted_content()`. Low incremental risk since errors originate from the same sandbox. Consider adding sanitization in a follow-up.
- [src/colonyos/config.py:790-793]: No upper-bound ceiling on `max_task_retries`. Recommend adding `min(max_task_retries, 3)` cap in a follow-up to prevent misconfiguration, per PRD Open Question #1.
- [src/colonyos/orchestrator.py:335-358]: `_clean_working_tree()` correctly handles failures gracefully with warnings rather than raising. Good defensive design.
- [tests/test_sequential_implement.py]: Comprehensive unit test coverage for all retry paths — success after retry, exhausted retries, clean tree invocation, error context propagation, recovery event logging, budget preservation, and `max_task_retries=0` disable path. Existing tests correctly updated to preserve original semantics.

SYNTHESIS:
This is a clean, well-scoped implementation that adds a meaningful recovery tier without introducing new security boundaries or expanding the agent's privilege surface. The changes are isolated to the sequential implement path as designed, and the code follows existing patterns faithfully. From a security perspective, the two items worth tracking for follow-up are (1) sanitizing error strings before prompt injection (low risk since the error source is already within the trusted execution boundary) and (2) adding an upper bound on `max_task_retries` to prevent misconfiguration. Neither is blocking. The test coverage is thorough and the defensive programming (safety net, graceful cleanup failures, timeout on git commands) demonstrates good security hygiene. Approve.
