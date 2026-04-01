# PRD: Fix Learn Phase — Tool Constraint Mismatch Causing 100% Failure Rate

## Introduction/Overview

The learn phase of the ColonyOS pipeline is failing on every single run. The root cause is a prompt-program mismatch: the `learn.md` instruction template tells the agent to "read all review artifacts recursively" but never communicates which tools are available. The orchestrator restricts the agent to `["Read", "Glob", "Grep"]` (line 3510 of `src/colonyos/orchestrator.py`), but the agent naturally reaches for `Bash` (to run `find`) and `Agent` (to spawn subagents for parallel reads) — neither of which are allowed. This causes the Claude CLI subprocess to exit with code 1, producing a "Fatal error in message reader" crash.

The learn phase is the pipeline's self-improvement mechanism — it extracts actionable patterns from review artifacts and persists them to `.colonyos/learnings.md` for injection into future implement/fix phases. With it broken, the pipeline loses its ability to learn from past reviews.

## Goals

1. **Eliminate the 100% failure rate** — the learn phase should complete successfully on every run
2. **Align instructions with tool constraints** — `learn.md` must explicitly state which tools are available and show how to use them
3. **Prevent regression** — add a test that catches prompt-tool constraint mismatches
4. **Zero disruption** — no changes to allowed_tools, budget, output format, or downstream consumers

## User Stories

1. **As a pipeline operator**, I want the learn phase to complete without crashing so that future runs benefit from accumulated review patterns.
2. **As a prompt engineer editing learn.md**, I want a test that fails if I accidentally reference tools not in the allowed list, so I don't silently break the phase.

## Functional Requirements

1. **FR-1**: Update `src/colonyos/instructions/learn.md` to include an explicit "Available Tools" section listing Read, Glob, and Grep as the only tools the agent can use.
2. **FR-2**: Replace the vague "Read all review artifacts recursively" instruction with concrete Glob patterns (e.g., `Glob` with pattern `{reviews_dir}/**/*.md`) and explicit Read steps.
3. **FR-3**: Add explicit negative constraint: "Do not attempt to use Bash, Write, Edit, Agent, or any other tool."
4. **FR-4**: Add a test in `tests/test_orchestrator.py` that asserts the learn phase system prompt contains tool-constraint language and that `allowed_tools` matches `["Read", "Glob", "Grep"]`.
5. **FR-5**: Verify the learn phase completes successfully by running the full test suite with no regressions.

## Non-Goals

- **Expanding allowed_tools** — the learn phase is read-only by design; adding Bash or Agent would be a privilege escalation (all 7 personas agreed)
- **Budget tuning** — the $0.50 cap at line 3502 is appropriate for read-only extraction; the crash was burning budget on tool-rejection retries, not on legitimate work
- **Graceful tool-rejection error handling in agent.py** — defense-in-depth improvement, but a separate concern from this bug fix
- **Changing the learnings output format** — `_parse_learn_output()` regex and `append_learnings()` remain unchanged
- **LLM-powered smart summaries** — already deferred in the project roadmap

## Technical Considerations

### Root Cause Analysis

The failure chain is:
1. `_run_learn_phase()` (orchestrator.py:3474) calls `run_phase_sync()` with `allowed_tools=["Read", "Glob", "Grep"]`
2. `run_phase_sync()` (agent.py) launches the Claude CLI subprocess with tool restrictions
3. The learn agent, following `learn.md` instructions that say "read all review artifacts recursively", tries `Bash(find cOS_reviews/ ...)` and `Agent(Read ALL review artifacts...)`
4. The Claude CLI rejects the disallowed tool calls and exits with code 1
5. `_run_learn_phase()` catches the error and logs it, but the phase produces no learnings

### Files to Modify

| File | Change |
|------|--------|
| `src/colonyos/instructions/learn.md` | Add tool constraints, explicit Glob patterns, negative constraints |
| `tests/test_orchestrator.py` | Add test for prompt-tool constraint alignment |

### Files NOT Modified

| File | Reason |
|------|--------|
| `src/colonyos/orchestrator.py` | `allowed_tools` and `_run_learn_phase()` logic are correct as-is |
| `src/colonyos/agent.py` | Tool enforcement works; the crash is expected behavior for disallowed tools |
| `src/colonyos/learnings.py` | Parsing, appending, deduplication logic is correct and well-tested |

### Existing Test Coverage

- `tests/test_learnings.py` — 21 tests covering parse, format, append, prune, load (all pass)
- `tests/test_orchestrator.py` — `TestLearnPhaseWiring` class with `test_learn_phase_uses_read_only_tools` (mocked, passes)
- Full suite: 2919 tests, 0 failures

### Persona Consensus

All 7 expert personas (YC Partner, Steve Jobs, Jony Ive, Principal Systems Engineer, Linus Torvalds, Staff Security Engineer, Andrej Karpathy) reached **unanimous agreement** on:
- Fix instructions only, do not expand allowed_tools
- Budget is fine as-is
- Explicit Glob patterns are essential
- A regression test is needed
- Risk is minimal since the phase is currently 100% broken

## Success Metrics

1. Learn phase succeeds on the next pipeline run (currently 0% success rate → target 95%+)
2. All existing 2919 tests continue to pass
3. New regression test catches future prompt-tool misalignment
4. Learnings entries appear in `.colonyos/learnings.md` after successful runs

## Open Questions

1. Should we use the `haiku` model for the learn phase to further reduce cost? (The README mentions this as an option in `phase_models` config, but it's a separate optimization.)
2. Should we add a generic "tool constraint" section to ALL phase instruction templates, not just learn.md? (Good idea but out of scope for this bug fix.)
