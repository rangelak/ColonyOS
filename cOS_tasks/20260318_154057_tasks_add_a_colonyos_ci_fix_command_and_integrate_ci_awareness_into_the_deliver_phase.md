# Tasks: `colonyos ci-fix` Command & CI-Aware Deliver Phase

## Relevant Files

### New Files
- `src/colonyos/ci.py` — CI log fetching, parsing, prompt formatting, and sanitization functions
- `src/colonyos/instructions/ci_fix.md` — Instruction template for the CI fix agent
- `tests/test_ci.py` — Unit tests for all CI module functions

### Modified Files
- `src/colonyos/models.py` — Add `Phase.CI_FIX` enum value
- `src/colonyos/config.py` — Add `CIFixConfig` dataclass, parse `ci_fix` section from YAML, add defaults
- `src/colonyos/sanitize.py` — Add `sanitize_ci_logs()` function with secret-pattern regex
- `src/colonyos/cli.py` — Add `ci-fix` Click command with `--max-retries`, `--wait`, `--wait-timeout` options
- `src/colonyos/orchestrator.py` — Wire CI fix loop after deliver phase when config enabled; add `_build_ci_fix_prompt()` builder
- `src/colonyos/stats.py` — Ensure `Phase.CI_FIX` is included in aggregate dashboards
- `tests/test_models.py` — Test `Phase.CI_FIX` serialization/deserialization
- `tests/test_config.py` — Test `CIFixConfig` parsing with defaults, overrides, and invalid values
- `tests/test_sanitize.py` — Test secret-pattern sanitization in `sanitize_ci_logs()`
- `tests/test_cli.py` — Test `ci-fix` command invocation, argument parsing, error cases
- `tests/test_orchestrator.py` — Test post-deliver CI fix loop integration
- `tests/test_stats.py` — Test that CI_FIX phases appear in stats output

## Tasks

- [x] 1.0 Add `Phase.CI_FIX` enum value and update models
  - [x] 1.1 Write tests in `tests/test_models.py`: verify `Phase.CI_FIX` serialization roundtrip (`Phase("ci_fix")` works), backward compat with existing RunLog JSON that lacks CI_FIX phases
  - [x] 1.2 Add `CI_FIX = "ci_fix"` to the `Phase` enum in `src/colonyos/models.py`
  - [x] 1.3 Run existing `test_models.py` tests to confirm no regressions

- [x] 2.0 Add `CIFixConfig` and config parsing
  - [x] 2.1 Write tests in `tests/test_config.py`: test default `CIFixConfig` values when `ci_fix` section absent, test parsing valid overrides, test invalid values (negative retries, etc.), test that existing configs without `ci_fix` still load correctly
  - [x] 2.2 Add `CIFixConfig` dataclass to `src/colonyos/config.py` with fields: `enabled: bool = False`, `max_retries: int = 2`, `wait_timeout: int = 600`, `log_char_cap: int = 12_000`
  - [x] 2.3 Add `ci_fix` field to `ColonyConfig` dataclass, defaulting to `CIFixConfig()`
  - [x] 2.4 Update `load_config()` to parse `ci_fix` section from YAML into `CIFixConfig`
  - [x] 2.5 Update `save_config()` to serialize `CIFixConfig` back to YAML
  - [x] 2.6 Add `DEFAULTS["ci_fix"]` entry with default values

- [x] 3.0 Extend sanitization for CI logs
  - [x] 3.1 Write tests in `tests/test_sanitize.py` (or extend existing test file): test that `ghp_abc123`, `sk-abc123`, `AKIA1234567890EXAMPLE`, `Bearer eyJhbG...` patterns are redacted to `[REDACTED]`; test that normal error messages are preserved; test that XML tags are still stripped; test edge cases (empty string, no secrets present)
  - [x] 3.2 Add `SECRET_PATTERNS` regex list and `sanitize_ci_logs()` function to `src/colonyos/sanitize.py` that applies XML tag stripping + secret-pattern redaction
  - [x] 3.3 Run sanitize tests to verify

- [x] 4.0 Implement CI log fetching and prompt formatting module (`src/colonyos/ci.py`)
  - [x] 4.1 Write tests in `tests/test_ci.py`: test `fetch_pr_checks()` with mocked `gh pr checks` output (all pass, some fail, all fail); test `fetch_check_logs()` with mocked `gh run view --log-failed` output; test log truncation (tail-biased, respects `_CI_LOG_CHAR_CAP`); test `format_ci_failures_as_prompt()` produces structured output with `<ci_failure_log>` delimiters; test error handling (gh not found, timeout, non-zero exit); test pre-flight checks (`validate_clean_worktree`, `validate_branch_not_behind`)
  - [x] 4.2 Implement `fetch_pr_checks(pr_number, repo_root)` — calls `gh pr checks <number> --json name,state,conclusion,detailsUrl`, parses JSON, returns list of check result dicts
  - [x] 4.3 Implement `fetch_check_logs(run_id, repo_root)` — calls `gh run view <run-id> --log-failed`, applies tail-biased truncation at `_CI_LOG_CHAR_CAP`, returns dict mapping step name to truncated log text
  - [x] 4.4 Implement `format_ci_failures_as_prompt(failures)` — takes list of `{name, conclusion, log}` dicts, wraps each in `<ci_failure_log step="...">` delimiters, calls `sanitize_ci_logs()`, returns structured text block
  - [x] 4.5 Implement `validate_clean_worktree(repo_root)` — runs `git status --porcelain`, raises `click.ClickException` if non-empty
  - [x] 4.6 Implement `validate_branch_not_behind(repo_root)` — runs `git rev-list HEAD..@{u}`, raises `click.ClickException` if non-empty
  - [x] 4.7 Implement `poll_pr_checks(pr_number, repo_root, timeout, initial_interval)` — polls `gh pr checks` with exponential backoff (1.5x, capped at 5min), returns final check results or raises on timeout

- [x] 5.0 Create `ci_fix.md` instruction template
  - [x] 5.1 Write the template at `src/colonyos/instructions/ci_fix.md` modeled after `fix.md`, with placeholders: `{branch_name}`, `{ci_failure_context}`, `{fix_attempt}`, `{max_retries}`. Include: Staff+ Engineer role, scoped instructions (fix only failing code, run tests locally, commit with clear message), explicit prohibitions (no refactoring unrelated code, no new features, no PR description changes)
  - [x] 5.2 Add `_build_ci_fix_prompt()` function to `src/colonyos/orchestrator.py` that loads `ci_fix.md`, formats with context variables, and returns `(system_prompt, user_prompt)` tuple following the pattern of `_build_fix_prompt()`

- [x] 6.0 Add `ci-fix` CLI command
  - [x] 6.1 Write tests in `tests/test_cli.py`: test `ci-fix` with all checks passing (success exit), test with failed checks (mocked agent run + push), test `--max-retries` argument parsing, test `--wait` and `--wait-timeout` flags, test error cases (no PR number, invalid PR, uncommitted changes, behind remote, gh not authenticated), test that `PhaseResult` with `Phase.CI_FIX` is recorded
  - [x] 6.2 Add `ci_fix` command to `src/colonyos/cli.py` with Click decorators: `@app.command("ci-fix")`, `@click.argument("pr_ref")`, `@click.option("--max-retries", default=1)`, `@click.option("--wait/--no-wait", default=False)`, `@click.option("--wait-timeout", default=600)`
  - [x] 6.3 Implement command body: pre-flight checks → fetch checks → if all pass exit → fetch logs → format prompt → run agent phase → push → (if --wait) poll → (if --max-retries > 1 and still failing) loop
  - [x] 6.4 Wire up `RunLog` creation and `_save_run_log()` for standalone ci-fix runs, recording each attempt as a `PhaseResult`

- [x] 7.0 Integrate CI fix into orchestrator's auto pipeline
  - [x] 7.1 Write tests in `tests/test_orchestrator.py`: test that when `ci_fix.enabled=True`, the `run()` function calls the CI fix loop after deliver; test that CI fix is skipped when `ci_fix.enabled=False`; test retry exhaustion (CI still fails after max_retries); test budget guard (CI fix cost counted against per_run); test that CI fix phases appear in the returned `RunLog`
  - [x] 7.2 Add post-deliver CI fix logic to the `run()` function in `orchestrator.py`: after the deliver phase completes and a PR URL is available, if `config.ci_fix.enabled`, call `poll_pr_checks()` → if failed, enter ci-fix loop (fetch logs → build prompt → run agent → push → poll → retry)
  - [x] 7.3 Ensure `RunStatus.COMPLETED` is set after CI passes or retries exhausted; failed CI fix attempts recorded with `success=False`

- [x] 8.0 Update stats and final integration
  - [x] 8.1 Write tests in `tests/test_stats.py`: test that `Phase.CI_FIX` appears in stats output with cost/duration/success-rate columns
  - [x] 8.2 Update `src/colonyos/stats.py` to include `Phase.CI_FIX` in aggregate dashboards (if it filters by known phases, add CI_FIX to the list)
  - [x] 8.3 Run the full test suite (`pytest tests/`) to confirm no regressions across all modules
  - [x] 8.4 Manually verify: `colonyos ci-fix --help` shows expected options and documentation
