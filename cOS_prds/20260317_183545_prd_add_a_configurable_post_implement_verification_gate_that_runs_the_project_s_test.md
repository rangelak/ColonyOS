# PRD: Post-Implement Verification Gate

## 1. Introduction / Overview

ColonyOS's pipeline currently flows **Plan → Implement → Review/Fix → Deliver**. When the implement phase produces code with basic test failures (import errors, syntax issues, trivial regressions), the expensive review phase still fires — launching parallel LLM reviewer agents at `$5–10/phase` each, plus fix iterations and a decision gate. This wastes significant budget on code that a `$0` subprocess call could have caught.

This feature adds a **configurable verification gate** between implement and review. After the implement phase succeeds, a user-specified test command (e.g., `pytest`, `npm test`) runs via `subprocess`. If the tests fail, the implement phase is retried with the failure output as context — up to a configurable number of retries. This creates a fast, cheap inner loop (**implement → verify → retry**) that catches deterministic failures before entering the expensive, stochastic outer loop (**review → fix → re-review**).

When no `verify_command` is configured, the gate is skipped entirely, preserving 100% backward compatibility.

## 2. Goals

1. **Reduce wasted review budget** by catching basic test failures before they reach parallel LLM reviewers.
2. **Improve implementation quality** by giving the implement agent targeted, deterministic feedback (test output) instead of relying solely on stochastic code review.
3. **Maintain backward compatibility** — no behavior change for users who don't configure `verify_command`.
4. **Keep the gate cheap** — verification is a raw subprocess ($0 LLM cost); only retries of the implement phase incur LLM spend.
5. **Integrate into `colonyos init`** so new users discover the feature during onboarding.

## 3. User Stories

- **As a developer**, I want ColonyOS to run my test suite after implementation so that obvious failures are caught before expensive reviews.
- **As a developer**, I want failed test output fed back to the implement agent automatically so that it can fix the issue without manual intervention.
- **As a developer**, I want to configure the retry limit so I can control how much budget is spent on automatic fix attempts.
- **As a new user running `colonyos init`**, I want to be asked about my test command so the verification gate is configured from the start.
- **As a developer using `colonyos init --quick`**, I want test runner auto-detection so verification is configured without manual input.

## 4. Functional Requirements

### 4.1 Configuration

| # | Requirement |
|---|-------------|
| FR-1 | Add a `verification:` section to `.colonyos/config.yaml` with two fields: `verify_command` (string, default: `null`) and `max_verify_retries` (int, default: `2`). |
| FR-2 | Add `verify_timeout` (int, seconds, default: `300`) to the `verification:` section. |
| FR-3 | When `verify_command` is `null` or empty string, the verification gate is skipped entirely. |
| FR-4 | Add a `VerificationConfig` dataclass in `config.py` and a `verification` field on `ColonyConfig`. |
| FR-5 | Update `load_config()` and `save_config()` to round-trip the `verification:` YAML section. |

### 4.2 Phase Enum & Run Log

| # | Requirement |
|---|-------------|
| FR-6 | Add `VERIFY = "verify"` to the `Phase` enum in `models.py`. |
| FR-7 | Each verification attempt is recorded as a `PhaseResult` with `phase=Phase.VERIFY`, `cost_usd=0.0`, and the test command's exit code and truncated output stored in `artifacts`. |
| FR-8 | Implement retries triggered by verification failures are recorded as normal `Phase.IMPLEMENT` entries in `log.phases`. |

### 4.3 Verification Execution

| # | Requirement |
|---|-------------|
| FR-9 | After the implement phase succeeds, if `verify_command` is configured, run it via `subprocess.run(cmd, shell=True, capture_output=True, cwd=repo_root, timeout=verify_timeout)`. |
| FR-10 | If exit code is `0`, proceed to the review phase. |
| FR-11 | If exit code is non-zero, enter the retry loop. |
| FR-12 | If the subprocess times out (`subprocess.TimeoutExpired`), treat it as a verification failure. |

### 4.4 Implement Retry with Failure Context

| # | Requirement |
|---|-------------|
| FR-13 | When verification fails, create a new implement phase prompt that includes: (a) the original PRD and task list references, (b) the full test failure output (truncated to last 4000 chars), and (c) explicit instructions to fix the failing tests on the existing branch without rewriting from scratch. |
| FR-14 | Create a new instruction template `src/colonyos/instructions/verify_fix.md` for the retry prompt. |
| FR-15 | The retry implement phase uses `per_phase` budget and is invoked via `run_phase_sync(Phase.IMPLEMENT, ...)`. |

### 4.5 Retry Budget Enforcement

| # | Requirement |
|---|-------------|
| FR-16 | Retries are capped by `max_verify_retries` (default: 2). After exhausting retries, proceed to review regardless. |
| FR-17 | Before each implement retry, check if `per_run` budget would be exceeded. If so, stop retrying and proceed to review. |
| FR-18 | Verify subprocess runs (`cost_usd=0.0`) do not count against the dollar budget. Only implement retries count. |

### 4.6 Pipeline Integration

| # | Requirement |
|---|-------------|
| FR-19 | Wire the verification gate into `orchestrator.run()` between the implement phase (line ~1161) and the review/fix loop (line ~1162). |
| FR-20 | The pipeline flow becomes: Plan → Implement → **Verify (retry loop)** → Review/Fix → Decision → Deliver. |
| FR-21 | Update `_compute_next_phase()` to map `"implement"` → `"verify"` (when verify is configured) and `"verify"` → `"review"`. |
| FR-22 | Update `_SKIP_MAP` to include `"verify": {"plan", "implement"}` so resume re-runs verification (which is free). |

### 4.7 CLI Output

| # | Requirement |
|---|-------------|
| FR-23 | Show a "Verify" phase header via `PhaseUI.phase_header()` with the test command being run. |
| FR-24 | On success: show green checkmark with "Tests passed". |
| FR-25 | On failure: show truncated error output and "Retrying implement (attempt N/M)..." message. |
| FR-26 | On timeout: show "Verify command timed out after N seconds". |

### 4.8 `colonyos init` Integration

| # | Requirement |
|---|-------------|
| FR-27 | In interactive mode, after budget prompts, ask: "What command runs your test suite? (leave blank to skip)". Save to `verification.verify_command`. |
| FR-28 | In `--quick` mode, auto-detect test runner by checking (in priority order): `Makefile` with `test` target, `package.json` with `test` script, `pytest.ini` / `pyproject.toml` with `[tool.pytest]`, `Cargo.toml`. |
| FR-29 | If no test runner is detected in quick mode, skip verification (set `verify_command` to `null`). |

## 5. Non-Goals

- **Multiple command support** — Users can chain commands with `&&` in the single string field. A list-of-commands abstraction is not needed for v1.
- **Configurable truncation limit** — 4000 chars is hardcoded for v1; can be promoted to config later if needed.
- **Sandboxing the verify command** — The tool already runs Claude Code with `permission_mode="bypassPermissions"` (agent.py line 52), so sandboxing a user-specified test command would be security theater.
- **Running verification through the Claude agent** — The entire value is that subprocess is free and fast. Agent-mediated verification defeats the purpose.
- **Injecting retry history into reviewer prompts** — Reviewers should judge final code on its merits. Retry history is logged for operators, not reviewers.
- **Lint-specific or multi-stage verification** — Out of scope; users compose via shell.

## 6. Technical Considerations

### 6.1 Architecture Fit

The verification gate follows existing patterns:
- **Subprocess usage**: `orchestrator.py` already uses `subprocess.run()` for git operations (`detect_base_branch`, `validate_review_preconditions`, `_validate_branch_exists`). The verify command follows the same pattern.
- **Config dataclass pattern**: `VerificationConfig` follows `BudgetConfig` and `PhasesConfig` — a frozen dataclass nested inside `ColonyConfig`.
- **Instruction template pattern**: `verify_fix.md` follows the existing `fix.md` template structure — loaded by `_load_instruction()` and formatted with config values.
- **Budget guard pattern**: The budget check before retries mirrors the guard in `run_review_loop()` at line 266-275.

### 6.2 Key Files to Modify

| File | Change |
|------|--------|
| `src/colonyos/models.py` | Add `Phase.VERIFY` to enum |
| `src/colonyos/config.py` | Add `VerificationConfig` dataclass, update `ColonyConfig`, `load_config()`, `save_config()`, `DEFAULTS` |
| `src/colonyos/orchestrator.py` | Add `run_verify_loop()`, wire into `run()`, update `_compute_next_phase()`, `_SKIP_MAP`, add `_build_verify_fix_prompt()` |
| `src/colonyos/init.py` | Add test command prompt (interactive), auto-detection (quick mode) |
| `src/colonyos/ui.py` | No changes needed — existing `phase_header()`, `phase_complete()`, `phase_error()` are sufficient |
| `src/colonyos/instructions/verify_fix.md` | New file — retry prompt template |

### 6.3 Failure Output Handling

Test output is truncated to the **last 4000 characters** (tail), because test runners put summaries and assertion errors at the end. The truncated output is stored in `PhaseResult.artifacts["test_output"]` for audit trail and injected into the retry prompt.

### 6.4 Timeout

The verify command has a default 300-second timeout. `subprocess.TimeoutExpired` is caught and treated as a verification failure. The timeout message is included in the retry prompt context so the implement agent knows to look for infinite loops or hanging fixtures.

### 6.5 Resume Semantics

When resuming a failed run where the last successful phase was `implement`, the orchestrator re-enters the verify loop (since verification is free). If `verify_command` is not configured, resume falls through to review as before.

## 7. Persona Synthesis

### Areas of Strong Agreement (All 7 Personas)

- **Subprocess, not agent**: Unanimous that verification must be a raw subprocess call, not routed through the Claude agent. The zero-cost property is the entire value proposition.
- **Single string command**: All agree a single string field is sufficient; users can chain with `&&` or point to a script.
- **Truncate from bottom (tail)**: Unanimous that test summaries appear at the end of output.
- **Don't sandbox**: All agree that sandboxing is security theater given the agent already has unrestricted shell access.
- **Re-run verify on resume**: All agree resume should re-run the free subprocess rather than re-running the expensive implement phase.
- **Timeout is mandatory**: All agree on a ~300s default timeout to prevent pipeline hangs.

### Areas of Tension

- **Budget accounting for verify runs**: Most say log with `cost_usd=0` but don't count against budget. The security engineer emphasized the retry *count* cap is more important than dollar tracking for verification.
- **Retry history visibility to reviewers**: Split between "never inject into reviewer prompts" (Steve Jobs, Karpathy, Linus) and "include a brief summary" (Jony Ive). **Resolution**: Log in `RunLog` for operators; keep out of reviewer prompts.
- **Auto-detection priority**: Minor disagreement on ordering. **Resolution**: `Makefile` test target → `package.json` test script → `pytest` → `cargo test` → `go test`. Most specific/intentional wins.
- **Truncation configurability**: Security engineer suggested a hard ceiling (16K max) even if made configurable, to prevent prompt injection via crafted test output. **Resolution**: Hardcode 4000 for v1, consider configurable with ceiling later.
- **Timeout configurability**: Split between hardcoded 300s (YC, Linus) and configurable with default (Systems Engineer, Security, Karpathy). **Resolution**: Make configurable via `verify_timeout` since test suite duration varies legitimately.

## 8. Success Metrics

1. **Budget saved**: Measure `(review_cost_without_verify - review_cost_with_verify)` across runs. Target: 30%+ reduction in wasted review spend on runs where tests initially fail.
2. **Verification pass rate**: Track what percentage of implement phases pass verification on first attempt vs. after retries. Baseline to measure agent implementation quality over time.
3. **Retry effectiveness**: Of runs that enter the retry loop, what percentage eventually pass verification? Target: >60%.
4. **No regressions**: All existing tests continue to pass. Runs without `verify_command` configured behave identically to current behavior.

## 9. Open Questions

1. **Should the verify phase be skippable via `phases:` config?** Currently `PhasesConfig` has boolean toggles for plan/implement/review/deliver. Should we add `verify: true`? Or is `verify_command: null` sufficient as the disable mechanism?
2. **Should we support `verify_command` as a CLI flag override?** e.g., `colonyos run "..." --verify-command "pytest -x"` for one-off overrides without editing config.
3. **Should retry attempts use a different (cheaper) model?** e.g., if the main implement uses `opus`, retries could use `sonnet` to save budget on fix-up work.
