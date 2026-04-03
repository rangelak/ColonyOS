# Review by Staff Security Engineer (Round 2)

I now have a comprehensive view of the implementation. Let me write my review.

---

## Security Review — Staff Security Engineer

I've reviewed the full diff on `colonyos/implement_the_latest_prd_tasks_file` against the three PRDs it implements (TUI, TUI UX/routing enhancements, and `colonyos sweep`). Here is my assessment.

### Key Security Observations

**Good security practices observed:**

1. **Sanitization is consistent.** The `TextualUI` adapter sanitizes all text via `sanitize_display_text()` before queuing — agent text, tool args, phase names, error messages. The `enqueue_user_injection()` path applies `sanitize_untrusted_content()` before the text reaches the orchestrator, and `_drain_injected_context()` in the orchestrator applies it again. This double-sanitize is defense-in-depth and correct.

2. **Terminal escape injection hardened.** The `sanitize_display_text()` regex was expanded to strip OSC sequences (clipboard writes, window title manipulation), DCS sequences, and bare carriage returns (`\r` overwrite attacks). This is a real improvement over the previous CSI-only filter.

3. **Sweep phase is read-only.** The `run_sweep()` function passes `allowed_tools=["Read", "Glob", "Grep"]` — no Write, Edit, or Bash. This enforces least privilege for the analysis phase.

4. **Preflight recovery has scope guards.** The `run_preflight_recovery()` function validates that: (a) no secret-like files are in the dirty set, (b) the agent actually created a commit, (c) the commit covered all blocked files, and (d) the agent didn't expand scope beyond blocked files + test files. This is a solid post-hoc audit.

5. **Review is never skipped.** The complexity routing (trivial/small/large) only skips planning, never review. The review phase remains mandatory for all code changes regardless of routing.

6. **No secrets in committed code.** No API keys, tokens, or credentials found in the diff.

**Security concerns:**

1. **Preflight recovery agent has full tool access.** The `run_preflight_recovery()` call doesn't pass `allowed_tools`, which means the agent gets the default full toolset including Bash and Write. While the post-hoc scope check catches *file changes* that exceed the dirty set, the agent can still execute arbitrary commands during the recovery phase. The instruction template says "do not push" but this is an advisory constraint, not a technical one. A compromised or confused model could `git push`, `curl` data out, etc. This is mitigated by the fact that recovery only fires when the user explicitly types "commit" in the TUI, but it's still a wider blast radius than necessary.

2. **Mode selection prompt includes unsanitized project metadata.** In `_build_mode_selection_prompt()`, `project_name`, `project_description`, `project_stack`, and `vision` are appended to the system prompt without sanitization. These come from the user's `config.yaml` so the risk is self-injection, but if config values are ever populated from external sources (e.g., GitHub repo descriptions), this becomes a prompt injection vector. The user query IS sanitized via `sanitize_untrusted_content()`.

3. **`_handle_tui_command` uses `shlex.split` on user input** then dispatches to `_invoke_cli_command`. While the safe command allowlist (`_SAFE_TUI_COMMANDS`) limits what can be executed, the fallback path uses `shlex` which can raise on malformed input (caught) but the actual command invocation delegates to Click's dispatch. This is acceptable given the allowlist.

4. **`bare except: pass` in sweep scan bootstrap.** In `run_sweep()`, the `scan_directory()` bootstrap silently swallows all exceptions including potential security-relevant ones. This is non-critical but reduces observability.

5. **Test failure.** `test_repl_accumulates_session_cost` is failing because the routing refactor changed the REPL flow — prompts now go through mode selection which returns FALLBACK instead of proceeding to the pipeline. This is a regression in test coverage, not a security issue per se, but it means the cost-accumulation path is untested.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/orchestrator.py]: `run_preflight_recovery()` does not restrict `allowed_tools` — the recovery agent gets full Bash/Write/Edit access. Should be scoped to `["Read", "Glob", "Grep", "Bash", "Write", "Edit"]` at minimum, or ideally restrict Bash to non-network commands. The post-hoc scope check only validates file changes, not side effects like network calls or pushes.
- [src/colonyos/router.py]: `_build_mode_selection_prompt()` appends `project_name`, `project_description`, `project_stack`, and `vision` to the system prompt without calling `sanitize_untrusted_content()` on them. Apply sanitization for defense-in-depth.
- [tests/test_cli.py]: `test_repl_accumulates_session_cost` fails — the routing refactor broke this test. The new mode-selection logic returns FALLBACK for synthetic prompts instead of proceeding to the pipeline, so cost is never accumulated.
- [src/colonyos/orchestrator.py]: `run_sweep()` line ~557 has a bare `except Exception: pass` around the `scan_directory()` bootstrap. At minimum log a warning so operators can diagnose scan failures.

SYNTHESIS:
The implementation demonstrates generally strong security hygiene: sanitization is applied consistently at both the display and content layers, the sweep phase enforces read-only tool access, terminal escape filtering was meaningfully hardened, and the preflight recovery flow has post-hoc scope validation. The two actionable concerns are: (1) the preflight recovery agent's unrestricted tool access — while the post-commit scope check catches file changes, it cannot prevent side effects like arbitrary command execution or data exfiltration during the recovery phase; and (2) the failing test, which should be fixed to maintain regression coverage. Neither issue is a show-stopper, but the recovery agent's tool scope should be tightened before merge, since this agent runs with `bypassPermissions` on user-controlled dirty worktree state — a classic confused-deputy scenario if the dirty files contain adversarial content.
