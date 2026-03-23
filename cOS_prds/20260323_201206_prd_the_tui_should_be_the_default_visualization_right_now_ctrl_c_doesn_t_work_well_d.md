# PRD: TUI Default Mode, UX Fixes, Idle Visualization, Mid-Run Input & Smart Routing

## Introduction/Overview

ColonyOS's interactive Textual TUI is currently opt-in (`--tui` flag) and has several critical UX bugs that break user trust: Ctrl+C doesn't actually stop runs, Shift+Enter doesn't insert newlines reliably, and the composer input box gets cut off at the bottom. Beyond fixing these broken fundamentals, this feature set makes the TUI the default visualization, adds a compelling ant-colony-themed idle state, enables user input during active runs, and introduces a smarter intent classifier that routes simple fixes directly to implement→review (skipping the full planning pipeline).

**Why this matters:** Users currently feel trapped — they can't stop a runaway agent burning Opus tokens, can't type multi-line prompts, and have to opt-in to the better interface. The "idle" screen wastes an opportunity to establish brand identity. And every typo fix goes through a 5-phase pipeline that was designed for complex features.

## Goals

1. **Fix critical UX bugs** — Ctrl+C reliably terminates the entire process (including underlying SDK subprocesses), Shift+Enter inserts newlines, and the composer shows at least 5 visible lines.
2. **TUI as default** — `colonyos run "prompt"` launches the TUI automatically when stdout is a TTY; `--no-tui` provides the escape hatch for CI/scripted use.
3. **Compelling idle state** — Replace the bare "idle" text with an animated ant-colony-themed visualization that communicates the product's identity.
4. **Mid-run user input** — Users can submit messages during an active run that get injected as context into the agent's next turn (no pause/interrupt).
5. **Smart routing with complexity classification** — The router adds a `complexity` field ("trivial"/"small"/"large") to `RouterResult`. Small code changes skip planning and go directly to implement→review. All pipeline phases use Opus.

## User Stories

1. **As a user**, I want to press Ctrl+C and have the entire run stop immediately — no orphaned subprocesses, no continued API spending — so I feel in control.
2. **As a user**, I want to type `colonyos run "fix the typo"` and see the TUI automatically, without remembering the `--tui` flag.
3. **As a user**, I want to see a cool, futuristic ant-colony animation when the TUI is idle, so I feel like I'm using something from the future.
4. **As a user**, I want to type a clarification or correction while the agent is working, and have it pick up my message on its next turn.
5. **As a user**, I want simple bug fixes to skip the planning phase and go straight to implementation, saving time and money.
6. **As a CI operator**, I want `--no-tui` to give me plain streaming output for automated pipelines.

## Functional Requirements

### FR-1: Ctrl+C Properly Terminates Runs
- `action_cancel_run()` in `tui/app.py` must propagate cancellation beyond Textual workers into the underlying `run_phase_sync` / Claude Agent SDK subprocess.
- On Ctrl+C: kill the subprocess tree (SIGTERM → SIGKILL fallback), mark the run as failed via `_fail_run_log()`, restore git branch state, and exit the TUI cleanly.
- Second Ctrl+C within 2 seconds force-quits the process (`sys.exit(1)`).

### FR-2: TUI as Default for Interactive Use
- `colonyos run` defaults to TUI when `sys.stdout.isatty()` is True and the `tui` extra is installed.
- Add `--no-tui` flag to force plain streaming output.
- Keep the existing `colonyos tui` command as an alias.
- Non-interactive commands (`status`, `show`, `stats`, `doctor`, `init`) remain unaffected.

### FR-3: Shift+Enter Inserts Newlines
- Fix the `_ComposerTextArea._on_key()` handler to reliably intercept `shift+enter` across terminal emulators.
- Add `ctrl+j` as a guaranteed fallback for newline insertion (already in code but verify it works).

### FR-4: Composer Minimum Height of 5 Lines
- Change `Composer.MIN_HEIGHT` from 3 to 5.
- Update CSS in `styles.py` to match: `min-height: 5` for both `Composer` and its inner `TextArea`.
- Ensure the transcript view still gets adequate space on small terminals (keep `TranscriptView min-height: 10`).

### FR-5: Ant-Colony Themed Idle Visualization
- Replace the "idle" text in `StatusBar._render_bar()` with an animated colony-themed idle state.
- Use the existing `set_interval` timer infrastructure for animation frames.
- Display a rotating set of colony-themed status phrases (e.g., "colony awaiting orders", "workers standing by", "tunnels quiet") with animated glyphs.
- The idle state in the `TranscriptView` should show a welcome banner with colony ASCII art on first launch.
- Animation must not interfere with SIGINT/Ctrl+C handling.

### FR-6: Mid-Run User Input (Context Injection)
- When a run is active, the Composer remains enabled and accepts user input.
- Submitted text is sanitized via `sanitize_untrusted_content()` and queued as a `UserInjectionMsg` in the janus queue.
- The orchestrator checks for queued user messages at turn boundaries and prepends them as additional context.
- The TranscriptView shows injected messages with a visual distinction from prompts that start new runs.
- The worker must NOT use `exclusive=True` during active runs (to avoid canceling the running worker).

### FR-7: Smart Routing with Complexity Classification
- Add a `complexity` field to `RouterResult`: `"trivial"` | `"small"` | `"large"` (default: `"large"`).
- Update the router prompt to classify complexity alongside intent category.
- Keep Haiku for the router classifier (fast, cheap, sufficient for classification).
- In `_handle_routed_query()` and the orchestrator's `run()`, when `category == CODE_CHANGE` and `complexity in ("trivial", "small")`: skip planning, go directly to implement→review.
- The review phase must NEVER be skipped regardless of complexity (security requirement).
- Update `RouterConfig` to add `small_fix_threshold` confidence setting.
- Switch Q&A model from Sonnet to Opus for higher-quality answers (per user direction: "All should use opus always").
- Update all pipeline phase models to use Opus (the global `model: str = "opus"` default already exists in `ColonyConfig`).

## Non-Goals

- **Removing the non-TUI interface entirely** — CI, Slack watchers, and scripted use require headless output.
- **Pausing the agent mid-turn** — Architecturally complex (requires checkpointing mid-SDK-call); inject-at-turn-boundary is sufficient.
- **Configurable idle animations** — One good default is enough; configurability adds maintenance burden.
- **Opus for the router classifier** — Haiku is correct for four-way JSON classification. Opus would be 30-60x more expensive for no meaningful accuracy gain.
- **Restructuring the orchestrator to be fully event-driven** — Out of scope; the thread + janus queue architecture is sufficient.

## Technical Considerations

### Ctrl+C Cancellation Chain
The critical path is: `action_cancel_run()` → cancel Textual worker → propagate to orchestrator thread → kill `run_phase_sync` subprocess → cleanup git state. The `claude-agent-sdk` subprocess must receive SIGTERM. Process group management (`os.setpgrp()` / `os.killpg()`) or explicit PID tracking is needed. The orchestrator already has `KeyboardInterrupt` handlers (8+ catch blocks in `cli.py` and `orchestrator.py`) that call `_fail_run_log()` — these must be reachable from the TUI cancellation path.

### Thread-Safety for Mid-Run Input
The janus queue pattern already provides thread-safe message passing from the Textual event loop to the orchestrator worker thread. A new `UserInjectionMsg` dataclass follows the same pattern as existing message types. The challenge is plumbing the message into the agent's next turn — this likely requires the `TextualUI` adapter to expose a method the orchestrator can poll at turn boundaries.

### Router Complexity Field
Adding `complexity` to the router's JSON schema is a prompt change. The existing `_parse_router_response()` already handles missing fields gracefully (defaults to CODE_CHANGE on parse failure). The new field can default to `"large"` for backward compatibility. The orchestrator needs a `_skip_planning()` code path that enters the pipeline at the implement phase — similar to the existing `--from-prd` logic.

### Files to Modify
- `src/colonyos/tui/app.py` — Ctrl+C propagation, mid-run input handling, worker exclusivity
- `src/colonyos/tui/widgets/composer.py` — MIN_HEIGHT bump, Shift+Enter fix
- `src/colonyos/tui/widgets/status_bar.py` — idle animation
- `src/colonyos/tui/widgets/transcript.py` — welcome banner, user injection message styling
- `src/colonyos/tui/styles.py` — CSS updates for composer height
- `src/colonyos/tui/adapter.py` — UserInjectionMsg, injection channel
- `src/colonyos/cli.py` — TUI default logic, `--no-tui` flag, isatty detection
- `src/colonyos/router.py` — complexity field in prompt and parser
- `src/colonyos/config.py` — RouterConfig updates (small_fix_threshold, qa_model default)
- `src/colonyos/orchestrator.py` — SMALL_FIX skip-planning path, mid-run input polling
- `src/colonyos/models.py` — No changes needed (Phase enum already has all needed values)

## Persona Synthesis & Areas of Tension

### Universal Agreement
- **Ctrl+C is the #1 priority** — All 7 personas rated it the most critical item. The current implementation is a "trust-destroying bug" (Seibel), "a violation of a thirty-year-old contract" (Ive), and "a security incident waiting to happen" (Security Engineer).
- **Keep `--no-tui` fallback** — Unanimous. CI, scripting, Slack, accessibility all need it.
- **Keep Haiku for routing** — 7/7 agree. Opus for classification is "like buying a Ferrari to drive to the mailbox" (Torvalds).
- **Don't make idle viz configurable** — 5/7 say one good default is enough.
- **Inject context, don't pause** — 5/7 prefer injection at turn boundaries.

### Key Tensions
- **SMALL_FIX: new category vs sub-classify** — Jobs advocates a new `RouterCategory.SMALL_FIX` for cleaner dispatch. Ive, Karpathy, Seibel, and Security prefer a `complexity` sub-field on `RouterResult` to keep the enum clean. **Resolution: Go with `complexity` field** — it's orthogonal to intent category and avoids touching all downstream switch statements.
- **Security concern on mid-run input** — The Security Engineer warns that injecting unsanitized user text into a live agent session with `bypassPermissions` is a prompt injection vector. **Resolution: All injected text must go through `sanitize_untrusted_content()` before reaching the agent.**
- **Review must never be skipped** — Security Engineer explicitly flags that SMALL_FIX skipping review is dangerous. **Resolution: Only planning is skippable; review is mandatory for all code changes.**
- **Linus argues against mid-run input entirely** — Says the orchestrator would need restructuring to be event-driven. **Resolution: Use the existing janus queue pattern with a polling check at turn boundaries — minimal architectural change.**

## Success Metrics

1. **Ctrl+C reliability** — 100% of Ctrl+C presses during a run result in process termination within 3 seconds, with no orphaned subprocesses.
2. **TUI adoption** — >90% of interactive `colonyos run` invocations use the TUI (measured via run log metadata).
3. **Small fix speed** — Prompts classified as `complexity: "small"` complete in <50% of the time of full pipeline runs.
4. **Mid-run input usage** — Users submit at least 1 mid-run correction in >10% of TUI sessions.
5. **No regressions** — All existing tests pass; CI/headless mode works identically to before.

## Open Questions

1. **SDK cancellation mechanism** — Does the `claude-agent-sdk` expose a cancellation/abort API, or do we need to kill the subprocess by PID? Need to check SDK docs.
2. **Shift+Enter terminal compatibility** — Some terminals don't send distinct key codes for Shift+Enter vs Enter. Do we need a terminal capability detection layer, or is `ctrl+j` as fallback sufficient?
3. **Complexity classification accuracy** — How accurately can Haiku distinguish "small" from "large" code changes? May need prompt engineering iteration and a small eval set.
4. **Turn boundary injection timing** — At what point in the agent loop can we safely inject user context? Need to verify the SDK's turn lifecycle.
