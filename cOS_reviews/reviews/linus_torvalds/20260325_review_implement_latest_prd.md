# Review: `colonyos/implement_the_latest_prd_tasks_file`

**Reviewer**: Linus Torvalds
**Date**: 2025-03-25
**Branch**: `colonyos/implement_the_latest_prd_tasks_file`

## Summary

This branch implements three major feature sets across 72 changed files (+9,084 / -149 lines):

1. **Interactive TUI** (Textual-based terminal UI with transcript, composer, status bar)
2. **TUI Default Mode + UX Fixes** (TUI as default, Ctrl+C, smart routing, mid-run injection, idle viz)
3. **`colonyos sweep`** (autonomous codebase quality analysis command)

All 1,922 tests pass. No TODOs, no secrets, no commented-out code.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/config.py]: Router model changed from "haiku" to "opus" for both `model` and `qa_model`. The TUI-default PRD explicitly states "Keep Haiku for routing — 7/7 agree" and "Opus for classification is like buying a Ferrari to drive to the mailbox". However, the user's top-level direction says "Default to opus for all phases — quality matters more than cost savings." The user direction wins. Acceptable.
- [src/colonyos/router.py]: The router module was substantially restructured — the original `RouterCategory`-based classifier coexists alongside a new `ModeAgentMode` system for TUI mode selection. This is two routing systems in one file. Not ideal, but it works because the old one handles legacy CLI and the new one handles TUI. The heuristic `_heuristic_mode_decision()` with regex patterns is the right call — cheap and predictable before falling back to an LLM call.
- [src/colonyos/cli.py]: The `_launch_tui` function is 100+ lines of nested closures (`_recovery_callback`, `_run_callback`, `_inject_callback`). This is the messiest part of the implementation. The closures capture `current_adapter` via `nonlocal` and mutate it freely. It works because there's only one run at a time, but it's fragile state management. The `_route_prompt` / `_handle_routed_query` duplication (new mode-based vs old category-based) adds weight but preserves backward compatibility.
- [src/colonyos/orchestrator.py]: `run_preflight_recovery()` is well-guarded — refuses secret files, validates commit scope, checks that the recovery agent didn't expand beyond the dirty files. Good defensive code. The `_drain_injected_context()` pattern is clean. The `_write_fast_path_artifacts()` creates stub PRD/task files for skip-planning runs, which is the simple obvious thing.
- [src/colonyos/tui/adapter.py]: Clean adapter with proper thread-safety (Lock on injection deque). Sanitizes all output through `sanitize_display_text()`. The 8-method duck-type interface contract is preserved. Good.
- [src/colonyos/tui/app.py]: The double-Ctrl+C force-quit via `SystemExit(1)` is correct. Worker uses `exclusive=False` as required by the PRD for mid-run input. The `_run_with_lifecycle` try/finally ensures `_mark_run_finished` always runs. Solid lifecycle management.
- [src/colonyos/sanitize.py]: The expanded ANSI regex now covers OSC, DCS, and single-char escapes. The carriage return normalization (`\r\n` → `\n`, bare `\r` stripped) closes a real terminal content-overwrite attack vector. Good security fix.
- [src/colonyos/models.py]: `PreflightError` now carries `code` and `details` dict — this is what enables the TUI dirty-worktree recovery flow. Clean enhancement.
- [src/colonyos/instructions/sweep.md]: Well-structured analysis prompt with clear scoring rubric, exclusions, and output format constraints. The task file format is compatible with `parse_task_file()`.
- [src/colonyos/instructions/preflight_recovery.md]: Conservative recovery instructions — no destructive git ops, no broad staging, no secret files. Good safety constraints.

SYNTHESIS:
This is a large branch — 9,000+ lines across 72 files. The data structures are clean: frozen dataclasses for queue messages, clear separation between the adapter (thread-safe sync queue producer) and the app (async consumer). The sweep implementation follows the existing `run_ceo()` pattern exactly, which is the right thing to do. The preflight recovery system is properly paranoid about scope creep and secrets. The sanitizer improvements are genuine security fixes that should have existed earlier. The biggest weakness is `cli.py` — it's accumulating too many responsibilities and the `_launch_tui` closure soup is the kind of thing that will become a maintenance headache. But it works, it's tested, and the alternative (premature refactoring into more modules) would be worse right now. The router model change to opus contradicts persona consensus but correctly follows the user's explicit direction. Ship it.
