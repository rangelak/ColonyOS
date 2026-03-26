# Tasks: TUI Default Mode, UX Fixes, Idle Visualization, Mid-Run Input & Smart Routing

## Relevant Files

- `src/colonyos/tui/app.py` - Main TUI app: Ctrl+C handler, worker management, queue consumer, mid-run input
- `src/colonyos/tui/widgets/composer.py` - Composer widget: MIN_HEIGHT, Shift+Enter key handling
- `src/colonyos/tui/widgets/status_bar.py` - StatusBar: idle state rendering, spinner timer
- `src/colonyos/tui/widgets/transcript.py` - TranscriptView: welcome banner, user injection message styling
- `src/colonyos/tui/widgets/hint_bar.py` - HintBar: keybinding hints text
- `src/colonyos/tui/styles.py` - CSS layout: composer min-height, layout constants
- `src/colonyos/tui/adapter.py` - TextualUI adapter: message types, UserInjectionMsg
- `src/colonyos/cli.py` - CLI entry point: --tui/--no-tui flag, isatty detection, _launch_tui, _handle_routed_query
- `src/colonyos/router.py` - Intent router: complexity field, prompt, parser
- `src/colonyos/config.py` - RouterConfig: small_fix_threshold, qa_model default
- `src/colonyos/orchestrator.py` - Pipeline orchestrator: skip-planning path, mid-run input polling
- `src/colonyos/models.py` - Phase enum (no changes expected)
- `tests/tui/test_app.py` - Tests for AssistantApp
- `tests/tui/test_composer.py` - Tests for Composer widget
- `tests/tui/test_status_bar.py` - Tests for StatusBar
- `tests/tui/test_transcript.py` - Tests for TranscriptView
- `tests/tui/test_adapter.py` - Tests for TextualUI adapter
- `tests/tui/test_cli_integration.py` - TUI CLI integration tests
- `tests/test_router.py` - Tests for intent router
- `tests/test_orchestrator.py` - Tests for orchestrator pipeline
- `tests/test_cli.py` - Tests for CLI commands
- `tests/test_config.py` - Tests for config parsing

## Tasks

- [ ] 1.0 Fix Ctrl+C to reliably terminate runs and quit the process (CRITICAL — ship first)
  depends_on: []
  - [ ] 1.1 Write/update tests in `tests/tui/test_app.py` for Ctrl+C cancellation behavior: verify `action_cancel_run` propagates cancellation to worker threads, verify double Ctrl+C force-quits, verify run is marked as failed on cancel
  - [ ] 1.2 Update `action_cancel_run()` in `src/colonyos/tui/app.py` to propagate SIGTERM to the orchestrator subprocess tree (use `os.killpg()` or explicit PID tracking), mark run as failed, and call `self.exit()` to quit the TUI
  - [ ] 1.3 Add double-Ctrl+C force-quit: if Ctrl+C pressed twice within 2 seconds, call `sys.exit(1)` immediately
  - [ ] 1.4 Ensure `_launch_tui` in `src/colonyos/cli.py` installs a SIGINT handler that coordinates with the TUI's cancel action (prevent the default Textual SIGINT from being swallowed)
  - [ ] 1.5 Update `HintBar.HINT_TEXT` in `src/colonyos/tui/widgets/hint_bar.py` to say "Ctrl+C quit" instead of "Ctrl+C stop run"

- [ ] 2.0 Fix composer: Shift+Enter newlines and minimum 5-line height
  depends_on: []
  - [ ] 2.1 Write/update tests in `tests/tui/test_composer.py` for Shift+Enter inserting newline, Enter submitting, and minimum height of 5 lines
  - [ ] 2.2 Update `Composer.MIN_HEIGHT` from 3 to 5 in `src/colonyos/tui/widgets/composer.py`
  - [ ] 2.3 Update CSS in `src/colonyos/tui/styles.py`: change `min-height: 3` to `min-height: 5` for both `Composer` and `Composer TextArea` / `Composer _ComposerTextArea` rules
  - [ ] 2.4 Verify/fix Shift+Enter handling in `_ComposerTextArea._on_key()` — test across terminal emulators (iTerm2, Terminal.app, kitty). If `shift+enter` key name varies, add alternate key names. Ensure `ctrl+j` fallback works.

- [ ] 3.0 Make TUI the default visualization for interactive use
  depends_on: [1.0, 2.0]
  - [ ] 3.1 Write/update tests in `tests/test_cli.py` and `tests/tui/test_cli_integration.py` for: TUI launches by default when isatty, `--no-tui` forces streaming output, non-TTY auto-degrades to streaming
  - [ ] 3.2 In `src/colonyos/cli.py` `run` command: replace `--tui` flag with `--no-tui` flag. Default to TUI when `sys.stdout.isatty()` and textual is importable. Gracefully fall back to streaming if textual is not installed.
  - [ ] 3.3 Keep the standalone `colonyos tui` command as an alias but add a deprecation notice pointing to `colonyos run`
  - [ ] 3.4 Integrate intent routing into the TUI path: when TUI is active, run `_handle_routed_query()` inside the worker thread and display results in the transcript (currently routing only works in the non-TUI CLI path)

- [ ] 4.0 Add ant-colony themed idle visualization
  depends_on: [2.0]
  - [ ] 4.1 Write/update tests in `tests/tui/test_status_bar.py` for idle animation rendering: verify animation frames cycle, verify animation stops when a phase starts, verify animation doesn't interfere with Ctrl+C
  - [ ] 4.2 In `src/colonyos/tui/widgets/status_bar.py`: replace the "idle" text in `_render_bar()` with an animated colony-themed idle state using the existing `set_interval` timer. Cycle through colony glyphs (🐜, ⬡, ◈) and status phrases ("colony awaiting orders", "workers standing by", "tunnels quiet", "antennae listening")
  - [ ] 4.3 In `src/colonyos/tui/widgets/transcript.py`: add an `append_welcome_banner()` method that renders a colony-themed ASCII art welcome message on first mount
  - [ ] 4.4 Call `append_welcome_banner()` from `AssistantApp.on_mount()` in `src/colonyos/tui/app.py` when no initial prompt is provided
  - [ ] 4.5 Add colony-themed color constants to `src/colonyos/tui/styles.py` (amber/gold for colony accents)

- [ ] 5.0 Enable mid-run user input (context injection at turn boundaries)
  depends_on: [1.0, 2.0]
  - [ ] 5.1 Write/update tests in `tests/tui/test_adapter.py` for `UserInjectionMsg` dataclass and injection channel
  - [ ] 5.2 Write/update tests in `tests/tui/test_app.py` for composer submission during active run: verify message is queued (not canceling the worker), verify transcript shows injection with distinct styling
  - [ ] 5.3 Add `UserInjectionMsg` frozen dataclass to `src/colonyos/tui/adapter.py` and add a thread-safe injection channel (second janus queue or shared list with lock)
  - [ ] 5.4 Update `on_composer_submitted()` in `src/colonyos/tui/app.py`: detect if a run is active; if so, queue the message as a `UserInjectionMsg` instead of spawning a new exclusive worker
  - [ ] 5.5 Update `TranscriptView` in `src/colonyos/tui/widgets/transcript.py`: add `append_injected_message()` method with distinct visual styling (e.g., "You (mid-run):" prefix, different color)
  - [ ] 5.6 Add sanitization: all injected text must pass through `sanitize_untrusted_content()` before being forwarded to the agent
  - [ ] 5.7 Update the orchestrator's phase loop in `src/colonyos/orchestrator.py` to check for queued user injections at turn boundaries and prepend them as additional context to the next agent turn

- [ ] 6.0 Add complexity classification to the router for smart fast-path routing
  depends_on: []
  - [ ] 6.1 Write/update tests in `tests/test_router.py` for: complexity field in `RouterResult`, prompt includes complexity instructions, parser extracts complexity (defaults to "large" on missing/invalid), small-fix routing logic
  - [ ] 6.2 Add `complexity: str = "large"` field to `RouterResult` dataclass in `src/colonyos/router.py`
  - [ ] 6.3 Update `_build_router_prompt()` in `src/colonyos/router.py` to instruct the LLM to also classify complexity as "trivial", "small", or "large" in the JSON output
  - [ ] 6.4 Update `_parse_router_response()` in `src/colonyos/router.py` to extract and validate the `complexity` field (default to "large" on missing/invalid)
  - [ ] 6.5 Update `log_router_decision()` in `src/colonyos/router.py` to include complexity in the audit log JSON
  - [ ] 6.6 Add `small_fix_threshold: float = 0.85` to `RouterConfig` in `src/colonyos/config.py` and update `_parse_router_config()` and serialization
  - [ ] 6.7 Write/update tests in `tests/test_config.py` for the new `small_fix_threshold` config field

- [ ] 7.0 Implement skip-planning fast path in orchestrator and CLI for small fixes
  depends_on: [6.0]
  - [ ] 7.1 Write/update tests in `tests/test_orchestrator.py` for: small-fix mode skips planning but runs implement→review→deliver, review is NEVER skipped
  - [ ] 7.2 Update `_handle_routed_query()` in `src/colonyos/cli.py` to detect `complexity in ("trivial", "small")` with sufficient confidence and pass a `skip_planning=True` flag to the orchestrator
  - [ ] 7.3 Update `run()` in `src/colonyos/orchestrator.py` to accept `skip_planning: bool = False` parameter. When True, skip the PLAN phase and go directly to implement (similar to existing `--from-prd` logic but without requiring a PRD file)
  - [ ] 7.4 Ensure the review phase is mandatory regardless of `skip_planning` (security requirement — never skip review for code changes)
  - [ ] 7.5 Update Q&A model default from Sonnet to Opus: change `qa_model: str = "sonnet"` to `qa_model: str = "opus"` in `RouterConfig` in `src/colonyos/config.py`, and update `DEFAULTS["router"]["qa_model"]`

- [ ] 8.0 Integration testing and polish
  depends_on: [1.0, 2.0, 3.0, 4.0, 5.0, 7.0]
  - [ ] 8.1 Run full test suite (`pytest tests/`) and fix any regressions
  - [ ] 8.2 Manual end-to-end test: launch TUI via `colonyos run "fix a typo"`, verify TUI appears by default, verify small-fix fast path triggers, verify Ctrl+C quits cleanly, verify mid-run input works
  - [ ] 8.3 Manual test: `colonyos run --no-tui "prompt"` gives plain streaming output (no TUI)
  - [ ] 8.4 Manual test: `echo "prompt" | colonyos run` (piped/non-TTY) gives plain streaming output
  - [ ] 8.5 Update `HintBar.HINT_TEXT` to reflect all current keybindings accurately
