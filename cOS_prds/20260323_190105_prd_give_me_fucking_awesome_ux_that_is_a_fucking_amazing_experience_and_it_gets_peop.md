# PRD: Interactive Terminal UI (Textual TUI)

## Introduction/Overview

ColonyOS currently renders agent activity through a one-way Rich streaming UI (`PhaseUI` in `src/colonyos/ui.py`). Users launch a pipeline run and become passive spectators — they cannot scroll back through completed phases, intervene mid-run, compose follow-up input, or see persistent status. The terminal is a television: you watch, but you cannot touch.

This feature replaces that experience with a full interactive terminal UI built on [Textual](https://textual.textualize.io/), featuring a scrollable execution transcript, a multi-line composer for input, live streaming of agent activity, and persistent status information. The result should feel like **mission control** — calm confidence while something powerful happens — not a raw log file.

The TUI is launched as an alternative mode (`colonyos tui` or `colonyos run --tui`), coexisting with the current Rich CLI for CI, piped output, and users who prefer simplicity. Textual is an optional dependency, mirroring the existing `[slack]` and `[ui]` dependency group pattern.

## Goals

1. **Interactive control**: Users can scroll back through completed phases, compose follow-up input mid-session, cancel running phases, and retry failed operations — all without leaving the terminal.
2. **Operational transparency**: A persistent status bar shows current phase, cumulative cost, turn count, and elapsed time at all times. Users always know what the agent is doing and what it costs.
3. **Visual clarity**: Structured, color-coded event rendering with consistent spacing makes the transcript feel designed, not hacked together. Tool calls, text output, commands, and status are visually distinct.
4. **Ship in one week**: The v1 scope is intentionally minimal — three core widgets (transcript, composer, status bar) adapting the existing 8-method `PhaseUI` callback interface. No new event architecture, no replay, no persistence.
5. **Zero regression**: The existing Rich CLI path (`PhaseUI`, `NullUI`) remains untouched. All current tests pass. Textual is optional.

## User Stories

1. **As a developer running `colonyos run --tui "Add dark mode"`**, I want to see the agent's activity stream in real-time in the top pane while the composer sits ready at the bottom, so I feel like I'm pair-programming with the agent rather than watching a build log.

2. **As a developer watching a long pipeline run**, I want to scroll back through earlier phases to review what the agent did three minutes ago, without losing my place in the live stream.

3. **As a developer who notices the agent going down the wrong path**, I want to press Ctrl+C to cancel the current phase and type a correction into the composer to redirect, so I'm not burning budget on wasted work.

4. **As a developer managing costs**, I want to see cumulative cost, current phase, and elapsed time in a persistent status bar, so I can make informed decisions about whether to let the run continue.

5. **As a developer in a tmux session on a remote box**, I want the TUI to render correctly over SSH with no visual artifacts, because that's how I actually work.

## Functional Requirements

### FR-1: TUI Entry Point
- Add `colonyos tui` CLI command and `--tui` flag on `colonyos run`
- Launches the Textual app instead of the current Rich streaming output
- Falls back gracefully with a clear error if `textual` is not installed

### FR-2: Transcript Pane (Top ~85% of Screen)
- Scrollable container occupying the top portion of the screen
- Renders agent activity using the existing `PhaseUI` callback semantics:
  - `phase_header` → phase boundary marker with name, budget, model
  - `on_tool_start` / `on_tool_input_delta` / `on_tool_done` → tool call lines with color-coded dots (matching existing `TOOL_STYLE` map)
  - `on_text_delta` / `on_turn_complete` → buffered agent text rendered as markdown when appropriate
  - `phase_complete` → success summary with cost/turns/duration
  - `phase_error` → error display
- Auto-scrolls to bottom when user is near the bottom; stops auto-scrolling when user scrolls up
- Uses `RichLog` widget (Textual built-in) for efficient append-only rendering, not one widget per event

### FR-3: Composer Pane (Bottom, Dynamic Height)
- Multi-line `TextArea` widget pinned to the bottom of the screen
- Starts at 3 lines height, grows with content, caps at 8 lines, scrolls internally after that
- **Enter** submits input, **Shift+Enter** or **Ctrl+J** inserts a newline
- On submit: text is sent to the agent/REPL handler, composer clears, a user message appears in the transcript
- Displays hint text showing key bindings (Enter to send, Shift+Enter for newline)

### FR-4: Status Bar
- Single-line bar between transcript and composer (or at the very top)
- Shows: current phase name, cumulative cost ($X.XX), turn count, elapsed time
- Updates on every `phase_header`, `phase_complete`, and `on_turn_complete` callback
- Pulsing/cycling indicator while an agent phase is actively running

### FR-5: TextualUI Adapter
- New class `TextualUI` implementing the same 8-method duck-type interface as `PhaseUI` and `NullUI`
- Posts Textual `Message` objects to the app's message queue instead of calling `console.print`
- The orchestrator's `_make_ui()` factory returns `TextualUI` when TUI mode is active
- Bridges the synchronous orchestrator (running in a `Worker(thread=True)`) with Textual's async event loop via thread-safe queue

### FR-6: Keybindings
- **Enter**: Submit composer input
- **Shift+Enter**: Insert newline in composer
- **Ctrl+C**: Cancel current running phase
- **Ctrl+L**: Clear visible transcript
- **Escape**: Unfocus overlays / return focus to composer

### FR-7: Optional Dependency
- Textual added to `pyproject.toml` under `[project.optional-dependencies]` as `tui = ["textual>=0.40"]`
- Import guarded with try/except; clean error message if not installed
- Zero impact on existing install path

### FR-8: Output Sanitization
- All agent output piped through `sanitize_display_text()` from `src/colonyos/sanitize.py` before rendering in the transcript
- Prevents terminal escape sequence injection from untrusted command output or repository files

## Non-Goals (Explicitly Out of Scope for v1)

- **Structured event model / event bus**: The existing 8 `PhaseUI` callbacks ARE the event model. No new architecture.
- **Event persistence / replay**: Not building a database. Transcript lives in memory only.
- **DiffBlock / CodeBlock custom widgets**: Diffs render as syntax-highlighted text in `RichLog`. No custom diff viewer.
- **Collapsible sections / accordion UI**: Tool calls are one line. No expand/collapse.
- **Event filtering / search**: The transcript is rarely more than a few hundred entries. No filtering.
- **Mouse-driven interaction** (beyond scrolling): Keyboard-first.
- **Light theme**: Dark theme only. Developers overwhelmingly use dark terminals.
- **20+ custom widget types**: v1 has exactly 4 widgets: `TranscriptView` (wrapping `RichLog`), `Composer` (wrapping `TextArea`), `StatusBar` (custom `Static`), and `HintBar`.
- **Parallel agent stream visualization**: Parallel reviews continue to use the existing `ParallelProgressLine` pattern adapted for the transcript.
- **prompt_toolkit integration**: Textual's `TextArea` handles multi-line editing. One framework, one event loop.

## Technical Considerations

### Existing Architecture (What We're Adapting)
- **`src/colonyos/ui.py`**: `PhaseUI` (8 callbacks), `NullUI` (drop-in no-op), `ParallelProgressLine`. The 8-method interface is the contract: `phase_header`, `phase_complete`, `phase_error`, `on_tool_start`, `on_tool_input_delta`, `on_tool_done`, `on_text_delta`, `on_turn_complete`.
- **`src/colonyos/agent.py`**: `run_phase()` async-iterates over `query()` SDK responses and dispatches to UI callbacks (lines 107-145). `run_phase_sync()` wraps this with `asyncio.run()`.
- **`src/colonyos/orchestrator.py`**: `_make_ui()` factory functions (lines ~1696, ~2213, ~2464) create UI instances. These are the injection points for `TextualUI`.
- **`src/colonyos/cli.py`**: `_run_repl()` at line ~392 is the existing interactive loop. The TUI composer replaces this.

### Concurrency Strategy
The orchestrator calls `run_phase_sync()` which calls `asyncio.run()`, creating and destroying an event loop per phase. This is incompatible with Textual's own event loop. **Solution**: Run the orchestrator in a `Worker(thread=True)` — a dedicated thread. The `TextualUI` adapter pushes events through a thread-safe `janus` queue (sync producer side → async consumer side). The Textual app drains the async side and posts `Message` objects to widgets. This avoids refactoring the orchestrator to be fully async.

### Performance Strategy
Do NOT create one widget per event. Use Textual's built-in `RichLog` widget for the transcript — it appends `Rich.Renderable` objects and handles virtual scrolling internally. Coalesce `TokenStreamDelta` events into a single updating line that gets finalized on `on_turn_complete`. Widget count stays proportional to tool calls and phases (tens to low hundreds), not tokens (thousands).

### Color Palette
- **Primary accent**: Muted blue (`bright_cyan`) for interactive elements and composer border
- **Success**: Green for completed phases
- **Error**: Red for failures
- **Warning**: Yellow for budget warnings
- **Tool calls**: Preserve existing `TOOL_STYLE` color map (cyan=Read, green=Write, yellow=Bash, magenta=Grep/Glob, blue=Agent)
- **Metadata/secondary**: `dim` for timestamps, turn counts, non-critical info
- **Content**: Standard foreground for agent text, bright for user messages

### Spacing & Layout
- 2 characters left padding inside all content blocks
- 1 empty line between major blocks (phase boundaries)
- No borders within transcript — whitespace separation only
- Single border between transcript and composer (genuine structural boundary)
- Status bar is a single dense line, no padding waste

### File Structure (New Files)
```
src/colonyos/tui/
├── __init__.py          # Package init, lazy import guard
├── app.py               # AssistantApp (Textual App subclass)
├── widgets/
│   ├── __init__.py
│   ├── transcript.py    # TranscriptView (wraps RichLog)
│   ├── composer.py      # Composer (wraps TextArea with auto-grow)
│   ├── status_bar.py    # StatusBar (Static widget)
│   └── hint_bar.py      # HintBar (keybinding hints)
├── adapter.py           # TextualUI class (8-method PhaseUI interface → Textual messages)
└── styles.py            # CSS-in-Python, color constants
```

### Dependency on Existing Code
- `TextualUI` in `adapter.py` implements the same duck-type interface as `PhaseUI`/`NullUI`
- `orchestrator.py` changes are minimal: `_make_ui()` returns `TextualUI` when a flag is set
- `cli.py` gets a new `tui` command that launches the Textual app
- No changes to `agent.py`, `models.py`, `config.py`, or any existing tests

## Persona Synthesis

### Areas of Agreement (All 7 Personas)
- **Ship as alternative mode**, not replacement. `colonyos tui` coexists with existing CLI.
- **Use the existing `PhaseUI` 8-method interface** as the contract. `NullUI` proves the pattern works.
- **Textual must be an optional dependency** in `[project.optional-dependencies]`, like `slack`.
- **v1 scope must be ruthlessly minimal**: transcript + composer + status bar. Three widgets, one week.
- **Run orchestrator in a separate thread** via `Worker(thread=True)` to avoid async event loop conflicts.
- **Use `RichLog`** (Textual built-in) for the transcript, not one widget per event.

### Areas of Tension
- **Linus Torvalds** questions whether this solves a real problem at all — suggests enhancing Rich output with `Live` displays instead of a full Textual rewrite. **Resolution**: We ship the smallest possible Textual implementation that proves value. If it doesn't ship in one week, we kill it.
- **Systems Engineer** advocates for a proper `asyncio.Queue[Event]` bridge with typed events for future extensibility. **Linus/Michael** say that's over-engineering. **Resolution**: v1 uses a simple `janus` queue with the existing callback semantics. No new event types.
- **Security Engineer** flags that the current streaming path doesn't sanitize output before rendering and that terminal injection via crafted command output is a real risk. **Resolution**: All output goes through `sanitize_display_text()` before rendering. This is a security fix that applies regardless of the TUI.
- **Jony Ive** advocates for exactly two animations (running indicator + scroll-to-bottom). **Steve Jobs** wants the "holy shit" moment to be character-by-character streaming. **Resolution**: v1 shows a pulsing status indicator during active phases. Text appears as buffered blocks on `on_turn_complete`, matching current behavior. Character streaming is a v2 experiment.
- **Karpathy** wants context window usage, prompt effectiveness signals, and "view full prompt" expanders. **Resolution**: v1 shows cost and turns in the status bar. Prompt inspection is v2.

## Success Metrics

1. **Ships in ≤ 1 week**: If the basic transcript+composer+status is not working in one week, the feature is killed.
2. **Zero test regressions**: All existing 37 test modules pass unchanged.
3. **Works over SSH/tmux**: Manual verification on remote terminal via tmux.
4. **Responsive streaming**: No visible lag when the agent streams tool calls. Frame rate stays above 15fps during active streaming.
5. **Optional install**: `pip install colonyos` works without Textual. `pip install colonyos[tui]` adds it.

## Open Questions

1. **REPL integration depth**: Should the TUI composer feed into the existing `_run_repl()` logic from `cli.py`, or should it be a simpler prompt-to-orchestrator pipe? The REPL has intent routing, triage, and special commands — how much of that do we replicate?
2. **Parallel review rendering**: The `ParallelProgressLine` uses carriage returns for inline rewrite. How does this adapt to the `RichLog`-based transcript? Likely needs a dedicated updating widget or a `RichLog` entry that gets replaced.
3. **`janus` dependency**: Thread-safe async queue requires the `janus` package. Is this acceptable, or should we use `loop.call_soon_threadsafe` directly? `janus` is small and well-maintained.
4. **First-launch experience**: Should the TUI open with the composer focused and ready, or should it show a brief orientation (phase names, key bindings)?
