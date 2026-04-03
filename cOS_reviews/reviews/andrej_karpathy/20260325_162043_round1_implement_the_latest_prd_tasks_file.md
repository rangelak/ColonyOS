# Review by Andrej Karpathy (Round 1)

Now I have a comprehensive picture. Let me write the review.

---

## Review: Andrej Karpathy — AI Engineering & Prompt Design Perspective

This implementation spans three interconnected PRDs: (1) Interactive TUI with Textual, (2) TUI UX fixes + smart routing, and (3) the `colonyos sweep` autonomous quality analysis command. I've read the PRDs, reviewed the full diff (~8,900 lines added across 72 files), examined all key implementation files, and verified that **all 1,898 tests pass**.

### Completeness Assessment

**TUI (PRDs 1 & 2):**
- ✅ FR-1 through FR-8 from TUI PRD are implemented: transcript pane, composer, status bar, TextualUI adapter, keybindings, optional dependency
- ✅ Ctrl+C cancellation with SIGTERM propagation and double-tap force exit
- ✅ TUI as default when `isatty()` and textual installed
- ✅ Shift+Enter / Ctrl+J newline insertion
- ✅ Mid-run user injection via janus queue with `sanitize_untrusted_content()`
- ✅ Smart routing via `ModeAgentMode` with heuristic fast path and LLM fallback
- ✅ Dirty-worktree preflight recovery phase with secret file guards

**Sweep (PRD 3):**
- ✅ FR-1: `colonyos sweep` CLI command with all flags (`--execute`, `--plan-only`, `--max-tasks`, etc.)
- ✅ FR-2: `Phase.SWEEP` enum with read-only tools `["Read", "Glob", "Grep"]`
- ✅ FR-3: `instructions/sweep.md` — well-crafted Staff Engineer persona prompt with scoring rubric, exclusions, and `parse_task_file()`-compatible output format
- ✅ FR-4: `run_sweep()` orchestration with dry-run/plan-only/execute modes
- ✅ FR-5: `SweepConfig` dataclass with validation
- ✅ FR-6: Rich table output for dry-run with color-coded scores
- ✅ FR-7: Single PR per sweep run via delegation to `run()` with `skip_planning=True`

### Quality Assessment from AI Engineering Perspective

**Prompts as Programs — Sweep Instruction (`sweep.md`):**
This is the most important artifact from a prompt engineering standpoint, and it's excellent. The scoring rubric (Impact 1-5 × Risk 1-5) gives the model a structured decision framework rather than vague "find issues." The exclusion list (auth, secrets, DB schemas, public APIs) is a critical safety boundary — the model needs explicit fences for what NOT to touch. The output format is tightly constrained to match `parse_task_file()`, which is exactly right: structured output makes the system reliable by reducing the stochastic surface area. The `depends_on:` annotation requirement enables the DAG to parallelize independent tasks. This prompt treats the model as a structured analysis tool, not a free-form assistant — correct approach.

**Mode Selection Router — Heuristic-First Pattern:**
The `_heuristic_mode_decision()` function is a smart design choice. Cheap keyword matching handles the obvious cases (questions, explicit "review", "cleanup" keywords) without burning a model call. The LLM fallback only fires for ambiguous inputs. This is the right pattern for production: deterministic where possible, stochastic only where needed. Confidence scores flow through the system, which enables downstream decisions about how aggressively to act.

**Sanitization as Defense-in-Depth:**
The `sanitize_display_text()` changes are a meaningful security improvement. The new regex covers CSI, OSC, DCS, and single-char escape sequences — not just basic ANSI colors. The `\r` stripping prevents content-overwrite attacks where `"safe text\rmalicious"` renders as `malicious`. This is applied consistently through the `TextualUI` adapter before rendering. Good.

**Thread-Safety for Orchestrator ↔ TUI Bridge:**
The janus queue pattern (sync producer in orchestrator thread → async consumer in Textual event loop) is the right architecture. The `TextualUI` adapter posts frozen dataclass messages, which are inherently thread-safe. The injection queue uses an explicit `Lock`. No shared mutable state crosses the thread boundary.

**`parse_sweep_findings()` Structured Output Parser:**
The regex-based parser for `- [ ] N.0 [Category] Title — impact:N risk:N` is correct but worth noting: this is fragile to model output variation. If the model uses an em-dash (—) vs en-dash (–) vs hyphen-minus (-), or adds extra whitespace, the regex may fail silently. The regex currently uses `—` (em-dash), matching the prompt. This is acceptable for v1 — the prompt explicitly shows the format, and the model will follow it in the overwhelming majority of cases. If this becomes a problem, a more lenient parser or structured JSON output would be the fix.

**Fast-Path Artifacts (`_write_fast_path_artifacts`):**
For skip-planning runs, the system generates minimal PRD/task stubs. The task file is intentionally vague ("Implement the requested fix" / "Update or add the relevant tests"). This is fine — the implement agent gets the full context from the user prompt. The stubs exist to satisfy the pipeline's file expectations.

### Safety Assessment

- ✅ No secrets in committed code
- ✅ Secret file detection in preflight recovery (`_is_secret_like_path()`) prevents auto-committing `.env`, `.pem`, `.key`, SSH keys
- ✅ Recovery scope validation prevents the agent from touching files beyond the dirty worktree set
- ✅ Sweep analysis uses read-only tools only — no writes possible
- ✅ All user injection sanitized through `sanitize_untrusted_content()` before reaching the agent
- ✅ Review phase is never skippable regardless of complexity classification
- ✅ `PreflightError` now carries structured `code` and `details` for programmatic handling

### Minor Observations (Non-Blocking)

1. **[src/colonyos/router.py]**: The router module has grown significantly (~400 lines of new mode-selection code). The module docstring was updated but the two systems (legacy `RouterCategory` intent classification and new `ModeAgentMode` selection) coexist somewhat awkwardly. Not blocking, but a future consolidation pass would help clarity.

2. **[src/colonyos/orchestrator.py]**: `run_sweep()` catches `Exception` broadly when bootstrapping scan context (line ~1597). This is intentional (non-critical bootstrap), but a more specific exception type would be cleaner.

3. **[src/colonyos/instructions/sweep.md]**: The prompt instructs the model to output a markdown task file, but there's no explicit instruction about what to do if no significant issues are found. The model will likely produce an empty or near-empty task list, which is fine, but an explicit "if you find nothing significant, say so" instruction would make the zero-finding case cleaner.

4. **[src/colonyos/tui/adapter.py]**: The `_drain_injected()` method returns messages and clears the queue atomically (good), but there's no upper bound on queue size. A runaway user spamming injections during a long run could theoretically accumulate unbounded context. Not a realistic concern for v1.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/router.py]: Module now serves dual purpose (legacy RouterCategory + new ModeAgentMode) — consider consolidation in a future pass
- [src/colonyos/orchestrator.py]: Broad `except Exception` in sweep scan bootstrap (line ~1597) — acceptable for non-critical path but could be narrowed
- [src/colonyos/instructions/sweep.md]: No explicit instruction for the zero-findings case — model will handle it reasonably but an explicit clause would be cleaner
- [src/colonyos/sanitize.py]: Improved escape sequence coverage (CSI, OSC, DCS) and \r stripping — solid security improvement

SYNTHESIS:
This is a well-executed implementation that treats prompts with the rigor they deserve. The sweep instruction template is the strongest artifact — it gives the model a structured scoring framework, explicit exclusions, and a tightly constrained output format that feeds directly into the existing DAG parser. The heuristic-first routing pattern in the mode selector is the right design: deterministic where possible, stochastic only where needed. The TUI bridge architecture (janus queue, frozen dataclass messages, consistent sanitization) is clean and thread-safe. All 1,898 tests pass, no secrets in code, no placeholders or TODOs remain. The implementation ships three features (TUI, TUI UX improvements + smart routing, sweep analysis) coherently across 72 files with strong test coverage. The main risk I see is the regex-based sweep findings parser, which is brittle to model output variation — but acceptable for v1 given the prompt's explicit format specification. Ship it.
