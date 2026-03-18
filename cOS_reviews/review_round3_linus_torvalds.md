# Review by Linus Torvalds (Round 3)

Now I have a complete picture. Let me write the review.

---

Alright. I've read the PRD, reviewed every line of the diff across 33 files, checked the task list, and run the full test suite. Here's my assessment.

## The Good

The core feature — `phase_models`, `VALID_MODELS`, `get_model()`, fail-fast validation, config round-trip, orchestrator rewiring — is **cleanly implemented**. The data structures are right: a simple dict for `phase_models`, a one-liner `get_model()` that does exactly what it should, validation at load time not at runtime. This is the correct approach. No over-engineering, no unnecessary abstraction layers.

The test coverage is thorough: 341 tests just for the modified files, 537 total, all passing. The validation tests cover invalid models, invalid phase keys, the safety-critical phase warnings, backward compat with missing fields — all the edge cases that matter.

The `_SAFETY_CRITICAL_PHASES` warning for haiku on review/decision/fix is a nice touch that the PRD didn't explicitly require but the Security Engineer recommended.

## The Problems

### 1. Unrelated Changes Stuffed Into This Branch

This is the biggest problem. This branch contains **three separate features** stacked together:

- **GitHub issue integration** (`github.py`, `--issue` flag, `source_issue` fields, CEO open-issues context) — commits `17bee4f` through `1fa42e6`
- **Stats CLI** (`stats.py`, `colonyos stats` command) — commits `961aada` through `2ca0995`
- **Per-phase model overrides** — commits `b729b80` through `0f2935b`

The PRD for this review is specifically about per-phase model overrides. The GitHub issue integration is **completely unrelated** and has no business being in this diff. The stats work partially overlaps (FR-16 through FR-19 require model usage in stats), but the *entire* stats module (576 lines) was built in a prior commit and goes far beyond what this PRD requested.

This makes the diff 3,923 lines instead of what should be ~400-500 lines. That's a 7x inflation that makes review harder and violates the principle of atomic, reviewable changes.

### 2. Cost-Optimized Preset Deviates From PRD

The PRD's FR-13 specifies: *"Cost-optimized (opus for implement, sonnet for plan/review/fix, haiku for decision/learn/deliver)"*

The actual implementation:
```python
"Cost-optimized": {
    "model": "sonnet",
    "phase_models": {
        "implement": "opus",
        "learn": "haiku",
        "deliver": "haiku",
    },
}
```

This keeps `decision` at `sonnet` (via the global default), not `haiku` as the PRD specifies. This is arguably a *better* choice given the security concerns about decision being a safety gate, but it's an undocumented deviation from the spec. The CEO phase also gets `sonnet` where the PRD doesn't specify it. If this was intentional, it should be called out.

### 3. `load_run_logs` Has Dead Code

```python
for f in runs_dir.glob("run-*.json"):
    if f.name.startswith("loop_state_"):
        continue
```

A file matching `run-*.json` will never start with `loop_state_`. This is dead code.

### 4. Import Inside Function Body (Duration Stats)

In `compute_duration_stats()`, `from datetime import datetime, timezone` is imported inside the loop body. This import should be at module level. Importing inside a function is acceptable when avoiding circular imports or heavy optional dependencies — neither applies to `datetime`.

---

## Review Output

VERDICT: request-changes

FINDINGS:
- [branch-level]: Branch contains 3 stacked features (GitHub issue integration, stats CLI, per-phase model overrides). Only the last feature matches this PRD. The unrelated changes should be on separate branches or the base branch should be the prior feature's branch, not main.
- [src/colonyos/init.py]: Cost-optimized preset keeps `decision` at `sonnet` instead of `haiku` as specified in PRD FR-13. If intentional (safety concern), document the deviation; if accidental, fix it.
- [src/colonyos/stats.py line ~1155]: Dead code — `loop_state_*` filename check inside a `run-*.json` glob can never match.
- [src/colonyos/stats.py line ~1325]: `from datetime import datetime, timezone` imported inside function body; should be at module level.
- [src/colonyos/ui.py]: Changes to tool styles and `_AGENT_TOOLS` set are unrelated to per-phase model overrides.

SYNTHESIS:
The per-phase model override feature itself is well-implemented — correct data structures, clean validation, thorough tests, proper backward compatibility. The `get_model()` method is a single line that does exactly what it should, the validation catches errors at config load time as the PRD mandates, and the orchestrator rewiring is mechanical and complete. However, this branch is carrying the weight of two prior, unrelated features that inflate the diff from ~500 to ~4000 lines. The right fix is to rebase this so the per-phase model work stands alone (or at minimum, clearly document that this is a stacked branch). The preset deviation from the PRD and the minor code quality issues (dead code, misplaced import) should be cleaned up. None of these are blocking bugs — the code is functionally correct and all 537 tests pass — but shipping a 4000-line diff that's 85% unrelated changes is how technical debt accumulates.