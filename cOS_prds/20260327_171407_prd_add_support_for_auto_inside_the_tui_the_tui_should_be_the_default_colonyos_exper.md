# PRD: TUI-Native Auto Mode, CEO Profile Rotation & UX Fixes

## Introduction/Overview

ColonyOS's TUI is already the default interactive surface — when a user runs `colonyos` with no subcommand, they get the Textual-based TUI (via `_launch_tui` in `cli.py`). However, the autonomous `auto` mode (CEO → pipeline loop) is currently CLI-only and blocked inside the TUI with a hard error: *"`auto` inside the TUI needs `--no-confirm` unless `auto_approve` is enabled."* This forces power users to drop out of the TUI for the product's most powerful workflow.

This PRD covers five tightly-coupled improvements to make the TUI the complete, first-class ColonyOS experience:

1. **Auto mode inside the TUI** — Wire the full autonomous loop (CEO → plan → implement → review → deliver) into the TUI with proper lifecycle management, cancellation, and budget visibility.
2. **CEO profile rotation** — Replace the single static CEO persona with a pool of famous founder/operator profiles that rotate per iteration, producing more diverse feature proposals.
3. **Run log persistence** — Save TUI transcript content to per-run log files for post-mortem debugging.
4. **Transcript copy/export** — Add a keybinding to export transcript content since Textual's RichLog doesn't support native text selection.
5. **Auto-scroll fix** — Fix the bug where new output yanks the user to the bottom while they're reading earlier content.

## Goals

1. **Auto-in-TUI**: Users can type `auto` (or `auto --loop 5`) in the TUI composer and have the full autonomous loop run with real-time transcript output, iteration boundaries visible in the StatusBar, and graceful cancellation via Ctrl+C.
2. **CEO diversity**: Each auto iteration uses a different CEO persona from a curated pool of founder/operator profiles, producing measurably more diverse proposals than a single static persona.
3. **Log persistence**: Every TUI run writes a plain-text transcript log to `.colonyos/logs/` (gitignored) so users can review what happened after the fact.
4. **Transcript export**: Users can press a keybinding (Ctrl+S) to dump the current transcript to a timestamped file and get the path displayed as a notice.
5. **Scroll fix**: When a user scrolls up to inspect content, new output does NOT yank them back to the bottom. Auto-scroll only re-engages when the user explicitly scrolls back to the bottom or presses End.

## User Stories

1. **As a developer using ColonyOS**, I want to type `auto` in the TUI and have it run the full autonomous loop (CEO → pipeline) with real-time output in the transcript, so I don't have to switch to the CLI for autonomous mode.
2. **As a developer running auto mode**, I want each iteration to use a different CEO persona (Steve Jobs, Elon Musk, Dario Amodei, etc.) so the system proposes a wider variety of features instead of converging on similar ideas.
3. **As a developer reviewing auto output**, I want to scroll up in the transcript without being yanked back to the bottom every time new output arrives, so I can actually read what happened.
4. **As a developer debugging a failed run**, I want a persistent log file of the TUI transcript so I can review it after closing the TUI or share it with collaborators.
5. **As a developer**, I want to press Ctrl+S to export the current transcript to a file so I can copy/paste content that I can't select natively in the TUI.
6. **As a developer with custom preferences**, I want to define my own CEO profiles in the config file and have `auto` use those instead of the defaults.

## Functional Requirements

### FR-1: Auto Mode in TUI
1. The `auto` command must work inside the TUI when `auto_approve` is enabled in config or `--no-confirm` is passed.
2. The TUI must support multi-iteration auto loops with `--loop N`, `--max-hours`, and `--max-budget` flags parsed from the composer input.
3. Each iteration boundary must emit a phase header in the transcript showing iteration number, selected CEO persona, and aggregate cost.
4. The StatusBar must display the current iteration count (e.g., "Iter 3/5") and aggregate cost during auto loops.
5. Cancellation must be two-tier: single Ctrl+C stops the loop after the current iteration completes; double Ctrl+C (within 2s) force-exits the TUI (existing behavior).
6. A `threading.Event` stop flag must be checked between iterations to enable graceful cancellation without killing mid-phase API calls.
7. The `_run_active` guard must prevent starting a second auto loop while one is running.

### FR-2: CEO Profile Rotation
1. Define a `CEO_PROFILES` constant containing 7-10 `Persona` instances representing famous founder/operator archetypes (not impersonations — use role descriptions like "Visionary Product CEO" inspired by Steve Jobs's philosophy).
2. Each profile must have meaningful `role`, `expertise`, and `perspective` fields that genuinely shape the CEO agent's proposal strategy (not just cosmetic name changes).
3. `auto` picks a profile at random by default for each iteration, avoiding the same profile twice in a row.
4. Users can override with `auto --persona <name>` to pin a specific profile.
5. Users can define custom CEO personas in `.colonyos/config.yaml` under a `ceo_profiles` key; when provided, these replace the defaults entirely.
6. The selected persona name must be displayed in the TUI StatusBar and transcript phase header.
7. Profile definitions must be validated/sanitized — user-defined profiles pass through `sanitize_display_text` to mitigate prompt injection risk.

### FR-3: Run Log Persistence
1. Every TUI session must write a plain-text transcript log to `.colonyos/logs/{run_id}.log`.
2. The `.colonyos/logs/` directory must be gitignored (added by `colonyos init`).
3. Log files must capture all transcript content: phase headers, tool calls, text blocks, command output, user messages, phase completion/error summaries.
4. Logs must strip Rich formatting to produce clean, grep-friendly plain text.
5. Log content must be sanitized using existing `SECRET_PATTERNS` from `sanitize.py` before writing to disk.
6. File permissions must be set to `0o600` (owner-only read/write).
7. Implement a `max_log_files` config option (default 50) with oldest-first rotation.

### FR-4: Transcript Export (Copy/Paste Workaround)
1. Add a `Ctrl+S` keybinding that exports the current transcript to `.colonyos/logs/transcript_{timestamp}.txt`.
2. Display a notice in the transcript with the full path to the exported file.
3. The export must produce clean plain text (no Rich markup or ANSI codes).
4. Add `Ctrl+S` to the HintBar keybinding display.

### FR-5: Auto-Scroll Fix
1. Once the user scrolls up (away from the bottom), auto-scroll must remain disabled regardless of new content arriving.
2. Auto-scroll re-enables only when: (a) the user scrolls back to the bottom manually, or (b) the user presses End.
3. Programmatic scrolls (from `scroll_end()` inside `_scroll_to_end`) must not trigger the `on_scroll_y` handler — use a `_programmatic_scroll` guard flag.
4. Remove the `_AUTO_SCROLL_THRESHOLD` constant; the new behavior is binary (at bottom = auto-scroll, not at bottom = no auto-scroll).

## Non-Goals

- **Interactive CEO persona picker/menu in TUI** — Random selection + config override is sufficient.
- **Native text selection in RichLog** — This is a Textual framework limitation; the transcript export keybinding is the pragmatic workaround.
- **Real-time streaming log file** — Logs are written at phase completion, not streamed line-by-line (avoids I/O overhead during fast tool calls).
- **CEO persona benchmarking/diversity measurement** — Interesting but out of scope for this PR.
- **Permission model changes** — The existing `bypassPermissions` + budget caps model is unchanged.
- **Splitting `cli.py`** — Acknowledged as technical debt but out of scope.

## Technical Considerations

### Auto-in-TUI Architecture
The key challenge is that the existing `auto` command in `cli.py` (line 1843) uses `click.echo` and `rich.Console.print` for all output, which doesn't work inside Textual. The TUI integration must:

- Reuse `_run_single_iteration` (line 1694) but route all output through the `TextualUI` adapter's janus queue instead of stdout.
- Pass a `TextualUI` adapter instance as the `ui` parameter to `run_ceo` and `run_orchestrator`.
- Add iteration-level messages to the adapter: `IterationHeaderMsg`, `LoopCompleteMsg`.
- Handle the auto loop lifecycle in a new `_run_auto_in_tui` function inside `_launch_tui`.

### Scroll Fix
The root cause (confirmed by Systems Engineer and Linus personas): `scroll_end()` triggers `on_scroll_y`, which re-evaluates `_auto_scroll` based on position. Since the programmatic scroll puts the viewport at the bottom, `_auto_scroll` gets flipped back to `True` even though the user explicitly scrolled away. Fix: guard `on_scroll_y` with a `_programmatic_scroll` flag set before/after `scroll_end()` calls.

### CEO Profile Design
Per Karpathy's analysis, persona rotation provides ~15-20% marginal diversity on top of what the changelog/directions context already provides. The main value is in varying `perspective` and implicit priority heuristics, not just role names. Profiles should encode genuine strategic preferences (e.g., "Prioritize developer experience and API ergonomics" vs. "Prioritize reliability and operational excellence").

### Security Considerations (from Security Engineer)
- CEO profiles defined in config pass through `sanitize_display_text` before prompt interpolation.
- Log files written with `0o600` permissions and sanitized for secrets.
- The `auto_approve` guard in `_handle_tui_command` must be preserved — auto mode in TUI requires explicit opt-in.
- Budget caps from config must be enforced in the TUI auto loop path, not just the CLI path.

### Persona Consensus Matrix

| Topic | Agreement | Tension |
|-------|-----------|---------|
| Fix scroll first | 7/7 | None |
| Full loop (not single iteration) | 7/7 | None |
| Use existing Persona dataclass | 7/7 | None |
| Random default + config override | 6/7 | Karpathy prefers strategic (least-recently-used) selection |
| Keybinding export over native selection | 7/7 | None |
| Per-run log files, plain text | 6/7 | Systems Engineer prefers JSONL |
| CEO rotation value | 5/7 positive | YC Partner and Karpathy skeptical (~gimmick risk) |
| Hardcode profiles vs. user-editable | 2/7 hardcode-only | User explicitly requested user-defined support |

## Success Metrics

1. **Auto-in-TUI adoption**: >80% of `auto` runs happen through TUI rather than CLI within 2 weeks of shipping.
2. **Scroll complaints eliminated**: Zero user reports of forced scroll-to-bottom after fix ships.
3. **Proposal diversity**: Pairwise semantic similarity of CEO proposals across different profiles is >20% lower than repeated runs with a single profile.
4. **Log utility**: Users reference log files in bug reports or debugging sessions.
5. **Export usage**: Ctrl+S keybinding is used at least once per TUI session on average.

## Open Questions

1. **Strategic vs. random profile selection**: Should we track which profiles have been used recently and prefer less-used ones (Karpathy's recommendation), or is pure random sufficient for v1?
2. **Log granularity**: Should logs capture every tool call line, or just phase-level summaries? (Current plan: everything, matching the transcript.)
3. **Auto-scroll indicator**: Should we show a "New output below ↓" indicator when auto-scroll is disabled? (Steve Jobs recommended this; would require a new widget overlay.)
4. **Queue size bounds**: The janus queue is currently unbounded. Should we add a max size for the auto loop use case to prevent memory growth during long runs?
