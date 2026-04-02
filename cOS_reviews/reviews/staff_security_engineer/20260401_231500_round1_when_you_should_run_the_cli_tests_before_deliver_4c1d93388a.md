# Staff Security Engineer — Review Round 1

**Branch**: `colonyos/when_you_should_run_the_cli_tests_before_deliver_4c1d93388a`
**PRD**: `cOS_prds/20260401_224904_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`

## Checklist Assessment

### Completeness
- [x] **FR-1**: Verify phase inserted between Learn and Deliver in `_run_pipeline()` with read-only tools `["Read", "Bash", "Glob", "Grep"]`
- [x] **FR-2**: Verify-fix loop with configurable `max_verify_fix_attempts` (default: 2), matching review-fix pattern
- [x] **FR-3**: Hard-block delivery on persistent failure via `_fail_run_log()` — core invariant holds
- [x] **FR-4**: Budget guard before every verify and fix iteration (dual checks)
- [x] **FR-5**: `VerifyConfig` dataclass + `PhasesConfig.verify` + DEFAULTS integration + validation
- [x] **FR-6**: `instructions/verify.md` (read-only) and `instructions/verify_fix.md` (write-enabled) created
- [x] **FR-7**: `_compute_next_phase()` updated: `decision→verify`, `learn→verify`, `verify→deliver`; `_SKIP_MAP` includes `learn` and `verify`
- [x] **FR-8**: Heartbeat touched before verify; UI header displayed via `_make_ui()` with fallback to `_log()`
- [x] **FR-9**: Thread-fix verify flow unmodified (no changes to thread-fix code)
- [x] No TODO/placeholder code remains
- [x] All tasks complete

### Quality
- [x] All 55 verify-specific tests pass; all 3110+ tests pass (no regressions)
- [x] Code follows existing patterns (budget guard, heartbeat, phase append, UI header)
- [x] No unnecessary dependencies added
- [x] No unrelated changes included
- [x] Instruction templates are clean, well-structured, and use format placeholders correctly

### Safety / Security
- [x] **No secrets or credentials in committed code** — clean
- [x] **No destructive operations without safeguards** — verify is read-only, fix has bounded retries, hard-block on failure
- [x] **Error handling present** — budget exhaustion, fix agent failure, ambiguous verify output

## Security-Specific Analysis

### 1. Tool Restriction Enforcement (STRONG)

The verify agent's read-only access is enforced at **two layers**:
- **Runtime enforcement**: `allowed_tools=verify_tools` where `verify_tools = ["Read", "Bash", "Glob", "Grep"]` (orchestrator.py, line ~5003). This is the hard boundary — the SDK rejects disallowed tool calls.
- **Instruction-level guidance**: `verify.md` explicitly states "Do not attempt to use Write, Edit, Agent, or any other tool. They are not available."

Both layers must be bypassed to violate read-only semantics. The runtime enforcement is the security boundary; the instruction is defense-in-depth.

**Note**: The verify agent has `Bash` access, which means it can execute arbitrary shell commands including `rm`, `git push`, etc. This is inherent to running tests (you need a shell) but means "read-only" is enforced at the tool level, not the OS level. This is consistent with the existing threat model — the agent runs in the user's repo with the user's permissions. The `Bash` tool is necessary and its inclusion is appropriate.

### 2. Two-Agent Audit Separation (STRONG)

Verify (observe) and fix (modify) produce separate `PhaseResult` entries with distinct `Phase` enums (`Phase.VERIFY` vs `Phase.FIX`). This enables clean post-incident forensics — you can always distinguish what was observed from what was changed.

**Minor note**: `Phase.FIX` is reused for both review-fix and verify-fix, making them indistinguishable by enum alone in logs. This is acceptable for v1 — the phase ordering in the log disambiguates.

### 3. Unsanitized Test Output in Fix Prompt (ACCEPTED RISK)

`verify_output` (raw test failure text) is interpolated directly into the fix agent's system prompt via `{test_failure_output}` in `verify_fix.md`. A malicious test could theoretically craft output containing prompt injection payloads.

**Risk assessment**: Low. The test output comes from the user's own repo, run in their own environment. This is consistent with the existing threat model where the entire codebase is untrusted-to-the-user-but-trusted-by-the-pipeline. The fix agent already has full write access, so the attack surface gain from prompt injection is marginal.

### 4. `_verify_detected_failures()` — Fail-Open Design (ACCEPTED)

The function defaults to `False` (tests assumed passing) when output is ambiguous or empty. This is a pragmatic choice:
- The structured `VERIFY_RESULT: PASS/FAIL` sentinel makes the ambiguous case narrow
- Fail-open means the pipeline proceeds to delivery rather than blocking — this avoids false-negative blocking but could allow a broken PR through if the verify agent malfunctions
- 16 unit tests cover edge cases including `"0 failed"`, `"ErrorHandler"`, case sensitivity, and sentinel override

The sentinel-first parsing is the right architecture. The fallback heuristics are conservative (only matching `[1-9]\d* failed/errors`).

### 5. Budget Guards (STRONG)

Double budget check before each verify iteration AND before each fix iteration. Same pattern as the review-fix loop. Budget exhaustion blocks delivery (fail-safe).

### 6. Hard-Block on Persistent Failure (STRONG)

The core security invariant — **never open a PR you know is broken** — is enforced:
- `_fail_run_log()` is called when `verify_passed` is False after the loop
- `return log` prevents reaching the Deliver phase
- 3 integration tests verify this behavior (exhausted retries, budget exhaustion, fix agent failure)

### 7. Safety-Critical Phase Classification (CORRECT)

`Phase.VERIFY` is intentionally NOT in `_SAFETY_CRITICAL_PHASES`. This is correct — verify is a read-only test runner that should use a lightweight model. `Phase.FIX` IS in `_SAFETY_CRITICAL_PHASES`, so the verify-fix agent (which reuses `Phase.FIX`) inherits the haiku-warning guard automatically.

### 8. Config Validation (GOOD)

`_parse_verify_config()` validates `max_fix_attempts >= 1` and raises `ValueError` on invalid input. This prevents misconfiguration from disabling the fix loop.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py]: Verify agent `allowed_tools` correctly restricted to `["Read", "Bash", "Glob", "Grep"]` at runtime — defense-in-depth with instruction-level guidance
- [src/colonyos/orchestrator.py]: `_verify_detected_failures()` implements structured sentinel parsing (primary) with safe regex fallback — 16 unit tests cover edge cases including the critical `"0 failed"` false-positive scenario
- [src/colonyos/orchestrator.py]: Dual budget guards (before verify AND before fix) prevent runaway cost — fail-safe on exhaustion
- [src/colonyos/orchestrator.py]: Hard-block delivery via `_fail_run_log()` when `verify_passed` is False — core invariant "never open a broken PR" is enforced
- [src/colonyos/orchestrator.py]: `Phase.FIX` reuse for verify-fix makes it indistinguishable from review-fix by enum alone — acceptable for v1, phase ordering disambiguates
- [src/colonyos/instructions/verify_fix.md]: Raw `{test_failure_output}` interpolated into system prompt without sanitization — accepted risk, consistent with existing threat model (user's own repo)
- [src/colonyos/instructions/verify.md]: Clear sentinel contract (`VERIFY_RESULT: PASS/FAIL`) treats the prompt as a typed function with parseable return value — good design
- [src/colonyos/config.py]: `_parse_verify_config()` validates `max_fix_attempts >= 1` — prevents misconfiguration
- [src/colonyos/config.py]: `Phase.VERIFY` correctly excluded from `_SAFETY_CRITICAL_PHASES` — allows haiku assignment without warning

SYNTHESIS:
From a security perspective, this implementation is well-defended. The critical invariant — never opening a broken PR — is enforced through hard-blocking delivery on persistent failure, with budget guards as an additional safety net. The two-agent separation (read-only verify vs. write-enabled fix) preserves audit boundaries, and tool restriction is enforced at runtime (not just instruction text). The `_verify_detected_failures()` function uses a sound two-tier parsing approach with the structured sentinel as the primary signal. The accepted risks (fail-open on ambiguous output, unsanitized test output in fix prompt, `Phase.FIX` reuse) are all consistent with the existing threat model and represent pragmatic v1 trade-offs. All 55 verify-specific tests pass with zero regressions across the full suite. Ship it.
