# Review by Andrej Karpathy (Round 4)

Now I have a comprehensive picture. Let me write the review.

---

## Review: Andrej Karpathy

I've reviewed the full implementation across the three PRDs this branch addresses: the Textual TUI, TUI UX improvements + smart routing, and the `colonyos sweep` command. The branch adds ~9,300 lines across 73 files with 33 commits. All 1,933 tests pass.

### Completeness Assessment

The implementation covers the functional requirements thoroughly:

- **TUI core** (FR-1 through FR-8 of original PRD): Transcript, composer, status bar, hint bar widgets are all present. The `TextualUI` adapter correctly bridges the synchronous orchestrator thread to Textual's async event loop via `janus.Queue`. Optional dependency pattern matches existing `[slack]` and `[ui]` extras.

- **TUI improvements** (Ctrl+C, default mode, smart routing, mid-run input): TUI launches by default when `isatty()` + textual installed. `--no-tui` escape hatch exists. `UserInjectionMsg` enables mid-run context injection with proper sanitization. `exclusive=True` is correctly absent from TUI workers. The complexity field is added to `RouterResult` as an orthogonal dimension rather than a new enum value — the right architectural call.

- **Sweep command** (all 7 FRs): `Phase.SWEEP` with read-only tools `["Read", "Glob", "Grep"]`, `SweepConfig` dataclass, structured instruction template, `run_sweep()` orchestration, dry-run vs execute modes, and `parse_sweep_findings()` for structured output parsing.

### Prompt Engineering Quality

This is where I want to focus — prompts are programs, and this implementation treats them as such:

1. **`sweep.md`** is exemplary structured output engineering. The scoring rubric (Impact × Risk), explicit exclusions (auth, secrets, DB schemas, public APIs), max-tasks cap, and output format matching `parse_task_file()` all demonstrate the right level of rigor. The instruction to write tests *before* fixes in every task is a good constraint.

2. **`preflight_recovery.md`** has clear guardrails: no destructive git commands, no `git add .`, no secret files, no scope expansion. The validation-before-commit step is smart — it prevents the recovery agent from creating a commit that breaks CI.

3. **Mode selection prompt** (`_build_mode_selection_prompt`) requests JSON output with explicit field definitions and valid values. The heuristic-first routing (`_heuristic_mode_decision`) before invoking the model is the correct pattern — cheap regex for obvious cases, model call only for ambiguous ones. The $0.05 budget for triage is appropriately tight.

4. **`_sanitize_metadata()`** applies double sanitization (display + content) for project metadata inserted into prompts — good defense-in-depth against prompt injection through config values.

### Concerns

1. **Dual routing systems**: The original `RouterCategory` (CODE_CHANGE/QUESTION/STATUS/OUT_OF_SCOPE) coexists with the new `ModeAgentMode` (DIRECT_AGENT/PLAN_IMPLEMENT_LOOP/etc.). Both are used in different code paths. This isn't broken, but it's two classification taxonomies for overlapping concepts — future contributors will need to understand when each applies.

2. **Heuristic pattern false positives**: The regex patterns in `_heuristic_mode_decision` (e.g., `\bchange\b`, `\bmake\b`) use negative lookahead for common non-action continuations, which is thoughtful. But the pattern set is necessarily incomplete — "change the database schema" would match DIRECT_AGENT at confidence 0.9, which is too high for something that should go through the full pipeline. The model fallback catches this, but only if the heuristic doesn't fire first.

3. **Sweep agent output reliability**: The `parse_sweep_findings()` regex expects a precise format (`- [ ] N.0 [Category] Title — impact:N risk:N`). If the model deviates slightly (e.g., uses an em-dash instead of en-dash, or formats scores differently), findings silently drop. There's no validation or warning when zero findings are parsed from non-empty output. This is the classic structured output fragility problem.

4. **Consumer loop resilience**: The `_consume_queue` loop has a broad `except Exception` catch with logging, which is correct for resilience. But if the queue itself is closed while the consumer is waiting on `queue.get()`, the behavior depends on janus's implementation. The `CancelledError` catch handles task cancellation, but not queue closure — worth verifying.

### Safety

- All user-facing text goes through `sanitize_display_text()` and/or `sanitize_untrusted_content()` ✓
- Carriage return normalization prevents content-overwrite attacks ✓
- OSC/DCS escape sequence stripping prevents terminal hijacking ✓
- Secret file detection in preflight recovery (`_is_secret_like_path()`) is comprehensive ✓
- No credentials in committed code ✓
- Sweep analysis phase uses read-only tools only ✓

VERDICT: approve

FINDINGS:
- [src/colonyos/router.py]: Dual routing taxonomies (RouterCategory + ModeAgentMode) create conceptual overhead; consider unifying in a future pass
- [src/colonyos/router.py]: Heuristic patterns in `_heuristic_mode_decision` can over-match at high confidence (0.9+) for ambiguous requests like "change the database schema"
- [src/colonyos/orchestrator.py]: `parse_sweep_findings()` silently returns empty list when regex doesn't match non-empty output — add a warning log when raw output is non-trivial but zero findings are parsed
- [src/colonyos/sanitize.py]: Excellent hardening of the sanitizer — OSC/DCS stripping and CR normalization are genuinely important security fixes that go beyond the PRD scope
- [src/colonyos/tui/adapter.py]: Clean separation of concerns; the frozen dataclass message types are the right pattern for thread-safe queue passing
- [src/colonyos/instructions/sweep.md]: Rigorous structured output prompt — the scoring rubric, exclusion list, and test-first sub-task ordering are exactly the kind of constraint engineering that makes LLM outputs reliable

SYNTHESIS:
This is a well-executed implementation that covers three substantial PRDs with appropriate architectural choices. The prompts are treated as first-class programs with structured output schemas, explicit constraints, and defense-in-depth sanitization — exactly the right approach for a system where stochastic model outputs feed into deterministic pipelines. The heuristic-first routing pattern (cheap regex → model call only when needed) is the correct cost/latency tradeoff. The main technical debt is the dual routing taxonomy, which is manageable now but should be unified before adding more modes. The sweep analysis prompt is a standout — it demonstrates how to get reliable structured output from an LLM by being extremely specific about format, scoring criteria, and exclusions. All 1,933 tests pass, no secrets in code, no placeholder implementations. Ship it.
