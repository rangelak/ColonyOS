# Tasks: Direct-Agent Conversational State Persistence

## Relevant Files

- `src/colonyos/agent.py` - Agent SDK wrapper; `run_phase()` and `run_phase_sync()` need `resume` parameter
- `tests/test_agent.py` - Tests for agent.py
- `src/colonyos/cli.py` - `_run_direct_agent()` (line 388), `_launch_tui()` / `_run_callback()` (line 4863), `_handle_tui_command()` (line 471), `_SAFE_TUI_COMMANDS` (line 460)
- `tests/test_cli.py` - Tests for cli.py
- `src/colonyos/models.py` - `PhaseResult` dataclass with `session_id` field
- `tests/test_models.py` - Tests for models.py
- `src/colonyos/tui/adapter.py` - TextualUI adapter (no changes expected, but verify)
- `tests/tui/test_adapter.py` - Tests for TUI adapter
- `tests/tui/test_app.py` - Tests for TUI app
- `tests/tui/test_cli_integration.py` - TUI/CLI integration tests

## Tasks

- [x] 1.0 Add `resume` parameter to agent SDK wrapper (foundation layer)
  depends_on: []
  - [x] 1.1 Write tests in `tests/test_agent.py` for `run_phase()` and `run_phase_sync()` accepting `resume: str | None` parameter and passing it to `ClaudeAgentOptions`
  - [x] 1.2 Add `resume: str | None = None` parameter to `run_phase()` in `src/colonyos/agent.py` (line 67) and thread it into `ClaudeAgentOptions` construction (line 87) as both `resume=resume` and `continue_conversation=bool(resume)`
  - [x] 1.3 Add `resume: str | None = None` parameter to `run_phase_sync()` (line 203) and pass it through to `run_phase()`
  - [x] 1.4 Verify existing tests still pass — no regressions in callers that don't pass `resume`

- [x] 2.0 Update `_run_direct_agent()` to support session resume and return session ID (depends on agent layer)
  depends_on: [1.0]
  - [x] 2.1 Write tests in `tests/test_cli.py` for `_run_direct_agent()` accepting `resume_session_id: str | None` and returning a `tuple[bool, str | None]` (success, session_id)
  - [x] 2.2 Add `resume_session_id: str | None = None` parameter to `_run_direct_agent()` in `src/colonyos/cli.py` (line 388)
  - [x] 2.3 Pass `resume=resume_session_id` to `run_phase_sync()` call (line 412)
  - [x] 2.4 Change return type from `bool` to `tuple[bool, str | None]` — return `(result.success, result.session_id)`
  - [x] 2.5 Update all existing callers of `_run_direct_agent()` to handle the new return type (TUI callback at line 4904, CLI REPL if applicable)

- [x] 3.0 Add `/new` TUI command for explicit conversation reset (independent of 1.0/2.0)
  depends_on: []
  - [x] 3.1 Write tests in `tests/test_cli.py` for `_handle_tui_command("new", ...)` returning `(True, "Conversation cleared.", False)`
  - [x] 3.2 Add `"new"` to `_SAFE_TUI_COMMANDS` set (line 460 of `src/colonyos/cli.py`)
  - [x] 3.3 Add handler in `_handle_tui_command()` (line 471) that returns a confirmation message when `lowered == "new"`
  - [x] 3.4 The actual state clearing happens in `_run_callback()` (task 4.0) — the command handler just returns the signal

- [x] 4.0 Wire session state into TUI `_run_callback()` closure (integration layer)
  depends_on: [2.0, 3.0]
  - [x] 4.1 Write integration tests in `tests/tui/test_cli_integration.py` verifying: (a) first direct-agent run stores session_id, (b) second direct-agent run passes it as resume, (c) mode switch clears session_id, (d) `/new` command clears session_id
  - [x] 4.2 Add `last_direct_session_id: str | None = None` as a `nonlocal` variable in the `_launch_tui()` closure (alongside existing `current_adapter`)
  - [x] 4.3 In the `_run_callback()` function (line 4863), after a successful `_run_direct_agent()` call (line 4904), capture the returned session_id into `last_direct_session_id`
  - [x] 4.4 Before calling `_run_direct_agent()`, pass `resume_session_id=last_direct_session_id`
  - [x] 4.5 When `route_outcome.mode != "direct_agent"`, clear `last_direct_session_id = None`
  - [x] 4.6 When `/new` command is handled (detected via `_handle_tui_command` returning handled=True and output containing "Conversation cleared"), clear `last_direct_session_id = None`
  - [x] 4.7 When resuming (i.e., `last_direct_session_id is not None`), emit a `TextBlockMsg(text="Continuing conversation...")` to the TUI queue before the phase header

- [x] 5.0 Add graceful fallback on resume failure
  depends_on: [4.0]
  - [x] 5.1 Write tests verifying that when `run_phase_sync()` with `resume` returns an error, the system retries without `resume` (fresh session)
  - [x] 5.2 In `_run_direct_agent()`, if the result has `success=False` and `resume_session_id` was provided, retry once without `resume` as a fallback
  - [x] 5.3 On fallback, clear `last_direct_session_id` so subsequent runs don't keep trying the stale session

- [x] 6.0 Wire session state into CLI REPL loop (parallel to TUI work)
  depends_on: [2.0]
  - [x] 6.1 Write tests for the CLI REPL loop maintaining `last_direct_session_id` across direct-agent runs
  - [x] 6.2 Locate the CLI REPL loop (around line 830 of `cli.py`) and add `last_direct_session_id` state variable
  - [x] 6.3 Pass `resume_session_id` to `_run_direct_agent()` calls in the REPL loop
  - [x] 6.4 Clear `last_direct_session_id` on mode transitions and explicit reset commands
  - [x] 6.5 Handle `/new` command in the REPL loop to clear conversation state

- [x] 7.0 End-to-end testing and regression verification
  depends_on: [4.0, 5.0, 6.0]
  - [x] 7.1 Write an end-to-end test simulating: user prompt → direct agent response → follow-up "yes" → verify resume session_id is passed
  - [x] 7.2 Write a test simulating: direct-agent run → mode switch to plan+implement → verify session_id is cleared
  - [x] 7.3 Write a test simulating: direct-agent run → `/new` → next run starts fresh
  - [x] 7.4 Run full existing test suite to verify no regressions
