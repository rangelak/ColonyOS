# Review by Staff Security Engineer (Round 1)

Now I have a complete picture. Let me write my review.

---

## Security Review: Git State Pre-flight Check

### Checklist Assessment

**Completeness:**
- [x] FR-1: `_preflight_check()` function added in orchestrator.py ✅
- [x] FR-2: Dirty working tree check with `git status --porcelain` ✅
- [x] FR-3: Existing branch + open PR detection ✅
- [x] FR-4: `git fetch origin main` with 5s timeout + staleness check ✅
- [x] FR-5: `PreflightResult` dataclass added to models.py ✅
- [x] FR-6: `PreflightResult` stored on `RunLog` and serialized/deserialized ✅
- [x] FR-7: Autonomous mode catches pre-flight failures and continues ✅
- [ ] FR-8: Resume pre-flight partially implemented — **missing HEAD SHA divergence check** (PRD says: "branch HEAD hasn't diverged from what the RunLog recorded")
- [x] FR-9: `--offline` flag on `run` and `auto` CLI commands ✅
- [x] FR-10: `--force` flag on `run` CLI command ✅

**Quality:**
- [x] All 21 new tests pass
- [ ] Inconsistent mock patching (some tests patch `subprocess.run` globally, others patch `colonyos.orchestrator.subprocess.run`)
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies
- [x] No unrelated changes

**Safety:**
- [x] No secrets or credentials in committed code
- [x] No destructive operations
- [x] Error handling present for failure cases (timeouts, missing tools, etc.)

### Security-Specific Findings

VERDICT: request-changes

FINDINGS:
- [src/colonyos/orchestrator.py]: `_resume_preflight()` does not validate branch HEAD SHA against RunLog (FR-8b). This was specifically called out in the PRD as a tampering detection mechanism — an attacker (or stale state) could modify the branch between resume runs and the pipeline would blindly continue on tampered code. The PRD explicitly requires checking "branch HEAD hasn't diverged from what the RunLog recorded."
- [src/colonyos/models.py]: `PreflightResult.from_dict()` defaults `is_clean=True` and `branch_exists=False` when keys are missing. This is a **fail-open** deserialization pattern — corrupted or tampered run log data silently produces a "clean, safe" result instead of raising an error. At minimum, `current_branch`, `is_clean`, and `branch_exists` should be required keys; missing them should raise `ValueError`.
- [tests/test_preflight.py]: Lines 163, 184, 255 patch `subprocess.run` globally instead of `colonyos.orchestrator.subprocess.run` (which the other tests use). This inconsistency means the `check_open_pr` call inside `_preflight_check` is intercepted via a different mechanism than other subprocess calls. While tests pass today, this makes them fragile — a future refactor could silently break coverage. All tests should consistently patch `colonyos.orchestrator.subprocess.run` and separately mock `colonyos.github.check_open_pr` for the branch-exists cases.
- [src/colonyos/orchestrator.py]: `_preflight_check` calls `validate_branch_exists()` which internally runs `subprocess.run(["git", "branch", "--list", branch_name])` but this call is NOT covered by the mock in tests that patch `colonyos.orchestrator.subprocess.run` — it works because `validate_branch_exists` also lives in `orchestrator.py` and shares the module's `subprocess`. However, the function's own `git branch --list` behavior should be explicitly tested to ensure the branch name is safely handled (e.g., glob characters in branch names — `git branch --list` treats its argument as a glob pattern, so a branch name containing `*` or `?` could match unintended branches).
- [src/colonyos/cli.py]: `--force` is correctly NOT exposed on `colonyos auto`. Good — this prevents autonomous mode from bypassing safety checks.

SYNTHESIS:
From a supply-chain and least-privilege perspective, this implementation is fundamentally sound: it adds a deterministic, non-LLM gate that blocks the pipeline before burning agent dollars or executing code on a dirty/ambiguous repo state. The `--force` flag is correctly restricted from autonomous mode, subprocess calls use list-form (no shell injection), and error messages are actionable without leaking sensitive data. However, there are two security gaps I'd want addressed before approval: (1) the missing HEAD SHA divergence check in resume mode is the PRD's only anti-tampering mechanism between runs — without it, an attacker who gains temporary write access to the branch between resume runs can inject malicious code that the pipeline will execute with `bypassPermissions`; and (2) the fail-open `from_dict` deserialization means a corrupted run log could silently report a clean pre-flight state, undermining the audit trail that was a key design goal. The test inconsistencies are a secondary concern but should be cleaned up to ensure the safety checks are actually being exercised through the correct code paths.
