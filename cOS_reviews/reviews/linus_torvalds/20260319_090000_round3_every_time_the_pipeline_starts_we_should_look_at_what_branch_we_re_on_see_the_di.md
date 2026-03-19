# Review: Git State Pre-flight Check — Round 3

**Reviewer**: Linus Torvalds
**Branch**: `colonyos/every_time_the_pipeline_starts_we_should_look_at_what_branch_we_re_on_see_the_di`
**PRD**: `cOS_prds/20260319_081958_prd_every_time_the_pipeline_starts_we_should_look_at_what_branch_we_re_on_see_the_di.md`

## Assessment

### Completeness

All 10 functional requirements from the PRD are implemented:

- **FR-1** (preflight function): `_preflight_check()` in orchestrator.py — done
- **FR-2** (uncommitted changes): `_check_working_tree_clean()` + raise on dirty — done
- **FR-3** (existing branch + open PR): `validate_branch_exists()` + `check_open_pr()` — done
- **FR-4** (stale main): `git fetch` with 5s timeout + `rev-list --count` — done
- **FR-5** (PreflightResult dataclass): In models.py with all specified fields — done
- **FR-6** (store on RunLog): `log.preflight` field, serialized in `_save_run_log` — done
- **FR-7** (autonomous mode): `_ensure_on_main()` + `PreflightError` catch in `_run_single_iteration()` — done
- **FR-8** (resume skip): `_resume_preflight()` with clean-tree + HEAD SHA check — done
- **FR-9** (`--offline` flag): On both `run` and `auto` commands — done
- **FR-10** (`--force` flag): On `run` command — done

All tasks in the task file are marked complete except 7.3 (manual testing), which is expected.

### Code Quality

The code is straightforward and does the obvious thing. No premature abstractions. The data structures are clean — `PreflightResult` is a plain dataclass with `to_dict()`/`from_dict()`, no ORM garbage, no metaclass magic.

Good decisions:
- Fail-closed on `git status` errors (non-zero returncode raises, not silently passes)
- `PreflightError` as a `ClickException` subclass so auto-mode can catch it specifically
- `_get_head_sha()` returns empty string on failure rather than raising — appropriate for a non-critical helper
- The `_check_working_tree_clean()` function is separated from the decision logic, making it testable
- The `check_open_pr()` function gracefully degrades on every failure mode (timeout, missing `gh`, bad JSON)

The test suite is comprehensive: 44 dedicated preflight tests covering happy paths, error paths, timeout degradation, force bypass, offline mode, resume divergence, and fail-closed semantics. All 275 tests pass.

### Minor Observations

1. The `_save_run_log` function mutates `log.preflight.head_sha` as a side effect of saving. This is a bit sneaky — updating the HEAD SHA to "current" state during serialization means the in-memory object changes as a side effect of a save operation. It works, but it couples the save path to state mutation. Acceptable for V1.

2. In `_ensure_on_main()`, the `git pull --ff-only` failure is a warning, not an error. This is the right call — you don't want to halt the auto loop because the network blipped during pull.

3. The existing test fixtures (`tmp_repo` in test_ceo.py and test_orchestrator.py) needed real git repos initialized. The fix is clean — `.gitignore` for colonyos working dirs to keep the tree clean during tests. Pragmatic.

### Safety

- No secrets or credentials in committed code
- No destructive operations — the preflight only reads git state, never mutates (except `git fetch` which is safe)
- `_ensure_on_main()` does `git checkout main` but only in auto mode, which is the documented behavior
- Error handling covers all subprocess failure modes: OSError, TimeoutExpired, non-zero exit codes

## Verdict

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py]: `_save_run_log` mutates `log.preflight.head_sha` as side effect of save — minor coupling concern, acceptable for V1
- [src/colonyos/orchestrator.py]: Dirty file list truncated at 10 entries — good UX decision for repos with many uncommitted files
- [src/colonyos/cli.py]: `_ensure_on_main()` correctly treats pull failure as warning, checkout failure as fatal — right priority ordering
- [tests/test_preflight.py]: 607 lines of tests for ~220 lines of implementation — appropriate coverage ratio for safety-critical code

SYNTHESIS:
This is a clean, well-structured implementation that does exactly what the PRD asks for and nothing more. The code is procedural where it should be procedural — no LLM calls, no over-engineered abstractions. The fail-closed semantics on git status errors are correct (if you can't determine state, refuse to proceed). The separation between state-gathering helpers and decision logic makes the code testable and the tests comprehensive. The `PreflightError` subclass is a good design — it lets autonomous mode catch preflight failures specifically without swallowing unrelated exceptions. The only nit is the head_sha mutation in `_save_run_log`, but that's a minor coupling issue, not a correctness bug. Ship it.
