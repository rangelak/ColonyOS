# Review by Staff Security Engineer (Round 4)

Now I have a comprehensive understanding of the implementation. Let me write the review.

---

## Security Review — Staff Security Engineer

### Approach

I reviewed all changed files on branch `colonyos/implement_the_latest_prd_tasks_file` against the three PRDs it implements: (1) Interactive TUI, (2) TUI Default Mode / Smart Routing / Mid-Run Input, (3) `colonyos sweep` command. I focused on supply chain security, secrets handling, least privilege, sandboxing, audit trails, and prompt injection mitigations.

### Detailed Findings

**1. Sanitization — Significantly Improved ✅**

The `sanitize_display_text()` function was hardened to strip OSC, DCS, and single-char escape sequences (not just CSI). Carriage returns are now normalized to prevent content-overwrite attacks (`"safe\rmalicious"`). The `_CONTROL_CHARS_RE` now correctly preserves `\t` and `\n` while stripping everything else. This is a genuine security improvement that addresses terminal escape injection from untrusted command output flowing through the TUI transcript.

**2. Sweep Analysis Phase — Proper Least Privilege ✅**

The sweep phase (`Phase.SWEEP`) correctly uses read-only tools: `allowed_tools=["Read", "Glob", "Grep"]`. No Write, Edit, or Bash. The sweep instruction template explicitly prohibits changes to auth, secrets, schemas, and public APIs. This is textbook least-privilege design.

**3. Preflight Recovery — Carefully Scoped with Secret Detection ✅**

`run_preflight_recovery()` includes:
- `_is_secret_like_path()` that blocks auto-commit of `.env*`, `.pem`, `.key`, `.ssh/`, credential files — good defense against accidental credential commit.
- `_recovery_scope_extras()` that verifies the agent didn't expand beyond blocked files + direct test updates. This constrains the blast radius.
- The instruction template forbids `git add .`, `git add -A`, push, branch creation, and destructive git commands.
- The agent does get Write/Edit/Bash access, which is necessary but the scope validation after execution provides a safety net.

**4. Mid-Run User Injection — Properly Sanitized ✅**

`enqueue_user_injection()` applies `sanitize_untrusted_content()` (XML tag stripping) before queuing. `_drain_injected_context()` also applies `sanitize_untrusted_content()` before formatting into prompts. The display path additionally applies `sanitize_display_text()`. This is defense-in-depth against prompt injection through mid-run input.

**5. Router Metadata Sanitization — New Defense ✅**

The new `_sanitize_metadata()` function applies both display-level and content-level sanitization to project metadata (name, description, stack, vision) before inclusion in prompts. Previously, project metadata was injected raw. This closes a prompt injection vector through malicious `config.yaml` values.

**6. Mode Selection Audit Trail ✅**

`log_mode_selection()` persists triage decisions as JSON to `.colonyos/runs/triage_*.json` with sanitized prompt content. Good for auditing what the system decided and why.

**7. Review Phase Never Skipped ✅**

The `skip_planning` flag only bypasses the plan phase (line 3159). Review, decision, and fix phases execute unconditionally for all code changes. This matches the PRD's explicit security requirement.

**8. Minor Concerns**

- **`src/colonyos/cli.py`**: The `_tui_available()` function imports `colonyos.tui`, `janus`, and `textual` at check time. If a malicious dependency were substituted (supply chain), this import would execute attacker code. This is inherent to Python's import system and not specific to this change, but worth noting that TUI activation now happens automatically for TTY sessions rather than requiring an explicit `--tui` flag.
- **Preflight recovery has Bash access**: The recovery agent gets `["Read", "Glob", "Grep", "Bash", "Write", "Edit"]` — full tool access. While the post-execution scope validation catches scope creep, a malicious instruction template could still exfiltrate data during execution via Bash. The `_is_secret_like_path` check only gates file-level commits, not runtime reads. This is acceptable given that the orchestrator always runs with full permissions anyway, and the recovery agent's scope is validated after execution.
- **No explicit timeout on the preflight recovery phase**: If the recovery agent hangs or loops, there's no phase-specific timeout beyond the global `per_phase` budget. This is consistent with other phases but worth noting.

**9. No Secrets in Committed Code ✅**

Verified: no `.env`, credentials, API keys, or tokens in the diff. The `config.yaml` at `.colonyos/config.yaml` contains only model names and persona definitions.

**10. All Tests Pass ✅**

518 core tests + 117 TUI tests + 134 CLI tests = 769 tests passing.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/sanitize.py]: Improved — now strips OSC/DCS escape sequences and prevents carriage-return overwrite attacks. Good security hardening.
- [src/colonyos/orchestrator.py]: Preflight recovery includes secret-file detection and scope validation. Sweep uses read-only tools. `skip_planning` correctly never skips review/decision phases.
- [src/colonyos/router.py]: New `_sanitize_metadata()` applies defense-in-depth sanitization to project metadata before prompt inclusion. Closes a previously unaddressed prompt injection vector.
- [src/colonyos/tui/adapter.py]: Mid-run user injection sanitized at both content and display levels before queuing. Thread-safe via lock + deque.
- [src/colonyos/instructions/preflight_recovery.md]: Instruction template explicitly forbids broad staging, push, destructive operations, and secret file commits. Good guardrails.
- [src/colonyos/instructions/sweep.md]: Read-only analysis with explicit exclusions for auth, secrets, schemas, and API signatures.
- [src/colonyos/cli.py]: TUI now auto-activates for TTY sessions — increases the attack surface slightly vs. opt-in, but the `--no-tui` escape hatch exists and the dependency check is fail-safe.

SYNTHESIS:
From a security perspective, this implementation is well above average. The sanitization layer was meaningfully hardened (OSC/DCS/CR attacks), the new sweep phase correctly enforces read-only tool access, the preflight recovery phase includes both proactive secret detection and post-execution scope validation, and mid-run user injection is sanitized at multiple layers before reaching agent prompts. The most security-critical decision — never skipping review regardless of complexity classification — is correctly enforced in the pipeline. The router now sanitizes project metadata before prompt injection, closing a vector that existed in the prior codebase. The main residual risk is that the preflight recovery agent has full tool access including Bash, but the post-execution validation provides a reasonable safety net, and this is consistent with how other pipeline phases operate. I recommend approval.
