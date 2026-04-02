# Tasks: Pipeline Lifecycle Hooks

## Relevant Files

- `src/colonyos/config.py` - Add HookConfig dataclass, hooks field to ColonyConfig, parsing in load_config/save_config
- `tests/test_config.py` - Tests for HookConfig parsing, validation, serialization
- `src/colonyos/hooks.py` - New module: HookRunner class, HookContext, HookResult, hook execution engine
- `tests/test_hooks.py` - Tests for hook execution: blocking/non-blocking, timeout, inject_output, env vars
- `src/colonyos/sanitize.py` - Add sanitize_hook_output() function
- `tests/test_sanitize.py` - Tests for sanitize_hook_output()
- `src/colonyos/orchestrator.py` - Wire HookRunner into _run_pipeline() at phase boundaries
- `tests/test_orchestrator.py` - Tests for hook wiring at phase boundaries (mock HookRunner)
- `src/colonyos/cli.py` - Add `colonyos hooks test` CLI command
- `tests/test_cli.py` - Tests for hooks test CLI command

## Tasks

- [x] 1.0 HookConfig data model and config parsing (config layer)
  depends_on: []
  - [x] 1.1 Write tests in `tests/test_config.py` for HookConfig parsing:
    - Test hooks section parsed from YAML with all fields (command, blocking, inject_output, timeout_seconds)
    - Test default values (blocking=True, inject_output=False, timeout_seconds=30)
    - Test invalid event names are rejected (e.g., "pre_unknown" raises ValueError)
    - Test timeout_seconds capped at 600s hard limit
    - Test empty hooks section produces empty dict
    - Test hooks round-trip through save_config/load_config
    - Test ColonyConfig defaults to empty hooks dict when no hooks in YAML
  - [x] 1.2 Add `HookConfig` dataclass to `src/colonyos/config.py`:
    - Fields: `command: str`, `blocking: bool = True`, `inject_output: bool = False`, `timeout_seconds: int = 30`
    - Add `VALID_HOOK_EVENTS` frozenset with all 9 event names
    - Add `MAX_HOOK_TIMEOUT_SECONDS = 600` constant
  - [x] 1.3 Add `hooks: dict[str, list[HookConfig]]` field to `ColonyConfig` dataclass (default: empty dict via `field(default_factory=dict)`)
  - [x] 1.4 Add `_parse_hooks_config(raw: dict) -> dict[str, list[HookConfig]]` function following existing `_parse_*_config` pattern:
    - Validate event names against `VALID_HOOK_EVENTS`
    - Clamp timeout_seconds to MAX_HOOK_TIMEOUT_SECONDS
    - Skip entries with empty/missing command
    - Log warnings for invalid entries
  - [x] 1.5 Wire `_parse_hooks_config` into `load_config()` and `save_config()`

- [x] 2.0 Hook sanitization function (sanitize layer)
  depends_on: []
  - [x] 2.1 Write tests in `tests/test_sanitize.py` for `sanitize_hook_output()`:
    - Test ANSI escape stripping
    - Test secret pattern redaction (github tokens, API keys, bearer tokens)
    - Test XML tag stripping
    - Test truncation at 8192 bytes with `[truncated]` marker
    - Test content under limit is returned unchanged (minus sanitization)
    - Test empty string input
    - Test combined: ANSI + secrets + XML tags + oversized content
  - [x] 2.2 Add `sanitize_hook_output(text: str, max_bytes: int = 8192) -> str` to `src/colonyos/sanitize.py`:
    - Apply `sanitize_display_text()` (ANSI/control char stripping)
    - Apply `sanitize_ci_logs()` (XML stripping + secret redaction)
    - Truncate to `max_bytes` with `\n[truncated — {original_len} bytes total]` marker
    - Return sanitized, size-capped text

- [x] 3.0 Hook execution engine (hooks module)
  depends_on: [1.0, 2.0]
  - [x] 3.1 Write tests in `tests/test_hooks.py` for HookRunner:
    - Test successful hook execution (echo command, exit 0)
    - Test blocking hook failure (exit 1) stops execution of remaining hooks
    - Test non-blocking hook failure (exit 1) continues to next hook
    - Test timeout enforcement (sleep command exceeds timeout)
    - Test inject_output captures and sanitizes stdout
    - Test inject_output with oversized output is truncated
    - Test environment variables: COLONYOS_RUN_ID, COLONYOS_PHASE, COLONYOS_BRANCH, COLONYOS_REPO_ROOT are set
    - Test environment scrubbing: ANTHROPIC_API_KEY, GITHUB_TOKEN, SLACK_BOT_TOKEN are stripped
    - Test CWD is repo_root
    - Test hooks execute in definition order
    - Test on_failure hooks run best-effort (failure logged, not raised)
    - Test on_failure hooks do not trigger further on_failure (no recursion)
    - Test run_hooks with empty config returns empty list
    - Test run_hooks with unknown event returns empty list
    - Test HookResult fields are populated correctly (exit_code, duration_ms, timed_out)
  - [x] 3.2 Create `src/colonyos/hooks.py` with:
    - `HookContext` dataclass: `run_id: str`, `phase: str`, `branch: str`, `repo_root: Path`, `status: str`
    - `HookResult` dataclass: `command: str`, `exit_code: int`, `stdout: str`, `stderr: str`, `duration_ms: int`, `timed_out: bool`, `success: bool`, `injected_output: str | None`
    - `SCRUBBED_ENV_PATTERNS`: list of env var patterns to strip (keys containing SECRET, TOKEN, KEY, PASSWORD, CREDENTIAL, plus explicit names ANTHROPIC_API_KEY, GITHUB_TOKEN, SLACK_BOT_TOKEN)
    - `_build_hook_env(context: HookContext) -> dict[str, str]`: build subprocess environment from os.environ with secrets stripped and COLONYOS_* vars added
    - `HookRunner` class:
      - `__init__(self, config: ColonyConfig)` — stores hooks config
      - `run_hooks(self, event: str, context: HookContext) -> list[HookResult]` — executes hooks for event, handles blocking/non-blocking/timeout/inject_output
      - `run_on_failure(self, context: HookContext) -> list[HookResult]` — runs on_failure hooks best-effort with `_in_failure_handler` guard to prevent recursion
    - Use `subprocess.run(command, shell=True, capture_output=True, text=True, cwd=context.repo_root, timeout=hook.timeout_seconds, env=env)` for execution
    - Call `sanitize_hook_output()` on stdout when `inject_output=True`
    - Log each hook execution at INFO level: event, command (first 80 chars), exit code, duration

- [ ] 4.0 Orchestrator wiring (integration layer)
  depends_on: [3.0]
  - [ ] 4.1 Write tests in `tests/test_orchestrator.py` for hook wiring:
    - Test that HookRunner.run_hooks is called with correct event names at each phase boundary (mock HookRunner, verify call args)
    - Test that blocking pre_* hook failure prevents phase execution and triggers on_failure
    - Test that blocking post_* hook failure triggers on_failure and halts pipeline
    - Test that inject_output results are appended to next phase user prompt
    - Test that when no hooks configured, pipeline runs unchanged (regression test)
    - Use mock/patch on HookRunner — do NOT mock the full pipeline
  - [ ] 4.2 Add `hook_runner: HookRunner | None = None` parameter to `_run_pipeline()`:
    - Create a helper `_run_hooks_at(hook_runner, event, context, log) -> str | None` that:
      - Calls `hook_runner.run_hooks(event, context)`
      - Returns concatenated inject_output text (or None)
      - On blocking failure: calls `hook_runner.run_on_failure(context)`, then calls `_fail_run_log` and returns sentinel
    - Insert `_run_hooks_at` calls at each phase boundary in `_run_pipeline`:
      - Before plan phase: `pre_plan`
      - After successful plan: `post_plan`
      - Before implement: `pre_implement`
      - After successful implement: `post_implement`
      - Before review loop: `pre_review`
      - After review loop: `post_review`
      - Before deliver: `pre_deliver`
      - After successful deliver: `post_deliver`
    - Wire `on_failure` into existing `_fail_run_log` calls
  - [ ] 4.3 Construct `HookRunner` in `run()` function (line ~4080) and pass to `_run_pipeline()`:
    - Only create if `config.hooks` is non-empty (zero overhead when unconfigured)
    - Build `HookContext` from available run state (run_id, phase, branch_name, repo_root, status)
  - [ ] 4.4 Wire inject_output into user prompt:
    - If `_run_hooks_at` returns inject_output text, append it to the next phase's user prompt
    - Follow the `_drain_injected_context` pattern (orchestrator.py line ~4663)
    - Wrap injected text in delimiters: `\n\n## Hook Output\n\n{text}\n`

- [x] 5.0 CLI test command
  depends_on: [3.0]
  - [x] 5.1 Write tests in `tests/test_cli.py` for `colonyos hooks test`:
    - Test with valid event name shows hook execution results
    - Test with invalid event name shows error
    - Test with no hooks configured shows informative message
    - Test --all flag runs all configured events
    - Test exit code is non-zero when a blocking hook fails
  - [x] 5.2 Add `hooks` command group and `hooks test` subcommand to `src/colonyos/cli.py`:
    - `@cli.group()` for `hooks`
    - `@hooks.command("test")` with `event_name` argument and `--all` flag
    - Load config, create HookRunner, create HookContext with dummy values (run_id="test", phase=event_name, branch="test")
    - Execute hooks and display results: command, exit code, duration, stdout preview (first 200 chars)
    - Use Click styling for pass/fail indication
    - Return sys.exit(1) if any blocking hook failed

- [ ] 6.0 End-to-end validation and edge cases
  depends_on: [4.0, 5.0]
  - [ ] 6.1 Run full existing test suite to confirm zero regressions (target: 152+ tests pass)
  - [ ] 6.2 Add edge case tests in `tests/test_hooks.py`:
    - Test hook command with shell features (pipes, redirects, env var expansion)
    - Test hook command that produces binary/non-UTF8 output
    - Test hook command that writes to stderr only
    - Test multiple inject_output hooks — outputs concatenated in order
    - Test hook with timeout_seconds=1 and a command that takes 2s
  - [ ] 6.3 Add a smoke test in `tests/test_hooks.py` that exercises the full flow:
    - Create a temp directory with a config.yaml containing hooks
    - Create a HookRunner from loaded config
    - Run hooks for each event type
    - Verify results match expectations
    - This tests config parsing → HookRunner → execution → results without touching the orchestrator
