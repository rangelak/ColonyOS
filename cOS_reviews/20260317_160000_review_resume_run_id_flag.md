# Review: Resume Failed Runs via `--resume <run-id>`

**Reviewer**: Principal Systems Engineer (Google/Stripe caliber)
**Branch**: `colonyos/add_a_resume_run_id_flag_to_colonyos_run_that_resumes_a_previously_failed_run_fr`
**PRD**: `cOS_prds/20260317_155508_prd_add_a_resume_run_id_flag_to_colonyos_run_that_resumes_a_previously_failed_run_fr.md`

## Checklist

### Completeness
- [x] FR-1: RunLog extended with `branch_name`, `prd_rel`, `task_rel` fields
- [x] FR-2: `--resume` CLI option added with mutual exclusivity checks
- [x] FR-3: Phase resumption logic with `resume_from` parameter and skip guards
- [x] FR-4: Run log continuity — reuses original RunLog, appends new phases
- [x] FR-5: Precondition validation (status, branch, PRD, task file)
- [x] FR-6: `[resumable]` tag in `colonyos status`
- [x] FR-7: Comprehensive tests for all requirements

### Quality
- [x] All 198 tests pass
- [x] No linter errors observed
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies added (only stdlib: `subprocess`)
- [x] No TODOs or placeholder code in shipped files

### Safety
- [x] Path traversal protection on run_id (`_validate_run_id`)
- [x] Path containment validation for `prd_rel`/`task_rel` (`_validate_rel_path`)
- [x] Git `--` argument termination prevents branch name injection
- [x] No secrets or credentials in committed code
- [x] Error handling present for all failure cases

## Detailed Findings

### Strengths

1. **Security-in-depth**: The `_validate_run_id()`, `_validate_rel_path()`, and `--` git argument termination are beyond what the PRD required. This is exactly the kind of defensive coding I want to see in a system that reads user-supplied identifiers from disk and constructs file paths from JSON content.

2. **Audit trail**: The `resume_events` list with ISO timestamps goes beyond the PRD scope (which only asked for run log continuity). This is valuable for debugging at 3am — I can see exactly when each resume happened.

3. **Clean separation of concerns**: `prepare_resume()` as the public API with `_load_run_log()` and `_validate_resume_preconditions()` as internal helpers is good layering. The CLI stays thin and the orchestrator owns the domain logic.

4. **Test coverage**: Excellent coverage including edge cases (empty run ID, path traversal, git branch name injection, no successful phases, old logs without resume fields). The E2E test for log continuity verifying both in-memory and on-disk state is particularly good.

### Minor Observations (Non-blocking)

1. **`_SKIP_MAP` with `"decision"` key includes `{"plan", "implement", "review"}`**: When resuming after a successful decision phase, the review phase is in `skip_phases`, so the `elif config.phases.review:` block is skipped entirely (correct — review already passed). The deliver phase is not in skip_phases, so it runs. This works correctly but the skip logic is implicit — the mapping silently depends on the fact that deliver is never explicitly guarded by skip_phases but rather always falls through. A comment clarifying this invariant would help future maintainers.

2. **`_save_run_log` re-reads its own file on every save to preserve `resume_events`**: This is a read-modify-write pattern. In a single-process CLI tool this is fine, but if ColonyOS ever moves to concurrent runs writing the same log file (unlikely for same run_id, but worth noting), this could produce lost writes. Acceptable for v1.

3. **`ResumeState` as a typed dataclass vs raw dict**: The PRD specified `resume_from: dict | None`, but the implementation uses a proper `ResumeState` dataclass. This is strictly better — type safety, IDE support, and prevents misspelled keys. Good deviation from the PRD.

4. **Branch contains unrelated changes**: The diff includes significant changes from other features (CEO phase, fix loop redesign, decision gate, parallel reviews). The resume feature builds on top of these correctly, but the branch is much larger than a single-feature branch should be. This doesn't affect the resume implementation quality but makes reviewing harder.

## Verdict

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py]: `_SKIP_MAP` relies on implicit invariant that deliver is never skip-guarded; a clarifying comment would help
- [src/colonyos/orchestrator.py]: `_save_run_log` read-modify-write on `resume_events` is fine for single-process but worth noting for future concurrency
- [src/colonyos/models.py]: `ResumeState` dataclass is a good improvement over the PRD's `dict` specification
- [src/colonyos/orchestrator.py]: Path traversal protection (`_validate_run_id`, `_validate_rel_path`, `--` termination) is excellent security hardening
- [tests/test_orchestrator.py]: Comprehensive test coverage including security edge cases (path traversal, branch name injection)

SYNTHESIS:
This is a well-executed implementation that meets all PRD requirements with several valuable extras (audit trail, path traversal protection, typed ResumeState). The phase-skip logic is correct and tested across all phase boundaries. The error messages are clear and actionable — if this fails at 3am, the operator will know exactly what to fix. The run log continuity is properly maintained with both in-memory object reuse and on-disk JSON persistence. The only structural concern is that the branch carries several unrelated features, but the resume-specific changes are clean, well-isolated, and thoroughly tested. Ship it.
