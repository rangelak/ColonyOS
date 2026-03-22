# Review by Linus Torvalds (Round 2)

## Review: Intent Router Agent Implementation

I've reviewed the full diff on branch `colonyos/right_now_the_pipeline_always_runs_this_huge_planner_implementation_orchestratio` against the PRD. Compared to Round 1 where there was literally zero code, there's now substantial implementation. Let me tell you what's good, what's bad, and what will crash at runtime.

### What's Actually Working

The core data structures are correct and simple — I like that:

1. **`RouterCategory` enum** — Four values, string-based, no overengineering. Good.
2. **`RouterResult` frozen dataclass** — Immutable, five fields, no inheritance hierarchy. This is the right data structure and I can understand the code from it.
3. **`_parse_router_response()`** — Handles JSON, markdown-fenced JSON, malformed input. Falls back to CODE_CHANGE on every failure path. This is the correct defensive pattern.
4. **`_build_router_prompt()`** — Straightforward string assembly with sanitized user input. No template engine, no abstraction layers. Perfect.
5. **`RouterConfig`** — Simple dataclass with validation in the parser. Proper bounds checking on confidence_threshold and qa_budget.
6. **CLI integration in `run()`** — The `should_route` guard is clean: skips routing for `--no-triage`, `--from-prd`, `--issue`, or disabled config. The routing logic handles all four categories correctly.
7. **82 tests passing** — Good coverage of parsing edge cases, config validation, and API contracts.

The architecture is sound: cheap haiku call with zero tools for classification, then either answer with read-only tools or proceed to full pipeline. Two phases, clear privilege separation. Show me the data structures and I understand the flow.

### The Show-Stopping Bug

**`_log_router_decision` does not exist but is imported and called in `cli.py:613`.** This will crash with an `ImportError` the moment any user runs `colonyos run "anything"` with routing enabled. Lines 609-613:

```python
from colonyos.router import (
    RouterCategory,
    answer_question,
    route_query,
    _log_router_decision,  # DOES NOT EXIST
)
```

And then called at line 630:
```python
_log_router_decision(
    repo_root=repo_root,
    prompt=effective_prompt,
    result=router_result,
    source="cli",
)
```

This is FR-8 (audit logging) — the function was supposed to be implemented in Task 9.0 but never was. **The entire feature is broken at runtime because of a missing function import.** This isn't a "nice to have" — this is a hard crash on the primary code path.

### Missing Implementations

1. **No REPL integration (FR-4, Task 7.0)** — `_run_repl()` at line 427 still calls `run_orchestrator()` directly. Every REPL prompt goes straight to the full pipeline. The router only exists in `run()`, not in the REPL.

2. **No Slack refactoring (FR-2, Task 8.0)** — `slack.py` still has its own independent `triage_message()`. The whole point of FR-2 was to factor shared logic into the router module. Not done.

3. **No audit logging (FR-8, Task 9.0)** — `_log_router_decision()` doesn't exist. No logging to `.colonyos/runs/triage_<timestamp>.json`. And as noted above, this causes a runtime crash.

4. **All tasks still marked `[ ]`** — The task file shows every single checkbox unchecked despite Tasks 1-6 being largely implemented. This is sloppy bookkeeping.

### Code Quality Issues

1. **`_print_run_summary(log)` moved inside the else branch** — The diff moves `_print_run_summary` from outside the if/else to inside both branches. In the resume path (line 573), it's been added. In the non-resume path (line 688), it's kept. This is fine functionally but the original code had it once after both branches. Verify the resume path actually needs the summary printed here now.

2. **Importing a private function across module boundaries** — `_log_router_decision` (underscore prefix = private) is imported from router.py into cli.py. If this function existed, it should be public (`log_router_decision`). Private functions shouldn't be part of the module's external interface.

3. **Repeated project context extraction** — Lines 621-626 and 651-653 both pull `config.project.name`, `config.project.description`, `config.project.stack` with the same `if config.project else ""` pattern. Extract this once before the routing block.

### What I Actually Like

The `should_route` guard at line 598 is the right way to do this:

```python
should_route = (
    config.router.enabled
    and not no_triage
    and not from_prd
    and not issue_ref
    and prompt
)
```

Clear, readable, no clever tricks. Each condition has an obvious reason. If any of them are false, skip routing. This is how you write conditional logic.

The confidence threshold fallback is also correct — if the LLM isn't sure, fall through to the full pipeline rather than taking a wrong shortcut. Fail-open is the right default for a system that can always do more work but can't undo skipping work.

### Checklist

#### Completeness
- [x] FR-1: Intent Classification — Implemented in router.py
- [x] FR-3: Two-Stage Design — Router + Q&A agent both implemented
- [x] FR-5: Fallback Behavior — Confidence threshold check in cli.py
- [x] FR-6: `--no-triage` flag — Added to `run()` command
- [x] FR-7: Configuration — RouterConfig with all fields
- [ ] FR-2: Reuse Slack Infrastructure — Not done, slack.py unchanged
- [ ] FR-4: Entry Point Integration — CLI `run()` done, REPL NOT done, Slack NOT done
- [ ] FR-8: Audit Logging — Function doesn't exist, causes runtime crash

#### Quality
- [x] 82 tests pass
- [ ] No runtime errors — **FAILS: ImportError on `_log_router_decision`**
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies

#### Safety
- [x] No secrets in committed code
- [x] Input sanitization present
- [x] Read-only tool restriction for Q&A agent

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/cli.py:613]: `_log_router_decision` is imported from router.py but does not exist — this will crash with ImportError at runtime for every `colonyos run` invocation with routing enabled. This is a ship-blocking bug.
- [src/colonyos/router.py]: Missing `_log_router_decision()` function entirely — FR-8 (audit logging) not implemented. No logging to `.colonyos/runs/triage_<timestamp>.json`.
- [src/colonyos/cli.py:309-447]: REPL (`_run_repl()`) has no router integration — still calls `run_orchestrator()` directly. FR-4 requires routing in the REPL path.
- [src/colonyos/slack.py]: No refactoring to use shared router — `triage_message()` is completely independent. FR-2 not implemented.
- [src/colonyos/cli.py:621-626,651-653]: Repeated `config.project.name if config.project else ""` pattern — extract once before the routing block.
- [cOS_tasks/]: All 10 task groups marked `[ ]` despite tasks 1-6 being substantially implemented — update the task file to reflect reality.

SYNTHESIS:
Significant progress from Round 1 (zero code) to now — the core router module is well-designed with correct data structures, proper fail-open behavior, input sanitization, and clean prompt construction. The CLI integration in `run()` is well-structured with a readable guard clause. 82 tests pass. However, this implementation has a **hard runtime crash** because `_log_router_decision` is imported but never defined — every single user who runs `colonyos run` with routing enabled will hit an ImportError. Beyond that, two of the three required entry points (REPL and Slack) have no router integration, and the audit logging that FR-8 requires doesn't exist. Fix the ImportError first (either implement the function or remove the import/call), then wire up the REPL, then deal with Slack and audit logging. The foundation is solid but the feature cannot ship in its current state.
