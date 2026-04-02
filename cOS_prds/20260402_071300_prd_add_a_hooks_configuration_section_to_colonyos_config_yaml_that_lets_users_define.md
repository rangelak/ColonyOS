# PRD: Pipeline Lifecycle Hooks

## Introduction/Overview

Add a `hooks` configuration section to `.colonyos/config.yaml` that lets users define shell commands to run at specific pipeline lifecycle points. Hooks enable users to integrate their own tooling — linters, notification systems, bundle size checks, custom gates — into the ColonyOS pipeline without modifying orchestrator code.

This addresses a concrete user pain: the pipeline is a rigid sequence (plan → implement → review → deliver) with no user-defined seams. Today, every customization requires a code change to the 4800+ line `orchestrator.py`. Hooks provide escape hatches at natural phase boundaries.

## Goals

1. **Extensibility without code changes**: Users can run arbitrary shell commands before/after any pipeline phase via YAML config
2. **Pipeline gating**: Blocking hooks halt the pipeline on failure (e.g., lint must pass before deliver)
3. **Context injection**: Hooks can optionally feed stdout back into the next agent phase prompt (e.g., bundle size analysis informs the agent)
4. **Failure notification**: `on_failure` hooks fire when the pipeline fails, enabling cleanup and alerting
5. **Zero regression**: No existing tests break; hooks are a purely additive feature with graceful degradation when unconfigured

## User Stories

1. **As a developer**, I want to run `npm run lint:fix` after implementation completes, so code style is enforced before review.
2. **As a team lead**, I want to send a Slack notification when implementation finishes, so I know a PR is coming.
3. **As a DevOps engineer**, I want to run a bundle size check before delivery that feeds results to the agent, so the agent can address size regressions.
4. **As an on-call engineer**, I want to be notified when a pipeline run fails, so I can investigate promptly.
5. **As a user**, I want to test my hook configuration before running a full pipeline, so I can catch errors early.

## Functional Requirements

### FR-1: HookConfig Data Model (`src/colonyos/config.py`)

1. Add a `HookConfig` dataclass with fields:
   - `command: str` — shell command to execute
   - `blocking: bool = True` — if True, pipeline halts on non-zero exit
   - `inject_output: bool = False` — if True, stdout is sanitized and injected into the next phase prompt
   - `timeout_seconds: int = 30` — per-hook timeout (hard cap: 600s)
2. Add a `hooks: dict[str, list[HookConfig]]` field to `ColonyConfig` (default: empty dict)
3. Valid hook event names: `pre_plan`, `post_plan`, `pre_implement`, `post_implement`, `pre_review`, `post_review`, `pre_deliver`, `post_deliver`, `on_failure`
4. Parse hooks from YAML in `load_config()`, validate event names and timeout bounds
5. Serialize hooks in `save_config()`

### FR-2: Hook Execution Engine (`src/colonyos/hooks.py`)

1. Create a `HookRunner` class with method `run_hooks(event: str, context: HookContext) -> list[HookResult]`
2. `HookContext` dataclass: `run_id`, `phase`, `branch`, `repo_root`, `status` (passed as `COLONYOS_*` environment variables)
3. Execute hooks sequentially in definition order via `subprocess.run`
4. CWD is always `repo_root`
5. Environment: inherit `os.environ`, strip known secret keys (`ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `SLACK_BOT_TOKEN`, and any `*_SECRET`/`*_TOKEN` patterns), add `COLONYOS_*` context vars
6. Timeout enforcement via `subprocess.run(timeout=...)`, treat `TimeoutExpired` as failure for blocking hooks
7. For `inject_output=True` hooks: capture stdout, run through `sanitize_ci_logs()` then `sanitize_untrusted_content()`, cap at 8KB, wrap in nonce-tagged delimiters
8. For blocking hooks: if exit code != 0, stop executing remaining hooks for this event, return failure
9. For non-blocking hooks: log errors, continue to next hook
10. `on_failure` hooks: run once (best-effort), never trigger further `on_failure` hooks, failures are logged but swallowed
11. `HookResult` dataclass: `hook_config`, `exit_code`, `stdout`, `stderr`, `duration_ms`, `timed_out`, `success`
12. All hook execution is logged at INFO level with command (truncated), exit code, and duration

### FR-3: Orchestrator Integration (`src/colonyos/orchestrator.py`)

1. Wire `HookRunner` into `_run_pipeline()` at each phase boundary:
   - `pre_plan` before plan phase execution
   - `post_plan` after successful plan phase
   - `pre_implement` before implement phase
   - `post_implement` after successful implement phase
   - `pre_review` before review/fix loop
   - `post_review` after review loop completes
   - `pre_deliver` before deliver phase
   - `post_deliver` after successful deliver phase
   - `on_failure` when `_fail_run_log()` is called
2. If a blocking `pre_*` hook fails: skip the phase, run `on_failure` hooks, halt pipeline
3. If a blocking `post_*` hook fails: run `on_failure` hooks, halt pipeline
4. Collect `inject_output` results and append to the next phase's user prompt via a new helper (following the `_drain_injected_context` pattern at orchestrator.py line 4663)
5. Pass `HookRunner` as a parameter to `_run_pipeline()` for testability (following `user_injection_provider` pattern)

### FR-4: Sanitization for inject_output (`src/colonyos/sanitize.py`)

1. Add a `sanitize_hook_output(text: str, max_bytes: int = 8192) -> str` function that:
   - Strips ANSI escapes via `sanitize_display_text()`
   - Redacts secrets via `sanitize_ci_logs()`
   - Strips XML tags via `sanitize_untrusted_content()`
   - Truncates to `max_bytes` with a clear `[truncated]` marker
2. Reuse existing sanitization primitives — no new regex patterns needed

### FR-5: CLI Test Command (`src/colonyos/cli.py`)

1. Add `colonyos hooks test <event_name>` CLI command
2. Validates hook configuration (event name exists, commands parse correctly)
3. Executes each hook for the given event with real subprocess execution
4. Displays: command, exit code, duration, stdout preview (first 200 chars)
5. Returns non-zero exit code if any blocking hook fails
6. Optional `--all` flag to test all configured events

## Non-Goals

- **Plugin/middleware system**: Hooks are shell commands only. A richer plugin API may come later based on usage patterns.
- **Hook-to-hook communication**: Hooks cannot pass data to each other, only to the next pipeline phase via `inject_output`.
- **Per-hook CWD configuration**: CWD is always repo root. Users who need a different directory should `cd` in their command.
- **Sandbox/containerized execution**: Hooks run with the same permissions as the orchestrator process. The user who writes the config owns the risk.
- **Hook output in Slack notifications**: Hook results are logged but not surfaced in Slack thread updates (V1).
- **README documentation**: Ship the feature first, docs follow in a separate PR.

## Technical Considerations

### Existing Patterns to Follow

- **Config dataclass pattern**: `HookConfig` follows the same pattern as `RetryConfig`, `RecoveryConfig`, etc. in `src/colonyos/config.py` (lines 239-257)
- **Config parsing**: Add `_parse_hooks_config()` following the `_parse_*_config()` pattern (e.g., `_parse_retry_config` at line ~850)
- **Subprocess execution**: The orchestrator already uses `subprocess.run` extensively with `cwd=repo_root`
- **Sanitization**: Reuse `sanitize_ci_logs()` (line 127) and `sanitize_untrusted_content()` (line 21) from `src/colonyos/sanitize.py`
- **Injected context**: Follow the `_drain_injected_context` / `user_injection_provider` pattern for feeding hook output into prompts

### Key Design Decisions (informed by 7 persona agents)

| Decision | Resolution | Rationale |
|----------|-----------|-----------|
| **Abstraction** | Shell hooks (not plugins) | 6/7 personas agree hooks map to existing phase seams; plugin system is premature |
| **CWD** | Repo root, always | 7/7 unanimous — matches `cwd=repo_root` used throughout orchestrator |
| **Environment** | Inherit `os.environ` + strip secrets + add `COLONYOS_*` | Pragmatic middle ground: allowlist-only breaks user toolchains; full inherit leaks secrets |
| **inject_output** | Ship with heavy guardrails | Triple-layer sanitization, 8KB cap, nonce-tagged delimiters, default false |
| **Default timeout** | 30s (per-hook override, 600s hard cap) | Most hooks are lint/notifications; 120s default wastes pipeline time on failures |
| **Blocking failure** | Run `on_failure` hooks first, then abort | 7/7 unanimous — `on_failure` exists precisely for this case |
| **No raw prompt** | Pass `COLONYOS_PROMPT_HASH` only | 6/7 agree — prompt may contain sensitive content; hooks can read artifacts from disk |
| **Testing** | Standalone `HookRunner` + mock wiring | 7/7 agree — previous attempt failed by mocking entire pipeline |

### Recovery Context

The previous implementation attempt completed tasks 1.0-5.0 (config, engine, wiring, CLI) successfully but failed at task 6.0 (integration testing). Root cause: integration tests tried to mock the full `_run_pipeline` function end-to-end, which is a ~700-line function with closures and recovery logic. This replan addresses the failure by:

1. **Standalone `HookRunner` class** testable in complete isolation with real subprocesses
2. **Mock-at-the-seam pattern** for orchestrator wiring (pass `HookRunner` as a parameter, mock in tests)
3. **No full-pipeline integration tests** — test hook wiring with targeted mocks of individual phase boundaries
4. **Simpler task decomposition** with no monolithic integration testing task

## Success Metrics

1. Users can define hooks in `.colonyos/config.yaml` and they fire at correct lifecycle points
2. Blocking hooks halt the pipeline on failure; non-blocking hooks log and continue
3. `inject_output` hooks feed sanitized stdout into subsequent phase prompts
4. `colonyos hooks test <event>` validates configuration with real execution
5. All existing tests continue to pass (152+ tests)
6. Hook execution adds < 1s overhead when no hooks are configured

## Open Questions

1. **Daemon mode**: Should hooks be disabled by default when running in daemon mode with Slack triggers (since those runs can be triggered by external actors)? Ive suggests requiring `daemon.allow_hooks: true`.
2. **Hook output in run log**: Should `HookResult` details be persisted in the run log JSON for audit/debugging? (Likely yes, but adds to log size.)
3. **Shell mode**: Should we use `shell=True` (convenient for pipes/redirects) or `shell=False` with `shlex.split()` (safer)? Security engineer recommends `shell=False` with script wrappers; pragmatists say `shell=True` is what users expect from "shell command".
