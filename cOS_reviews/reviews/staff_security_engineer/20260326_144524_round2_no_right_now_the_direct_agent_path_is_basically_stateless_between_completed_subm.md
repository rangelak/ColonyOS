# Review by Staff Security Engineer (Round 2)

All 1980 tests pass. Now I have enough information to provide a thorough security review.

---

## Security Review: Direct-Agent Conversational State Persistence

### Completeness

All 7 task groups (1.0–7.0) in the task file are marked complete. The PRD's 7 functional requirements (FR-1 through FR-7) map to implemented code:

| FR | Status | Notes |
|---|---|---|
| FR-1: `resume` param in `run_phase`/`run_phase_sync` | ✅ | `agent.py` — clean parameter threading |
| FR-2: `_run_direct_agent` accepts/returns session ID | ✅ | Returns `tuple[bool, str \| None]` |
| FR-3: `last_direct_session_id` in TUI closure | ✅ | Both `_launch_tui` and REPL loop |
| FR-4: Clear session on non-direct-agent mode | ✅ | Present in both TUI and REPL paths |
| FR-5: `/new` command | ✅ | In `_SAFE_TUI_COMMANDS`, handler returns signal |
| FR-6: "Continuing conversation..." indicator | ✅ | Both CLI `click.echo` and TUI `TextBlockMsg` |
| FR-7: Graceful fallback on resume failure | ✅ | Retries without resume, clears session |

### Quality

- **All 1980 tests pass** with no failures
- No TODOs or placeholder code found in source changes
- Code follows existing project conventions (dataclasses, `run_phase_sync` pattern, sanitization pipeline)
- New dependencies are minimal — no new external packages for the core feature

### Security Findings

VERDICT: approve

FINDINGS:
- [src/colonyos/cli.py]: **Good — Session ID validation is defense-in-depth.** The `re.fullmatch(r"[A-Za-z0-9_-]+", resume_session_id)` check prevents injection of path traversal or escape sequences into the SDK's resume parameter. Silently falls back to `None` on mismatch rather than raising, which is correct for UX.
- [src/colonyos/cli.py]: **Good — Session state is in-memory only.** `last_direct_session_id` lives as a closure variable — no disk persistence, no cross-process leakage. Session state dies when the TUI process exits, matching PRD's explicit non-goal of cross-restart persistence.
- [src/colonyos/cli.py]: **Good — Mode transitions clear session state.** Both the TUI `_run_callback` and CLI REPL properly set `last_direct_session_id = None` when routing to non-direct-agent modes (plan+implement, review, cleanup). This prevents stale session context from leaking into pipeline phases.
- [src/colonyos/sanitize.py]: **Good — Hardened ANSI/control char stripping.** The expanded regex now covers OSC sequences (clipboard write attacks via `\x1b]52;...`), DCS sequences, and bare `\r` carriage returns that enable content-overwrite attacks. This is a meaningful security improvement independent of the session feature.
- [src/colonyos/tui/adapter.py]: **Good — Double sanitization on user injections.** `enqueue_user_injection` applies both `sanitize_untrusted_content` (XML tag stripping) and `sanitize_display_text` (ANSI/control chars). This creates a proper sanitization boundary between user input and agent context.
- [src/colonyos/orchestrator.py]: **Good — Preflight recovery refuses secret-like files.** `_is_secret_like_path()` checks against `.env*`, private keys, certificates, and `.ssh/` paths. The agent is explicitly instructed never to commit these via the instruction template AND the code enforces it programmatically — defense-in-depth.
- [src/colonyos/orchestrator.py]: **Good — Recovery scope validation.** `_recovery_scope_extras()` detects if the recovery agent touched files outside the original dirty set (excluding tests), providing audit capability for scope creep.
- [src/colonyos/instructions/preflight_recovery.md]: **Good — Explicit security constraints in agent instructions.** The template prohibits destructive git commands, broad staging (`git add .`), secret file commits, and scope expansion. While instruction-level guardrails are not a hard security boundary, they are the correct approach given the SDK's execution model.
- [src/colonyos/router.py]: **Good — Project metadata sanitization.** `_sanitize_metadata()` applies both display and content sanitization to project name/description/stack before embedding in prompts, preventing prompt injection via malicious config values.
- [src/colonyos/agent.py]: **Note — `bypassPermissions` remains the default.** This is pre-existing, not introduced by this PR, but worth flagging: all phases including the new `PREFLIGHT_RECOVERY` and `SWEEP` run with `bypassPermissions`. For a tool that runs arbitrary code in user repos, this is the expected trust model (the user chose to run ColonyOS), but it means the instruction-level guardrails in templates are the primary control, not a technical enforcement boundary.

SYNTHESIS:
From a security perspective, this implementation is well-executed. The core session persistence feature is architecturally simple — an in-memory string variable threaded through existing function signatures — which minimizes the attack surface. The session ID is validated against a strict alphanumeric pattern before being passed to the SDK, preventing injection. Session state is properly cleared on mode transitions, preventing context leakage between direct-agent and pipeline phases. The `/new` command provides an explicit user escape hatch. The graceful fallback (retry without resume on failure) ensures no user-visible errors from stale sessions. The broader changes in this branch (sanitization hardening, OSC/DCS sequence stripping, carriage return normalization, preflight recovery with secret-file guards) all improve the security posture. The user injection pipeline applies proper double-sanitization. The only architectural observation — not a blocker — is that `bypassPermissions` is the universal default, meaning agent instruction templates are the primary security control rather than technical enforcement. This is acceptable for the current trust model where the user explicitly invokes ColonyOS on their own repository. Overall, this is a clean, well-tested implementation with appropriate defense-in-depth measures.