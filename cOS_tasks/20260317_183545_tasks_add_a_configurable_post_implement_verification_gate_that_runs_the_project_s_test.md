# Tasks: Post-Implement Verification Gate

## Relevant Files

- `src/colonyos/models.py` - Add `Phase.VERIFY` enum value
- `src/colonyos/config.py` - Add `VerificationConfig` dataclass, update `ColonyConfig`, `load_config()`, `save_config()`, `DEFAULTS`
- `src/colonyos/orchestrator.py` - Add `run_verify_loop()`, wire into `run()`, update `_compute_next_phase()`, `_SKIP_MAP`, add `_build_verify_fix_prompt()`
- `src/colonyos/init.py` - Add test command prompt (interactive mode) and auto-detection (quick mode)
- `src/colonyos/instructions/verify_fix.md` - New instruction template for implement retry after verification failure
- `tests/test_models.py` - Tests for `Phase.VERIFY` enum value
- `tests/test_config.py` - Tests for `VerificationConfig` parsing, `load_config()`, `save_config()` round-trip
- `tests/test_orchestrator.py` - Tests for verify loop, retry logic, budget enforcement, resume semantics, prompt building
- `tests/test_init.py` - Tests for test command prompt and auto-detection logic
- `tests/test_verify.py` - New file for focused verification gate unit tests (subprocess mock, retry loop, truncation)

## Tasks

- [x]1.0 Add `Phase.VERIFY` to the Phase enum and update dependent code
  - [x]1.1 Write tests in `tests/test_models.py` asserting `Phase.VERIFY` exists with value `"verify"` and that `list(Phase)` includes it in the correct order (after IMPLEMENT, before REVIEW)
  - [x]1.2 Write tests in `tests/test_orchestrator.py` asserting that `_compute_next_phase("implement")` returns `"verify"` and `_compute_next_phase("verify")` returns `"review"`, and that `_SKIP_MAP["verify"]` equals `{"plan", "implement"}`
  - [x]1.3 Add `VERIFY = "verify"` to the `Phase` enum in `src/colonyos/models.py` between `IMPLEMENT` and `REVIEW`
  - [x]1.4 Update `_compute_next_phase()` in `orchestrator.py`: add `"verify": "review"` mapping and change `"implement"` to map to `"verify"` instead of `"review"`
  - [x]1.5 Update `_SKIP_MAP` in `orchestrator.py`: add `"verify": {"plan", "implement"}` entry
  - [x]1.6 Run existing tests to ensure no regressions from the enum ordering change (especially any tests that assert `list(Phase)`)

- [x]2.0 Add `VerificationConfig` and config parsing
  - [x]2.1 Write tests in `tests/test_config.py` for: (a) default `VerificationConfig` has `verify_command=None`, `max_verify_retries=2`, `verify_timeout=300`; (b) `load_config()` parses a `verification:` YAML section correctly; (c) `load_config()` returns defaults when `verification:` section is missing; (d) `save_config()` writes the `verification:` section; (e) round-trip: save then load preserves all verification fields
  - [x]2.2 Add `VerificationConfig` dataclass to `src/colonyos/config.py` with fields: `verify_command: str | None = None`, `max_verify_retries: int = 2`, `verify_timeout: int = 300`
  - [x]2.3 Add `verification: VerificationConfig` field to `ColonyConfig` with default `VerificationConfig()`
  - [x]2.4 Update `DEFAULTS` dict with `"verification": {"verify_command": None, "max_verify_retries": 2, "verify_timeout": 300}`
  - [x]2.5 Update `load_config()` to parse the `verification:` YAML section into `VerificationConfig`
  - [x]2.6 Update `save_config()` to write the `verification:` section to YAML (only when `verify_command` is not None)
  - [x]2.7 Run config tests to verify

- [x]3.0 Implement the verification gate (`run_verify_loop`)
  - [x]3.1 Write tests in `tests/test_verify.py` (new file) for: (a) subprocess is called with correct args (`shell=True`, `capture_output=True`, `cwd=repo_root`, `timeout`); (b) exit code 0 returns success with `cost_usd=0.0`; (c) exit code non-zero returns failure with truncated output in artifacts; (d) `subprocess.TimeoutExpired` is caught and treated as failure; (e) output truncation keeps the last 4000 chars; (f) retry loop calls implement phase up to `max_verify_retries` times; (g) retry loop stops early when `per_run` budget would be exceeded; (h) all retries exhausted proceeds to review (does not raise/fail the run); (i) when `verify_command` is `None`, the gate is skipped entirely
  - [x]3.2 Add helper function `_run_verify_command(cmd: str, cwd: Path, timeout: int) -> tuple[bool, str, int]` to `orchestrator.py` that runs the subprocess and returns `(passed, output, exit_code)`. Truncate output to last 4000 chars.
  - [x]3.3 Add `run_verify_loop(repo_root, config, log, prd_rel, task_rel, branch_name, verbose, quiet) -> bool` to `orchestrator.py`. This function: (a) runs the verify command, (b) if it passes, returns `True`, (c) if it fails, checks budget, runs implement retry with failure context, and loops up to `max_verify_retries` times, (d) logs each verify attempt as a `PhaseResult(phase=Phase.VERIFY, cost_usd=0.0, ...)`, (e) logs each implement retry as a normal `PhaseResult(phase=Phase.IMPLEMENT, ...)`.
  - [x]3.4 Add CLI output for verification: phase header "Verify", pass/fail result, retry messages. Use existing `PhaseUI.phase_header()` and `phase_complete()` / `phase_error()`.

- [x]4.0 Create the `verify_fix.md` instruction template
  - [x]4.1 Write tests in `tests/test_orchestrator.py` asserting that `_build_verify_fix_prompt()` returns a system/user prompt tuple that includes the PRD path, task path, test failure output, and explicit "fix" instructions
  - [x]4.2 Create `src/colonyos/instructions/verify_fix.md` with template content. The template should instruct the agent to: (a) read the PRD and task list, (b) analyze the test failure output, (c) fix the failing tests on the existing branch, (d) not rewrite from scratch, (e) run the tests locally to verify the fix before finishing
  - [x]4.3 Add `_build_verify_fix_prompt(config, prd_rel, task_rel, branch_name, test_output)` function to `orchestrator.py` that loads `verify_fix.md` and formats it with the provided arguments

- [x]5.0 Wire verification gate into `orchestrator.run()`
  - [x]5.1 Write integration-level tests in `tests/test_orchestrator.py` for the full pipeline flow: (a) `verify_command` configured + tests pass → proceeds to review; (b) `verify_command` configured + tests fail once + retry passes → proceeds to review with verify and 2 implement phases logged; (c) `verify_command` configured + all retries exhausted → proceeds to review anyway; (d) `verify_command` is `None` → skips verification entirely; (e) resume from failed verify re-runs verification
  - [x]5.2 Insert the verification gate call into `orchestrator.run()` between the implement phase (after line ~1161) and the review/fix loop (before line ~1162). Gate: `if config.verification.verify_command:` call `run_verify_loop()`.
  - [x]5.3 Handle the "verify" phase in skip logic: if `"verify" in skip_phases`, log and skip. Otherwise run the verify loop.
  - [x]5.4 Save run log after verification completes (whether success or exhausted retries) so progress is persisted for resume.
  - [x]5.5 Run full test suite to verify no regressions

- [x]6.0 Integrate into `colonyos init`
  - [x]6.1 Write tests in `tests/test_init.py` for: (a) interactive mode prompts for test command and saves to config; (b) interactive mode with blank input results in `verify_command=None`; (c) quick mode with `Makefile` containing `test:` target auto-detects `make test`; (d) quick mode with `package.json` containing `"test"` script auto-detects `npm test`; (e) quick mode with `pyproject.toml` containing `[tool.pytest.ini_options]` auto-detects `pytest`; (f) quick mode with no test runner detected sets `verify_command=None`; (g) detection priority: Makefile > package.json > pytest
  - [x]6.2 Add `_detect_test_command(repo_root: Path) -> str | None` function to `init.py` that checks (in order): `Makefile` for `test:` target, `package.json` for `"test"` script, `pyproject.toml`/`pytest.ini` for pytest config, `Cargo.toml` for Rust projects. Returns the detected command string or `None`.
  - [x]6.3 In `run_init()` interactive mode (the `else` branch, after budget prompts ~line 220), add a prompt: `"What command runs your test suite? (leave blank to skip)"`. Save result to `config.verification.verify_command`.
  - [x]6.4 In `run_init()` quick mode (the `if quick:` branch ~line 152), call `_detect_test_command(repo_root)` and set `config.verification.verify_command` to the result.
  - [x]6.5 Ensure `VerificationConfig` is properly passed through all `ColonyConfig` construction paths in `run_init()` (interactive, quick, and personas-only modes).

- [x]7.0 End-to-end validation and cleanup
  - [x]7.1 Run the full test suite (`pytest`) and fix any failures
  - [x]7.2 Verify backward compatibility: run with a config that has no `verification:` section and confirm behavior is identical to pre-change
  - [x]7.3 Verify the example YAML in `.colonyos/config.yaml` still loads correctly (existing config has no `verification:` section)
  - [x]7.4 Test manual flow: add `verification: { verify_command: "pytest", max_verify_retries: 2 }` to a test config and trace through the logic path mentally or with a targeted test
