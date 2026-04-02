# Review by Staff Security Engineer (Round 1)

Now I have all the information I need for my review. Let me write it up.

---

## Security Review — Staff Security Engineer

I've conducted a thorough review of the implementation on branch `colonyos/can_we_make_colonyos_setup_choice_one_where_an_assistant_sets_you_up_dynamically` against the PRD.

### Summary of Findings

**All 181 tests pass.** The implementation is functionally complete against the PRD and task list. However, I've identified one significant security gap and several observations.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/agent.py:92]: **CRITICAL — `bypassPermissions` used for init agent.** The PRD Section 6 (Security) explicitly mandates: "No `bypassPermissions`: Use `default` permission mode for the init call since no writes are needed." However, `run_phase_sync()` hardcodes `permission_mode="bypassPermissions"` with no parameter to override it. The init LLM call (`run_ai_init` → `run_phase_sync`) therefore runs with full bypass permissions. While `allowed_tools=["Read", "Glob", "Grep"]` provides a layer of defense-in-depth by restricting available tools, `bypassPermissions` means the Claude Code agent could theoretically bypass tool restrictions depending on the SDK's enforcement model. The fix is to add a `permission_mode` parameter to `run_phase_sync()` / `run_phase()` (defaulting to `"bypassPermissions"` for backward compatibility) and have `run_ai_init()` pass `permission_mode="default"`.
- [src/colonyos/init.py:207-251]: **Prompt injection surface via repo files.** The `_build_init_system_prompt()` function injects `repo_context.readme_excerpt` (up to 1500 chars of README content) directly into the system prompt. A malicious README could contain adversarial instructions attempting to manipulate the LLM's JSON output. Mitigating factors: (1) the LLM only selects from predefined `pack_keys` and `preset_names` validated by Python code post-response, (2) `project_name`/`description`/`stack` are free-text but flow only into `config.yaml` (not into downstream `bypassPermissions` agents' system prompts), (3) `vision` is optional and defaults to empty. The constrained output validation is well-designed. This is **acceptable risk for v1** but should be documented.
- [src/colonyos/init.py:420-429]: **Good: Least-privilege tool restriction.** `allowed_tools=["Read", "Glob", "Grep"]` correctly follows the PRD's least-privilege mandate. No Write, Edit, or Bash tools are exposed to the init agent.
- [src/colonyos/init.py:254-308]: **Good: Output validation is sound.** The `_parse_ai_config_response()` function properly validates `pack_key` against `pack_keys()` and `preset_name` against `MODEL_PRESETS`. It returns `None` on any validation failure, triggering graceful fallback. The LLM cannot inject arbitrary persona text or model names.
- [src/colonyos/init.py:430-433]: **Good: Exception handling catches all failure modes.** The broad `except Exception` around `run_phase_sync` ensures auth failures, network timeouts, and SDK errors all gracefully fall back to the manual wizard without stack traces or partial state.
- [src/colonyos/init.py:70-190]: **Good: Deterministic pre-scan.** `scan_repo_context()` reads only well-known manifest files, truncates to 2000 chars, and handles `OSError` gracefully. No secrets files (`.env`, credentials) are in the scan list.
- [src/colonyos/init.py:76-100]: **Note: No `.env`/secret file exclusion needed** — the `_MANIFEST_FILES` list is an explicit allowlist (not a directory scan), so there's no risk of accidentally reading secrets. This is the correct design.
- [tests/test_init.py]: **Good: 39 new tests** cover happy path, all fallback scenarios, parse validation, empty repos, and no-partial-state guarantees. Test coverage is comprehensive.

SYNTHESIS:
From a security perspective, the implementation is **well-designed in principle** — the constrained output validation (Python validates all LLM selections against predefined allowlists), the allowlisted file scan (no risk of reading `.env`/credentials), and the graceful fallback on any failure are all exactly what the security section of the PRD prescribed. The single blocking issue is that `run_phase_sync()` hardcodes `permission_mode="bypassPermissions"` with no override mechanism, violating the PRD's explicit requirement to use `"default"` permission mode for the init agent. While the `allowed_tools` restriction provides partial mitigation, defense-in-depth requires both layers. The fix is straightforward: add a `permission_mode` parameter to `run_phase_sync()` and `run_phase()`, default it to `"bypassPermissions"` to preserve backward compatibility for all existing callers, and have `run_ai_init()` explicitly pass `permission_mode="default"`. This is the only change I'm requesting before approval.
