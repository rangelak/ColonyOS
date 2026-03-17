# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

Now I have all the information needed for a comprehensive review. Here is my assessment:

---

## Review: Standalone `colonyos review <branch>` Command

### Completeness Assessment

All 30 functional requirements (FR-1 through FR-30) from the PRD are implemented. All tasks in the task file are marked complete. The three instruction templates, the extracted `run_review_loop()`, the CLI command, base branch detection, pre-flight validation, run ID generation, artifact naming, summary table, and exit codes are all present. 192 tests pass, including 25+ new tests covering the new functionality.

### Critical Findings

**BUG: Review loop wastes budget when `--fix` is disabled (lines 294-330, orchestrator.py)**

When `enable_fix=False` and reviewers request changes, the loop does NOT break. It continues for all `max_fix_iterations + 1` iterations (default: 4 rounds), re-running identical parallel reviews each time because no code is being fixed between rounds. This silently burns 4x the review budget for zero value.

The fix is straightforward — add an `else: break` after the `if enable_fix and iteration < config.max_fix_iterations:` block at line 294:

```python
        if enable_fix and iteration < config.max_fix_iterations:
            # ... fix logic ...
        else:
            break  # No fix to apply; re-reviewing won't change anything
```

**BUG: Reviewer verdict summary shows stale (round 1) verdicts instead of latest round (cli.py lines 381-388)**

The `review` CLI command iterates `log.phases` forward and takes the first N `Phase.REVIEW` results. When fix iterations run (e.g., round 1 → fix → round 2), the summary table displays round 1 verdicts (which requested changes) rather than round 2 verdicts (which may now approve). This gives the user misleading output.

Fix: iterate `log.phases` in reverse order, or filter for the highest round number.

**CODE SMELL: Import statement at line 372 of orchestrator.py is syntactically valid but structurally broken**

```python
    return verdict
from colonyos.ui import NullUI, PhaseUI
```

The `from colonyos.ui import NullUI, PhaseUI` module-level import was displaced by the insertion of ~355 lines of new code before it. It now sits at line 372, after the `run_review_loop()` function definition, rather than at the top of the file with the other imports. This works at runtime (Python processes all module-level statements before any function calls), but it's a maintenance hazard — any developer reading the file top-down will see `PhaseUI` referenced in `run_review_loop`'s type hint without an import in sight.

### Minor Findings

- **cli.py line 361**: `prd_rel = prd_path if prd_path else None` is redundant — `prd_path` is already `None` when not provided (Click default).
- **orchestrator.py line 298**: When `prd_rel` is provided but `task_rel` is None (standalone review with `--prd`), the code falls through to `_build_standalone_fix_prompt()`. This means PRD-provided standalone reviews get a standalone fix prompt that doesn't reference the PRD. This is a subtle behavioral inconsistency — the review phase uses the PRD but the fix phase ignores it.
- **CEO Proposal Panel (cli.py ~555-566)**: The Rich Panel formatting for CEO proposals is an unrelated cosmetic change bundled into this branch.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/orchestrator.py:294-330]: BUG — When `enable_fix=False`, the review loop runs `max_fix_iterations+1` identical review rounds, burning budget for zero value. Need `else: break` after the fix block.
- [src/colonyos/cli.py:381-388]: BUG — Reviewer verdict summary always shows round 1 verdicts, not the latest round. After fix iterations, the summary table is stale/misleading.
- [src/colonyos/orchestrator.py:372]: Import `from colonyos.ui import NullUI, PhaseUI` displaced from top of file to line 372 (between function definitions). Technically works but is a maintenance hazard.
- [src/colonyos/orchestrator.py:298]: When `prd_rel` is set but `task_rel` is None (standalone `--prd` mode), the fix prompt falls through to standalone variant, losing PRD context during fix iterations.
- [src/colonyos/cli.py:555-566]: Unrelated change — CEO Proposal output reformatted from plain text to Rich Panel. Should be a separate commit.

SYNTHESIS:
The implementation is structurally sound — the extraction of `run_review_loop()` is the right architectural move, the pre-flight checks are thorough, the test coverage is strong (192 passing tests), and the instruction templates are well-crafted. However, there are two bugs that matter at 3am: the budget-burning loop when `--fix` is disabled will silently cost users 4x what they expect (this is the kind of thing that gets a CI budget burned through in a day), and the stale verdict display will cause developers to debug phantom failures. The displaced import is a code quality issue that should be fixed while we're here. The PRD-context-loss in fix mode with `--prd` is a design gap that should at minimum be documented. Fix the budget loop bug and the verdict display, move the import, and this is ready to ship.