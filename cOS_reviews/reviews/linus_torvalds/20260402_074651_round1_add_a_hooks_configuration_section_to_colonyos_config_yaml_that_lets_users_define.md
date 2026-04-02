# Review by Linus Torvalds (Round 1)

Now I have the full picture. Let me write the review.

---

I've reviewed the entire implementation. Here's my assessment.

## Review

### Code Quality Assessment

The code is clean, well-structured, and follows the existing patterns in this codebase. The `HookRunner` is a proper standalone class — no tangled dependencies on the orchestrator internals. The config parsing follows the established `_parse_*_config` pattern to the letter. Good.

### Issues Found

**1. `_zip_results_with_configs` reaches into `HookRunner._hooks` (private attribute)**

`orchestrator.py:2291` — `hook_runner._hooks.get(event, [])`. This is the orchestrator reaching across the abstraction boundary and poking at `HookRunner`'s internals. The entire point of making `HookRunner` a standalone class was clean separation. The information about whether a hook is blocking is *already available* inside `HookRunner.run_hooks()` — it already stops on blocking failures. The orchestrator shouldn't need to re-derive this.

The `HookResult` dataclass should just carry a `blocking: bool` field copied from the `HookConfig`. Then `_run_hooks_at` doesn't need `_zip_results_with_configs` at all — it checks `result.blocking` directly. That eliminates the cross-module coupling *and* a helper function.

**2. FR-4 specifies three sanitization layers; implementation only applies two**

The PRD says: "Strips ANSI escapes via `sanitize_display_text()`, Redacts secrets via `sanitize_ci_logs()`, Strips XML tags via `sanitize_untrusted_content()`". The implementation applies `sanitize_display_text()` then `sanitize_ci_logs()` — it skips `sanitize_untrusted_content()` entirely. The docstring claims `sanitize_ci_logs()` "strips XML tags and redacts secrets" which is partially true, but `sanitize_untrusted_content()` has additional prompt injection defenses. This is a deliberate simplification that should be documented as such, or the third pass should be added. Not a showstopper since `sanitize_ci_logs` does strip XML, but the PRD explicitly calls for the triple layer.

**3. `_SCRUBBED_ENV_SUBSTRINGS` includes `"KEY"` — overly aggressive**

This will scrub `KEYBOARD_LAYOUT`, `COLORTERM` containing "key" variations, `XAUTHORITY` won't be hit but `SSH_KEY_PATH` will. The safelist (`_SAFE_ENV_EXACT`) is a bandaid — you'll play whack-a-mole as users report broken environments. The substring `"KEY"` should probably be `"_KEY"` or `"API_KEY"` to be more targeted, or at minimum the safelist needs to be more comprehensive.

**4. `post_review` hooks fire even when review is skipped**

Looking at orchestrator.py, `post_review` hooks fire unconditionally — they're placed after the review skip/disable check block. If review is disabled via `config.phases.review = False` or `"review" in skip_phases`, the pipeline still runs `post_review` hooks. That's semantically wrong. Same issue: `post_deliver` hooks fire even when `config.phases.deliver` is False.

**5. Return type annotation `str | None | object` is a code smell**

`_run_hooks_at` returns `str | None | object` — that's basically `object`, which tells you nothing. Use a proper discriminated union or a small result dataclass. The sentinel pattern is fine internally, but the type annotation should reflect the actual protocol.

**6. No nonce-tagged delimiters for injected output**

FR-2.7 specifies "wrap in nonce-tagged delimiters" for injected output. The implementation uses a static `## Hook Output` header. A deterministic delimiter is trivially forgeable by hook output. The PRD specifically calls this out because hook output is untrusted content being injected into agent prompts.

### What's Done Well

- `HookRunner` is fully standalone and testable — 26 tests with real subprocess execution. This is the right call.
- Config parsing validates event names, clamps timeouts, skips malformed entries — exactly the defensive coding you need for user-provided config.
- The `_in_failure_handler` recursion guard is simple and correct.
- Environment scrubbing inherits `os.environ` and strips secrets — pragmatic approach.
- 70 new tests total, all passing. No regressions from this branch (the 2 daemon test failures are pre-existing on main).
- Zero overhead when no hooks are configured (the `HookRunner` isn't even constructed).

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/orchestrator.py:2291]: `_zip_results_with_configs` accesses private `hook_runner._hooks` — break the abstraction. Add `blocking` field to `HookResult` instead.
- [src/colonyos/sanitize.py:218]: FR-4 specifies triple-layer sanitization (display_text → ci_logs → untrusted_content) but implementation only applies two passes, omitting `sanitize_untrusted_content()`.
- [src/colonyos/hooks.py:30-31]: `"KEY"` substring in `_SCRUBBED_ENV_SUBSTRINGS` is overly broad — will scrub legitimate env vars like `SSH_KEY_PATH`. Use `"_KEY"` or `"API_KEY"` pattern.
- [src/colonyos/orchestrator.py:5017-5019]: `post_review` hooks fire even when review phase is skipped/disabled — semantically incorrect.
- [src/colonyos/orchestrator.py:5089-5092]: `post_deliver` hooks fire even when deliver phase is disabled — same issue.
- [src/colonyos/orchestrator.py:2251]: Return type `str | None | object` is meaningless — use a proper discriminated type.
- [src/colonyos/orchestrator.py:2296]: Missing nonce-tagged delimiters for injected output per FR-2.7 — static `## Hook Output` header is trivially forgeable by untrusted hook output.

SYNTHESIS:
The architecture is sound — `HookRunner` as a standalone testable class was the right call, the config layer follows existing patterns perfectly, and the test coverage is serious (70 tests, real subprocesses). The code is clean and readable. But there are two categories of problems: first, abstraction leaks (`_hooks` access, missing `blocking` on `HookResult`) that create unnecessary coupling between modules; second, the security guardrails don't match the PRD spec — missing the third sanitization pass and missing nonce-tagged delimiters for prompt injection defense. The conditional hook firing bugs (post_review/post_deliver firing when phases are skipped) are logic errors that will bite users. None of these are hard to fix — they're mostly one-liner changes — but they need to be fixed before this ships.