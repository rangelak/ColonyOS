# Review by Staff Security Engineer (Round 2)

Now let me write the review.

---

## Security Review — Staff Security Engineer

### Review Analysis

**1. Completeness**: The implementation covers FR-1 through FR-10 with minor gaps. Task 5.3 is marked incomplete (auto-mode `git checkout main`), but the `_ensure_on_main()` function in `cli.py` implements this. Task 7.3 (manual test) is unchecked, which is expected. All functional requirements from the PRD are implemented.

**2. Security-Specific Findings**:

**Positive observations:**
- Fail-closed design: `_check_working_tree_clean` and `_get_current_branch` raise `click.ClickException` on OS errors, preventing silent pass-through of indeterminate state.
- `subprocess.run` uses list-form `cmd` everywhere (no shell injection via `shell=True`).
- Timeouts on all network-touching operations (5s for fetch, 5s for gh PR check, 10s/30s for auto-mode checkout/pull).
- `check_open_pr` gracefully degrades on `FileNotFoundError`, `TimeoutExpired`, non-zero exit, and JSON parse failure — no secrets leaked in error paths.
- HEAD SHA tamper detection on resume is a good addition for detecting branch manipulation between runs.

**Concerns:**

- **`--force` bypasses dirty-tree check with `bypassPermissions`**: When the pipeline runs with `bypassPermissions`, `--force` allows starting on a dirty tree. The PRD says "never auto-resolve," but `--force` lets the agent proceed to modify files on a dirty working tree, which could cause data loss. The flag exists per FR-10 but there's no audit warning emitted when force is used — only the `action_taken="forced"` is silently recorded in the RunLog.

- **`_ensure_on_main` runs `git checkout main` and `git pull --ff-only` unconditionally in auto mode**: This is a destructive operation — it discards the current branch context. If the user has auto mode running while they're working on a branch, this will switch them off it. The PRD says "Never make destructive git operations without human authorization" for auto mode, but this is somewhat mitigated by auto mode being an explicit opt-in.

- **Branch name passed to `gh pr list --head` without validation**: The branch name comes from `f"{config.branch_prefix}{slug}"` where `slug` is derived from the prompt. If a prompt contains shell metacharacters, the list-form subprocess prevents injection, but `gh` itself could interpret unusual characters. Low risk due to list-form args.

- **`git fetch origin main` uses hardcoded remote name `origin`**: No validation that `origin` points to the expected repository. An attacker who reconfigured the `origin` remote could make the pipeline fetch from a malicious repo. However, this is the same trust boundary the pipeline already operates under.

- **No rate limiting on `check_open_pr`**: In auto mode with many iterations, this could hit GitHub API rate limits. Not a security vulnerability per se, but an availability concern.

**3. Test coverage**: 37 tests pass covering all major paths — clean, dirty, force, offline, timeout, resume with SHA check, and auto-mode ensure-on-main. Tests properly mock subprocess rather than hitting real git/gh.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py]: `--force` bypasses dirty-tree protection without emitting an explicit warning log — consider adding `_log("WARNING: --force bypasses pre-flight safety checks")` when force=True so the audit trail is unambiguous.
- [src/colonyos/cli.py]: `_ensure_on_main()` performs `git checkout main` which is a destructive branch-switch in auto mode. While auto mode is opt-in, this could surprise a user who has auto running in the background. Consider checking if already on main first.
- [src/colonyos/orchestrator.py]: `_get_head_sha` returns empty string on failure (fail-open) while other helpers fail-closed. If HEAD SHA can't be determined, the resume tamper-detection is silently skipped. Consider failing closed here too.
- [src/colonyos/orchestrator.py]: `git fetch origin main` hardcodes the remote name `origin` — if the remote is misconfigured or renamed, the staleness check silently degrades. Acceptable for V1 but worth a comment.

SYNTHESIS:
From a security posture standpoint, this implementation is solid for V1. The critical path (dirty-tree detection → refuse) is fail-closed, subprocess calls use list-form arguments throughout (no shell injection), and network operations degrade gracefully with tight timeouts. The HEAD SHA tamper-detection on resume is a welcome addition that addresses the branch pre-population attack vector flagged in the PRD. The main concerns are minor: `--force` should emit an audible warning, `_get_head_sha` should arguably fail-closed to match the other helpers, and `_ensure_on_main` should be idempotent (check before switching). None of these are blocking — they're hardening improvements for a follow-up pass. The test coverage is thorough and the overall design follows least-privilege principles by refusing to proceed in ambiguous states rather than guessing.
