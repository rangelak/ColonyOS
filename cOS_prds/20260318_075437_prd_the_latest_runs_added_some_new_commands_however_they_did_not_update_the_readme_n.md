# PRD: Interactive REPL Mode & Command Registry Sync Enforcement

## Introduction/Overview

ColonyOS has accumulated commands (`stats`, and partially `review`) that are registered in the Click CLI group but missing from both the welcome banner (`_show_welcome()` in `src/colonyos/cli.py`) and the README CLI Reference table. This creates a discoverability gap where shipped features are invisible to users.

This PRD covers three related improvements:

1. **Command registry sync** — Fix the immediate drift and make it structurally impossible for banner/README to fall out of sync with actual commands.
2. **Interactive REPL mode** — When a user types bare `colonyos` with no subcommand, show the welcome banner then drop into an interactive prompt where typing a feature description directly triggers `colonyos run`. Inspired by Claude Code's REPL experience.
3. **CI-based sync enforcement** — A pytest test that catches command/documentation drift automatically.

## Goals

1. Every registered CLI command is always visible in the welcome banner and README CLI Reference table — zero drift.
2. Users can go from `colonyos` → typing a feature idea → pipeline running, with no intermediate command knowledge required.
3. The REPL feels like a natural extension of the existing banner, not a separate mode.
4. The sync enforcement runs in the existing test suite with no new infrastructure.

## User Stories

1. **New user discovery**: As a developer who just installed ColonyOS, I type `colonyos` and see all available commands, then type a feature description directly into the prompt and the pipeline starts — no need to learn `colonyos run` first.
2. **Iterative development**: As a developer doing multiple feature runs, I stay in the REPL and type successive feature prompts without re-invoking the CLI each time. I can see accumulated session cost.
3. **Contributor safety**: As a contributor adding a new command, the test suite fails if I forget to update the banner or README, catching the issue before merge.
4. **Graceful exit**: As a user in the REPL, I can type "quit", "exit", or press Ctrl+C twice to leave, with clear hints about how to do so.

## Functional Requirements

### FR-1: Fix Immediate Command Drift
1. Add `stats` command to the welcome banner in `_show_welcome()` with description "Aggregate run analytics"
2. Add `stats` command to the README CLI Reference table with all its options
3. Verify `review` command is present in both locations (it's in the banner but partially missing from README)

### FR-2: Dynamic Banner Generation
4. Refactor `_show_welcome()` to generate the command list from the Click `app.commands` registry rather than hardcoding command names
5. Each command's summary comes from its Click docstring (the `help` parameter or function docstring)
6. Maintain the existing Rich visual style (green command names, dim separators, yellow ant logo)

### FR-3: Interactive REPL Mode
7. When `colonyos` is invoked with no subcommand and `sys.stdin.isatty()` is True, show the banner then enter an interactive prompt loop
8. When stdin is not a TTY (piped, CI), show the banner and exit (current behavior preserved)
9. The prompt character is `>` styled green, consistent with the banner's command color
10. A dim hint line appears above the first prompt: `Type a feature to build, or "exit" to quit. Enter to send.`
11. User input is passed directly to `run_orchestrator()` as the prompt argument
12. The REPL displays phase progress using the existing `PhaseUI` infrastructure (verbose mode by default in REPL)
13. After each run completes, `_print_run_summary()` is shown, then the prompt reappears
14. Session cost accumulates and is displayed in the prompt: `[$4.23] > `
15. Exit on: typing "quit", "exit", EOF (Ctrl+D), or double Ctrl+C within 2 seconds
16. First Ctrl+C prints a dim message: `Press Ctrl+C again to exit`
17. Empty input (just Enter) is silently ignored, prompt reappears
18. If project is not initialized (no `.colonyos/config.yaml`), print "Run `colonyos init` first" and do not enter the REPL
19. Before launching each run, display the configured per-run budget cap: `Max cost: $15.00 (per_run cap). Proceed? [Y/n]` — confirm by default
20. Support readline-based command history (up arrow) via `import readline`; persist to `~/.colonyos_history`

### FR-4: Sync Enforcement Test
21. Add `tests/test_registry_sync.py` with a test that introspects `app.commands.keys()` and asserts every command name appears in the `_show_welcome()` output
22. Add a test that asserts every command name appears in the README CLI Reference table
23. These tests run as part of the standard `pytest` suite and in CI

## Non-Goals

- **Natural language command routing**: The REPL only routes to `run`. It does not try to map "check my setup" → `doctor`. Users type subcommands directly for non-run operations.
- **Multiline input**: The REPL accepts single-line prompts only. For complex prompts, users should use `colonyos run "..."` or `--from-prd`.
- **Shell replacement**: The REPL is not a shell. It does not support piping, tab completion of subcommands, or command chaining.
- **README auto-generation**: We do not auto-generate the README from code. The test asserts sync; humans maintain the README content and wording.
- **Git pre-push hooks**: Per persona consensus, git hooks are opt-in and fragile. We use pytest tests + CI for enforcement, not hooks.
- **New runtime dependencies**: No `prompt_toolkit`. We use stdlib `readline` + `input()` to avoid dependency bloat. The existing four runtime deps (click, pyyaml, claude-agent-sdk, rich) are sufficient.

## Technical Considerations

### Existing Code Structure
- `src/colonyos/cli.py` — `_show_welcome()` (lines 62-149) hardcodes command names via `Text.append()`. The `app` Click group (line 152) uses `invoke_without_command=True`. The REPL logic goes in the `if ctx.invoked_subcommand is None` block (line 157).
- `src/colonyos/ui.py` — `PhaseUI` and `NullUI` classes for streaming output. REPL reuses `PhaseUI`.
- `src/colonyos/orchestrator.py` — `run()` function is the entry point for the pipeline. REPL calls this directly.
- `src/colonyos/config.py` — `load_config()` and `ColonyConfig` for budget caps.
- `tests/test_cli.py` — Extensive test suite using `CliRunner`. REPL tests go here or in a new file.

### Signal Handling
- First Ctrl+C catches `KeyboardInterrupt`, prints hint, sets a flag with timestamp
- Second Ctrl+C within 2 seconds exits cleanly
- During a run, Ctrl+C propagates to the orchestrator which handles cleanup (atomic state writes via `_save_loop_state` pattern)

### Banner Refactoring
- Extract a `COMMAND_METADATA` dict or generate from `app.commands` at render time
- Each command's Click docstring becomes the banner description
- The dynamic generation must preserve the current visual layout (left column: ant art, right column: commands + flags)

### Persona Consensus & Tensions

**Strong agreement across all personas:**
- The sync problem is real and must be fixed (all 7 personas)
- A pytest test is the right enforcement mechanism, not git hooks (6/7 — Steve Jobs preferred self-documenting code, but a test achieves the same goal)
- The REPL should only route to `run`, not all commands (all 7)
- Clean prompt with no run history (use `status` for that) (all 7)
- Guard against non-TTY environments with `sys.stdin.isatty()` (4/4 who addressed it)

**Key tensions:**
- **REPL value**: Linus Torvalds argues the REPL is overengineering for a tool that runs long pipelines ("the shell is already the REPL"). Michael Seibel agrees it's a nice-to-have, not critical. Steve Jobs and Karpathy see it as reducing friction at the discovery moment. **Resolution**: Ship it, but keep it minimal — a simple `while True` + `input()` loop, not a framework.
- **Dependencies**: Systems engineer recommends `prompt_toolkit` for proper async cancellation. Linus and Seibel say stdlib only. **Resolution**: Use stdlib `readline` + `input()`. The REPL is simple enough that prompt_toolkit's benefits don't justify the dependency.
- **Dynamic vs static banner**: Steve Jobs wants the banner generated from the Click registry. Linus prefers a test that catches drift. **Resolution**: Generate dynamically from Click registry (eliminates drift structurally) AND add a test for the README (catches the other sync surface).
- **Cost confirmation**: Security engineer and Karpathy strongly recommend a confirmation step before each REPL run. Seibel thinks it adds friction. **Resolution**: Show the budget cap and confirm, but default to "yes" so Enter proceeds immediately.

## Success Metrics

1. `pytest tests/test_registry_sync.py` passes and would fail if a new command were added without updating README
2. The REPL starts and exits cleanly in manual testing
3. `colonyos` in a non-TTY environment shows the banner and exits (no REPL)
4. All existing tests continue to pass after changes

## Open Questions

1. Should the REPL support `--verbose` / `--quiet` flags, or should it default to verbose (streaming output)?
2. Should the REPL persist history across sessions to `~/.colonyos_history`, or keep history in-memory only?
3. Should the cost confirmation be skippable if `auto_approve: true` is set in config?
