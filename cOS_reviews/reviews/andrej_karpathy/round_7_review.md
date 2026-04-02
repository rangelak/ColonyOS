# Review: Pipeline Lifecycle Hooks — Round 7

**Reviewer**: Andrej Karpathy
**Branch**: `colonyos/recovery-24cd295dcb`
**Date**: 2026-04-02

## Checklist

### Completeness
- [x] All functional requirements from the PRD are implemented
- [x] All tasks in the task file are marked complete
- [x] No placeholder or TODO code remains

### Quality
- [x] All tests pass (771 across relevant test files)
- [x] No linter errors introduced
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies added
- [x] No unrelated changes included

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive database operations without safeguards
- [x] Error handling is present for failure cases

## Detailed Findings

### What's Excellent

1. **Standalone HookRunner architecture** — The previous attempt failed because integration tests mocked the full 700-line `_run_pipeline()`. This implementation learned the right lesson: `HookRunner` is fully testable in isolation with real subprocesses. The 540-line test file exercises real `subprocess.run` calls — no mock subprocess anywhere in `test_hooks.py`. This is the correct design for testing systems that shell out.

2. **Secret scrubbing precision** — The env scrubbing evolved through review rounds from an overly-aggressive `"KEY"` substring match to the current `"_KEY"` / `"API_KEY"` pattern with a `_SAFE_ENV_EXACT` allowlist. This is the right tradeoff: it catches `MY_API_KEY`, `AUTH_TOKEN`, `SSH_KEY_PATH` while preserving `KEYBOARD_LAYOUT`, `COLORTERM`. The test suite explicitly verifies both positive and negative cases.

3. **All previous review findings addressed**:
   - `post_review` hooks now correctly fire only inside the `elif config.phases.review:` block (line 5046)
   - `post_deliver` hooks correctly fire only inside the `if config.phases.deliver:` block (line 5118)
   - `_run_hooks_at` uses `result.blocking` field on `HookResult` instead of reaching into `hook_runner._hooks`
   - Public `get_hooks()` accessor added
   - Nonce-tagged `<hook_output nonce="...">` delimiters implemented with `secrets.token_hex(8)`
   - Aggregate cap (32KB) on `_hook_injected_text` prevents prompt bloat
   - Triple-layer sanitization in `sanitize_hook_output()`: display_text → ci_logs → untrusted_content
   - `_fail_pipeline()` wrapper runs `on_failure` hooks before persisting failure

4. **Zero-overhead when unconfigured** — `HookRunner` is only constructed when `config.hooks` is non-empty. The `_hooks_at()` closure short-circuits on `hook_runner is None`. No measurable overhead for the 99% of runs without hooks.

5. **Config parsing robustness** — Timeout clamping (1s min, 600s max), empty command skipping, non-dict entry handling, invalid event name validation with clear error messages. The round-trip save/load test confirms serialization fidelity.

### Minor Observations (Non-blocking)

1. **`shell=True` decision** — The PRD left this as an open question. The implementation chose `shell=True`, which is the pragmatic choice for a hooks system where users expect pipes and redirects. The security boundary is already defined by the PRD: "the user who writes the config owns the risk." Correct tradeoff for V1.

2. **Hook results not in RunLog** — PRD open question #2. Hook execution results are logged at INFO level but not persisted in the RunLog JSON. This is fine for V1 — adding structured `hook_results` to RunLog would be a natural follow-up for audit/debugging.

3. **No daemon-mode guardrail** — PRD open question #1 suggested `daemon.allow_hooks: true`. Not implemented. This is the right call for V1 — it would add config surface area for a concern that hasn't materialized yet. Can be added when daemon mode adoption grows.

4. **`_is_hook_blocking` in CLI** — The CLI test command uses a lookup function `_is_hook_blocking()` that matches by command string to determine if a failed hook was blocking. This could false-positive if two hooks have the same command string, but in practice this is a test/diagnostic command, not pipeline-critical code.

## Test Coverage Assessment

| Module | Tests | Coverage |
|--------|-------|----------|
| `hooks.py` (HookRunner) | 26 tests across 10 test classes | Comprehensive: success, blocking, timeout, inject_output, env vars, on_failure recursion, shell pipes, non-UTF8, edge cases |
| `config.py` (HookConfig) | 18 tests across 2 test classes | Full: defaults, parsing, validation, round-trip, error cases |
| `sanitize.py` (sanitize_hook_output) | 11 tests | All four passes verified independently and combined |
| `orchestrator.py` (wiring) | 5 tests | Phase boundary events, blocking failure, inject_output propagation, regression |
| `cli.py` (hooks test) | 5 tests | Valid event, invalid event, no hooks, --all flag, blocking failure exit code |

Total: ~65 new tests covering the hooks feature end-to-end.

## Verdict

This implementation is solid. The architecture is clean (standalone HookRunner, mock-at-the-seam orchestrator wiring), every PRD requirement is met, all previous review findings are resolved, and the test suite is thorough with real subprocess execution. The open questions from the PRD are correctly deferred to follow-up work rather than over-engineering V1.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/hooks.py]: Clean standalone design, fully testable in isolation. Secret scrubbing precision is correct after `_KEY` fix. `on_failure` recursion guard works correctly.
- [src/colonyos/orchestrator.py]: All 8 phase boundary hooks correctly wired. `post_review` inside review block, `post_deliver` inside deliver block. `_fail_pipeline()` correctly runs `on_failure` before persisting. Aggregate 32KB cap on injected text prevents prompt bloat. Nonce-tagged delimiters implemented.
- [src/colonyos/config.py]: HookConfig follows existing dataclass patterns. Parsing validates event names, clamps timeouts, skips empty commands. Round-trip serialization verified.
- [src/colonyos/sanitize.py]: `sanitize_hook_output()` applies all three sanitization layers plus byte-level truncation with safe multi-byte handling.
- [src/colonyos/cli.py]: `colonyos hooks test` command with `--all` flag, proper validation, and non-zero exit on blocking failure.
- [tests/]: 65 new tests with real subprocess execution in hooks tests. No mocked subprocesses where real execution matters.

SYNTHESIS:
This is a well-executed V1 of pipeline lifecycle hooks that correctly addresses the core user need — extensibility without code changes. The implementation learned from the previous attempt's failure (monolithic integration testing) and adopted the right pattern: standalone HookRunner testable in isolation, thin orchestrator wiring tested with targeted mocks. All PRD functional requirements (FR-1 through FR-5) are implemented. All findings from six previous review rounds are resolved. The security posture is appropriate — triple-layer output sanitization, secret scrubbing from the subprocess environment, 8KB per-hook and 32KB aggregate output caps, nonce-tagged injection delimiters, and on_failure recursion prevention. The three PRD open questions (daemon guardrail, RunLog persistence, shell mode) are correctly deferred rather than prematurely solved. 771 tests pass. Ship it.
