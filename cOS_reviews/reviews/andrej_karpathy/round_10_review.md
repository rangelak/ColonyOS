# Andrej Karpathy — Review Round 10

**Branch**: `colonyos/recovery-24cd295dcb`
**PRD**: Pipeline Lifecycle Hooks
**Tests**: 774 passed across all changed files (test_hooks, test_config, test_sanitize, test_orchestrator, test_cli)

---

## Checklist Assessment

### Completeness
- [x] **FR-1 (HookConfig data model)**: `HookConfig` dataclass with all 4 fields, `VALID_HOOK_EVENTS` with all 9 events, parsing via `_parse_hooks_config()`, serialization in `save_config()` — all implemented.
- [x] **FR-2 (Hook execution engine)**: Standalone `HookRunner` with `run_hooks()` and `run_on_failure()`. Sequential execution, env scrubbing, timeout enforcement, inject_output sanitization, blocking/non-blocking behavior, recursion guard — all present.
- [x] **FR-3 (Orchestrator integration)**: All 8 phase boundary hooks wired (`pre/post_plan`, `pre/post_implement`, `pre/post_review`, `pre/post_deliver`), `on_failure` via `_fail_pipeline()`, inject_output fed to next phase prompt, `HookRunner` passed as parameter.
- [x] **FR-4 (Sanitization)**: `sanitize_hook_output()` with 4-pass pipeline (display text → CI logs → untrusted content → byte truncation with safe multibyte handling).
- [x] **FR-5 (CLI test command)**: `colonyos hooks test <event>` with `--all` flag, real execution, result display, non-zero exit on blocking failure.
- [x] No TODO/placeholder code remains.

### Quality
- [x] 774 tests pass
- [x] Code follows existing `_parse_*_config()` and dataclass patterns
- [x] No unnecessary dependencies
- [x] No unrelated changes

### Safety
- [x] No secrets in committed code
- [x] Three-tier env scrubbing (exact → safe-list bypass → substring)
- [x] Error handling throughout (timeout, subprocess failure, recursion guard)

## AI Engineering Assessment

### What's done right — prompts are programs

The core design decision that matters most from an AI engineering perspective is the `inject_output` path. When you feed untrusted subprocess output into an LLM prompt, you're essentially writing a program that composes user-controlled strings into a structured input. This implementation treats that with appropriate rigor:

1. **Four-pass sanitization** before text enters the prompt: ANSI stripping → secret redaction → XML/injection defense → byte truncation. This is the right layering — each pass addresses a distinct attack surface.

2. **Nonce-tagged XML delimiters** (`<hook_output nonce="...">`) prevent a hook from spoofing the delimiter boundary. The nonce is `secrets.token_hex(8)` — unique per injection. This is a simple defense that blocks the most obvious delimiter-injection vector.

3. **Dual byte caps** — 8KB per-hook in `sanitize_hook_output()`, 32KB aggregate in `_hooks_at()`. This prevents a chatty hook from ballooning the prompt and degrading model performance. The aggregate cap is especially important because prompt length directly impacts latency, cost, and attention quality.

4. **`inject_output=False` by default**. This is critical. The dangerous path is opt-in, not opt-out. Most hooks (notifications, linting) don't need to feed output back into the model.

### Zero overhead when unconfigured

`hook_runner` is `None` when `config.hooks` is empty. The `_hooks_at()` closure early-returns `True` on `None`. This means the ~4800-line orchestrator pays zero runtime cost when hooks aren't configured. For a feature that most users won't use on day one, this is the right default.

### Single failure owner

The `_fail_pipeline()` closure is the sole call site for `on_failure` hook dispatch. Every `_fail_run_log()` call in the pipeline has been replaced with `_fail_pipeline()`. This eliminates the double-fire bug from earlier rounds and means there's exactly one code path to audit for failure-hook behavior. Clean.

### Recursion guard is correct

`run_on_failure()` uses `_in_failure_handler` with a `try/finally` to ensure the flag is always reset. This prevents infinite loops if an `on_failure` hook itself fails. The guard is instance-level (not global), which is correct for testability.

### Minor observations (non-blocking)

- **`shell=True`**: Deliberate per PRD — the config author is the repo owner. The alternative (`shlex.split`) breaks pipes, redirects, and env expansion that users expect from "shell command". Correct tradeoff for V1.
- **No RunLog persistence of HookResult**: Hook results are logged but not in the JSON run log. This limits post-incident debugging but is correctly deferred per PRD Open Question #2.
- **No daemon-mode guardrail**: When hooks run in daemon mode with Slack triggers, an external actor could indirectly trigger arbitrary shell commands. A `daemon.allow_hooks: true` opt-in would be prudent before broad daemon deployment. Correctly deferred per PRD Open Question #1.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/hooks.py]: inject_output sanitization pipeline correctly ordered — display strip before CI redaction before untrusted content defense before byte cap
- [src/colonyos/hooks.py]: Environment scrubbing three-tier check handles TERM_SESSION_ID/SSH_AUTH_SOCK edge cases via safe-list — prevents false positives without leaking secrets
- [src/colonyos/hooks.py]: `shell=True` is deliberate per PRD; config author == repo owner trust boundary is correct for V1
- [src/colonyos/orchestrator.py]: `_fail_pipeline()` is sole owner of on_failure dispatch — eliminates double-fire bug from earlier rounds
- [src/colonyos/orchestrator.py]: Nonce-tagged delimiters + dual byte caps (8KB per-hook, 32KB aggregate) provide defense-in-depth against prompt injection and prompt bloat
- [src/colonyos/orchestrator.py]: Hook results not persisted in RunLog — limits post-incident audit (PRD OQ#2, non-blocking V2 deferral)
- [src/colonyos/sanitize.py]: Safe multibyte truncation via `errors="ignore"` prevents mid-codepoint corruption in truncated output
- [src/colonyos/config.py]: Strict validation — invalid event names fail-fast with ValueError, timeouts clamped to [1, 600], empty commands warned and skipped
- [tests/test_hooks.py]: 577 lines of real-subprocess tests covering blocking, non-blocking, timeout, inject_output, env scrubbing, encoding edge cases, and config-to-runner roundtrip

SYNTHESIS:
This is a well-engineered feature that treats the LLM prompt as a program — exactly the right mental model. The inject_output path has the defense-in-depth I'd want to see before feeding untrusted subprocess output into model context: four-pass sanitization, nonce-tagged delimiters, and dual byte caps. The architecture makes the right zero-cost abstraction choice (None runner when unconfigured), maintains a single failure owner to prevent double-fire bugs, and ships with 65+ new tests that exercise real subprocesses rather than relying on brittle mocks. The three non-blocking observations (daemon guardrail, RunLog persistence, shell=True) are all correctly scoped as V2 deferrals per the PRD. Ready for merge.
