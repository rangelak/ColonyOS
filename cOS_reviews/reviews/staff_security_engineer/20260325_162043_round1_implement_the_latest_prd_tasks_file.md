# Review by Staff Security Engineer (Round 1)

I now have a comprehensive picture. Here's my review:

---

## Security Review — `colonyos/implement_the_latest_prd_tasks_file`

**Reviewer:** Staff Security Engineer

This branch introduces three major feature areas: (1) a full TUI with REPL, (2) a preflight recovery agent that auto-commits dirty worktree changes, and (3) the `colonyos sweep` command. The PRD specifically covers only (3), but all changes on this branch are in-scope for a security review.

---

### Sweep Feature (Core PRD)

**Read-only tool enforcement — ✅ Good.** The sweep analysis phase correctly restricts allowed tools to `["Read", "Glob", "Grep"]` (line ~1630 of `orchestrator.py`). This is tested in `test_analysis_uses_read_only_tools`. The agent cannot write, edit, or execute shell commands during analysis.

**Instruction template exclusions — ✅ Good.** `instructions/sweep.md` explicitly excludes auth/security code, secrets, DB schemas, and public API signatures from modification scope. The `## Output Rules` section reminds the agent that this is analysis-only.

**`target_path` injection into system prompt — ⚠️ Low concern.** User-supplied `target_path` is interpolated directly into the system prompt via f-string (`f"Analyze only the following path: \`{target_path}\`"`). While the CLI validates the path exists, there's no sanitization of the path string itself. A path containing backticks or markdown could theoretically alter prompt structure. This is low-risk because: (a) the path must exist on disk, and (b) it's injected into a system prompt consumed by the agent, not rendered to other users. Still, sanitizing with `sanitize_untrusted_content()` would be more defensive.

**Audit logging — ✅ Good.** Sweep results are persisted via `write_cleanup_log()` with event type `"sweep"`, enabling post-hoc auditing.

### Preflight Recovery Agent

**Secret detection — ✅ Good.** `_is_secret_like_path()` checks a comprehensive blocklist of file names (`.env*`, `credentials.json`, SSH keys) and file suffixes (`.pem`, `.key`, `.crt`, etc.). If any dirty file matches, recovery is **refused outright** with a clear error. This is the correct approach — fail closed.

**Scope verification — ✅ Excellent.** After the recovery agent runs, the orchestrator verifies: (a) working tree is clean, (b) a commit was actually created, (c) the commit covers all blocked files, and (d) the commit didn't touch files outside the blocked+test scope. This is a strong audit boundary. An agent that goes rogue and touches unrelated files will be caught by `_recovery_scope_extras()`.

**Instruction template — ✅ Good.** `instructions/preflight_recovery.md` explicitly forbids destructive git commands, pushing, branch creation, broad staging (`git add .`), and committing secret-like files.

### TUI / REPL

**Input sanitization — ✅ Good.** The TUI adapter applies `sanitize_display_text()` to all agent output before rendering and `sanitize_untrusted_content()` to user injection text. The improved `sanitize_display_text()` now handles OSC/DCS escape sequences and strips bare `\r` to prevent content-overwrite attacks — a genuine terminal security fix.

**REPL command dispatch — ⚠️ Moderate concern.** The `_try_dispatch_repl_command()` function uses `shlex.split()` on user input and dispatches to Click CLI commands. It whitelists allowed commands via `_repl_top_level_names()` and blocks `run`/`tui` re-entry. However, the input is not sanitized through `sanitize_untrusted_content()` before being split/dispatched — it goes directly to the Click invocation machinery. Since this only dispatches to registered Click commands (not arbitrary shell), the risk is contained, but a sanitization pass would be more defensive.

**Mode agent heuristics — ✅ Good.** The heuristic keyword matching in `_heuristic_mode_decision()` uses `sanitize_untrusted_content()` on the query before processing. The fallback to the model-based mode selector also benefits from system prompt constraints.

### Sanitizer Improvements

**The `\r` stripping — ✅ Critical fix.** The new `sanitize_display_text()` normalizes `\r\n` to `\n` and strips bare `\r`. This prevents the classic terminal overwrite attack where `"safe text\rmalicious"` renders as "malicious" in many terminals. This is a meaningful security hardening.

**Broader ANSI coverage — ✅ Good.** Adding OSC, DCS, and single-char escape sequence stripping closes gaps where malicious output could set window titles, write to clipboard, or issue device control strings.

### Missing Items

1. **No `--from-tasks` flag** — mentioned as an open question in the PRD but not implemented. This is fine for v1.
2. **No `max_tasks` upper bound validation** — `_parse_sweep_config` validates `>= 1` but has no upper bound. A user could set `max_tasks: 10000` causing an expensive analysis. Low risk since it's user-configured.
3. **The referenced PRD path `cOS_prds/20260325_155954_prd_implement_the_latest_prd_tasks_file.md` does not exist.** The actual PRD is `cOS_prds/20260324_112017_prd_i_want_to_introduce_a_new_feature_for_a_cleanup_agent_that_basically_functions_l.md`.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py:1509]: `target_path` is interpolated into system prompt without sanitization via `sanitize_untrusted_content()` — low risk since path is validated to exist on disk, but could be hardened
- [src/colonyos/cli.py:~340-370]: REPL command dispatch via `shlex.split()` does not sanitize user input through `sanitize_untrusted_content()` before processing — mitigated by whitelist of allowed Click commands
- [src/colonyos/sanitize.py]: Excellent hardening of `sanitize_display_text()` — stripping bare `\r`, OSC, DCS sequences closes real terminal attack vectors
- [src/colonyos/orchestrator.py:943-956]: Secret file detection in preflight recovery is well-implemented with fail-closed behavior
- [src/colonyos/orchestrator.py:1066-1078]: Post-recovery scope verification is a strong audit control — prevents agent scope creep
- [tests/test_cli.py::TestRepl::test_repl_accumulates_session_cost]: Pre-existing flaky test failure (not introduced by this branch)

SYNTHESIS:
From a security perspective, this is a solid implementation. The sweep feature correctly enforces read-only tool access during analysis, preventing the analysis agent from modifying the codebase. The preflight recovery agent has excellent guardrails: secret detection with fail-closed behavior, post-commit scope verification, and explicit instruction-level constraints against destructive operations. The TUI's sanitization story is strong — `sanitize_display_text()` now handles the full spectrum of terminal escape sequences including the critical `\r` overwrite vector. The two findings (unsanitized `target_path` in prompt, unsanitized REPL input before dispatch) are low-to-moderate risk given their mitigating controls, but should be addressed in a future hardening pass. No secrets, credentials, or destructive operations were found in the committed code. The principle of least privilege is well-applied: each phase gets only the tools it needs (sweep gets read-only, recovery gets git access, Q&A gets read-only).