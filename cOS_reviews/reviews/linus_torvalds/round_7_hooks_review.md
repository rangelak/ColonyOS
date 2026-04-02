# Review: Pipeline Lifecycle Hooks — Round 7

**Reviewer**: Linus Torvalds
**Branch**: `colonyos/recovery-24cd295dcb`
**Date**: 2026-04-02

## Assessment

### Completeness

- [x] FR-1: HookConfig data model with all fields, validation, parsing, serialization
- [x] FR-2: HookRunner execution engine — sequential, blocking/non-blocking, timeout, inject_output, on_failure recursion guard
- [x] FR-3: Orchestrator integration — all 9 events wired at correct phase boundaries
- [x] FR-4: Triple-layer sanitization with 8KB truncation
- [x] FR-5: CLI `hooks test <event>` with `--all` flag
- [x] `post_review` hooks only fire when review actually runs (inside `elif config.phases.review:`)
- [x] `post_deliver` hooks only fire when deliver is enabled (inside `if config.phases.deliver:`)
- [x] Nonce-tagged delimiters for injected output (FR-2.7)
- [x] Aggregate cap on injected text (32KB)
- [x] `blocking` field on `HookResult` — no more private `_hooks` access
- [x] `get_hooks()` public accessor on HookRunner

### Quality

- [x] 771 tests pass
- [x] No linter errors observed
- [x] Code follows existing project patterns (dataclass configs, `_parse_*` functions, mock-at-seam testing)
- [x] No unnecessary dependencies
- [x] No unrelated changes

### Safety

- [x] No secrets in committed code
- [x] Environment secret scrubbing with exact + substring matching
- [x] Error handling present throughout (timeout, subprocess failures, non-UTF8 output)

## Findings

### Bug: on_failure hooks fire twice on hook failures

**Severity**: Medium
**File**: `src/colonyos/orchestrator.py`, lines 4408-4416 and 4443-4454

When a blocking hook fails, `_hooks_at()` calls `hook_runner.run_on_failure()` at line 4416. Then the caller does `_fail_pipeline()` which calls `hook_runner.run_on_failure()` again at line 4453. The recursion guard doesn't help because `_in_failure_handler` is reset to `False` in the `finally` block after the first call completes.

The fix is simple: remove the `run_on_failure` call from `_hooks_at()`. Let `_fail_pipeline()` be the single point where on_failure hooks fire. That's what it exists for.

### Nit: `_run_hooks_at` return type is ugly

**File**: `src/colonyos/orchestrator.py`, line 2262

```python
def _run_hooks_at(...) -> str | None | object:
```

`str | None | object` — `object` subsumes everything, so this type annotation is meaningless to a type checker. You could use a proper result enum or a named sentinel with `typing.Final`, but honestly the sentinel pattern works fine at runtime. Just don't pretend the type annotation is doing anything useful. Either annotate it as `object` (honest) or create a tiny result type.

### Observation: env scrubbing safelist is maintenance debt

**File**: `src/colonyos/hooks.py`, lines 39-47

The `_SAFE_ENV_EXACT` safelist (5 entries) is a manually maintained exception list. Every new system tool that puts `_KEY` or `_TOKEN` in an env var name will get silently scrubbed until someone notices and adds an exemption. This is acceptable for V1 but will cause user confusion. Consider logging a DEBUG message when scrubbing non-exact-match keys so users can diagnose why their tools break.

### Observation: `_MAX_HOOK_INJECTION_BYTES` defined inside function body

**File**: `src/colonyos/orchestrator.py`, line 4432

The constant is defined after the function that uses it (`_hooks_at`). Python closures handle this fine, but it's odd style — define constants before the code that references them.

## VERDICT: request-changes

## FINDINGS:
- [src/colonyos/orchestrator.py]: on_failure hooks fire twice when a blocking hook fails — `_hooks_at()` calls `run_on_failure()`, then `_fail_pipeline()` calls it again. Remove the call from `_hooks_at()`.
- [src/colonyos/orchestrator.py]: `_run_hooks_at` return type `str | None | object` is meaningless — `object` is the supertype of everything.
- [src/colonyos/hooks.py]: env scrubbing safelist (`_SAFE_ENV_EXACT`) will silently break user toolchains as new env vars appear with `_KEY`/`_TOKEN` substrings. Consider logging scrubbed non-exact keys at DEBUG level.
- [src/colonyos/orchestrator.py]: `_MAX_HOOK_INJECTION_BYTES` constant defined after the closure that references it — unusual ordering.

## SYNTHESIS:
This is a solid, well-tested implementation. The architecture is right: standalone `HookRunner` testable in isolation, clean seam injection into the orchestrator via parameter passing, no massive mocking of 700-line functions. The test suite is thorough — 540 lines covering real subprocess execution, timeouts, encoding edge cases, and config round-trips. The previous review findings (post_review/post_deliver conditional placement, private attribute access, nonce-tagged delimiters, aggregate injection cap, env scrubbing precision) have all been addressed correctly. One real bug remains: on_failure hooks execute twice when a blocking hook triggers the failure path, because both `_hooks_at()` and `_fail_pipeline()` independently call `run_on_failure()`. It's a one-line fix — remove the call from `_hooks_at()` and let `_fail_pipeline()` be the single owner of failure hook execution. Fix that and this ships.
