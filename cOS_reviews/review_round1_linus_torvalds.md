# Review by Linus Torvalds (Round 1)

Good — `prune_ledger` takes `content` string (not `repo_root` as the PRD says), which is actually a better design since it's a pure function called inside `append_learnings`. The PRD's signature was a suggestion, and this is a valid deviation that's cleaner.

Now I have everything I need for the review.

---

## Review: Cross-Run Learnings System

I've reviewed the full diff (41 files, ~3800 lines added) against the PRD. Let me be direct.

### Completeness Assessment

All 15 functional requirements from the PRD are implemented:

- **FR-1** ✅ `LEARN = "learn"` added to `Phase` enum
- **FR-2** ✅ `learnings.py` with all five required functions
- **FR-3** ✅ `learn.md` instruction template with categories, dedup instructions, format
- **FR-4** ✅ Ledger format matches spec exactly
- **FR-5** ✅ Cap enforcement via `prune_ledger()` with FIFO eviction
- **FR-6** ✅ Normalized text dedup (lowercase, whitespace-collapsed)
- **FR-7** ✅ `_build_implement_prompt()` injects learnings
- **FR-8** ✅ `_build_fix_prompt()` injects learnings
- **FR-9** ✅ `LearningsConfig` dataclass, parsed/serialized, in DEFAULTS
- **FR-10** ✅ Learn phase wired after decision, before deliver; runs on NO-GO
- **FR-11** ✅ Read-only tools `["Read", "Glob", "Grep"]`, budget `min(0.50, per_phase/2)`
- **FR-12** ✅ Exception handling wraps entire learn block, logs warning, never raises
- **FR-13** ✅ `if not config.learnings.enabled: return` guard
- **FR-14** ✅ Status command shows learnings count
- **FR-15** ✅ DEFAULTS dict updated

All 7 task groups and their subtasks are marked complete.

### Quality

- **353 tests pass**, zero failures
- No linter errors observed
- No TODOs, FIXMEs, or placeholder code
- Code follows existing project conventions (dataclasses, `run_phase_sync` pattern, instruction templates)
- No unnecessary dependencies added

### Findings

VERDICT: approve

FINDINGS:
- [src/colonyos/learnings.py]: `prune_ledger` takes `(content, max_entries)` instead of PRD's `(repo_root, max_entries)` — this is actually better design (pure function), called internally by `append_learnings`. Approved deviation.
- [src/colonyos/learnings.py]: `parse_learnings` return type is `list[tuple[str, str, str, list[LearningEntry]]]` — the PRD said `list[LearningEntry]`. The tuple return is correct since sections contain metadata (run_id, date, feature). A named dataclass instead of a 4-tuple would be marginally more readable, but this is fine for internal use.
- [src/colonyos/orchestrator.py]: `_run_learn_phase` defines `learn_budget` twice (once inside the UI block, once outside). The first assignment is dead code when `learn_ui` is None. Minor, harmless.
- [src/colonyos/orchestrator.py]: Standalone review (`run_standalone_review`) was added in a prior commit on this branch but is not part of this PRD's scope. It's a significant chunk of the diff (~250 lines). Not a problem per se, but it means this branch carries scope from multiple features.
- [src/colonyos/cli.py]: The `status` command previously had an early `return` when no runs/loops were found; this was changed to fall through so the learnings count always shows. Correct behavior change.
- [tests/test_orchestrator.py]: Two test names appear to have had spaces removed (`test_review_skipped_when_noreviewer_personas`, `test_multiplereviewer_personas`) — these are cosmetic renames that happened in a prior commit. Harmless but untidy.
- [src/colonyos/orchestrator.py]: The `_build_standalone_fix_prompt` does NOT inject learnings (no `repo_root` param), matching the PRD's non-goal that standalone review doesn't extract learnings. Consistent.

SYNTHESIS:
This is clean, straightforward work. The learnings module (`learnings.py`) is 198 lines of pure functions with no magic — regex-based parsing, text normalization for dedup, FIFO pruning. The data structures are right: a flat list of entries organized by run sections, stored as human-readable markdown. The learn phase is properly isolated — read-only tools, conservative budget, exception-swallowing wrapper that logs and moves on. The injection into implement/fix prompts is a minimal, non-invasive change (append to system prompt). The test coverage is comprehensive: 21 unit tests for `learnings.py`, config roundtrip tests, orchestrator integration tests covering the happy path, NO-GO path, disabled config, exception handling, and budget enforcement. The one thing I'd nitpick is the 4-tuple return from `parse_learnings` — a `RunSection` dataclass would make the code more self-documenting — but that's a style preference, not a defect. The branch carries some unrelated changes from prior features (standalone review), which muddies the diff, but the learnings-specific changes are focused and correct. Ship it.