# Staff Security Engineer — Review Round 3 (Thread Fix Feature)

**Branch:** `colonyos/you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following`
**PRD:** `cOS_prds/20260319_152207_prd_you_are_a_code_assistant_working_on_behalf_of_the_engineering_team_the_following.md`
**Date:** 2026-03-19

---

## Checklist Assessment

### Completeness

- [x] **FR-1** `should_process_thread_fix()` implemented in `slack.py` — checks `thread_ts != ts`, bot mention, completed parent QueueItem
- [x] **FR-2** `should_process_message()` untouched — separate code path confirmed
- [x] **FR-3** Thread fix respects `allowed_user_ids` allowlist
- [x] **FR-4** Parent lookup via `find_parent_queue_item()` scanning `QueueState.items`
- [x] **FR-5** `branch_name` field added to `QueueItem`
- [x] **FR-6** `fix_rounds` counter on `QueueItem`
- [x] **FR-7** `run_thread_fix()` validates branch, checks open PR, verifies HEAD SHA
- [x] **FR-8** Plan phase skipped in thread-fix pipeline
- [x] **FR-9** Triage skipped for thread fixes
- [x] **FR-10** `:eyes:` reaction + acknowledgment message
- [x] **FR-11** Phase updates via existing `SlackUI`
- [x] **FR-12** Fix run summary with cost
- [x] **FR-13** Error messages for branch deleted, PR merged, max rounds
- [x] **FR-14** `max_fix_rounds_per_thread` in `SlackConfig` (default 3)
- [x] **FR-15** Fix requests count against daily budget and rate limits
- [x] **FR-16** Per-phase budget cap reused
- [x] **FR-17** Max rounds message with cumulative cost
- [x] **FR-18** Thread reply text passes through `sanitize_slack_content()` via `format_slack_as_prompt()`
- [x] **FR-19** Fix instructions wrapped with role-anchoring preamble
- [x] **FR-20** `strip_slack_links()` added to sanitization pipeline
- [x] **FR-21** `thread_ts` validated against completed QueueItem before any agent work

### Quality

- [x] All 456 tests pass
- [x] Code follows existing conventions (dataclass models, phase-sync pattern)
- [x] No unnecessary dependencies added
- [x] Thread-fix template follows existing instruction template patterns

### Safety

- [x] No secrets or credentials in committed code (tokens read from env vars, `.env` in `.gitignore`)
- [x] Git ref validation (`is_valid_git_ref`) rejects shell metacharacters, path traversal (`..`), newlines, backticks
- [x] Branch name validated at point of use in `run_thread_fix()` (defense-in-depth, not just at entry)
- [x] HEAD SHA verification prevents force-push tampering
- [x] `format_slack_as_prompt()` applies role-anchoring preamble to reduce prompt injection effectiveness
- [x] `strip_slack_links()` strips `<URL|display_text>` Slack markup (FR-20)
- [x] Triage agent uses `allowed_tools=[]` — no tool access for the LLM during triage
- [x] Fix round counter prevents unbounded iteration

---

## Security Findings

### Positive

- **[src/colonyos/slack.py]**: `is_valid_git_ref()` strict allowlist (`[a-zA-Z0-9._/-]`) with `..` rejection and length cap (255). This is the right approach — allowlist over denylist.
- **[src/colonyos/orchestrator.py]**: Defense-in-depth — `run_thread_fix()` re-validates `branch_name` even though callers should already validate. Good.
- **[src/colonyos/orchestrator.py]**: HEAD SHA comparison before executing fixes prevents a class of TOCTOU attacks where an attacker force-pushes malicious code between the user's fix request and the agent checkout.
- **[src/colonyos/sanitize.py]**: `strip_slack_links()` correctly handles the `<URL|display_text>` attack vector — the URL is discarded, only display text kept. Order of operations is correct (strip links first, then strip XML tags).
- **[src/colonyos/slack.py]**: Triage LLM call uses `budget_usd=0.05` and `allowed_tools=[]` — minimal blast radius if prompt injection occurs during triage.
- **[src/colonyos/cli.py]**: `_handle_thread_fix` acquires `state_lock` before reading/mutating `fix_rounds` and queue state — race condition between concurrent Slack events is handled.

### Concerns (Low Severity)

- **[src/colonyos/cli.py]**: The `_load_dotenv()` function loads `.env` with `override=False`, which is the safe default. However, this runs on every CLI invocation. If a malicious `.env` exists in a cloned repo, it could set environment variables that affect agent behavior (e.g., `ANTHROPIC_API_KEY`). This is pre-existing and not introduced by this PR, but worth noting for the audit trail.
- **[src/colonyos/sanitize.py]**: `strip_slack_links` regex `_SLACK_LINK_RE` uses `<([^|>]+)\|([^>]+)>` which is greedy on the display text portion. A crafted input like `<url|text>more<url2|text2>` would work correctly due to `[^>]+` stopping at `>`, but deeply nested angle brackets could theoretically cause edge cases. The current implementation is safe for Slack's actual markup format.
- **[src/colonyos/orchestrator.py]**: The `run_thread_fix()` finally block restores the original branch but only logs a warning on failure. In a watch loop, if branch restoration fails, subsequent queue items could execute on the wrong branch. This is mitigated by the pipeline semaphore (only one concurrent run), but a stale checkout could persist.
- **[src/colonyos/instructions/thread_fix.md]**: The instruction template includes `{original_prompt}` and `{fix_request}` directly in the system prompt. While these pass through `sanitize_slack_content()` before reaching `format_slack_as_prompt()`, the thread-fix template injects them into the *system* prompt rather than the user prompt. An attacker who controls the original Slack message could craft content that, after sanitization, still influences agent behavior through the system prompt context. The role-anchoring preamble in `format_slack_as_prompt()` helps, but the thread-fix template re-injects the content at a different trust boundary. **Recommendation**: Consider keeping user-supplied content strictly in the user prompt, not the system prompt.

### Not Yet Addressed (PRD Open Questions)

- **Artifact integrity** (`prd_sha256`/`task_sha256`): Not implemented. PRD acknowledged this as a fast-follow. A malicious actor with repo write access could modify the PRD/task files between the original run and the fix request, causing the agent to execute different instructions than what was originally approved. The HEAD SHA check partially mitigates this (it catches force-pushes on the feature branch), but not modifications to PRD files on other branches.
- **Audit logging of stripped URLs**: FR-20 strips URLs from Slack links but does not log them. The PRD's open question #3 asked whether URLs should be logged for audit. Currently they are silently discarded. For forensic analysis after an incident, having the original URLs would be valuable.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/thread_fix.md]: User-supplied content (`original_prompt`, `fix_request`) is injected into the system prompt via template formatting. Consider keeping untrusted content in the user prompt only to maintain trust boundary separation. Low severity — sanitization is applied, but defense-in-depth favors stricter separation.
- [src/colonyos/sanitize.py]: Stripped Slack URLs are silently discarded without logging. For security audit trails, consider logging the original URL before stripping. Informational only.
- [src/colonyos/orchestrator.py]: Branch restoration failure in `run_thread_fix()` finally block only logs a warning. In watch mode, a failed restoration could leave the repo on the wrong branch for the next queue item. Low severity — pipeline semaphore limits blast radius.
- [PRD open question]: `prd_sha256`/`task_sha256` artifact integrity verification not implemented. Acknowledged as fast-follow in PRD. Recommend prioritizing this for the next iteration.

SYNTHESIS:
This implementation demonstrates strong security awareness throughout. The sanitization pipeline is correctly applied to thread-fix requests (FR-18 through FR-21), with `strip_slack_links()` closing the Slack URL markup attack vector. Git ref validation uses a strict allowlist approach rather than a denylist, which is the correct pattern. HEAD SHA verification (FR-7) provides meaningful protection against force-push TOCTOU attacks. The triage agent's zero-tool-access constraint minimizes prompt injection blast radius. Thread safety is handled via `state_lock` for shared state mutations. The main area for improvement is the trust boundary between system and user prompts in the thread-fix template — user-supplied content should ideally stay in the user prompt. The missing artifact integrity checks (SHA hashes for PRD/task files) represent the most significant residual risk, as they would prevent a class of attacks where an adversary modifies planning artifacts between the original run and a fix request. Overall, this is a well-implemented feature with appropriate security controls for an MVP. Approved with recommendations for the next iteration.
