# Review by Staff Security Engineer (Round 1)

Now I have enough information to provide a comprehensive security review. Let me write it up.

---

## Staff Security Engineer Review

### Analysis

I've reviewed the full diff (~5900 lines added across 54 files) implementing Slack thread-fix requests for conversational PR iteration against the PRD. Here is my assessment from a security perspective.

#### Positive Security Findings

1. **Sanitization pipeline is correctly applied**: Thread-fix text passes through `sanitize_slack_content()` (FR-18 ✅), which now chains `strip_slack_links()` → `sanitize_untrusted_content()`. The Slack link stripping (`<URL|display_text>` → `display_text`) eliminates the URL exfiltration vector (FR-20 ✅).

2. **Input validation for git refs**: `is_valid_git_ref()` uses a strict allowlist regex `[a-zA-Z0-9._/-]` with length limits, `..` traversal rejection, and leading/trailing character checks. This is defense-in-depth applied at both triage parse time AND orchestrator execution time.

3. **Thread-fix validation is correctly ordered**: `should_process_thread_fix()` validates `thread_ts` maps to a completed `QueueItem` BEFORE any agent work (FR-21 ✅), preventing spoofed thread targeting.

4. **No secrets committed**: Tokens are read from environment variables (`COLONYOS_SLACK_BOT_TOKEN`, `COLONYOS_SLACK_APP_TOKEN`). No hardcoded credentials in code. The README mentions `xoxb-...` and `xapp-...` only as placeholder examples.

5. **Triage agent sandboxing**: `triage_message()` runs with `allowed_tools=[]` and `budget_usd=0.05` — minimal blast radius for LLM-based triage.

6. **Cost controls**: `max_fix_rounds_per_thread` (default 3), `daily_budget_usd`, `max_runs_per_hour`, `max_queue_depth`, and circuit breaker with cooldown all properly validated at config parse time.

7. **Locking discipline**: `state_lock` protects `fix_rounds` increment and queue mutations. Lock is NOT held across LLM calls or pipeline execution — correct pattern.

#### Security Concerns

1. **`_handle_thread_fix` trusts `parent_item.branch_name` without re-validating**: The branch name stored in the parent `QueueItem` is passed directly to `run_thread_fix()` which feeds it into `subprocess.run(["git", "checkout", branch_name])`. While the branch name was originally validated when first stored, a hand-edited queue JSON file (mentioned in the codebase as a possibility) could inject a malicious branch name. `run_thread_fix` does call `validate_branch_exists()` first, but does NOT call `is_valid_git_ref()` on the branch name before the subprocess call.

2. **`fix_prompt` truncation in user prompt is cosmetic only**: `_build_thread_fix_prompt` passes the full `fix_request` to the system prompt template (no truncation), while the user prompt truncates to `fix_request[:500]`. The full unsanitized-length fix request is in the system prompt. This is fine IF sanitization already ran, but the call chain should be verified.

3. **No HEAD SHA verification**: The PRD mentions "Verifies HEAD SHA matches last known state (defense against force-push tampering)" in FR-7, but the implementation does NOT verify HEAD SHA. This is a gap — a force-pushed branch could have been tampered with between the original run completion and the fix request.

4. **`_load_dotenv()` added to CLI entrypoint**: This loads `.env` from repo root with `override=False`. While benign in isolation, this means a cloned malicious repo could have a `.env` that sets environment variables. The `override=False` mitigates the highest-risk scenario (overwriting existing secrets), but it still sets vars that weren't previously set.

5. **No audit log of what the fix agent did**: The PRD's open question about auditing is unaddressed. `RunLog` captures phase results and cost, but there's no diff-level audit of what code changes the agent made during a fix round. This makes post-incident forensics harder.

#### Functional Completeness Check

- FR-1 through FR-6: ✅ Implemented
- FR-7: ⚠️ Missing HEAD SHA verification
- FR-8, FR-9: ✅ Plan and triage skipped
- FR-10 through FR-13: ✅ Slack UX implemented
- FR-14 through FR-17: ✅ Cost controls implemented
- FR-18 through FR-21: ✅ Sanitization and security controls implemented

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/orchestrator.py]: `run_thread_fix()` does not call `is_valid_git_ref()` on `branch_name` before passing it to `subprocess.run(["git", "checkout", branch_name])`. Defense-in-depth requires validation at point of use, not just at point of storage. The orchestrator already does this for `base_branch` in `run()` — apply the same pattern here.
- [src/colonyos/orchestrator.py]: FR-7 requires HEAD SHA verification ("defense against force-push tampering") but `run_thread_fix()` does not compare current HEAD against last known state. A force-pushed branch could contain tampered code that the fix agent blindly builds on.
- [src/colonyos/cli.py]: `_load_dotenv()` loads `.env` from repo root on every CLI invocation. A malicious repository could ship a `.env` that sets arbitrary environment variables (e.g., `GIT_SSH_COMMAND`, `LD_PRELOAD`, `PYTHONPATH`). Consider documenting this risk or restricting which vars are loaded.
- [src/colonyos/cli.py]: `_handle_thread_fix` passes `parent_item.branch_name` to the fix queue item without re-validating it through `is_valid_git_ref()`. While the original pipeline validated it, deserialized queue state from disk should be treated as untrusted input.

SYNTHESIS:
The implementation is architecturally sound and demonstrates good security hygiene in most areas — sanitization is correctly layered, triage is sandboxed, git refs are validated with a strict allowlist, cost controls are enforced, and no secrets are committed. However, two gaps concern me from a supply-chain and least-privilege perspective: (1) the missing HEAD SHA verification for force-push tampering defense (explicitly called out in FR-7), and (2) the missing `is_valid_git_ref()` check in `run_thread_fix()` before the subprocess call, which breaks the defense-in-depth pattern established elsewhere in the codebase. These are not theoretical — they represent the exact scenario where a bad actor modifies a branch between runs and the agent blindly executes on tampered code. Adding the git ref validation is a 2-line fix; the HEAD SHA check requires storing the SHA in `QueueItem` and comparing before checkout. I recommend both before merge.
