---

## Staff Security Engineer Review — Round 9 (Final)

**539 tests passing (test_hooks, test_config, test_sanitize, test_cli). 283 hooks+orchestrator tests passing. All PRD requirements implemented.**

### Security Checklist

| Area | Status | Notes |
|------|--------|-------|
| Env scrubbing: exact match | ✅ | `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `SLACK_BOT_TOKEN` |
| Env scrubbing: substring patterns | ✅ | `SECRET`, `_TOKEN`, `_KEY`, `PASSWORD`, `CREDENTIAL` — with safe-list bypass for `TERM_SESSION_ID`, `SSH_AUTH_SOCK`, `KEYCHAIN_PATH`, `TOKENIZERS_PARALLELISM`, `GPG_AGENT_INFO` |
| Env scrubbing: auditability | ✅ | DEBUG-level logging for substring-matched scrubs |
| Prompt injection defense | ✅ | Triple-layer sanitization + nonce-tagged XML delimiters |
| Output size caps | ✅ | 8KB per-hook + 32KB aggregate |
| Timeout enforcement | ✅ | `subprocess.run(timeout=...)`, clamped [1, 600] at config parse |
| on_failure recursion guard | ✅ | `_in_failure_handler` flag with try/finally cleanup |
| Single-owner failure dispatch | ✅ | `_fail_pipeline()` is sole on_failure hook invoker |
| No secrets in committed code | ✅ | Verified across all diffs |
| Config validation fail-fast | ✅ | Invalid event names → ValueError, empty commands → warning + skip |
| Non-UTF8 subprocess output | ✅ | `text=True, errors="replace"` handles gracefully |
| shell=True deliberate | ✅ | Per PRD — config author == repo owner trust boundary |

### Findings

1. **[src/colonyos/hooks.py]**: `shell=True` is deliberate per PRD design decision. The trust boundary is correct for V1: the person writing `.colonyos/config.yaml` is the repo owner. Recommend revisiting for daemon mode (PRD OQ#1).

2. **[src/colonyos/hooks.py]**: Env scrubbing uses a three-tier approach (exact → safe-list → substring) with DEBUG logging. The `_KEY` substring correctly catches `API_KEY`, `SSH_KEY_PATH`, etc. while the safe-list prevents false positives on `KEYCHAIN_PATH`. After round 8's fix removing redundant `"API_KEY"` from `_SCRUBBED_ENV_SUBSTRINGS`, the coverage is precise and minimal.

3. **[src/colonyos/hooks.py]**: No daemon-mode guardrail — recommend `daemon.allow_hooks: true` opt-in before broad daemon deployment (PRD OQ#1, non-blocking for V1).

4. **[src/colonyos/orchestrator.py]**: `_fail_pipeline()` is the sole owner of on_failure hook dispatch. The double-fire bug from round 6 is definitively resolved — `_hooks_at()` explicitly does NOT call `run_on_failure()`.

5. **[src/colonyos/orchestrator.py]**: Nonce-tagged delimiters (`secrets.token_hex(8)`) + 32KB aggregate cap + 8KB per-hook cap provide defense-in-depth against prompt injection via hook stdout and prompt bloat.

6. **[src/colonyos/orchestrator.py]**: Hook results are not persisted in RunLog — limits post-incident audit capability (PRD OQ#2, non-blocking for V1).

7. **[src/colonyos/sanitize.py]**: Four-pass sanitization pipeline (`sanitize_display_text` → `sanitize_ci_logs` → `sanitize_untrusted_content` → byte truncation) with safe multi-byte truncation via `errors="ignore"`.

8. **[src/colonyos/config.py]**: Strict validation — invalid event names fail-fast with `ValueError`, timeouts clamped to [1, 600], empty commands rejected with warnings. No YAML deserialization vulnerabilities — uses standard dict access patterns.

### Non-blocking Recommendations for V2

- Add `daemon.allow_hooks: true` gate before daemon mode goes wide
- Persist `HookResult` in RunLog for audit trail
- Consider `shell=False` + `shlex.split()` option for security-conscious users
- Add rate limiting / concurrency guard for rapid successive pipeline runs

VERDICT: approve

FINDINGS:
- [src/colonyos/hooks.py]: shell=True deliberate per PRD — config author == repo owner trust boundary is correct for V1
- [src/colonyos/hooks.py]: Env scrubbing correctly implemented with exact + substring + safe-list triple-check and DEBUG logging for scrubbed keys
- [src/colonyos/hooks.py]: No daemon-mode guardrail — recommend daemon.allow_hooks opt-in before broad daemon deployment (PRD OQ#1, non-blocking)
- [src/colonyos/orchestrator.py]: _fail_pipeline() is sole owner of on_failure dispatch — double-fire bug from round 6 is resolved
- [src/colonyos/orchestrator.py]: Nonce-tagged delimiters + 32KB aggregate cap + 8KB per-hook cap provide defense-in-depth against prompt injection and bloat
- [src/colonyos/orchestrator.py]: Hook results not persisted in RunLog — limits post-incident audit capability (PRD OQ#2, non-blocking)
- [src/colonyos/sanitize.py]: Four-pass sanitization pipeline with safe multi-byte truncation
- [src/colonyos/config.py]: Strict validation — invalid event names fail-fast with ValueError, timeouts clamped to [1, 600], empty commands rejected with warnings

SYNTHESIS:
This implementation is solid from a security engineering perspective and ready for merge. The security architecture follows defense-in-depth principles across every layer: environment variable scrubbing uses a three-tier check (exact match → safe-list bypass → substring match) with debug logging for auditability; injected output passes through four-pass sanitization before reaching agent prompts; nonce-tagged XML delimiters prevent delimiter-spoofing attacks; aggregate (32KB) and per-hook (8KB) byte caps prevent prompt bloat; and the on_failure recursion guard prevents infinite hook loops. The _fail_pipeline() refactor ensures on_failure hooks fire exactly once per failure, closing the double-fire bug from earlier rounds. The single deliberate risk — shell=True — is appropriate for V1 where config author == repo owner, but should be gated behind an opt-in flag before daemon mode (where external actors can trigger runs) goes wide.
