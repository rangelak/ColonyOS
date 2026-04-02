# Review: Pipeline Lifecycle Hooks — Round 6

**Reviewer**: Andrej Karpathy
**Branch**: `colonyos/recovery-24cd295dcb`
**PRD**: `cOS_prds/20260402_071300_prd_add_a_hooks_configuration_section_to_colonyos_config_yaml_that_lets_users_define.md`

## Summary

This is a well-executed, cleanly structured feature addition. The `HookRunner` is properly standalone — fully testable in isolation with real subprocesses, which is exactly the right pattern for subprocess-heavy functionality. The previous attempt's failure at integration testing was correctly diagnosed and addressed: standalone engine + mock-at-the-seam for orchestrator wiring. 757 tests pass. The code follows existing conventions closely.

That said, I have a few concerns, one of which is a bug.

## Findings

### Bug: `post_review` hooks fire when review is skipped/disabled

`post_review` hooks (line 5020 of orchestrator.py) are **outside** the `if "review" in skip_phases` / `elif config.phases.review` conditional block, meaning they fire unconditionally — even when review is skipped or disabled. This is inconsistent with `pre_review` (which correctly fires only inside the review block) and could cause user confusion or unexpected blocking failures on a phase that never ran.

### Env scrubbing substring matching is overly aggressive

The `_SCRUBBED_ENV_SUBSTRINGS` include `"KEY"` which matches `KEYBOARD`, `KEYBOARD_LAYOUT`, `DONKEY_KONG`, etc. In practice on a real macOS system, this scrubs `STARSHIP_SESSION_KEY` (fine) but could surprise users with custom env vars. The safelist (`_SAFE_ENV_EXACT`) only covers 5 entries. Consider using `_KEY` / `_TOKEN` / `_SECRET` / `_PASSWORD` suffix patterns instead of substring matching, or expanding the safelist. Not a blocker, but a footgun for edge cases.

### Missing nonce-tagged delimiters for inject_output

PRD FR-2.7 specifies "wrap in nonce-tagged delimiters" for injected output. The implementation uses a fixed `## Hook Output` header in `_format_hook_injection()`. Without a random nonce, a sufficiently adversarial hook output (post-sanitization) could spoof the delimiter boundary. The triple-layer sanitization mitigates this significantly, but the nonce was a deliberate design decision from 7 persona agents. Low-risk gap, but worth noting.

### Private attribute access in `_zip_results_with_configs`

`_zip_results_with_configs` accesses `hook_runner._hooks` directly — a private attribute. This creates coupling and makes it harder to refactor `HookRunner` internals. A simple `get_hooks(event)` public method would be cleaner. Not a blocker.

### `text=True` in subprocess.run for non-UTF8 output

Using `text=True` with `subprocess.run` means non-UTF8 stdout causes `UnicodeDecodeError`, caught by the generic exception handler which returns `exit_code=-1`. This works but is silent — the user sees a failed hook with no useful error message. Consider using `encoding="utf-8", errors="replace"` instead, which would still capture partial output for debugging. The test covers this case, which is good.

### `shell=True` is the right call

The open question about `shell=True` vs `shell=False` was correctly resolved in favor of `shell=True`. Users defining shell commands in YAML expect pipes, redirects, and shell expansion to work. The user who writes the config owns the risk — this is exactly what the PRD's non-goals section says about sandboxing.

## What's Done Well

- **Standalone HookRunner**: Fully testable with real subprocesses, no orchestrator dependency. This is the correct architecture.
- **Recursion guard in `run_on_failure`**: The `_in_failure_handler` flag with `try/finally` cleanup is clean and prevents the most obvious failure mode.
- **Secret scrubbing**: The approach of inherit-and-strip (vs. allowlist) is pragmatic — allowlist breaks toolchains, full inherit leaks secrets. Good tradeoff.
- **Config parsing**: Follows the exact `_parse_*_config` pattern, with proper validation, clamping, and warnings.
- **Test coverage**: 26 tests for HookRunner alone covering success, blocking, timeout, inject_output, shell pipes, non-UTF8, on_failure recursion, and an end-to-end config→runner smoke test. This is thorough.
- **Zero overhead when unconfigured**: `hook_runner` is only constructed when `config.hooks` is non-empty.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/orchestrator.py:5020]: `post_review` hooks fire unconditionally, even when review phase is skipped or disabled — inconsistent with `pre_review` guard and likely a bug
- [src/colonyos/hooks.py:30-35]: `_SCRUBBED_ENV_SUBSTRINGS` substring matching for "KEY" is overly broad, scrubbing benign env vars like KEYBOARD_LAYOUT; consider suffix patterns `_KEY` instead
- [src/colonyos/orchestrator.py:_format_hook_injection]: Missing nonce-tagged delimiters per PRD FR-2.7; uses fixed `## Hook Output` header instead
- [src/colonyos/orchestrator.py:_zip_results_with_configs]: Accesses private `hook_runner._hooks` attribute; should use a public accessor
- [src/colonyos/hooks.py:199]: `text=True` in subprocess.run silently fails on non-UTF8 output with no useful error message to user

SYNTHESIS:
This is a solid implementation that learned the right lessons from the previous failure. The HookRunner is properly standalone and testable — the architecture is correct. The test suite is thorough with 757 tests passing. However, the `post_review` hook placement bug is a real issue that would cause hooks to fire for a phase that never ran, which violates user expectations and could cause blocking failures on phantom events. The env scrubbing aggressiveness and missing nonce-tagged delimiters are lower-priority but worth addressing. I'm requesting changes solely for the `post_review` placement bug — the rest are improvements that could be addressed in a follow-up, but that one needs to be fixed before merge.
