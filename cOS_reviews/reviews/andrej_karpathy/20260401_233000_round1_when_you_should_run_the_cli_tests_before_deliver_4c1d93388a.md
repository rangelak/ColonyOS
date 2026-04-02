# Review — Andrej Karpathy, Round 1

**Branch**: `colonyos/when_you_should_run_the_cli_tests_before_deliver_4c1d93388a`
**PRD**: `cOS_prds/20260401_224904_prd_...`

## Completeness

| Requirement | Status | Notes |
|---|---|---|
| FR-1: Verify phase in main pipeline | ✅ | Between Learn and Deliver, read-only tools enforced via `allowed_tools` |
| FR-2: Verify-fix loop | ✅ | Two-agent pattern, loops up to `max_fix_attempts` re-verifies |
| FR-3: Hard-block on persistent failure | ✅ | `_fail_run_log()` + early `return log` prevents Deliver |
| FR-4: Budget guard | ✅ | Dual guards — before verify AND before fix, matching review loop |
| FR-5: Config integration | ✅ | `VerifyConfig`, `PhasesConfig.verify`, DEFAULTS, `load_config`/`save_config` |
| FR-6: Instruction templates | ✅ | `verify.md` + `verify_fix.md` with structured sentinel |
| FR-7: Resume support | ✅ | `_compute_next_phase` routes `decision→verify`, `verify→deliver`; `_SKIP_MAP` updated |
| FR-8: Heartbeat + UI | ✅ | `_touch_heartbeat()` + `phase_header()` with `_log()` fallback |
| FR-9: Thread-fix unchanged | ✅ | No modifications to thread-fix flow |

All 9 functional requirements are implemented.

## Quality — Prompt Engineering Deep Dive

### The sentinel contract is the right design

`_verify_detected_failures()` parses `VERIFY_RESULT: PASS/FAIL` as the primary signal. This is exactly right — prompts are programs, and the verify prompt defines a typed return value. The regex fallback for non-zero failure counts (e.g. `3 failed`) is a sensible degradation path, and critically it **avoids false positives** on `0 failed` — a bug that would have silently blocked every passing run. The 16 unit tests covering edge cases (class names containing "error", zero counts, case sensitivity) demonstrate proper rigor.

### Instruction templates are well-structured

`verify.md` defines a clear 3-step contract: discover → run → emit sentinel. The constraints (no writes, no fixes, full suite) are stated as affirmative rules rather than buried in prose. `verify_fix.md` properly injects `{test_failure_output}` as structured context, giving the fix agent the full diagnostic picture rather than asking it to re-discover failures. Both templates follow the principle that prompts should be treated with the same rigor as code.

### Two-agent separation preserves auditability

The verify agent (read-only, `Phase.VERIFY`) and fix agent (write-enabled, `Phase.FIX`) produce separate `PhaseResult` entries in the run log. This is the correct architecture — you can always reconstruct what was observed vs. what was changed. The reuse of `Phase.FIX` for both review-fix and verify-fix is pragmatic; phase ordering in the log disambiguates them.

### Model selection: no haiku default (noted, acceptable)

The PRD suggests haiku for the verify agent since it's just running tests. The implementation uses `config.get_model(Phase.VERIFY)` which falls back to the global model (opus) since there's no phase-specific override. This is fine for v1 — the verify agent's work is cheap (mostly Bash calls), so the model overhead is small. Users who care can set `phase_models.verify: haiku` in config. Not blocking on this.

### Fail-open default is the right call

When the verify output is ambiguous (no sentinel, no recognizable pattern), `_verify_detected_failures()` returns `False` (tests passed). This is the correct default for an autonomous pipeline — fail-open avoids blocking delivery on a malformed agent response. The structured sentinel makes the ambiguous case narrow in practice.

## Test Coverage

- 222 verify-specific tests pass with zero regressions
- Integration tests cover: all-pass → deliver, persistent-fail → block, budget exhaustion → block
- Sentinel parsing has 16 unit tests covering edge cases
- Config roundtrip (load/save) tested
- Resume/skip mapping tested
- Safety-critical phase coverage verified (FIX is safety-critical → verify-fix inherits)

## Findings

- [src/colonyos/orchestrator.py]: `Phase.FIX` is reused for both review-fix and verify-fix. Enum alone can't distinguish them, but phase ordering in the run log disambiguates. Acceptable for v1, consider `Phase.VERIFY_FIX` if audit requirements increase.
- [src/colonyos/config.py]: No haiku default for `Phase.VERIFY`. PRD suggested it for cost savings. Users can override via `phase_models`. Non-blocking.
- [src/colonyos/orchestrator.py]: `_verify_detected_failures()` is fail-open on ambiguous output. Correct design choice given the structured sentinel contract makes this case narrow.

## Verdict

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py]: Phase.FIX reuse for verify-fix is pragmatic but limits audit granularity — acceptable for v1
- [src/colonyos/config.py]: No haiku default for Phase.VERIFY as PRD suggested — users can override, non-blocking
- [src/colonyos/orchestrator.py]: Fail-open on ambiguous verify output is correct given structured sentinel contract

SYNTHESIS:
This is a clean, well-engineered implementation that treats prompts as programs — exactly as they should be. The structured sentinel contract (`VERIFY_RESULT: PASS/FAIL`) with regex fallback is the right two-tier parsing strategy for building reliable systems on stochastic LLM outputs. The two-agent separation (observe vs. modify) preserves audit boundaries. The instruction templates are clear, constrained, and inject the right context. All 222 tests pass, config integration follows existing patterns, and the hard-block on persistent failure enforces the core invariant: never open a PR you know is broken. The minor gaps (no haiku default, Phase.FIX reuse) are non-blocking trade-offs that both previous reviewers correctly identified as acceptable. Ship it.
