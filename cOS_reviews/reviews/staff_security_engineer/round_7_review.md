# Staff Security Engineer Review — Round 7

**Branch:** `colonyos/recovery-24cd295dcb`
**PRD:** Pipeline Lifecycle Hooks
**Date:** 2026-04-02
**Test Results:** 771 passed

---

## Checklist Assessment

### Completeness
- [x] All functional requirements from the PRD are implemented (FR-1 through FR-5)
- [x] HookConfig data model with all fields (FR-1)
- [x] HookRunner with sequential execution, blocking/non-blocking, inject_output, timeout enforcement (FR-2)
- [x] Orchestrator wiring at all 9 lifecycle points including on_failure (FR-3)
- [x] Triple-layer sanitization: sanitize_display_text → sanitize_ci_logs → sanitize_untrusted_content (FR-4)
- [x] CLI `hooks test` command with `--all` flag (FR-5)
- [x] Nonce-tagged delimiters for inject_output (FR-2.7) — `secrets.token_hex(8)`
- [x] 32KB aggregate cap on concatenated hook injection text
- [x] on_failure recursion prevention via `_in_failure_handler` guard
- [x] `_fail_pipeline()` wrapper ensures on_failure hooks fire on all failure paths
- [x] `post_review` correctly inside `elif config.phases.review:` block
- [x] `post_deliver` correctly inside `if config.phases.deliver:` block
- [x] Public `get_hooks()` accessor — no private attribute access from orchestrator
- [x] `blocking` field on HookResult for clean failure detection

### Quality
- [x] All 771 tests pass
- [x] Code follows existing project conventions (dataclass pattern, `_parse_*` pattern, `_drain_*` pattern)
- [x] No unnecessary dependencies added
- [x] No unrelated changes included
- [x] 540 lines of hook-specific tests covering: blocking, non-blocking, timeout, inject_output, env scrubbing, on_failure recursion, shell pipes, non-UTF8 output, config round-trip

### Safety
- [x] No secrets or credentials in committed code
- [x] Environment variable scrubbing strips `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `SLACK_BOT_TOKEN`, `*SECRET*`, `*_TOKEN`, `*_KEY`, `*PASSWORD*`, `*CREDENTIAL*`
- [x] Safe-list for false positives: `TERM_SESSION_ID`, `SSH_AUTH_SOCK`, `KEYCHAIN_PATH`, `TOKENIZERS_PARALLELISM`, `GPG_AGENT_INFO`
- [x] 8KB per-hook output cap with `[truncated]` marker
- [x] 32KB aggregate injection cap with logged warning on discard
- [x] Timeout enforcement via `subprocess.run(timeout=...)` with 600s hard cap
- [x] Error handling present for: TimeoutExpired, unexpected exceptions in on_failure, mid-codepoint UTF-8 truncation

---

## Security-Specific Findings

### Addressed from Previous Rounds (all resolved)

| Finding | Status |
|---------|--------|
| post_review fires when review skipped | **Fixed** — inside `elif config.phases.review:` |
| post_deliver fires when deliver disabled | **Fixed** — inside `if config.phases.deliver:` |
| Private `_hooks` attribute access | **Fixed** — `blocking` field on HookResult + `get_hooks()` accessor |
| Missing triple-layer sanitization | **Fixed** — all three passes applied |
| `"KEY"` substring too aggressive | **Fixed** — changed to `"_KEY"` + safe-list |
| Missing nonce-tagged delimiters | **Fixed** — `secrets.token_hex(8)` per injection |
| No aggregate injection cap | **Fixed** — 32KB cap with discard logging |
| on_failure not wired to all failure paths | **Fixed** — `_fail_pipeline()` replaces all `_fail_run_log` calls |

### Remaining Security Notes (acceptable for V1, recommend fast-follow)

1. **`shell=True` by design**: Hooks execute with `shell=True`, which means shell metacharacters, pipes, and redirects are available. This is a deliberate design decision (PRD non-goals: "The user who writes the config owns the risk") and matches user expectations for "shell commands." The trust boundary is the committed `.colonyos/config.yaml` — same as any other code in the repo.

2. **No daemon-mode guardrail** (PRD Open Question #1): In daemon mode with Slack triggers, external actors can trigger pipeline runs that execute hooks. Recommend shipping a `daemon.allow_hooks: true` opt-in in a fast-follow before broad daemon adoption.

3. **Hook results not persisted in RunLog** (PRD Open Question #2): No audit trail of which hooks ran, their exit codes, or output. For post-incident forensics this is a gap. Recommend adding `hook_results: list[dict]` to RunLog in a fast-follow.

4. **Env scrubbing safe-list is static**: The `_SAFE_ENV_EXACT` set handles known false positives, but users with custom env vars matching `_KEY`/`_TOKEN` patterns have no override mechanism. Low priority — users can work around by referencing values from files in their hook scripts.

---

## VERDICT: approve

## FINDINGS:
- [src/colonyos/hooks.py]: `shell=True` is used for hook execution — deliberate design choice per PRD, acceptable for V1 where config author == repo owner
- [src/colonyos/hooks.py]: No daemon-mode guardrail for hook execution — recommend `daemon.allow_hooks` opt-in before broad daemon deployment (PRD Open Question #1)
- [src/colonyos/orchestrator.py]: Hook execution results not persisted in RunLog — limits post-incident audit capability (PRD Open Question #2)
- [src/colonyos/hooks.py]: `_SAFE_ENV_EXACT` safe-list is static with no user-configurable override — low priority, workaround available

## SYNTHESIS:
This implementation is solid from a security engineering perspective. All critical findings from the previous six review rounds have been addressed: on_failure hooks now fire on every failure path via `_fail_pipeline()`, post_review/post_deliver hooks are correctly gated behind their phase conditionals, the nonce-tagged XML delimiters prevent delimiter spoofing, the 32KB aggregate cap prevents prompt bloat attacks, and the triple-layer sanitization pipeline (display → CI logs → untrusted content) provides defense-in-depth against prompt injection from hook output. The env scrubbing approach — inherit-and-strip with explicit safe-listing — is the right pragmatic tradeoff between security and usability. The three remaining items (daemon guardrail, RunLog persistence, safe-list configurability) are all acknowledged as open questions in the PRD and are appropriate for fast-follow iterations rather than blocking the initial merge. The 771 passing tests with 540 lines of hook-specific coverage give confidence in the implementation's correctness. Approve for merge.
