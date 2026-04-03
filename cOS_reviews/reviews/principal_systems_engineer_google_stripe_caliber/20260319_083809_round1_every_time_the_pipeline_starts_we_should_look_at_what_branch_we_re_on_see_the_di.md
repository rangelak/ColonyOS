# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

Now I have a complete picture. Let me write the review.

---

## Review: Principal Systems Engineer Perspective

### Completeness Assessment

**FR-1 ✅**: `_preflight_check()` added to `orchestrator.py`, called before agent phases.

**FR-2 ✅**: Dirty working tree detection via `git status --porcelain` with actionable error messages listing up to 10 dirty files.

**FR-3 ✅**: Branch existence check reuses `validate_branch_exists()`, then calls `check_open_pr()` for open PRs. Refuses with PR URL and suggests `--resume`.

**FR-4 ✅**: `git fetch origin main` with 5-second timeout, graceful degradation to warnings on failure. `--offline` flag skips.

**FR-5 ✅**: `PreflightResult` dataclass in `models.py` with all specified fields plus `to_dict()`/`from_dict()` for serialization.

**FR-6 ✅**: `preflight` field added to `RunLog`, serialized in `_save_run_log()` and deserialized in `_load_run_log()`.

**FR-7 ⚠️ Partial**: Auto mode catches `click.ClickException` and marks iteration as failed (good), but **Task 5.3 is not implemented** — auto mode does NOT ensure it starts from `main` with `git checkout main && git pull --ff-only` before each iteration. This means auto mode can still start from a stale or wrong branch.

**FR-8 ⚠️ Partial**: `_resume_preflight()` only checks clean working tree. The PRD specifies two checks: (a) working tree clean ✅ and (b) branch HEAD matches RunLog's last known state ❌. The HEAD divergence check is missing entirely.

**FR-9 ✅**: `--offline` flag on both `run` and `auto` commands.

**FR-10 ✅**: `--force` flag on `run` command.

### Quality Assessment

**Tests**: All 996 tests pass, including 16 new preflight tests and 5 new `check_open_pr` tests. Good coverage of happy path, error paths, and edge cases.

**Mock patching inconsistency**: Tests mix `@patch("colonyos.orchestrator.subprocess.run")` (lines 121, 146, 209, 233, 286, 320, 336) with `@patch("subprocess.run")` globally (lines 163, 184, 255). The global patches are needed because `validate_branch_exists()` has its own `subprocess` import, so patching only the orchestrator module's reference doesn't cover it. This works today but is **fragile** — any refactor that changes import style in either module will silently break the mock without test failures (subprocess will call through to real git). The proper fix is to consistently patch at the module level in both modules.

**Task file**: Tasks 5.3 and 7.3 are unchecked. 7.3 is manual testing (acceptable to skip), but 5.3 is a functional gap.

**No commented-out code, no TODOs**: Clean.

**Code follows project conventions**: Uses existing patterns (`_log()`, `click.ClickException`, `subprocess.run` with `capture_output=True`).

### Safety Assessment

**No secrets in committed code**: Clean.

**No destructive operations**: The preflight never modifies the working tree — it only reads state and refuses. This is exactly right.

**Error handling**: All subprocess calls wrapped in try/except for `OSError` and `TimeoutExpired`. `check_open_pr` handles `FileNotFoundError`, `TimeoutExpired`, non-zero return codes, and JSON parse errors. Graceful degradation throughout.

**One race condition concern**: Between the `git status --porcelain` check and the actual pipeline start, a user (or another process) could modify the working tree. This is inherent to any pre-flight check and acceptable — the blast radius is small since the pipeline will just see unexpected files, not lose data.

### Specific Findings

VERDICT: request-changes

FINDINGS:
- [src/colonyos/cli.py]: FR-7/Task 5.3 incomplete — autonomous mode does not ensure it starts from `main` before each iteration. A `git checkout main && git pull --ff-only` sequence (with error handling) should precede the `run_orchestrator()` call in `_run_single_iteration()`. Without this, the auto loop can build on stale or wrong branches, which is one of the core failure modes this PRD exists to prevent.
- [src/colonyos/orchestrator.py]: FR-8 partial — `_resume_preflight()` only validates clean working tree but does not verify branch HEAD matches the RunLog's last recorded state. The PRD explicitly requires this to "detect tampering between runs." Add a HEAD SHA comparison against the RunLog.
- [tests/test_preflight.py]: Inconsistent mock targets — `test_existing_branch_no_pr_refuses`, `test_existing_branch_with_open_pr_refuses_with_url`, and `test_force_bypasses_all_checks` patch `subprocess.run` globally instead of at the module level. This is fragile and masks which modules are actually being called. Should consistently patch `colonyos.orchestrator.subprocess.run` and `colonyos.github.subprocess.run` separately.
- [tests/test_cli.py]: Task file lists "6.1 Write tests for `--offline` and `--force` flags in `tests/test_cli.py`" as complete, but no changes to `test_cli.py` appear in the diff. These CLI flag tests are missing.
- [tests/test_orchestrator.py]: Task file lists "4.1 Write integration tests in `tests/test_orchestrator.py`" as complete, but no changes to `test_orchestrator.py` appear in the diff. Integration tests verifying `run()` calls preflight before Plan phase are missing.

SYNTHESIS:
The core architecture is sound — deterministic pre-flight logic (not an LLM phase), clean separation between state gathering and decision making, graceful degradation on network failures, and actionable error messages. The `PreflightResult` dataclass and its audit trail integration are well-designed. However, two of the three core failure modes the PRD targets are only partially addressed: auto mode can still start from a wrong branch (missing Task 5.3), and resume mode doesn't detect inter-run tampering (missing HEAD SHA check from FR-8). The test gaps in `test_cli.py` and `test_orchestrator.py` are also concerning — tasks are marked complete but no code was written. The mock inconsistency is a quality issue that will bite during future refactoring. None of these are blocking architectural problems; they're incomplete implementations of specified requirements that should be finished before merge.
