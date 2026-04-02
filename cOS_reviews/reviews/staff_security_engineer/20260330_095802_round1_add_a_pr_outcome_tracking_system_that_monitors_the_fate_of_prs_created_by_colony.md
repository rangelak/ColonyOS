# Review by Staff Security Engineer (Round 1)

I now have a comprehensive view of the implementation. Let me produce my security-focused review.

---

## Review — Staff Security Engineer

### Artifact Verification

| Required Artifact | Status |
|---|---|
| Branch `colonyos/add_a_pr_outcome_tracking_system_that_monitors_the_fate_of_prs_created_by_colony` | ✅ Exists, 10 commits |
| PRD | ✅ Present at expected path |
| Task file | ✅ Present on branch, all 8 parent tasks / 30 sub-tasks marked complete |
| Tests | ✅ 334 tests pass (0 failures) |

### Checklist Assessment

#### Completeness
- [x] All 8 functional requirement groups (FR-1 through FR-8) are implemented
- [x] All tasks in the task file are marked complete
- [x] No placeholder or TODO code remains — verified via diff inspection

#### Quality
- [x] All tests pass (334 passed in 1.62s)
- [x] Code follows existing project conventions (subprocess `gh` CLI pattern from `github.py`, `MemoryStore._init_db` pattern, try/except-log-continue resilience pattern)
- [x] No unnecessary dependencies added — only uses stdlib, existing `colonyos.memory`, `colonyos.sanitize`, and `rich`
- [x] Unrelated TUI CSS change is minor (scrollbar fix in `styles.py`) — cosmetic, low risk

#### Safety (Security-Focused Assessment)

- [x] **No secrets or credentials in committed code** — no API keys, tokens, or `.env` files
- [x] **Untrusted input sanitization** — PR reviewer comments (which are attacker-controlled text from GitHub) pass through `sanitize_ci_logs()` before storage. This function chains XML tag stripping (anti-prompt-injection) with secret-pattern redaction (GitHub tokens, AWS keys, generic Base64 patterns). This is the correct approach.
- [x] **Length capping on untrusted input** — `_CLOSE_CONTEXT_MAX_CHARS = 500` prevents a malicious reviewer comment from bloating the SQLite database or the CEO prompt. The CEO summary has a secondary 2000-char hard cap. This is good defense-in-depth.
- [x] **SQL injection prevention** — All SQL queries use parameterized queries (`?` placeholders). The only dynamic SQL construction is `f"UPDATE ... SET {', '.join(sets)}"` where `sets` is a list of hardcoded column names (never user-controlled). This is safe.
- [x] **Subprocess security** — `subprocess.run` uses list-form arguments (not `shell=True`), preventing shell injection. The `pr_number` argument is converted to `str(int)` upstream, so it cannot contain malicious characters.
- [x] **Non-blocking error handling** — All tracking/polling operations are wrapped in try/except with logging, ensuring tracking failures never crash the main pipeline or daemon. This is the correct fail-open pattern for non-critical observability features.
- [x] **No destructive database operations** — Only INSERT and UPDATE; no DELETE, DROP, or TRUNCATE. Schema creation uses `CREATE TABLE IF NOT EXISTS`.

### Security Observations (Non-Blocking)

1. **`_call_gh_pr_view` trusts PR number origin**: The `pr_number` passed to `gh pr view` comes from `OutcomeStore.get_open_outcomes()`, which itself was originally parsed from a PR URL regex match and cast to `int`. This is safe — `int()` ensures no command injection.

2. **Double-open of `memory.db`**: `poll_outcomes()` opens `OutcomeStore` (one connection to `memory.db`) and then opens `MemoryStore` (another connection to `memory.db`) within the same function. SQLite handles concurrent reads/writes from the same process via WAL mode or serialized mode, but this does create a window where two connections are held simultaneously. The `with MemoryStore(...)` context manager ensures the second connection is closed promptly. Low risk, but worth noting for future refactoring.

3. **No pruning strategy**: The PRD's Open Question #1 asks about pruning old outcome records. No pruning is implemented, so `pr_outcomes` will grow unbounded. For a security perspective this means an attacker who repeatedly triggers PR creation could slowly bloat `memory.db`. This is a V2 concern — the CEO prompt summary is capped, so the immediate blast radius is limited.

4. **CEO prompt injection surface**: The `format_outcome_summary()` output is injected directly into the CEO prompt. The `close_context` within it has been sanitized by `sanitize_ci_logs` (XML tags stripped, secrets redacted) and then double-truncated (500 chars at storage, 100 chars in the summary). However, the sanitized text still contains free-form natural language from an external reviewer. A sophisticated prompt injection could theoretically survive the XML-stripping pass. This is the same risk surface that already exists for GitHub issue titles and PR descriptions elsewhere in the codebase — the implementation follows the established pattern correctly and doesn't introduce a new class of vulnerability.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/outcomes.py]: Untrusted reviewer comments correctly sanitized via `sanitize_ci_logs()` and length-capped at 500 chars before SQLite storage. All SQL uses parameterized queries. Subprocess calls use list-form arguments (no shell injection). Sound security posture.
- [src/colonyos/outcomes.py]: `poll_outcomes()` opens two simultaneous connections to `memory.db` (OutcomeStore + MemoryStore). Low risk but worth noting for future cleanup.
- [src/colonyos/outcomes.py]: No pruning strategy for `pr_outcomes` table — unbounded growth possible. Mitigated by CEO prompt summary capping. Acceptable for V1.
- [src/colonyos/orchestrator.py]: `_register_pr_outcome()` wraps all tracking in try/except, ensuring tracking failures are non-blocking. PR number extraction uses `int(match.group(1))` — safe against injection.
- [src/colonyos/orchestrator.py]: CEO prompt injection in `_build_ceo_prompt()` follows the same try/except non-blocking pattern as existing PR/issue sections. Sanitized close context survives into the prompt as free-form text (same risk profile as existing GitHub issue injection — not a new vulnerability class).
- [src/colonyos/daemon.py]: `_poll_pr_outcomes()` follows the exact resilience pattern of `_poll_github_issues()` — exception-safe, non-crashing. Correct.
- [src/colonyos/config.py]: `outcome_poll_interval_minutes` validated as positive integer. Minimum value is 1 minute; no maximum enforced. An operator could set it to 1 minute and generate heavy `gh` API traffic, but this is a configuration choice, not a vulnerability.
- [tests/]: 654 lines of new tests covering all security-relevant paths: sanitization of close context, handling of `gh` CLI failures, non-blocking error handling, empty/missing data edge cases. Test coverage is thorough.

SYNTHESIS:
This is a well-executed feature from a security standpoint. The implementation correctly identifies the primary threat — untrusted reviewer comments being ingested into the SQLite database and then injected into LLM prompts — and applies the existing `sanitize_ci_logs()` pipeline (XML tag stripping + secret pattern redaction) plus aggressive length capping (500 chars at storage, 100 chars in CEO summary, 2000 chars total hard cap). All subprocess calls to `gh` use list-form arguments with integer-validated PR numbers, eliminating shell injection risk. All SQL uses parameterized queries. The fail-open error handling pattern (try/except + log warning + continue) is correctly applied everywhere, ensuring that tracking — a non-critical observability feature — can never crash the main pipeline or daemon. The only concern I'd flag for V2 is the lack of a pruning strategy for the `pr_outcomes` table, which could grow unbounded, and the inherent prompt injection risk of passing sanitized-but-still-free-form reviewer text into the CEO prompt (which is not a regression — it's the same risk class that already exists for issue titles and PR descriptions). Approved.
