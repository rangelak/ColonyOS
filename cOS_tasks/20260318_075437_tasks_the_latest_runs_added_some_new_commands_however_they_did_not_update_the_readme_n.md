# Tasks: Interactive REPL Mode & Command Registry Sync Enforcement

## Relevant Files

- `src/colonyos/cli.py` - Main CLI entry point; `_show_welcome()` banner, `app` Click group, all subcommands. Primary file for REPL implementation and banner refactoring.
- `README.md` - CLI Reference table (lines 149-168) needs `stats` added and kept in sync.
- `src/colonyos/ui.py` - `PhaseUI` / `NullUI` classes reused by the REPL for streaming output.
- `src/colonyos/orchestrator.py` - `run()` function called by the REPL to execute pipelines.
- `src/colonyos/config.py` - `load_config()`, `ColonyConfig`, `BudgetConfig` for budget cap display.
- `tests/test_cli.py` - Existing CLI test suite using `CliRunner`. REPL tests extend this.
- `tests/test_registry_sync.py` - **New file** — Tests asserting banner and README stay in sync with registered commands.

## Tasks

- [x] 1.0 Fix immediate command drift (banner + README)
  - [x] 1.1 Add `stats` command entry to `_show_welcome()` in `src/colonyos/cli.py` with description "Aggregate run analytics"
  - [x] 1.2 Add `stats` command and its options (`-n/--last`, `--phase`) to the README CLI Reference table
  - [x] 1.3 Verify `review` command and its options (`--base`, `--no-fix`, `--decide`) are fully documented in README CLI Reference table
  - [x] 1.4 Run existing tests to confirm no regressions

- [x] 2.0 Refactor banner to generate command list dynamically
  - [x] 2.1 Write tests in `tests/test_registry_sync.py` that assert every command in `app.commands.keys()` appears in the banner output
  - [x] 2.2 Refactor `_show_welcome()` to iterate over `app.commands` and pull command names + help text from Click metadata instead of hardcoding `Text.append()` calls
  - [x] 2.3 Preserve the existing visual layout: left column (ant art, model, path), right column (commands, separator, flags)
  - [x] 2.4 Ensure the "Run `colonyos init` to get started" hint still appears when project is uninitialized
  - [x] 2.5 Run tests to verify banner renders correctly with all commands

- [x] 3.0 Add README sync enforcement test
  - [x] 3.1 Write a test in `tests/test_registry_sync.py` that reads `README.md`, extracts command names from the CLI Reference table, and asserts they match `app.commands.keys()`
  - [x] 3.2 Ensure the test fails when a command is missing from the README (verify by temporarily removing one)
  - [x] 3.3 Document in the test docstring what a contributor should do when this test fails

- [x] 4.0 Implement interactive REPL loop
  - [x] 4.1 Write tests in `tests/test_cli.py` for the REPL: (a) typing "quit" exits with code 0, (b) "exit" exits with code 0, (c) a prompt string invokes `run_orchestrator` with correct args (mocked), (d) EOF exits gracefully, (e) empty input is ignored and prompt reappears, (f) uninitialized project shows error and does not enter REPL
  - [x] 4.2 Add TTY detection gate: `if sys.stdin.isatty()` before entering REPL, otherwise show banner and exit (current behavior)
  - [x] 4.3 Implement the REPL loop in the `app()` function's `if ctx.invoked_subcommand is None` block: show banner, then `while True` with `input()` and `readline` for history
  - [x] 4.4 Add dim hint line above first prompt: `Type a feature to build, or "exit" to quit. Enter to send.`
  - [x] 4.5 Style the prompt as green `>` character with session cost: `[$0.00] > `
  - [x] 4.6 Route non-empty, non-exit input to `run_orchestrator()` with `PhaseUI(verbose=True)` for streaming output
  - [x] 4.7 Display `_print_run_summary()` after each run completes, then return to prompt
  - [x] 4.8 Accumulate session cost from each `RunLog.total_cost_usd` and update the prompt display

- [x] 5.0 Implement REPL exit handling
  - [x] 5.1 Write tests for signal handling: (a) first Ctrl+C prints hint message, (b) simulated double Ctrl+C exits cleanly
  - [x] 5.2 Handle "quit" and "exit" keywords (case-insensitive) to break the loop
  - [x] 5.3 Handle EOF (Ctrl+D / `EOFError`) to break the loop gracefully
  - [x] 5.4 Implement double Ctrl+C logic: first `KeyboardInterrupt` prints `Press Ctrl+C again to exit`, sets timestamp; second within 2 seconds exits
  - [x] 5.5 Handle `KeyboardInterrupt` during a pipeline run: let it propagate to orchestrator for cleanup, then return to prompt (do not exit REPL)

- [x] 6.0 Add REPL budget confirmation and config guards
  - [x] 6.1 Write tests for: (a) budget confirmation prompt appears with correct cap value, (b) declining confirmation returns to prompt without running, (c) uninitialized project behavior
  - [x] 6.2 Before each run, display configured `budget.per_run` cap and prompt for confirmation (default yes)
  - [x] 6.3 If `auto_approve` is true in config, skip the confirmation
  - [x] 6.4 Check for valid config at REPL startup; if missing, print error and fall through to non-REPL behavior

- [x] 7.0 Add readline history support
  - [x] 7.1 Write test that verifies `readline` is imported and history file path is correct
  - [x] 7.2 On REPL startup, `import readline` and call `readline.read_history_file("~/.colonyos_history")` (ignore FileNotFoundError)
  - [x] 7.3 On REPL exit (normal or Ctrl+C), call `readline.write_history_file("~/.colonyos_history")`
  - [x] 7.4 Set `readline.set_history_length(1000)` to cap history file size

- [x] 8.0 Final integration testing and cleanup
  - [x] 8.1 Run full test suite (`pytest`) and verify all tests pass
  - [x] 8.2 Manually test the REPL end-to-end: banner → prompt → type feature → run starts → summary → prompt returns → exit
  - [x] 8.3 Manually test non-TTY behavior: `echo "test" | colonyos` shows banner and exits
  - [x] 8.4 Verify the README CLI Reference table includes all commands and matches the dynamic banner
