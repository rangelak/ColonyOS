# Review by Staff Security Engineer (Round 1)

I now have a comprehensive view of the implementation. Let me write the review output directly — I've read all the changed files, the PRD, checked tests (434 passed), and assessed security concerns.

---

## Staff Security Engineer Review

### Checklist Assessment

**Completeness**
- [x] All 10 functional requirements (FR-1 through FR-10) are implemented
- [x] All tasks in the task file are marked complete
- [x] No placeholder or TODO code remains (only a design-note code comment about SDK structured errors, which is appropriate)

**Quality**
- [x] All 434 tests pass (including 729 new lines of test code)
- [x] Code follows existing project conventions (`RetryConfig` follows `CIFixConfig`/`RecoveryConfig` pattern)
- [x] No unnecessary dependencies added (`random` is stdlib)
- [ ] **Unrelated file committed**: `.colonyos/daemon_state.json` — see finding below

**Safety**
- [x] No secrets or credentials in committed code
- [x] No destructive operations without safeguards
- [x] Error handling present for all failure cases
- [x] Input validation on config values (`max_attempts >= 1`, delays non-negative, model allowlist)

### Security-Specific Findings

**1. [.colonyos/daemon_state.json]: Runtime state file committed to the repository.**
This file contains ephemeral daemon state (`daily_spend_usd`, `daemon_started_at`, `last_heartbeat`, timestamps). It should NOT be tracked in git — it's runtime state, not configuration. It's already not in `.gitignore` (only `runs/`, `queue.json`, and `memory.db` are excluded). This is a **data leak vector**: in a shared repo, daemon state from one operator leaks to all collaborators. Add `.colonyos/daemon_state.json` to `.gitignore` and remove it from tracking.

**2. [src/colonyos/agent.py, `_is_transient_error()`]: String matching on "503" is overly broad.**
The pattern `"503"` matches any string containing that substring — including error messages like "Error at line 503" or port numbers. Similarly, "529" could theoretically false-positive. The structured `status_code` check is correct and prioritized, but the string fallback path could misclassify a permanent error as transient and trigger retries. This is **low severity** — the blast radius is bounded by `max_attempts` and per-run budget cap — but worth noting. Consider requiring `"529"` and `"503"` patterns to be preceded by "HTTP" or "status" or to appear as standalone tokens.

**3. [src/colonyos/agent.py, retry loop]: Budget amplification on retries is untracked.**
When a 529 hits mid-stream (after partial token generation), the partial cost is lost — the SDK returns no `ResultMessage`. With `max_attempts=3` and fallback adding another 3 attempts, a single phase could consume up to 6× its intended budget in untracked partial costs. The PRD acknowledges this as an accepted risk with the per-run budget cap as safety net. This is **correctly documented** but operators should be made aware. The `retry_info.total_retry_delay_seconds` helps with observability, but there's no `estimated_wasted_cost` metric. Acceptable for v1.

**4. [src/colonyos/agent.py, `_friendly_error()`]: Error messages are sanitized — good.**
The `_friendly_error()` function returns a generic `"API is temporarily overloaded (529). Will retry..."` rather than forwarding raw API response bodies that could leak internal infrastructure details. This is correct security practice.

**5. [src/colonyos/config.py, `_parse_retry_config()`]: Fallback model is validated against allowlist — good.**
The `fallback_model` value is checked against `VALID_MODELS`, preventing injection of arbitrary model identifiers. This closes a potential config-driven attack vector where a malicious config could point to an unintended endpoint.

**6. [src/colonyos/config.py, `_SAFETY_CRITICAL_PHASES`]: Hardcoded as `frozenset` — correct.**
The safety-critical phase list is immutable and not configurable via YAML. An attacker who can modify `config.yaml` cannot bypass the fallback block on `review`/`decision`/`fix`. This is the right security posture — safety gates should not be user-configurable.

**7. [src/colonyos/agent.py]: `resume` parameter is still passed during retries.**
When `resume` is provided (session continuation), a retry after 529 still passes the same `resume` session ID. But the PRD explicitly states retries restart from scratch (no `ResultMessage` = no `session_id`). If `resume` was set by the *caller*, it would be passed on every retry attempt, potentially resuming into a stale session. In practice this is unlikely to cause issues since 529 means the session never started, but the intent would be clearer if `resume` were set to `None` on retry attempts (attempts > 1).

**8. [src/colonyos/agent.py]: No `max_attempts` upper bound.**
Config validation ensures `max_attempts >= 1` but imposes no ceiling. A user could set `max_attempts: 1000` in config, creating a phase that retries for hours. Combined with `max_delay_seconds: 120`, worst case is ~33 hours of retries for a single phase. Consider adding a sane upper bound (e.g., 10) or at least logging a warning for values > 10.

---

VERDICT: request-changes

FINDINGS:
- [.colonyos/daemon_state.json]: Runtime daemon state file committed to git — should be gitignored and untracked. Leaks operator-specific ephemeral data.
- [src/colonyos/agent.py]: String matching for "503"/"529" in `_is_transient_error()` could false-positive on unrelated error messages containing those substrings. Low severity but tighten the patterns.
- [src/colonyos/agent.py]: No upper bound on `max_attempts` config — a misconfigured value could cause indefinite retry loops. Add a ceiling or warning.

SYNTHESIS:
The implementation is architecturally sound and follows the PRD closely. The security-critical decisions — immutable safety-critical phase set, fallback model allowlist validation, generic error messages instead of raw API responses, and fallback hard-blocked on review/decision/fix — are all correct. Test coverage is thorough with 729 new lines covering all retry paths, fallback logic, and edge cases. The primary blocker is the committed `daemon_state.json` which is unrelated to this feature and should not be in the repository. The two code-level findings (string pattern broadness and unbounded `max_attempts`) are low severity but worth addressing before merge to avoid operational surprises. Overall, this is a clean, well-scoped transport-layer retry that correctly stays below the orchestrator's recovery system.