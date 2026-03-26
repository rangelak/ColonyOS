# Review: colonyos/implement_the_latest_prd_tasks_file

**Reviewer**: Andrej Karpathy
**Branch**: `colonyos/implement_the_latest_prd_tasks_file`
**PRDs Covered**: TUI (20260323), TUI Default + Smart Routing (20260323), Sweep (20260324)
**Date**: 2025-03-25

---

## Checklist

### Completeness
- [x] TUI entry point (`colonyos tui`, `--tui`, auto-default when TTY)
- [x] TranscriptView, Composer, StatusBar, HintBar widgets
- [x] TextualUI adapter with janus queue bridge
- [x] Ctrl+C cancellation chain
- [x] TUI as default for interactive use with `--no-tui` escape hatch
- [x] Mid-run user injection via `UserInjectionMsg`
- [x] Smart routing with `ModeAgentMode` (replaces old `complexity` field approach with a cleaner mode-selection agent)
- [x] `colonyos sweep` command with read-only analysis phase
- [x] `Phase.SWEEP` and `Phase.PREFLIGHT_RECOVERY` enum values
- [x] `SweepConfig` dataclass and config parsing
- [x] Sweep instruction template (`instructions/sweep.md`)
- [x] Preflight recovery agent for dirty worktree
- [x] Output sanitization hardened (OSC, DCS, bare CR attacks)
- [x] All 1922 tests pass

### Quality
- [x] Tests pass (1922 passed)
- [x] Code follows existing conventions (dataclass patterns, Click decorators, instruction templates)
- [x] No unnecessary dependencies (textual/janus remain optional)
- [x] Comprehensive test coverage for new TUI widgets, adapter, sweep, router modes

### Safety
- [x] No secrets in committed code
- [x] Preflight recovery explicitly blocks secret-like files (`_is_secret_like_path`)
- [x] Sweep analysis phase is read-only (`Read`, `Glob`, `Grep` only)
- [x] All injected user text goes through `sanitize_untrusted_content()`
- [x] Sanitizer now handles OSC/DCS escape sequences and bare CR overwrite attacks

---

## Findings

### Positive

- [src/colonyos/tui/adapter.py]: The `TextualUI` adapter is well-designed. It correctly implements the 8-method duck-type interface, uses a thread-safe janus queue, coalesces text deltas into blocks flushed on `on_turn_complete`, and sanitizes all output before queuing. This is the right level of abstraction — the orchestrator thread doesn't know about Textual, and Textual doesn't know about the SDK.

- [src/colonyos/router.py]: The `ModeAgentMode` enum and `choose_tui_mode()` are a better design than the PRD's `complexity` field approach. Instead of bolting a sub-field onto `RouterResult`, the implementation creates a clean parallel routing system with its own heuristic fast-path and LLM fallback. The heuristic patterns use word-boundary regex to avoid false positives like "make sure" matching "make". Smart.

- [src/colonyos/sanitize.py]: The sanitizer improvements are genuinely important security work. Bare `\r` overwrite attacks are a real terminal injection vector, and stripping OSC/DCS sequences prevents clipboard injection via `\x1b]52;...`. This should have been done earlier, but it's done right now.

- [src/colonyos/instructions/sweep.md]: Excellent prompt engineering. The scoring rubric is concrete (1-5 scales with examples), the output format is precisely specified to match `parse_task_file()`, the exclusions are explicit, and the persona framing ("staff engineer joining the team") gives the model the right calibration. This is how you write a prompt that produces reliable structured output.

- [src/colonyos/orchestrator.py]: The preflight recovery agent has proper scope validation — it checks that the recovery commit covers exactly the blocked files (no more, no less), rejects secret-like files, and fails if the agent expanded scope. This is the right level of paranoia for an agent that runs `git add` and `git commit`.

### Concerns

- [src/colonyos/config.py]: **Router model changed from `haiku` to `opus`**. The PRD explicitly says "Keep Haiku for routing — 7/7 agree. Opus for classification is 'like buying a Ferrari to drive to the mailbox.'" Yet the implementation changes `RouterConfig.model` default from `"haiku"` to `"opus"`. The mode-selection call in `choose_tui_mode()` uses this as its model. This is a 30-60x cost increase for a simple JSON classification task. The heuristic fast-path mitigates this somewhat (many requests will be caught before the LLM call), but when the heuristic falls through, you're running Opus for a 4-way JSON switch. The `qa_model` change to opus is fine per user direction, but the router classifier model should stay haiku.

- [src/colonyos/router.py]: The `_heuristic_mode_decision()` function is good but has a structural issue: the patterns are evaluated in a fixed order, so a query like "add a review for the new feature" would match `_PIPELINE_PATTERNS` (because of "add") before it could match the review heuristic. The review check (`startswith("review ")`) runs earlier in the function, but "add a review" doesn't start with "review". This is fine for v1 since the LLM fallback would handle it, but the heuristic ordering deserves a comment explaining the precedence.

- [src/colonyos/tui/app.py]: The `_last_cancel_at` double-Ctrl+C pattern is implemented but I don't see where the actual subprocess kill chain lives. The `action_cancel_run` method should propagate cancellation to the underlying Claude SDK subprocess. If the `cancel_callback` is `None` or doesn't kill the process tree, Ctrl+C just cancels the Textual worker but leaves the SDK subprocess burning tokens. Need to verify the `cancel_callback` wiring in `_launch_tui`.

- [src/colonyos/cli.py]: The `_launch_tui` function and its `_handle_tui_command` helper are doing a lot of work. The `_route_prompt` → `RouteOutcome` → dispatch pattern in the TUI is essentially a second routing layer on top of the mode-selection agent. There's `_handle_routed_query` (legacy) and `_route_prompt` (new TUI path) — two different routing codepaths that could drift over time. Consider a TODO/tracking issue to unify these.

- [src/colonyos/orchestrator.py]: `_drain_injected_context()` is called... where? I see the function defined but need to verify it's wired into the actual phase execution loop. If it's not being called at turn boundaries, mid-run injection is defined but not connected.

---

## Metrics Check

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| All tests pass | 0 failures | 1922 passed | PASS |
| Zero test regressions | No existing test breakage | All pass | PASS |
| Optional install | `textual` not required | Guarded with try/except | PASS |
| Sweep read-only tools | Read, Glob, Grep only | Per instruction template | PASS |
| Review never skipped | Mandatory for all code changes | Not skipped in any path | PASS |

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/config.py]: Router classifier model changed from haiku to opus, contradicting all three PRDs and the unanimous persona consensus. The mode-selection LLM call should use haiku — it's a cheap JSON classification, not a creative task. The qa_model→opus change is fine.
- [src/colonyos/router.py]: Heuristic pattern precedence needs a comment — "add a review" will match PIPELINE_PATTERNS before REVIEW, falling through to the LLM unnecessarily.
- [src/colonyos/tui/app.py]: Verify that cancel_callback actually kills the SDK subprocess tree, not just the Textual worker. The PRD's FR-1 requires SIGTERM→SIGKILL propagation.
- [src/colonyos/orchestrator.py]: Confirm _drain_injected_context() is wired into phase execution. The function exists but its call site needs verification.
- [src/colonyos/cli.py]: Two parallel routing codepaths (_handle_routed_query legacy + _route_prompt TUI) — track unification to prevent drift.

SYNTHESIS:
This is a large, ambitious branch that implements three PRDs worth of functionality: a full Textual TUI, a sweep command, and smart routing. The architecture is sound — the janus queue bridge, the adapter pattern, the mode-selection heuristic/LLM cascade, and the sweep instruction template are all well-engineered. The security improvements to the sanitizer are genuinely valuable. The test coverage is impressive (1922 tests, all passing). However, there's one blocking issue: the router model was changed from haiku to opus for the classification step, which is a direct contradiction of the PRD and will burn 30-60x more money on every non-heuristic routing decision. This is the kind of mistake that compounds silently — users won't notice until their bill arrives. Fix the router.model default back to haiku (keep qa_model as opus), verify the Ctrl+C kill chain actually propagates to the SDK subprocess, and this is ready to ship.
