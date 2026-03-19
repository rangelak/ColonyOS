# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 3)

I now have a complete picture. Here is my review:

---

## Review: Principal Systems Engineer Perspective

### Checklist Assessment

**Completeness:**
- [x] **FR-1**: `_preflight_check()` added to `orchestrator.py`, called before agent phases ✅
- [x] **FR-2**: Dirty working tree detection via `git status --porcelain` with actionable error ✅
- [x] **FR-3**: Branch existence check + open PR detection via `gh pr list` ✅
- [x] **FR-4**: `git fetch origin main` with 5s timeout, graceful degradation ✅
- [x] **FR-5**: `PreflightResult` dataclass in `models.py` with all specified fields ✅
- [x] **FR-6**: `PreflightResult` stored on `RunLog`, serialized to JSON ✅
- [x] **FR-7**: Auto mode: `_ensure_on_main()` + `PreflightError` catch → mark failed, continue ✅
- [x] **FR-8**: Resume: `_resume_preflight()` checks clean tree + HEAD SHA divergence ✅
- [x] **FR-9**: `--offline` flag on both `run` and `auto` CLI commands ✅
- [x] **FR-10**: `--force` flag on `run` command ✅

**Quality:**
- [x] All 319 tests pass (44 new preflight tests + 275 existing)
- [x] Code follows existing patterns (subprocess usage, `click.ClickException`, dataclass serialization)
- [x] No unnecessary dependencies — uses only `git` and `gh` already in the project
- [x] No unrelated changes (only existing test fixtures updated for git init)

**Safety:**
- [x] No secrets in code
- [x] Fail-closed on `git status` errors (non-zero exit, timeout, OSError all raise `PreflightError`)
- [x] Never auto-stashes, auto-commits, or auto-resolves — always refuses with actionable message
- [x] HEAD SHA tracking for tamper detection on resume

### Findings

- [src/colonyos/orchestrator.py]: **TOCTOU race on branch existence check** — Between `validate_branch_exists()` returning false and the actual branch creation later in the pipeline, another process could create the branch. Low probability in practice since this is a single-user tool, but worth noting. The `--force` flag mitigates if it happens.

- [src/colonyos/orchestrator.py]: **`_get_head_sha` silently swallows failures** — Returns empty string on error, which means `_resume_preflight` will skip the SHA divergence check if `rev-parse HEAD` fails. This is fail-open for the SHA check specifically. The clean-tree check is still fail-closed, so the blast radius is limited to tamper detection.

- [src/colonyos/cli.py]: **`_ensure_on_main` does `git pull --ff-only`** — If this fails (e.g., diverged history), it only warns and continues. This is the right call — a warning-only approach avoids blocking the auto loop on a transient state. However, the auto loop then proceeds with a potentially stale main, which is the exact scenario preflight is trying to prevent. Consider whether this should be a hard failure in auto mode.

- [src/colonyos/orchestrator.py]: **`_save_run_log` mutates `log.preflight.head_sha`** — The save function has a side effect of updating `head_sha` to current HEAD. This is clever (captures post-phase state for resume validation), but mutating state inside a "save" function violates separation of concerns. A comment documents the intent, so this is acceptable for V1.

- [src/colonyos/cli.py]: **`--offline` not passed through in `_run_single_iteration`** — The `offline` parameter is added to `_run_single_iteration`'s signature and passed to `run_orchestrator`, but `_ensure_on_main()` is called unconditionally before it. In offline mode, `_ensure_on_main` will still attempt `git checkout main` and `git pull --ff-only`, which both require network. The `--offline` flag should suppress the pull.

- [tests/test_preflight.py]: **Comprehensive test coverage** — 607 lines of well-structured tests covering happy paths, error paths, force bypass, offline mode, timeout degradation, fail-closed behavior, and serialization roundtrips. The test structure (mocked subprocess, separated concerns) follows the PRD's testing guidance precisely.

VERDICT: approve

FINDINGS:
- [src/colonyos/cli.py]: `_ensure_on_main()` runs `git pull --ff-only` even in `--offline` mode — the network call should be gated on the offline flag
- [src/colonyos/orchestrator.py]: `_get_head_sha` returns empty string on failure, making the resume SHA divergence check fail-open (tamper detection bypass); the clean-tree check remains fail-closed so blast radius is limited
- [src/colonyos/orchestrator.py]: `_save_run_log` mutates `log.preflight.head_sha` as a side effect — acceptable for V1 but should be refactored to explicit state updates in the orchestration flow
- [src/colonyos/orchestrator.py]: Minor TOCTOU window between branch existence check and later branch creation — acceptable for single-user CLI tool
- [tests/test_preflight.py]: Excellent test coverage (607 lines, 44 tests) with proper fail-closed verification and graceful degradation scenarios

SYNTHESIS:
This is a solid, well-engineered implementation that addresses a real operational pain point. The architecture decisions are sound: procedural logic (not LLM), `PreflightError` as a `ClickException` subclass for clean catch in auto mode, fail-closed on git status, and graceful degradation on network failures. The one issue I'd flag for a fast follow-up is the `--offline` flag not suppressing `git pull` in `_ensure_on_main` — in an air-gapped environment, the auto loop will emit spurious warnings every iteration, which degrades the signal-to-noise ratio in logs. The SHA tracking in `_save_run_log` is clever but the mutation-in-save pattern should be cleaned up before it becomes a footgun. Overall, this is the kind of defensive infrastructure that pays for itself the first time it prevents a wasted $5 agent run on a dirty working tree. Approving with the `--offline` gap noted as a low-severity follow-up.