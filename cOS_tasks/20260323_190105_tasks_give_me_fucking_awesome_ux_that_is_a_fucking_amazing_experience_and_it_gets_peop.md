# Tasks: Interactive Terminal UI (Textual TUI)

## Relevant Files

### Existing Files to Modify
- `src/colonyos/ui.py` - Extract `UIProtocol` type alias; `TextualUI` implements same 8-method interface as `PhaseUI`/`NullUI`
- `src/colonyos/cli.py` - Add `tui` CLI command and `--tui` flag on `run` command
- `src/colonyos/orchestrator.py` - Modify `_make_ui()` factory functions to return `TextualUI` when TUI mode is active
- `pyproject.toml` - Add `tui` optional dependency group with `textual>=0.40` and `janus>=1.0`
- `tests/test_ui.py` - Add tests for `TextualUI` adapter

### New Files to Create
- `src/colonyos/tui/__init__.py` - Package init with lazy import guard for Textual
- `src/colonyos/tui/app.py` - `AssistantApp` Textual App subclass (main app shell)
- `src/colonyos/tui/adapter.py` - `TextualUI` class implementing 8-method PhaseUI interface
- `src/colonyos/tui/widgets/__init__.py` - Widget package init
- `src/colonyos/tui/widgets/transcript.py` - `TranscriptView` wrapping Textual `RichLog`
- `src/colonyos/tui/widgets/composer.py` - `Composer` wrapping `TextArea` with auto-grow + max height
- `src/colonyos/tui/widgets/status_bar.py` - `StatusBar` showing phase/cost/turns/elapsed
- `src/colonyos/tui/widgets/hint_bar.py` - `HintBar` showing keybinding hints
- `src/colonyos/tui/styles.py` - CSS strings and color constants
- `tests/tui/__init__.py` - TUI test package
- `tests/tui/test_adapter.py` - Unit tests for TextualUI adapter (no Textual dependency needed)
- `tests/tui/test_composer.py` - Textual pilot tests for Composer widget
- `tests/tui/test_app.py` - Textual pilot tests for full app integration
- `tests/tui/conftest.py` - Shared TUI test fixtures

## Tasks

- [ ] 1.0 Project Setup: Optional Dependency & Package Structure
  depends_on: []
  - [ ] 1.1 Add `tui = ["textual>=0.40", "janus>=1.0"]` to `[project.optional-dependencies]` in `pyproject.toml`; add `"colonyos[tui]"` to the `dev` group
  - [ ] 1.2 Create `src/colonyos/tui/__init__.py` with lazy import guard that raises a clear error if `textual` is not installed (e.g., `ImportError: colonyos[tui] extra required — run: pip install colonyos[tui]`)
  - [ ] 1.3 Create `src/colonyos/tui/widgets/__init__.py` as empty package init
  - [ ] 1.4 Create `src/colonyos/tui/styles.py` with CSS-in-Python string constants for the app layout (transcript ~85% height, composer at bottom, status bar between them) and color constants matching existing `TOOL_STYLE` map from `ui.py`
  - [ ] 1.5 Create `tests/tui/__init__.py` and `tests/tui/conftest.py` with shared fixtures
  - [ ] 1.6 Run `pip install -e ".[tui,dev]"` and verify all existing tests still pass

- [ ] 2.0 TextualUI Adapter: Bridge Orchestrator Callbacks to Textual Messages
  depends_on: [1.0]
  - [ ] 2.1 Write tests in `tests/tui/test_adapter.py` for the `TextualUI` class: verify all 8 methods (`phase_header`, `phase_complete`, `phase_error`, `on_tool_start`, `on_tool_input_delta`, `on_tool_done`, `on_text_delta`, `on_turn_complete`) push typed messages onto a `janus` sync queue. Test that tool arg extraction and text buffering work correctly. These tests do NOT require Textual — they test the queue contract only.
  - [ ] 2.2 Implement `TextualUI` in `src/colonyos/tui/adapter.py`:
    - Same 8-method duck-type interface as `PhaseUI`/`NullUI`
    - Constructor takes a `janus.SyncQueue` for thread-safe event pushing
    - `on_text_delta` buffers text; `on_turn_complete` flushes buffer as a single message
    - `on_tool_start`/`on_tool_input_delta`/`on_tool_done` use same arg extraction logic as `PhaseUI._try_extract_arg`
    - All output sanitized through `sanitize_display_text()` before queuing
    - Define simple frozen dataclasses for queue messages: `PhaseHeaderMsg`, `PhaseCompleteMsg`, `PhaseErrorMsg`, `ToolLineMsg`, `TextBlockMsg`, `TurnCompleteMsg`
  - [ ] 2.3 Verify adapter tests pass

- [ ] 3.0 Transcript Widget: Scrollable Event Display
  depends_on: [1.0]
  - [ ] 3.1 Write Textual pilot tests in `tests/tui/test_app.py` for `TranscriptView`: verify that appending messages adds entries to the `RichLog`, auto-scroll behavior works (scrolls when near bottom, stops when user scrolls up), and phase boundaries render with rule lines.
  - [ ] 3.2 Implement `TranscriptView` in `src/colonyos/tui/widgets/transcript.py`:
    - Wraps Textual's built-in `RichLog` widget
    - Methods: `append_phase_header(name, budget, model)`, `append_tool_line(name, arg, style)`, `append_text_block(text)`, `append_phase_complete(cost, turns, duration)`, `append_phase_error(error)`, `append_user_message(text)`
    - Uses Rich renderables (`Text`, `Markdown`, `Rule`) for each entry type
    - 2-char left padding, 1 blank line between phase boundaries
    - Tool lines use colored dots matching existing `TOOL_STYLE` color map
    - Auto-scroll: scrolls to bottom on new content if user is within 3 lines of bottom; stops if user has scrolled up
  - [ ] 3.3 Verify transcript tests pass

- [ ] 4.0 Composer Widget: Multi-line Input with Auto-Grow
  depends_on: [1.0]
  - [ ] 4.1 Write Textual pilot tests in `tests/tui/test_composer.py`: verify height grows from 3 to 8 lines with content, caps at 8, Enter submits and clears, Shift+Enter inserts newline, submitted text is emitted as a Textual `Message`.
  - [ ] 4.2 Implement `Composer` in `src/colonyos/tui/widgets/composer.py`:
    - Wraps Textual `TextArea` in a container
    - Min height: 3 lines. Max height: 8 lines. Recalculates on every content change.
    - `Enter` key binding: emits `Composer.Submitted(text)` message, clears the TextArea
    - `Shift+Enter` / `Ctrl+J`: inserts newline (TextArea default behavior for Shift+Enter, may need explicit binding for Ctrl+J)
    - Focus styling: subtle border highlight when focused
  - [ ] 4.3 Implement `HintBar` in `src/colonyos/tui/widgets/hint_bar.py`:
    - Single-line `Static` widget below the composer
    - Shows: `Enter send · Shift+Enter newline · Ctrl+C cancel · Ctrl+L clear`
    - Dim styling so it doesn't distract
  - [ ] 4.4 Verify composer and hint bar tests pass

- [ ] 5.0 Status Bar Widget: Phase/Cost/Turns/Elapsed Display
  depends_on: [1.0]
  - [ ] 5.1 Write tests for `StatusBar`: verify it renders phase name, cost, turns, elapsed; updates when methods are called; shows pulsing indicator during active phases.
  - [ ] 5.2 Implement `StatusBar` in `src/colonyos/tui/widgets/status_bar.py`:
    - Subclass of Textual `Static` widget, single line
    - Displays: `[phase_name] · $X.XX · N turns · Xm Xs` — or `idle` when no phase is running
    - Methods: `set_phase(name, budget, model)`, `set_complete(cost, turns, duration)`, `set_error(msg)`, `increment_turn()`
    - Running indicator: text-based spinner or cycling dots (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) updated via `set_interval`
    - Cost accumulates across phases within a run
  - [ ] 5.3 Verify status bar tests pass

- [ ] 6.0 App Shell: Assemble Layout and Wire Event Loop
  depends_on: [2.0, 3.0, 4.0, 5.0]
  - [ ] 6.1 Write integration tests in `tests/tui/test_app.py`: verify the full app mounts with all 4 widgets, that feeding mock messages through the janus queue results in transcript entries, and that composer submission appears as a user message in the transcript.
  - [ ] 6.2 Implement `AssistantApp` in `src/colonyos/tui/app.py`:
    - Textual `App` subclass with vertical layout: `StatusBar` (top), `TranscriptView` (middle, flex), `Composer` + `HintBar` (bottom, fixed)
    - CSS layout via `styles.py` constants
    - On mount: create `janus.Queue`, start a `set_interval` or async task to drain the async side of the queue and dispatch messages to widgets (transcript, status bar)
    - Handle `Composer.Submitted` message: append user message to transcript, invoke the run callback
    - Keybindings: `Ctrl+C` → cancel signal, `Ctrl+L` → clear transcript, `Escape` → focus composer
    - App accepts a `run_callback: Callable[[str], None]` that gets invoked in a `Worker(thread=True)` when the user submits input
  - [ ] 6.3 Wire the queue consumer loop:
    - Async coroutine drains `queue.async_q` in a loop
    - Dispatches each message type to the appropriate widget method
    - `PhaseHeaderMsg` → `status_bar.set_phase()` + `transcript.append_phase_header()`
    - `ToolLineMsg` → `transcript.append_tool_line()`
    - `TextBlockMsg` → `transcript.append_text_block()`
    - `PhaseCompleteMsg` → `status_bar.set_complete()` + `transcript.append_phase_complete()`
    - `PhaseErrorMsg` → `status_bar.set_error()` + `transcript.append_phase_error()`
    - `TurnCompleteMsg` → `status_bar.increment_turn()`
  - [ ] 6.4 Verify all integration tests pass

- [ ] 7.0 CLI Integration: Wire TUI into Existing Commands
  depends_on: [6.0]
  - [ ] 7.1 Write tests for the CLI entry point: verify `colonyos tui` launches without error when textual is installed, and shows a clear error when it's not.
  - [ ] 7.2 Add `tui` command to `src/colonyos/cli.py`:
    - `@app.command()` with optional `--prompt` argument
    - Imports `src/colonyos/tui` lazily (try/except for missing dependency)
    - Creates `AssistantApp` with a `run_callback` that calls the existing orchestrator `run()` function with a `TextualUI` adapter
    - Pass the `janus` queue to both the adapter and the app
  - [ ] 7.3 Modify `_make_ui()` factory functions in `src/colonyos/orchestrator.py` to accept an optional `ui_override` parameter. When provided, return the override instead of creating a new `PhaseUI`. This is the minimal change — no new ABC, no Protocol class, just an optional parameter.
  - [ ] 7.4 Add `--tui` flag to the existing `run` command as a convenience alias for launching in TUI mode
  - [ ] 7.5 Verify CLI tests pass and existing `run` command tests are unaffected

- [ ] 8.0 Polish & Validation
  depends_on: [7.0]
  - [ ] 8.1 Run the full test suite (`pytest tests/ -n auto`) and verify zero regressions across all 37+ existing test modules
  - [ ] 8.2 Manual testing: launch `colonyos tui`, submit a prompt, verify streaming output appears in transcript, status bar updates, composer clears and re-focuses
  - [ ] 8.3 Manual testing: verify the TUI renders correctly over SSH in a tmux session
  - [ ] 8.4 Manual testing: verify `pip install colonyos` (without `[tui]`) still works and `colonyos run` uses the existing Rich UI
  - [ ] 8.5 Manual testing: verify `colonyos tui` shows a helpful error message when textual is not installed
  - [ ] 8.6 Review all new code for: no commented-out code, no TODOs, consistent style with existing codebase, all sanitization applied
