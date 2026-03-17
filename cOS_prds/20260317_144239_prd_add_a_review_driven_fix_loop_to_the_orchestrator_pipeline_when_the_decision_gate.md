# PRD: Review-Driven Fix Loop for Orchestrator Pipeline

## Introduction/Overview

When the ColonyOS decision gate returns a **NO-GO** verdict, the pipeline currently fails immediately (`orchestrator.py` line 608-613). This feature adds a closed feedback loop: after a NO-GO, the orchestrator automatically re-enters an implementation phase (called "fix") with the review/decision findings injected as context, then re-runs a holistic review and decision gate. The cycle repeats until a **GO** verdict is received or iteration/budget limits are exhausted.

This transforms ColonyOS from a single-shot pipeline into a self-correcting one — dramatically increasing the probability that a run completes successfully without human intervention.

## Goals

1. **Increase pipeline success rate** — Automatically resolve review findings instead of failing on first NO-GO.
2. **Bound cost and risk** — Cap fix iterations via `max_fix_iterations` (default 2) and enforce per-run budget across fix cycles.
3. **Maintain observability** — Each fix iteration is tracked as a distinct `Phase.FIX` in the `RunLog`, with clear CLI feedback.
4. **Preserve backward compatibility** — Setting `max_fix_iterations: 0` restores current fail-fast behavior.

## User Stories

1. **As a developer running `colonyos run`**, I want the pipeline to automatically attempt to fix issues flagged by reviewers, so I don't have to manually re-run after a NO-GO verdict.
2. **As a team lead managing costs**, I want to cap how many fix iterations run and how much budget they consume, so autonomous runs don't spiral in cost.
3. **As a developer watching terminal output**, I want clear log messages indicating which fix iteration is running and whether the loop succeeded, so I can follow progress.
4. **As a CI/CD operator**, I want to disable the fix loop entirely (`max_fix_iterations: 0`), so NO-GO means immediate failure in automated environments.

## Functional Requirements

### FR-1: `Phase.FIX` Enum Value
Add a `FIX = "fix"` value to the `Phase` enum in `src/colonyos/models.py` (line 8). Fix iterations are tracked distinctly from initial implementation in the run log.

### FR-2: `max_fix_iterations` Config Field
Add `max_fix_iterations: int = 2` to `ColonyConfig` in `src/colonyos/config.py`. This field is parsed from `config.yaml` and controls how many fix cycles the pipeline attempts before giving up. Setting to `0` disables the fix loop (current fail-fast behavior).

### FR-3: Fix Instruction Template
Create `src/colonyos/instructions/fix.md` — a new instruction template that tells the fix agent to:
- Read the review artifacts in `{reviews_dir}`
- Read the decision artifact with its "Unresolved Issues" list
- Understand the specific findings that need to change
- Make targeted fixes on branch `{branch_name}` (same branch, incremental commits)
- Run tests to verify fixes don't introduce regressions
- Update the task file to reflect changes

### FR-4: `_build_fix_prompt()` Function
Create a `_build_fix_prompt()` function in `src/colonyos/orchestrator.py` that takes:
- `config: ColonyConfig`
- `prd_path: str`
- `task_path: str`
- `branch_name: str`
- `reviews_dir: str`
- `decision_text: str` (the full decision gate output, embedded inline)
- `fix_iteration: int`

The function builds a system prompt from `base.md` + `fix.md` and a user prompt that embeds the decision text (including the "Unresolved Issues" list) inline for immediate agent action. It also references the reviews directory for additional context.

### FR-5: Orchestrator Fix Loop
In the `run()` function of `orchestrator.py`, after a NO-GO verdict (currently line 608), enter a loop that:
1. Checks `max_fix_iterations > 0` and iteration count < max
2. Checks remaining per-run budget is sufficient
3. Logs `"=== Fix Iteration {i}/{max} ==="` to stderr
4. Runs the fix phase via `run_phase_sync(Phase.FIX, ...)`
5. Appends the `PhaseResult` to the `RunLog`
6. Re-runs only the **holistic review** (not per-task reviews) to save cost
7. Appends the review `PhaseResult` to the `RunLog`
8. Re-runs the **decision gate**
9. Appends the decision `PhaseResult` to the `RunLog`
10. On GO → break out of loop and proceed to deliver
11. On NO-GO → continue to next iteration (or fail if max reached)
12. On phase failure → fail the run

### FR-6: Budget Guard
Track aggregate cost across all fix iterations. Before each fix iteration, compute remaining budget as `config.budget.per_run - log.total_cost_so_far`. If remaining budget is less than `config.budget.per_phase` (the minimum needed for a fix + review + decision cycle), skip the iteration and fail gracefully with a clear budget-exhaustion message.

### FR-7: CLI Feedback
Log clear, structured messages for fix loop progress:
- `"=== Fix Iteration 1/2 ==="` at iteration start
- `"  Fix phase completed (cost=$X.XX)"` after fix
- `"  Re-running holistic review..."` before review
- `"  Decision: GO"` or `"  Decision: NO-GO"` after decision
- `"Fix loop exhausted after 2 iterations. Pipeline failed."` on max iterations
- `"Fix loop: budget exhausted. Pipeline failed."` on budget limit

### FR-8: Review Artifact Naming for Fix Iterations
Save fix-iteration review artifacts with iteration-tagged filenames (e.g., `review_final_fix1.md`, `decision_fix1.md`) so they don't overwrite the original review artifacts and provide an audit trail.

### FR-9: Tests
Add comprehensive unit tests covering:
- `_build_fix_prompt` output structure and content
- Fix loop with mocked phase runner: NO-GO → fix → GO path
- Max iteration cap: NO-GO → fix → NO-GO → fix → NO-GO → fail
- Budget exhaustion mid-loop
- `max_fix_iterations: 0` preserves fail-fast behavior
- Fix iterations appear as `Phase.FIX` in the run log
- UNKNOWN verdict does NOT trigger fix loop
- Existing tests continue to pass unmodified

## Non-Goals

- **Per-task re-review in fix iterations** — Only holistic review runs during fix cycles. Per-task review is too expensive for targeted fixes. Can be added later if needed.
- **Structured finding tracker** — No programmatic parsing of individual findings into a data model. The decision gate's "Unresolved Issues" markdown is passed as-is to the fix agent.
- **Separate `per_fix` budget field** — Fix iterations use the same `per_phase` budget. A separate field can be added later if users request cost differentiation.
- **UNKNOWN verdict handling** — UNKNOWN verdicts continue to proceed-with-warning (current behavior). Only explicit NO-GO triggers the fix loop.
- **Accumulated cross-iteration findings** — Each fix iteration gets a fresh holistic review. The fix prompt includes only the most recent decision output, not a cumulative history.
- **New branch per fix attempt** — Fixes are incremental commits on the same branch.

## Technical Considerations

### Codebase Integration Points
- **`src/colonyos/models.py`** — Add `FIX = "fix"` to `Phase` enum (line 8). Existing `PhaseResult` and `RunLog` structures are sufficient; no new dataclasses needed.
- **`src/colonyos/config.py`** — Add `max_fix_iterations: int = 2` to `ColonyConfig` (line 41). Parse from `config.yaml`. Update `save_config` to serialize it.
- **`src/colonyos/orchestrator.py`** — Major changes: new `_build_fix_prompt()` function, refactored `run()` to wrap lines 608-613 in a fix loop.
- **`src/colonyos/instructions/fix.md`** — New file, following the pattern of existing instruction templates (`implement.md`, `review.md`).
- **`tests/test_orchestrator.py`** — Existing test `test_decision_nogo_stops_pipeline` (line 424) must be updated to account for the fix loop (set `max_fix_iterations=0` to preserve its assertion, or update the mock side effects).

### Architecture Decision: Inline vs. File-Path for Fix Prompt

**Personas were split** on this question:
- **Inline camp** (Steve Jobs, Jony Ive, Karpathy): Embed the decision text directly in the fix prompt so the agent acts immediately without extra file-reading tool calls.
- **File-path camp** (Michael Seibel, Linus Torvalds, Security Engineer): Point to file paths to keep prompts lean and maintain trust boundaries.

**Decision**: **Hybrid approach**. Embed the decision gate output (which contains the "Unresolved Issues" list) inline in the fix prompt for immediate action, but also reference the `reviews_dir` path so the agent can read full review details if needed. The decision output is typically small (< 500 tokens) so inline embedding is acceptable without bloating the prompt.

### Architecture Decision: Budget Model

**Personas agreed** that fix iterations should be cost-bounded, but **disagreed on whether to add a separate `per_fix` field**:
- **Separate budget** (Steve Jobs, Jony Ive, Systems Engineer, Security, Karpathy): A fix should be cheaper than a full implement.
- **Same budget** (Michael Seibel, Linus Torvalds): Keep it simple, one field.

**Decision**: Use existing `per_phase` budget for fix iterations in v1. This avoids adding config complexity. The per-run budget (`budget.per_run`) naturally constrains total fix loop cost. A `per_fix` field can be added in a follow-up if users request it.

### Risk: Existing Test Breakage
The test `test_decision_nogo_stops_pipeline` asserts that NO-GO → `RunStatus.FAILED`. With the fix loop, NO-GO triggers fix iterations instead. This test must either:
- Set `max_fix_iterations=0` on its config fixture to preserve the assertion, OR
- Be updated to mock additional fix/review/decision phases.

The cleanest approach is to set `max_fix_iterations=0` so the test explicitly validates fail-fast behavior.

## Success Metrics

1. **Fix loop success rate** — Percentage of NO-GO verdicts that convert to GO after fix iterations. Target: >50% of NO-GO runs succeed within 2 fix iterations.
2. **Cost efficiency** — Average cost of a successful fix loop vs. cost of manual re-run. Fix loop should cost less than a full re-run.
3. **Zero regression** — All existing tests pass without modification (except the NO-GO test which needs `max_fix_iterations=0`).
4. **Iteration cap respected** — No run exceeds `max_fix_iterations` fix cycles.

## Open Questions

1. **Should fix-iteration review re-run persona subagents?** The holistic review currently uses persona subagents. For cost savings, fix-iteration reviews could skip persona subagents and run a single non-persona holistic review. This is a cost/quality tradeoff to evaluate after initial rollout.
2. **Should the fix prompt be more aggressive about scoping?** e.g., "Only modify files mentioned in the review findings." This could prevent the fix agent from making unnecessary changes but might also prevent it from fixing root causes in other files.
3. **Oscillation detection** — If fix iteration 1 produces findings A,B and fix iteration 2 produces findings A,B again, the loop is not converging. Should we detect this and bail early? Not in v1, but worth monitoring.
