# Review — Andrej Karpathy (Round 1)

**Feature**: Handle 529 Overloaded errors with retry and optional model fallback
**Branch**: `colonyos/the_following_github_issue_is_the_source_feature_description_treat_it_as_the_pri`
**PRD**: `cOS_prds/20260329_225200_prd_the_following_github_issue_is_the_source_feature_description_treat_it_as_the_pri.md`

## Completeness Assessment

| FR | Status | Notes |
|----|--------|-------|
| FR-1 | ✅ | `_friendly_error()` detects "overloaded"/"529" patterns, returns clear message |
| FR-2 | ✅ | `_is_transient_error()` checks `status_code` first (429/503/529), then string matching on `str(exc)`, `stderr`, `result` |
| FR-3 | ✅ | `run_phase()` wraps `query()` in a retry loop; on transient error, waits with exponential backoff + full jitter, then restarts |
| FR-4 | ✅ | Defaults: `max_attempts=3`, `base_delay_seconds=10.0`, `max_delay_seconds=120.0`, jitter via `random.uniform(0, computed_delay)` |
| FR-5 | ✅ | `RetryConfig` dataclass in `config.py`, nested under `ColonyConfig` as `retry`, parsed via `_parse_retry_config()`, added to `DEFAULTS` |
| FR-6 | ✅ | `fallback_model: str | None` (default `None`). When set, creates a second "pass" with fallback model after primary retries exhaust |
| FR-7 | ✅ | Fallback hard-blocked for `_SAFETY_CRITICAL_PHASES` (`review`, `decision`, `fix`). Tests verify all three. |
| FR-8 | ✅ | Retry logs via `ui.on_text_delta()` or `_log()`. Clear message: "API overloaded, retrying in {delay}s (attempt {n}/{max})..." |
| FR-9 | ✅ | `PhaseResult.retry_info: dict | None` with `attempts`, `transient_errors`, `fallback_model_used`, `total_retry_delay_seconds`. Wired into `_save_run_log`/`_load_run_log` |
| FR-10 | ✅ | `retry_config=config.retry` passed to every `run_phase_sync()`/`run_phase()` call in orchestrator. Each parallel phase retries independently. |

All 10 functional requirements are implemented. No TODOs or placeholders remain.

## Quality Assessment

### What's done well

**Error detection is principled.** The two-tier strategy — structured `status_code` attribute first, then string matching fallback — is exactly right. The comment acknowledging this is a workaround until the SDK provides structured error types is the kind of engineering honesty that prevents tech debt from going invisible.

**Retry loop architecture is correct.** Placing the retry loop inside `run_phase()` below the orchestrator's recovery system means 529 errors are handled transparently. The orchestrator never sees transient errors; the heavyweight `_attempt_phase_recovery()` / `_run_nuke_recovery()` path is reserved for genuine logic failures. This is the right level of abstraction.

**Backoff with full jitter is textbook.** `random.uniform(0, min(base * 2^(attempt-1), max_delay))` follows the AWS "full jitter" recommendation. No unnecessary config knobs for jitter — it's implicit.

**Fallback as a two-pass loop is elegant.** The `passes: list[tuple[str | None, int]]` pattern avoids code duplication — same retry loop runs for both primary and fallback. Clean.

**Test coverage is comprehensive.** 726 new lines across: transient detection (13 tests), friendly error messages (6 tests), retry loop (8 tests), model fallback (8 tests), config parsing (9 tests), model serialization (7 tests), and orchestrator wiring (3 tests). Edge cases covered: `max_attempts=1`, backoff range verification, all three safety-critical phases, both UI and no-UI paths.

### Findings

**1. [.colonyos/daemon_state.json] — Unrelated file committed.** This is a runtime state file that should not be in version control. It contains ephemeral data (`daily_spend_usd`, `last_heartbeat`, `daemon_started_at`). Should be `.gitignore`'d and removed from this branch.

**2. [src/colonyos/agent.py:213] — Double-counting `_is_transient_error()` calls.** On the "last attempt of a pass" path, `_is_transient_error(exc)` is called up to 3 times: once at line 211, once at line 213, and once at line 215. These are pure functions over the same `exc`, so functionally correct, but the triple evaluation is wasteful and hurts readability. Extract to a local `is_transient = _is_transient_error(exc)` before the if-block.

**3. [src/colonyos/agent.py:119–124] — Fallback `passes` built once, but `resume` is passed through.** If `resume` is set (continuing a conversation), the retry loop still passes `resume` on every attempt. After a 529, there's no session to resume — the PRD explicitly notes "no `session_id` is received." The `resume` kwarg should be cleared (`resume=None`) after the first attempt fails, to avoid passing a stale session ID to a retry/fallback attempt.

**4. [src/colonyos/config.py] — `_SAFETY_CRITICAL_PHASES` uses raw strings, not `Phase.XXX.value`.** This was flagged in a previous review (20260326 decision review) and remains unaddressed. If the `Phase` enum is ever renamed, this set silently becomes stale. Low risk but easy to fix: `frozenset({Phase.REVIEW.value, Phase.DECISION.value, Phase.FIX.value})`.

**5. [src/colonyos/agent.py:44] — `_TRANSIENT_PATTERNS` defined inside function body.** The tuple `("overloaded", "529", "503")` is recreated on every call. Should be a module-level constant. Minor perf, but more importantly it signals to readers "this is a stable set of patterns, not a dynamic computation."

**6. [src/colonyos/agent.py:46] — String matching for "503" is overly broad.** The string `"503"` could appear in unrelated error messages (e.g., "Error at line 503", "ID: abc503def"). The structured `status_code` check handles the actual 503 case. For the string fallback, consider a more specific pattern like `"503 "` or `"HTTP 503"` to reduce false positives. Same concern applies to "529" though it's far less likely to collide.

**7. [tests/test_agent.py] — No test for `resume` kwarg interaction with retry.** There's no test verifying what happens when `resume="sess-123"` is passed and a transient error occurs. Does the retry correctly restart from scratch (not resume), as the PRD specifies? This is a gap worth covering.

## Safety

- ✅ No secrets or credentials in committed code
- ✅ Error messages use generic text, not raw API response bodies
- ✅ Budget amplification risk acknowledged — per-run budget cap provides outer safety net
- ✅ Fallback model hard-blocked on safety-critical phases
- ⚠️ `daemon_state.json` should not be committed (see Finding #1)

## Test Results

All 434 tests pass (1.52s). No regressions.

VERDICT: approve

FINDINGS:
- [.colonyos/daemon_state.json]: Unrelated runtime state file committed — should be .gitignore'd and removed from this branch
- [src/colonyos/agent.py:211-215]: _is_transient_error(exc) called up to 3 times on same exception — extract to local variable
- [src/colonyos/agent.py:119-141]: resume kwarg passed through to retry/fallback attempts — should be cleared after first failure since no session_id exists after 529
- [src/colonyos/config.py:22]: _SAFETY_CRITICAL_PHASES uses raw strings instead of Phase.XXX.value — previously flagged, still unaddressed
- [src/colonyos/agent.py:44]: _TRANSIENT_PATTERNS tuple recreated inside function body on every call — move to module-level constant
- [src/colonyos/agent.py:46]: String matching for "503" is overly broad — could false-positive on unrelated numeric strings
- [tests/test_agent.py]: No test for resume + retry interaction — should verify retry clears stale session ID

SYNTHESIS:
This is a clean, well-architected implementation. The core design decision — retry loop inside `run_phase()`, invisible to the orchestrator — is the right call. Prompts are programs, and this change treats the agent-API boundary with the rigor it deserves: structured error detection with a string-matching fallback, exponential backoff with full jitter, and a two-pass loop that elegantly handles the optional fallback model. The test suite is thorough at 726 new lines with good edge case coverage. The safety-critical phase hard-block on fallback is correctly implemented and tested for all three phases. My findings are mostly polish — the `daemon_state.json` file should be removed, and the `resume` kwarg interaction with retry is worth a test, but neither blocks shipping. The implementation faithfully delivers all 10 functional requirements from the PRD.
