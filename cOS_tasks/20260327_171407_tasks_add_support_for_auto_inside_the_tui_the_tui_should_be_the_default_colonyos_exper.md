# Tasks: TUI-Native Auto Mode, CEO Profile Rotation & UX Fixes

## Relevant Files

- `src/colonyos/tui/widgets/transcript.py` - TranscriptView with auto-scroll logic (FR-5 fix target)
- `tests/tui/test_transcript.py` - Tests for TranscriptView scroll behavior
- `src/colonyos/tui/app.py` - AssistantApp with worker lifecycle, keybindings, queue consumer
- `tests/tui/test_app.py` - Tests for AssistantApp
- `src/colonyos/tui/adapter.py` - TextualUI adapter and message types (new messages needed)
- `tests/tui/test_adapter.py` - Tests for TextualUI adapter
- `src/colonyos/tui/widgets/status_bar.py` - StatusBar (needs iteration count display)
- `tests/tui/test_status_bar.py` - Tests for StatusBar
- `src/colonyos/tui/widgets/hint_bar.py` - HintBar (needs Ctrl+S hint)
- `src/colonyos/tui/styles.py` - CSS and color constants
- `src/colonyos/cli.py` - `_handle_tui_command`, `_launch_tui`, `auto` command, `_run_single_iteration`
- `tests/test_cli.py` - CLI integration tests
- `src/colonyos/orchestrator.py` - `run_ceo`, `_build_ceo_prompt`, `DEFAULT_CEO_PERSONA`
- `tests/test_orchestrator.py` - Orchestrator tests
- `src/colonyos/models.py` - `Persona` dataclass, `LoopState`
- `src/colonyos/config.py` - `ColonyConfig`, `ceo_persona` field
- `tests/test_config.py` - Config tests
- `src/colonyos/persona_packs.py` - Existing persona pack infrastructure
- `src/colonyos/ceo_profiles.py` - **New file**: CEO founder/operator profile definitions
- `tests/test_ceo_profiles.py` - **New file**: Tests for CEO profile selection
- `src/colonyos/tui/log_writer.py` - **New file**: TUI transcript log writer
- `tests/tui/test_log_writer.py` - **New file**: Tests for log writer
- `src/colonyos/instructions/ceo.md` - CEO prompt template
- `src/colonyos/sanitize.py` - `sanitize_display_text`, `SECRET_PATTERNS`

## Tasks

- [x] 1.0 Fix auto-scroll behavior in TranscriptView (FR-5)
  depends_on: []
  - [x] 1.1 Write tests for the new scroll behavior: verify that `_auto_scroll` stays `False` after user scrolls up even when new content is appended; verify programmatic scrolls don't re-enable auto-scroll; verify scrolling to bottom re-enables auto-scroll; verify End key re-enables auto-scroll.
    - File: `tests/tui/test_transcript.py`
  - [x] 1.2 Add `_programmatic_scroll` guard flag to `TranscriptView`. Set it `True` before `scroll_end()` calls, `False` after. In `on_scroll_y`, skip auto-scroll evaluation when flag is set.
    - File: `src/colonyos/tui/widgets/transcript.py`
  - [x] 1.3 Remove `_AUTO_SCROLL_THRESHOLD` constant. Change `on_scroll_y` to binary: `_auto_scroll = (scroll_y >= max_scroll)` (at bottom = enabled, otherwise disabled).
    - File: `src/colonyos/tui/widgets/transcript.py`
  - [x] 1.4 Add End key binding in `AssistantApp` that scrolls transcript to bottom and re-enables auto-scroll.
    - Files: `src/colonyos/tui/app.py`, `src/colonyos/tui/widgets/transcript.py`

- [x] 2.0 Define CEO founder/operator profiles (FR-2 profiles)
  depends_on: []
  - [x] 2.1 Write tests for CEO profile definitions: verify all profiles have non-empty role/expertise/perspective; verify `get_ceo_profile` returns a valid Persona; verify random selection avoids consecutive duplicates; verify `get_ceo_profile(name=...)` returns the named profile or raises ValueError.
    - File: `tests/test_ceo_profiles.py`
  - [x] 2.2 Create `src/colonyos/ceo_profiles.py` with `CEO_PROFILES` tuple of 8 `Persona` instances inspired by: Elon Musk (first-principles engineering CEO), Steve Jobs (product-obsessed simplicity CEO), Dario Amodei (safety-conscious AI CEO), Michael Seibel (velocity-focused startup CEO), Sam Altman (ambitious scaling CEO), Mark Zuckerberg (platform-thinking CEO), Larry Page (moonshot-thinking CEO), Jensen Huang (full-stack computing CEO). Use descriptive roles, not impersonation names.
    - File: `src/colonyos/ceo_profiles.py`
  - [x] 2.3 Add `get_ceo_profile(name: str | None = None, exclude: str | None = None) -> Persona` function that returns a random profile (excluding `exclude` to avoid repeats), or the named profile if specified.
    - File: `src/colonyos/ceo_profiles.py`
  - [x] 2.4 Add `ceo_profiles` config key to `ColonyConfig` (list of Persona dicts, optional). When provided, these replace the default `CEO_PROFILES`. Validate and sanitize user-defined profiles on load.
    - Files: `src/colonyos/config.py`, `tests/test_config.py`

- [x] 3.0 Implement TUI transcript log writer (FR-3)
  depends_on: []
  - [x] 3.1 Write tests for log writer: verify log file is created with correct permissions (0o600); verify plain-text output has no Rich markup; verify secret patterns are redacted; verify max_log_files rotation deletes oldest files; verify log content matches transcript messages.
    - File: `tests/tui/test_log_writer.py`
  - [x] 3.2 Create `src/colonyos/tui/log_writer.py` with a `TranscriptLogWriter` class that accepts transcript messages and writes plain-text to a log file. Use `sanitize.SECRET_PATTERNS` for redaction. Set file permissions to `0o600`.
    - File: `src/colonyos/tui/log_writer.py`
  - [x] 3.3 Add `max_log_files` config option (default 50) and rotation logic to `TranscriptLogWriter`.
    - Files: `src/colonyos/tui/log_writer.py`, `src/colonyos/config.py`
  - [x] 3.4 Ensure `.colonyos/logs/` is added to `.gitignore` by `colonyos init`.
    - File: `src/colonyos/cli.py` (init command section)

- [x] 4.0 Add transcript export keybinding (FR-4)
  depends_on: [1.0, 3.0]
  - [x] 4.1 Write tests for transcript export: verify Ctrl+S creates a file; verify file path notice appears in transcript; verify exported content is plain text.
    - File: `tests/tui/test_app.py`
  - [x] 4.2 Add `action_export_transcript` method to `AssistantApp` that dumps current transcript content to `.colonyos/logs/transcript_{timestamp}.txt` and appends a notice with the file path.
    - File: `src/colonyos/tui/app.py`
  - [x] 4.3 Add `Ctrl+S` binding to `AssistantApp.BINDINGS` and add hint to `HintBar`.
    - Files: `src/colonyos/tui/app.py`, `src/colonyos/tui/widgets/hint_bar.py`
  - [x] 4.4 Add `get_plain_text` method to `TranscriptView` that returns the full transcript as plain text (stripping Rich renderables to text).
    - File: `src/colonyos/tui/widgets/transcript.py`

- [x] 5.0 Wire auto mode into the TUI (FR-1 — core integration)
  depends_on: [1.0, 2.0]
  - [x] 5.1 Write tests for TUI auto mode: verify `auto` command is accepted when `auto_approve` is True; verify `auto --loop 3` parses correctly; verify iteration header messages appear in transcript; verify Ctrl+C between iterations stops the loop gracefully; verify double Ctrl+C exits the TUI; verify `_run_active` prevents concurrent auto loops.
    - File: `tests/tui/test_cli_integration.py`
  - [x] 5.2 Add new adapter message types: `IterationHeaderMsg(iteration: int, total: int, persona_name: str, aggregate_cost: float)` and `LoopCompleteMsg(iterations_completed: int, total_cost: float)`.
    - Files: `src/colonyos/tui/adapter.py`, `tests/tui/test_adapter.py`
  - [x] 5.3 Update `_consume_queue` in `AssistantApp` to handle `IterationHeaderMsg` (update StatusBar iteration display, append iteration header to transcript) and `LoopCompleteMsg` (show summary).
    - File: `src/colonyos/tui/app.py`
  - [x] 5.4 Add iteration count display to `StatusBar` — new reactive `iteration` and `total_iterations` attributes, rendered as "Iter 3/5" when active.
    - Files: `src/colonyos/tui/widgets/status_bar.py`, `tests/tui/test_status_bar.py`
  - [x] 5.5 Implement `_run_auto_in_tui` function inside `_launch_tui` that: parses auto flags from composer input, runs `_run_single_iteration` in a loop inside a worker thread, emits `IterationHeaderMsg` per iteration, checks a `threading.Event` stop flag between iterations, enforces budget/time caps, and emits `LoopCompleteMsg` on completion.
    - File: `src/colonyos/cli.py`
  - [x] 5.6 Update `_handle_tui_command` to route `auto` commands to `_run_auto_in_tui` instead of blocking with an error. Parse `--loop`, `--no-confirm`, `--max-hours`, `--max-budget`, `--propose-only`, `--persona` flags from the composer input.
    - File: `src/colonyos/cli.py`
  - [x] 5.7 Implement two-tier cancellation: update `action_cancel_run` to set the stop `threading.Event` on first Ctrl+C (graceful stop between iterations) and call `self.exit()` on second Ctrl+C within 2s (existing behavior). Remove the unconditional `self.exit()` from the first Ctrl+C path.
    - File: `src/colonyos/tui/app.py`

- [x] 6.0 Integrate CEO profile rotation into orchestrator (FR-2 wiring)
  depends_on: [2.0, 5.0]
  - [x] 6.1 Write tests for CEO profile rotation in orchestrator: verify `run_ceo` uses the provided persona; verify `_run_single_iteration` passes a different persona per iteration; verify `--persona` flag pins a specific profile.
    - File: `tests/test_orchestrator.py`
  - [x] 6.2 Update `_run_single_iteration` to accept an optional `ceo_persona: Persona | None` parameter and pass it through to `run_ceo`. When `None`, use `get_ceo_profile(exclude=last_profile_name)` for random rotation.
    - Files: `src/colonyos/cli.py`, `src/colonyos/orchestrator.py`
  - [x] 6.3 Update `_build_ceo_prompt` to use the passed persona instead of `config.ceo_persona` when one is provided, preserving backward compatibility.
    - File: `src/colonyos/orchestrator.py`
  - [x] 6.4 Log the selected persona name in the CEO phase's `PhaseResult.artifacts` dict for run history tracking.
    - File: `src/colonyos/orchestrator.py`

- [x] 7.0 Integration: Wire log writer into TUI and connect all pieces (FR-3 + FR-1 integration)
  depends_on: [3.0, 5.0]
  - [x] 7.1 Write integration tests: verify that a full auto run inside the TUI produces both transcript output AND a log file; verify log file content matches transcript; verify log rotation works across multiple runs.
    - File: `tests/tui/test_cli_integration.py`
  - [x] 7.2 Instantiate `TranscriptLogWriter` in `_launch_tui` and hook it into the `_consume_queue` loop so every dispatched message is also written to the log file.
    - File: `src/colonyos/cli.py`
  - [x] 7.3 Ensure `TranscriptLogWriter` is properly closed on TUI exit (in `on_unmount` or the `finally` block of `_launch_tui`).
    - File: `src/colonyos/tui/app.py` or `src/colonyos/cli.py`

- [x] 8.0 Final validation and polish
  depends_on: [4.0, 6.0, 7.0]
  - [x] 8.1 Run full test suite (`pytest tests/`) and fix any regressions.
  - [x] 8.2 Manual smoke test: launch TUI → type `auto --loop 2` → verify iteration headers, CEO persona display, auto-scroll behavior, Ctrl+C graceful stop, log file creation, and Ctrl+S transcript export.
  - [x] 8.3 Update HintBar to show `auto` as an available command alongside existing hints.
    - File: `src/colonyos/tui/widgets/hint_bar.py`
  - [x] 8.4 Verify `.colonyos/logs/` is gitignored and log files have 0o600 permissions.
