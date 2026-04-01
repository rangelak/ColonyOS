# Review by Staff Security Engineer (Round 3)

All 377 tests pass, no secrets in the diff. Now I have a complete picture. Let me write the review.

---

## Staff Security Engineer Review — Stuck Daemon Detection

### Completeness Assessment

All 7 functional requirements from the PRD are implemented:

| FR | Status | Notes |
|----|--------|-------|
| FR-1: Watchdog Thread | ✅ | `daemon=True` thread, 30s wake interval, independent of `_agent_lock` |
| FR-2: Auto-Recovery | ✅ | Graceful cancel → 30s grace → force cancel → reset state → mark FAILED |
| FR-3: Slack Alert | ✅ | Posts via `_post_slack_message()`, wrapped in try/except |
| FR-4: `started_at` on QueueItem | ✅ | Field added, schema v5, set atomically under `_lock` |
| FR-5: Enhanced `/healthz` | ✅ | `pipeline_started_at`, `pipeline_duration_seconds`, `pipeline_stalled` |
| FR-6: Monitor Event | ✅ | `watchdog_stall_detected` event with correct fields |
| FR-7: Configurable Threshold | ✅ | `watchdog_stall_seconds` with 120s floor, logged at startup |

All 377 tests pass. No linter errors. No secrets or credentials in committed code.

### Security-Specific Analysis

**1. Heartbeat file spoofing — the documented open gap**

The PRD's Security Considerations section (§6) explicitly flagged that a malicious instruction template could keep touching the heartbeat file at `.colonyos/runs/heartbeat` to mask a hang. The dual-gate design (elapsed time AND heartbeat age both must exceed `watchdog_stall_seconds`) mitigates naive stalls but does **not** defend against active spoofing. If a compromised Claude subprocess continuously touches the heartbeat file, the second condition never fires, and the pipeline can run up to `pipeline_timeout_seconds` (2 hours) without the watchdog intervening. PRD Open Question #1 asked about a hard wall-clock ceiling independent of the heartbeat — this was intentionally not implemented for v1. This is a **known, documented gap**, not a missed requirement. Non-blocking for v1 but should be tracked for v2.

**2. `/healthz` information exposure**

The new healthz fields expose: `pipeline_started_at` (ISO timestamp), `pipeline_duration_seconds` (float), `pipeline_stalled` (bool). These are operational metadata, not queue item contents — no `source_value`, no prompt text, no error details leak through healthz. The PRD's security requirement that healthz "must not leak queue item contents or source values" is satisfied. The `item_id` is only emitted in the monitor event (stdout for TUI), not the HTTP healthz endpoint. **Acceptable.**

**3. Watchdog recovery — force-reset under `_lock` is safe**

The Step 4 force-reset (`_watchdog_recover` lines 261-268) correctly acquires `self._lock` before mutating `_pipeline_running`, `_pipeline_started_at`, `_current_running_item`, and the item's status. This is critical — it prevents a race where the main thread's `finally` block and the watchdog thread both write to queue state simultaneously. The potential for a double-write (both the main thread's `finally` and the watchdog resetting the item) is acknowledged in the memory context as a "benign race" that converges on FAILED state. **Acceptable for v1.**

**4. `_post_slack_message()` has no explicit socket timeout**

The Slack alert in `_watchdog_recover` calls `_post_slack_message()` without an explicit timeout parameter. If the Slack API endpoint hangs, the watchdog thread blocks on the Slack call indefinitely. The try/except wrapper catches exceptions but not hangs. The Slack SDK has internal timeouts (typically 30s), and this is wrapped in try/except, so a timeout *will* eventually fire. However, the watchdog is single-threaded — during that 30s hang, no further stall checks occur. This is a **low-severity gap** documented in prior rounds as non-blocking for v1.

**5. Configurable threshold floor enforcement**

The 120-second minimum floor is enforced via clamping (not rejection), with a warning log. This prevents misconfiguration from creating false positives. The clamping approach is appropriate — it's fail-safe rather than fail-hard. **Good.**

**6. No audit trail of watchdog actions beyond logs**

When the watchdog fires, it: (a) logs a warning, (b) posts to Slack, (c) emits a monitor event, (d) marks the item FAILED with an error string containing "watchdog". There is no persistent audit record beyond the queue item's error field and Slack history. For a security-sensitive recovery action (force-canceling a running pipeline), this is minimally adequate for v1. Consider adding a structured event to the daemon state file in v2.

**7. No privilege escalation in recovery path**

The recovery path only calls existing cancellation functions (`request_active_phase_cancel`, `request_cancel`) and mutates in-memory state. It does not spawn new processes, write to disk beyond the queue persist, or escalate privileges. **Clean.**

---

VERDICT: approve

FINDINGS:
- [src/colonyos/daemon.py]: Heartbeat file spoofing remains an open gap — a malicious Claude subprocess can continuously touch `.colonyos/runs/heartbeat` to prevent watchdog detection, relying on the 2-hour `pipeline_timeout_seconds` as the only backstop. Known, documented as PRD Open Question #1. Track for v2 hard wall-clock ceiling.
- [src/colonyos/daemon.py]: `_post_slack_message()` in `_watchdog_recover` has no explicit socket timeout; relies on Slack SDK's internal ~30s timeout. During that window the watchdog thread is blocked and cannot perform further checks. Low severity for v1.
- [src/colonyos/daemon.py]: `/healthz` new fields expose only operational metadata (timestamps, duration, boolean stall flag) — no queue item contents or source values leak. PRD security requirement satisfied.
- [src/colonyos/daemon.py]: Force-reset in Step 4 correctly acquires `_lock` before mutating shared state, preventing data races with the main thread's `finally` block.
- [src/colonyos/config.py]: 120-second minimum floor enforced via clamping with warning log — prevents misconfiguration from creating false-positive stall detections.
- [src/colonyos/daemon.py]: No persistent audit trail of watchdog recovery actions beyond the queue item's error field and Slack message. Consider structured audit events in v2.

SYNTHESIS:
From a security perspective, this implementation is sound for v1. The core threat model — a stuck pipeline blocking the daemon indefinitely — is addressed with appropriate defense-in-depth. The watchdog thread is architecturally isolated from the locks held by stuck pipelines, reads only GIL-safe primitives and filesystem stats, and cannot deadlock. The recovery path uses only existing cancellation infrastructure without privilege escalation. The known gap around heartbeat file spoofing is explicitly documented in the PRD and accepted as a v1 trade-off, with `pipeline_timeout_seconds` serving as the hard backstop. The `/healthz` endpoint additions are clean — no sensitive data leaks. The configurable threshold has an enforced minimum floor. The two items to track for v2 are: (1) a hard wall-clock ceiling independent of heartbeat freshness to close the spoofing gap, and (2) explicit socket timeouts on the Slack alert to prevent the watchdog itself from hanging. Overall, 162 lines of production code across 4 files with 664 lines of tests — the attack surface is small and well-tested.