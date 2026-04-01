# Tasks: Pre-Delivery Test Verification Phase

## Relevant Files

- `src/colonyos/config.py` - Add `VerifyConfig` dataclass, update `PhasesConfig` and `DEFAULTS`
- `src/colonyos/models.py` - `Phase.VERIFY` already exists (line 74), no changes needed
- `src/colonyos/orchestrator.py` - Insert verify-fix loop between Learn and Deliver (~line 4901), update resume logic (~line 3011)
- `src/colonyos/instructions/verify.md` - New instruction template for read-only verify agent
- `src/colonyos/instructions/verify_fix.md` - New instruction template for write-enabled fix agent
- `src/colonyos/instructions/thread_fix_verify.md` - Existing template (reference, no changes)
- `tests/test_config.py` - Tests for new config fields
- `tests/test_orchestrator.py` - Tests for verify-fix loop, resume logic, budget guards
- `tests/test_verify_phase.py` - New: dedicated tests for the verify phase behavior

## Tasks

- [x] 1.0 Add VerifyConfig and update PhasesConfig (config layer)
  depends_on: []
  - [x] 1.1 Write tests in `tests/test_config.py` for: `VerifyConfig` defaults (`max_fix_attempts=2`), `PhasesConfig.verify` defaults to `True`, `DEFAULTS["phases"]["verify"]` is `True`, and round-trip serialization of the new config fields
  - [x] 1.2 Add `VerifyConfig` dataclass to `src/colonyos/config.py` with field `max_fix_attempts: int = 2`
  - [x] 1.3 Add `verify: bool = True` to `PhasesConfig` in `src/colonyos/config.py` (line 147)
  - [x] 1.4 Add `"verify": True` to `DEFAULTS["phases"]` dict (line 38) and add `"verify": {"max_fix_attempts": 2}` to `DEFAULTS`
  - [x] 1.5 Wire `VerifyConfig` into the main `Config` dataclass (add `verify: VerifyConfig` field and parse it in config loading)
  - [x] 1.6 Run tests to confirm config changes work

- [ ] 2.0 Create instruction templates for verify and verify-fix agents
  depends_on: []
  - [ ] 2.1 Create `src/colonyos/instructions/verify.md` — read-only verify agent instructions: run the project's full test suite, report pass/fail with failing test details, do NOT modify code. Based on `thread_fix_verify.md` but with richer context (branch name, change summary)
  - [ ] 2.2 Create `src/colonyos/instructions/verify_fix.md` — write-enabled fix agent instructions: receive test failure output, diagnose root cause, fix the code (not the tests unless genuinely wrong), run tests again to confirm fix

- [ ] 3.0 Update resume and skip logic for verify phase
  depends_on: [1.0]
  - [ ] 3.1 Write tests in `tests/test_orchestrator.py` for: `_compute_next_phase("decision")` returns `"verify"`, `_compute_next_phase("verify")` returns `"deliver"`, and `_SKIP_MAP["verify"]` skips plan/implement/review
  - [ ] 3.2 Update `_compute_next_phase()` mapping (orchestrator.py line 3019): change `"decision": "deliver"` to `"decision": "verify"`, add `"verify": "deliver"`
  - [ ] 3.3 Update `_SKIP_MAP` (orchestrator.py line 3030): change `"decision"` entry to skip `{"plan", "implement", "review"}`, add `"verify"` entry to skip `{"plan", "implement", "review", "verify"}`

- [ ] 4.0 Implement verify-fix loop in main pipeline
  depends_on: [1.0, 2.0, 3.0]
  - [ ] 4.1 Write tests in `tests/test_verify_phase.py` for: (a) verify passes → proceeds to deliver, (b) verify fails → fix runs → re-verify passes → proceeds to deliver, (c) verify fails → fix exhausts retries → run marked FAILED and delivery blocked, (d) budget guard prevents loop when budget exhausted, (e) verify skipped when `config.phases.verify` is `False`, (f) heartbeat is touched before verify
  - [ ] 4.2 Add `_build_verify_prompt()` helper to orchestrator — loads `verify.md` instruction, builds user prompt with branch name and change summary
  - [ ] 4.3 Add `_build_verify_fix_prompt()` helper to orchestrator — loads `verify_fix.md` instruction, builds user prompt with test failure output
  - [ ] 4.4 Insert the verify-fix loop in `_run_pipeline()` between Learn (line 4900) and Deliver (line 4902):
    - Touch heartbeat
    - Check `config.phases.verify` — skip if False
    - Display phase header via UI or `_log()`
    - Run verify agent (read-only tools, haiku model)
    - If tests pass, proceed to deliver
    - If tests fail, enter fix loop (up to `config.verify.max_fix_attempts`):
      - Budget guard check (same pattern as review loop lines 4720-4729)
      - Run fix agent with test failure output (full tools, opus model)
      - Re-run verify agent
      - If tests pass, break loop and proceed to deliver
    - If loop exhausts, call `_fail_run_log()` and return
  - [ ] 4.5 Run full test suite to confirm no regressions

- [ ] 5.0 Add verify-fix phase to safety-critical phases list
  depends_on: [1.0]
  - [ ] 5.1 Write test that `Phase.FIX` behavior in verify context does not use fallback model
  - [ ] 5.2 Evaluate whether the verify-fix agent should be added to `_SAFETY_CRITICAL_PHASES` (config.py line 25) — if using `Phase.FIX` for the verify-fix step, it's already covered; if using a new phase enum, add it

- [ ] 6.0 Integration testing and edge cases
  depends_on: [4.0]
  - [ ] 6.1 Write integration test: full pipeline run with verify enabled, tests pass on first try — verify runs and deliver proceeds
  - [ ] 6.2 Write integration test: full pipeline run with verify enabled, tests fail, fix succeeds — verify-fix loop completes and deliver proceeds
  - [ ] 6.3 Write integration test: full pipeline run with verify disabled (`phases.verify: false`) — verify is skipped, deliver proceeds directly
  - [ ] 6.4 Write integration test: resume from failed verify — pipeline resumes at verify phase, not from scratch
  - [ ] 6.5 Run full test suite (`pytest --tb=short -q`) to confirm zero regressions across all 2956+ existing tests
