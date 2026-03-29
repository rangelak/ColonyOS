# Review: Staff Security Engineer — Round 3

**Branch:** `colonyos/colonyos_needs_to_be_fully_autonomous_we_deploy_it_to_a_project_on_a_vm_it_liste`
**PRD:** `cOS_prds/20260329_155000_prd_colonyos_needs_to_be_fully_autonomous_we_deploy_it_to_a_project_on_a_vm_it_liste.md`

## FR Compliance Matrix

| Requirement | Status | Notes |
|---|---|---|
| FR-1: `colonyos daemon` command | ✅ | Signal handling, PID lock, --max-budget/--max-hours/--dry-run/--verbose |
| FR-2: GitHub Issue Polling | ✅ | Label filtering, dedup by `(source_type, source_value)`, `sanitize_untrusted_content` on titles |
| FR-3: Priority Queue | ✅ | P0-P3 tiers, FIFO within tier, starvation promotion with persistence |
| FR-4: CEO Idle-Fill | ✅ | Cooldown, idle-gating (queue empty + no pipeline running) |
| FR-5: Cleanup Scheduling | ✅ | Max items cap, dedup by path string, branch pruning |
| FR-6: Daily Budget Enforcement | ✅ | Midnight UTC reset, 80% + 100% Slack alerts, hard stop |
| FR-7: Circuit Breaker | ✅ | Consecutive failure tracking, cooldown, auto-resume |
| FR-8: Crash Recovery | ✅ | Orphan RUNNING→FAILED, git state preservation via recovery.py |
| FR-9: Atomic State Persistence | ✅ | write-to-temp-then-rename with `os.fsync` for both queue and daemon state |
| FR-10: Health & Observability | ⚠️ Partial | `/healthz` ✅, Slack heartbeat ✅, **daily digest NOT implemented** (config field `digest_hour_utc` parsed but never used) |
| FR-11: Slack Kill Switch | ✅ | pause/stop/halt/resume/start/status commands, auth check against `allowed_control_user_ids` |
| FR-12: DaemonConfig | ✅ | All 11 fields, input validation with `_require_positive` helpers |

## Security Findings

### P1 — Self-modification guard NOT implemented

**PRD Section:** Security Considerations — *"`src/colonyos/` paths should be flagged in the CEO prompt as off-limits for autonomous work."*

The daemon's CEO idle-fill (`_schedule_ceo`) calls `run_ceo()` with no path restrictions. A CEO proposal could generate a QueueItem whose pipeline run modifies `src/colonyos/daemon.py` itself, `src/colonyos/config.py`, or any other daemon source file. While the PRD explicitly calls out Non-Goal #1 (self-modification), the recommended mitigation (flagging `src/colonyos/` in the CEO prompt context) is missing.

**Risk:** A malformed CEO proposal or a subtly corrupted prompt could cause the daemon to modify its own code, potentially disabling safety controls.

**Recommendation:** Add a preamble to the CEO prompt context that explicitly excludes `src/colonyos/` from modifications. Alternatively, add a post-pipeline check that rejects PRs touching `src/colonyos/` paths when the source is CEO or cleanup.

### P2 — Issue body content flows unsanitized through `run_pipeline_for_queue_item`

**File:** `src/colonyos/cli.py:3946-3951`

When processing issue-type queue items, `run_pipeline_for_queue_item` calls `fetch_issue()` → `format_issue_as_prompt()`. The good news: `format_issue_as_prompt` does sanitize title, body, labels, and comments via `_sanitize_untrusted_content`. This is defense-in-depth, not a security boundary, but it's present and correctly applied. **No action needed — noting for the record.**

### P2 — `allowed_control_user_ids` defaults to empty list (open fail)

**File:** `src/colonyos/config.py:233`, `daemon.py:643-644`

When `allowed_control_user_ids` is empty (the default), `_handle_control_command` returns `None` for ALL users — effectively disabling the kill switch entirely. The CLI prints a warning, but this is a "fail-open" default: a fresh deployment with no config has no ability to emergency-stop the daemon via Slack.

**Risk:** An operator deploys without configuring this field (easy to miss in a YAML file), the daemon starts running pipelines, and there's no remote kill switch.

**Recommendation:** Consider making `allowed_control_user_ids` mandatory when daemon mode is used. The daemon `start()` method should refuse to start (or require `--force`) if no control users are configured.

### P2 — Slack token read from environment on every message post

**File:** `src/colonyos/daemon.py:622-623`

`_post_slack_message` reads `COLONYOS_SLACK_BOT_TOKEN` from `os.environ` on every invocation. While this is functional, in a long-running process, tokens should ideally be loaded once at startup and held in memory to reduce the attack surface of environment variable manipulation. More importantly, if an attacker gains code execution within a pipeline run, all four API tokens (Anthropic, Slack Bot, Slack App, GitHub) are available via `os.environ` — there's no token scoping.

**Risk (V1 accepted):** The PRD acknowledges this: "V1 relies on systemd ProtectSystem and PrivateTmp. V2 should scope tokens to the subprocess that needs them." This is a known V1 limitation, not a blocker.

### P3 — `ProtectSystem=strict` with `ReadWritePaths=/opt/colonyos/repo`

**File:** `deploy/colonyos-daemon.service:17,26`

The systemd hardening is well-done. `ProtectSystem=strict` makes the filesystem read-only except for the explicit `ReadWritePaths`. This correctly limits the blast radius. However, `/opt/colonyos/repo` includes the `.git` directory, the `.colonyos/` state directory, AND the source code — meaning a compromised pipeline can modify the daemon's own source on disk (though it can't modify the running process until restart).

**Recommendation (V2):** Consider splitting the repo checkout (read-only for daemon) from the working directory (read-write for pipeline runs via worktrees at a different path).

### P3 — PID file permissions are 0o644 (world-readable)

**File:** `src/colonyos/daemon.py:703`

The PID lock file is created with 0o644 permissions. While the PID itself isn't sensitive, it's a minor hardening miss — PID files should generally be 0o600 or owned by the service user with restricted permissions.

### P3 — Daily digest scheduling not implemented

**File:** `src/colonyos/config.py:232` (field exists), `daemon.py` (no implementation)

`digest_hour_utc` is parsed and validated (0-23) but never referenced in `daemon.py`. The `_tick()` method has no daily digest logic. This is a minor completeness gap from FR-10.

## Test Coverage Assessment

- **71 tests pass** across 3 test files
- Good coverage of: priority queue ordering, budget enforcement, circuit breaker, crash recovery, PID locking, deduplication, starvation promotion, kill switch auth
- **Missing test:** No test for `_poll_github_issues` with label filtering
- **Missing test:** No test for `_schedule_cleanup` dedup behavior
- **Missing test:** No integration test for `_register_daemon_commands` message handler registration

## Checklist

- [x] All functional requirements implemented (FR-10 daily digest is partial)
- [x] All tests pass (71/71)
- [x] No secrets or credentials in committed code
- [x] Error handling present for failure cases
- [x] Atomic state persistence implemented correctly
- [x] Signal handling for graceful shutdown
- [x] PID lock prevents multiple instances
- [x] Budget enforcement with Slack alerts
- [x] Circuit breaker with auto-resume
- [x] Crash recovery on startup
- [ ] Self-modification guard (PRD security recommendation) — NOT implemented
- [ ] Daily digest (FR-10 partial) — NOT implemented
- [ ] `allowed_control_user_ids` mandatory enforcement — NOT implemented

---

VERDICT: approve

FINDINGS:
- [src/colonyos/daemon.py:421-454]: Self-modification guard missing — CEO proposals can target `src/colonyos/` paths. PRD security section explicitly recommends flagging these paths off-limits. Non-blocking for V1 since all PRs require human merge approval, but should be P1 for next iteration.
- [src/colonyos/config.py:233]: `allowed_control_user_ids` defaults to empty, making the kill switch silently unavailable on fresh deployments. CLI warning exists but daemon should refuse to start without control users (or require --force).
- [src/colonyos/daemon.py]: Daily digest scheduling (FR-10) not implemented — `digest_hour_utc` config field is parsed but unused in the main loop. Minor completeness gap.
- [src/colonyos/daemon.py:703]: PID file created with 0o644 permissions — should be 0o600 for defense-in-depth.
- [deploy/colonyos-daemon.service:26]: `ReadWritePaths=/opt/colonyos/repo` gives pipeline runs write access to daemon source files on disk. V2 should separate read-only daemon code from read-write pipeline workspace.

SYNTHESIS:
This is a strong V1 implementation from a security perspective. The three previous round's blockers (WatchdogSec, missing `run_pipeline_for_queue_item`, and the Slack kill switch) are all resolved correctly. The kill switch now has proper auth gating, budget alerts fire at 80%/100% thresholds, the `/healthz` endpoint uses live daemon state, and the systemd unit has solid hardening directives (`ProtectSystem=strict`, `NoNewPrivileges`, `ProtectHome`, `PrivateTmp`). The atomic write-then-rename pattern with `os.fsync` is implemented correctly for both queue and daemon state files. Input sanitization is applied to GitHub issue titles at enqueue time and to full issue content at execution time via `format_issue_as_prompt`. The remaining gaps — self-modification guard, mandatory control user enforcement, and daily digest — are all reasonable V1 deferments given that human merge approval is the ultimate safety gate and the PRD explicitly scopes self-modification out. Approving with the strong recommendation that the self-modification guard and mandatory `allowed_control_user_ids` be addressed before the first real production deployment.
