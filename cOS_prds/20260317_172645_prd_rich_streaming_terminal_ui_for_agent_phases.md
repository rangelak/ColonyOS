# PRD: Rich Streaming Terminal UI for Agent Phases

## Summary

Replace the minimal stderr logging in ColonyOS with a streaming, rich terminal UI that shows real-time agent activity — tool calls, text output, phase headers/footers, and progress — using the `rich` library.

## Problem

When running `colonyos run` or `colonyos auto`, the CLI prints flat `[colonyos] ...` lines to stderr. There's no indication of what the agent is doing in real-time: which tools it's calling, how far along it is, or what it's producing. This makes it feel like nothing is happening during long phases.

## Goals

1. Show real-time tool activity per phase (e.g., `● Read src/foo.py`, `● Bash npm test`)
2. Render phase headers and completion summaries with cost, turns, and duration
3. Support parallel review phases with per-persona prefixed output
4. Stream agent text output in `--verbose` mode
5. Provide `--quiet` mode that suppresses streaming (tests and CI)
6. Maintain backward compatibility — `ui=None` default keeps all existing behavior

## Non-Goals

- Full TUI framework (no curses, no panels, no interactive elements)
- Progress bars or spinners (phases have unknown duration)
- Color theme customization

## Design

### New Module: `src/colonyos/ui.py`

- `PhaseUI` — renders streaming output for a single phase, with optional prefix for parallel reviewers
- `NullUI` — drop-in no-op for tests and `--quiet` mode
- Both expose: `phase_header()`, `phase_complete()`, `phase_error()`, `on_tool_start()`, `on_tool_input_delta()`, `on_tool_done()`, `on_text_delta()`, `on_turn_complete()`

### Agent Integration (`agent.py`)

- `run_phase()` accepts optional `ui` parameter
- When `ui` is provided, sets `include_partial_messages=True` on `ClaudeAgentOptions`
- Processes `StreamEvent` messages: `content_block_start` (tool_use), `content_block_delta` (text/input_json), `content_block_stop`
- Processes `AssistantMessage` for turn counting

### Orchestrator Integration (`orchestrator.py`)

- `run()` accepts `verbose` and `quiet` parameters
- Creates `PhaseUI` instances per phase, passing them to `run_phase_sync()`
- Parallel reviews get per-persona `PhaseUI(prefix="[Role] ")`
- Falls back to `_log()` when `ui` is None (quiet mode)

### CLI Integration (`cli.py`)

- `-v/--verbose` flag: streams agent text alongside tool activity
- `-q/--quiet` flag: suppresses streaming UI (phase start/end only via _log)
- Both `run` and `auto` commands support these flags

## Dependencies

- `rich>=13.0` added to `pyproject.toml`

## Relevant Files

- `src/colonyos/ui.py` (new)
- `src/colonyos/agent.py` (modified)
- `src/colonyos/orchestrator.py` (modified)
- `src/colonyos/cli.py` (modified)
- `pyproject.toml` (modified)
