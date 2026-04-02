# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

## Review Complete

Here's my assessment as **Principal Systems Engineer**:

---

VERDICT: **request-changes**

### Critical Finding

**`on_failure` hooks are not wired into the general pipeline failure path.** The `run_on_failure()` method is only invoked when a *hook itself* fails (inside `_hooks_at`). When a phase fails — the plan phase returns an error, implementation crashes, review loop exhausts retries — `_fail_run_log()` is called (~21 sites) but `on_failure` hooks never fire. User story 4 ("notified when a pipeline run fails") is broken for the most common failure scenarios.

### Other Key Findings

| Severity | File | Issue |
|----------|------|-------|
| **High** | `orchestrator.py` | `post_review` hook fires even when review is skipped (placed outside the skip guard), could incorrectly gate delivery |
| **Medium** | `orchestrator.py` | `_zip_results_with_configs` reaches into `hook_runner._hooks` (private attribute) — brittle coupling |
| **Medium** | `sanitize.py` | PRD specifies triple-pass sanitization (`sanitize_display_text` → `sanitize_ci_logs` → `sanitize_untrusted_content`); implementation omits the third pass |
| **Medium** | `hooks.py` | `text=True` means non-UTF8 output crashes the hook; `errors="replace"` would be more resilient |
| **Low** | `hooks.py` | Env scrubbing with substring matching ("KEY", "TOKEN") will silently break `docker push`, `npm publish` — scrubbed vars should be logged at DEBUG |
| **Low** | `cli.py` | `hooks test --all` stops on first blocking failure, defeating the purpose of a test command |

### What's Good

- `HookRunner` is cleanly isolated and independently testable — this was the right architectural call
- Config parsing follows existing `_parse_*_config()` patterns perfectly
- Secret scrubbing with safe-list is a pragmatic design
- 757 tests pass, 26 dedicated hook tests with real subprocess execution
- Recursion guard on `run_on_failure` prevents infinite loops
- Timeout clamping (1s floor, 600s cap) is well-implemented

### Recommendation

Fix the `on_failure` wiring (inject `hook_runner` into `_fail_run_log` or add a wrapper) and move `post_review` inside the review guard block before merge. The remaining items can be follow-ups.