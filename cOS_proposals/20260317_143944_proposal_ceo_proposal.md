## Proposal: Review-Driven Fix Loop

### Rationale
Today, when the decision gate returns NO-GO, the pipeline stops dead and the user must manually intervene — defeating the core promise of autonomous feature shipping. This is the biggest gap in the autonomous loop: the system can identify problems but cannot act on its own feedback. Adding an automated fix cycle that feeds review findings back to the implement phase would make ColonyOS genuinely self-correcting and dramatically increase the end-to-end success rate of autonomous runs.

### Feature Request
Add a review-driven fix loop to the orchestrator pipeline. When the decision gate returns a NO-GO verdict, instead of immediately failing, the system should automatically re-enter the implement phase with the review findings injected as context, then re-run review and decision. This creates a closed feedback loop: implement → review → decision → (if NO-GO) fix → review → decision → (if GO) deliver.

**Specific requirements:**

1. **Max fix iterations**: Add a `max_fix_iterations` config field (default: 2) that caps how many fix cycles the pipeline will attempt before giving up. This prevents infinite loops and runaway spend.

2. **Fix prompt construction**: Create a `_build_fix_prompt()` function in the orchestrator that takes the original PRD path, the branch name, and the review/decision artifacts as input. The system prompt should instruct the agent to read the review findings, understand what needs to change, and make targeted fixes on the existing branch — not rewrite from scratch.

3. **New `Phase.FIX` enum value**: Add a `FIX` phase to the Phase enum so fix iterations are tracked distinctly from initial implementation in the run log.

4. **Fix instruction template**: Create `src/colonyos/instructions/fix.md` — a new instruction template that tells the agent: read the review artifacts in `{reviews_dir}`, understand the findings, fix the code on branch `{branch_name}`, and update the task file to reflect changes.

5. **Orchestrator loop**: In `run()`, after a NO-GO verdict, enter a loop that: (a) runs the fix phase, (b) re-runs review, (c) re-runs decision gate. Each iteration appends its PhaseResults to the RunLog. Exit the loop on GO, on max iterations reached, or on any phase failure.

6. **Budget guard**: Each fix iteration consumes budget. The aggregate cost across all fix iterations must be tracked and the loop must stop if the remaining per-run budget would be exceeded.

7. **CLI feedback**: Log clear messages like `"=== Fix Iteration 1/2 ==="` so the user can follow progress in the terminal output.

8. **Tests**: Add unit tests for `_build_fix_prompt`, the fix loop logic (mock the phase runner), max iteration cap, and budget exhaustion during fix cycles.

**Acceptance criteria:**
- A NO-GO verdict triggers automatic fix iteration instead of pipeline failure
- Fix iterations are capped by `max_fix_iterations` (default 2)
- Each fix iteration appears as a `FIX` phase in the run log
- Budget is enforced across fix iterations
- Pipeline still fails gracefully if max iterations are exhausted without a GO verdict
- All existing tests continue to pass
- New tests cover the fix loop, prompt construction, iteration cap, and budget guard