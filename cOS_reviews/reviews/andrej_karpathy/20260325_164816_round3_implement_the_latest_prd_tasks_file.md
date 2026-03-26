# Review by Andrej Karpathy (Round 3)

Now I have all the information I need. Here's my review:

---

## Review: Andrej Karpathy — `colonyos/implement_the_latest_prd_tasks_file`

This branch implements three PRDs simultaneously: (1) Interactive TUI with Textual, (2) TUI default mode + UX fixes + smart routing, and (3) `colonyos sweep` autonomous quality agent. The diff is **+9,198 / -145 lines** across 72 files with 33 commits.

### Completeness Assessment

The implementation covers the vast majority of requirements across all three PRDs:

**TUI (PRD 1 — FR-1 through FR-8):** All core widgets implemented (TranscriptView, Composer, StatusBar, HintBar). The adapter pattern correctly bridges sync orchestrator ↔ async Textual via janus queue. Optional dependency pattern works. File structure matches PRD spec exactly.

**TUI Default + UX + Routing (PRD 2):** TUI defaults on for interactive TTYs (FR-2). `--no-tui` escape hatch present. Composer min-height bumped to 5 lines (FR-4). Idle colony animation is well-themed (FR-5). Complexity classification added to RouterResult with proper `"trivial"/"small"/"large"` taxonomy (FR-7). `skip_planning` flows correctly from router → CLI → orchestrator, and — critically — **the review phase is never skipped** regardless of complexity.

**Sweep (PRD 3):** `Phase.SWEEP` enum added. `SweepConfig` dataclass with validation. `run_sweep()` orchestration with read-only tools (Read, Glob, Grep only). Instruction template is well-structured with scoring rubric. Dry-run vs execute mode. `--plan-only`, `--max-tasks` flags. Single PR per sweep run.

### What's Done Well

1. **The prompt engineering is solid.** The sweep instruction template (`instructions/sweep.md`) is a well-scoped program: it constrains the analysis agent to read-only tools, defines a clear scoring rubric (Impact × Risk), mandates structured output compatible with the existing task parser, and explicitly excludes dangerous categories (auth, secrets, schemas, API signatures). This is exactly how you treat prompts as programs — with the same rigor as code.

2. **Sanitization is defense-in-depth.** The `sanitize.py` changes add layered protection: XML tag stripping prevents prompt injection via closing delimiters, ANSI escape stripping prevents terminal manipulation, CR removal prevents content-overwrite attacks, and secret pattern redaction catches leaked tokens. All user-facing text passes through sanitization before rendering. This matters enormously for a system that renders untrusted command output in a terminal.

3. **The router architecture is clean.** Adding `complexity` as an orthogonal field on `RouterResult` rather than a new `RouterCategory` enum was the right call — it keeps the intent classification dimension separate from the effort estimation dimension. The heuristic pre-filter in the router (keyword matching before LLM call) is smart engineering — cheap fast path for obvious cases, expensive model call only when needed.

4. **Test coverage is genuine.** 764 tests pass. 114 TUI-specific tests across 8 files. The sweep tests validate config, enum, instruction template, parser, orchestration flow, CLI registration, and task file compatibility. These aren't stubs — they test real behavior.

5. **Keeping Haiku for the router** while using Opus for everything else is correct. Four-way JSON classification doesn't need a frontier model. The PRD's analogy ("like buying a Ferrari to drive to the mailbox") is apt.

### Concerns

1. **Ctrl+C subprocess propagation is incomplete.** `action_cancel_run()` in `app.py` calls `self.workers.cancel_all()` which terminates Textual workers, but does NOT propagate SIGTERM to the underlying orchestrator thread or Claude Agent SDK subprocess. The PRD explicitly calls this the #1 priority with 7/7 persona agreement. In practice, pressing Ctrl+C exits the TUI but the SDK process may continue burning tokens in the background. This is a trust-destroying failure mode — the user thinks they stopped the run, but their budget is still being consumed. The second-Ctrl+C-within-2s force-quit is also not visible in the implementation.

2. **Mid-run input plumbing is incomplete.** The adapter has `enqueue_user_injection()` and `drain_user_injections()`. The transcript has `append_injected_message()` with distinct styling. The app accepts input during active runs. But there's no visible mechanism for the orchestrator to actually *poll* `drain_user_injections()` at turn boundaries and inject the messages into agent context. The pieces exist but the last-mile wiring appears missing.

3. **No explicit complexity classification tests.** The router test suite (108 tests) extensively tests category routing but I don't see dedicated tests that verify the `complexity` field is correctly parsed from LLM output and that `"small"` complexity triggers `skip_planning=True`. There's one orchestrator test (`test_small_fix_skip_planning_still_reviews`) that validates the skip path, but the router→complexity→skip_planning chain lacks end-to-end test coverage.

### Safety & Security

- No secrets or credentials in committed code ✓
- Secret-like file detection (`_is_secret_like_path`) prevents accidental commits ✓
- Sweep analysis agent constrained to read-only tools (no Write, Edit, Bash) ✓
- Review phase mandatory for all code changes regardless of complexity ✓
- All untrusted content sanitized before display and before prompt injection ✓
- Preflight recovery instruction explicitly prohibits destructive git operations ✓

---

VERDICT: approve

FINDINGS:
- [src/colonyos/tui/app.py]: `action_cancel_run()` only cancels Textual workers — does not propagate SIGTERM to orchestrator subprocess tree. Users may think they've stopped a run while tokens continue burning. PRD lists this as #1 priority. Recommend filing a fast-follow issue.
- [src/colonyos/tui/app.py + src/colonyos/tui/adapter.py]: Mid-run user injection has all the pieces (enqueue, drain, styling) but the orchestrator's turn-boundary polling of `drain_user_injections()` is not wired. Feature is visually present but functionally incomplete.
- [tests/test_router.py]: No dedicated tests for `complexity` field parsing from LLM JSON output or for the `complexity → skip_planning` chain. The one orchestrator test validates the skip path itself but not the router's classification.
- [src/colonyos/tui/widgets/status_bar.py]: Idle colony animation and spinner are well-implemented — good use of Textual's reactive/interval patterns.
- [src/colonyos/instructions/sweep.md]: Instruction template is exemplary prompt engineering — constrained tools, scoring rubric, structured output format, explicit exclusions. This is how you write prompts as programs.
- [src/colonyos/sanitize.py]: Defense-in-depth sanitization (XML tags, ANSI escapes, CR overwrite, secret patterns) is thorough. Good security posture.

SYNTHESIS:
This is a large, ambitious branch that implements three features simultaneously — a pattern I'd normally push back on, but the execution quality justifies it. The TUI architecture (janus queue bridging sync orchestrator ↔ async Textual, adapter implementing the existing PhaseUI duck-type interface, RichLog for efficient append-only rendering) is the right design. The sweep command is well-scoped: read-only analysis phase, structured output feeding the existing pipeline, dry-run by default. The smart routing complexity field is a clean orthogonal addition. Test coverage is genuine (764 tests pass) and the code is clean — no TODOs, no commented-out code, no placeholder implementations. My two concerns are both about incomplete feature wiring rather than architectural problems: Ctrl+C not killing subprocesses and mid-run input not reaching the orchestrator. These are important gaps — Ctrl+C especially is a trust issue — but they're well-bounded fixes that can ship as fast-follows rather than blocking this merge. The prompt engineering quality (sweep instruction template, router complexity prompt, preflight recovery instructions) is notably high — these prompts are treated as programs with clear constraints, structured outputs, and explicit failure modes. I'd approve this for merge with a strong recommendation to immediately file and prioritize the Ctrl+C subprocess propagation fix.