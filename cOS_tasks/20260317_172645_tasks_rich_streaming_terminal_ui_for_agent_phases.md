# Tasks: Rich Streaming Terminal UI for Agent Phases

PRD: `cOS_prds/20260317_172645_prd_rich_streaming_terminal_ui_for_agent_phases.md`

## Tasks

- [x] 1.0 Add `rich>=13.0` to `pyproject.toml` and install
  - [x] 1.1 Add dependency to `pyproject.toml`
  - [x] 1.2 Reinstall package in editable mode

- [x] 2.0 Create `src/colonyos/ui.py` with PhaseUI and NullUI classes
  - [x] 2.1 Implement `PhaseUI` with phase_header, phase_complete, phase_error
  - [x] 2.2 Implement streaming callbacks: on_tool_start, on_tool_input_delta, on_tool_done, on_text_delta, on_turn_complete
  - [x] 2.3 Implement `NullUI` as no-op drop-in
  - [x] 2.4 Add `TOOL_DISPLAY` mapping for tool argument extraction

- [x] 3.0 Enable streaming in `agent.py`
  - [x] 3.1 Accept `ui` parameter in `run_phase()` and `run_phase_sync()`
  - [x] 3.2 Set `include_partial_messages=True` when `ui` is provided
  - [x] 3.3 Process `StreamEvent` messages (content_block_start/delta/stop)
  - [x] 3.4 Process `AssistantMessage` for turn counting
  - [x] 3.5 Call `ui.phase_complete()` / `ui.phase_error()` on result

- [x] 4.0 Wire PhaseUI into `orchestrator.py`
  - [x] 4.1 Add `verbose`/`quiet` params to `run()` and `run_ceo()`
  - [x] 4.2 Create PhaseUI instances per phase (Plan, Implement, Deliver)
  - [x] 4.3 Create per-persona PhaseUI for parallel reviews with prefix
  - [x] 4.4 Wire UI into Fix and Decision Gate phases
  - [x] 4.5 Fall back to `_log()` when ui is None

- [x] 5.0 Add CLI flags
  - [x] 5.1 Add `-v/--verbose` and `-q/--quiet` to `run` command
  - [x] 5.2 Add `-v/--verbose` and `-q/--quiet` to `auto` command
  - [x] 5.3 Pass flags through to orchestrator and `_run_single_iteration`

- [x] 6.0 Verify no regressions
  - [x] 6.1 Run full test suite (257 tests pass)
  - [x] 6.2 Check linter on modified files (clean)

## Relevant Files

- `src/colonyos/ui.py` — new module
- `src/colonyos/agent.py` — streaming event processing
- `src/colonyos/orchestrator.py` — UI wiring per phase
- `src/colonyos/cli.py` — verbose/quiet flags
- `pyproject.toml` — rich dependency
