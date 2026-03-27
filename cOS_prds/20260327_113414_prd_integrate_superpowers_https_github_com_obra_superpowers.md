# PRD: Integrate Superpowers Methodologies into ColonyOS

_Generated: 2026-03-27 | Source: [obra/superpowers](https://github.com/obra/superpowers)_

## 1. Introduction/Overview

This feature enriches ColonyOS's agent instruction templates with battle-tested development methodologies from the [superpowers](https://github.com/obra/superpowers) agentic skills framework. Rather than taking a runtime dependency on superpowers (which is a Claude Code plugin with an incompatible execution model), we will **adopt the best methodological content** — TDD enforcement, systematic debugging, verification-before-completion, and task decomposition guidance — directly into ColonyOS's existing instruction markdown files under `src/colonyos/instructions/`.

ColonyOS already has a robust autonomous pipeline (plan → implement → review → fix → deliver), but the instruction templates that drive each phase are procedural checklists that tell agents *what* to do without deep guidance on *how* to think through hard problems. Superpowers provides exactly this cognitive scaffolding. By distilling the highest-value techniques into ColonyOS's native instruction system, we improve agent output quality across the entire pipeline without new dependencies, architecture changes, or configuration complexity.

### Why Not a Runtime Dependency?

All 7 expert personas unanimously agreed: **do not take a dependency on superpowers**. Key reasons:

- **Incompatible execution models**: ColonyOS calls `claude_agent_sdk.query()` with a `system_prompt` string (see `agent.py`). Superpowers is a Claude Code CLI plugin with shell hooks and a `.claude/` directory convention. There is no bridge that isn't duct tape.
- **Instruction templates are core IP**: The quality of `implement.md`, `fix.md`, and `review.md` determines ColonyOS's output quality. Outsourcing this to an external project means losing control of the product's brain.
- **Supply chain risk**: ColonyOS agents run with `permission_mode="bypassPermissions"`. External prompt content that changes without review could silently alter agent behavior in safety-critical phases.
- **Context mismatch**: Superpowers prompts are tuned for interactive human-in-the-loop sessions. ColonyOS agents operate autonomously — instructions like "ask the user to clarify" are actively harmful.

## 2. Goals

1. **Stronger TDD enforcement**: Upgrade `implement.md` and `implement_parallel.md` from a one-line "write tests first" to a rigorous RED-GREEN-REFACTOR cycle with explicit behavioral invariants that agents cannot casually skip.
2. **Structured debugging methodology**: Add a systematic "reproduce → isolate → hypothesize → fix → verify" protocol to `fix.md` and `ci_fix.md`, reducing fix-loop iterations.
3. **Verification-before-completion rigor**: Add an explicit requirement-by-requirement PRD verification checklist to the implement phase, catching issues before they reach the review phase.
4. **Task decomposition guidance**: Enhance implementation instructions with guidance on breaking complex tasks into small, verifiable steps — inspired by superpowers' "2-5 minute task" philosophy.
5. **Zero new dependencies**: No new Python packages, no new config knobs, no architecture changes. Pure instruction quality improvement.

## 3. User Stories

1. **As a ColonyOS user**, I want the implement phase to produce code with better test coverage out of the box, so that fewer issues are caught in the review phase and fix loops are shorter.
2. **As a ColonyOS user**, I want the fix phase to systematically debug issues rather than guessing, so that fix iterations converge faster and don't introduce new regressions.
3. **As a ColonyOS user**, I want the implement phase to verify its own work against the PRD before declaring done, so that review feedback is about code quality rather than missing requirements.
4. **As a ColonyOS developer**, I want the instruction improvements to be self-contained markdown changes with no Python code modifications, so that they are easy to review, test, and iterate on.

## 4. Functional Requirements

### FR-1: TDD Behavioral Invariants in `implement.md`

Add a `## Behavioral Invariants` section to `implement.md` that includes:
- "You MUST write a failing test before writing any production code"
- Explicit RED-GREEN-REFACTOR cycle description
- Anti-pattern warnings (tests that pass immediately prove nothing)
- Guidance on test granularity (one behavior per test, descriptive names)
- When TDD applies (always for features/fixes) and exceptions (config files, generated code)

### FR-2: TDD Guidance in `implement_parallel.md`

Mirror the TDD invariants in the parallel implementation template, adapted for single-task context. Include self-review step before committing.

### FR-3: Systematic Debugging Protocol in `fix.md`

Add a `## Debugging Protocol` section to `fix.md` that replaces the current "locate → fix → test" checklist with:
1. **Reproduce**: Run the failing test or reproduce the exact error
2. **Isolate**: Narrow down to the smallest failing case
3. **Hypothesize**: Form an explicit hypothesis about the root cause before changing code
4. **Fix**: Make the minimal change that addresses the root cause
5. **Verify**: Confirm the original error is resolved AND no regressions introduced

### FR-4: Structured Debugging in `ci_fix.md`

Apply the same debugging protocol to `ci_fix.md`, adapted for CI-specific failures (build errors, linting, type checking).

### FR-5: Verification-Before-Completion in `implement.md`

Enhance "Step 5: Final Verification" to include:
- Requirement-by-requirement PRD verification (read each functional requirement, verify it is implemented)
- Full test suite run with zero failures required
- Explicit "red flags" check: no TODO/FIXME in new code, no commented-out code, no placeholder implementations
- A hard gate: "Do NOT declare implementation complete until every PRD requirement has been verified"

### FR-6: Task Decomposition Guidance

Add guidance to `implement.md` for breaking complex tasks into small, verifiable steps:
- Each step should be completable in one focused effort
- Each step should have a clear verification (test passes, output matches)
- Commit after each verified step, not after all steps

## 5. Non-Goals

- **No superpowers runtime dependency**: We are not installing superpowers as a plugin or package.
- **No new Python code**: This is purely instruction template improvements. No changes to `orchestrator.py`, `agent.py`, `config.py`, or any `.py` file.
- **No new configuration knobs**: The improvements are baked in as defaults, not gated behind config flags.
- **No brainstorming/planning skill adoption**: ColonyOS's `plan.md` with persona-based Q&A already covers this well.
- **No code review skill adoption**: ColonyOS's multi-persona review system is already more sophisticated than superpowers' single-reviewer approach.
- **No git worktree skill adoption**: ColonyOS's `worktree.py` and `parallel_orchestrator.py` already handle this natively.
- **No subagent-driven development architecture changes**: ColonyOS's parallel DAG-based implementation is already more advanced. We may adopt the "self-review before merge" insight as a future enhancement.

## 6. Technical Considerations

### Existing Architecture (No Changes Needed)

- **Instruction loading**: `_load_instruction(name)` in `orchestrator.py` (line 441) reads `.md` files from `src/colonyos/instructions/`
- **Prompt assembly**: `_format_base(config)` + phase template with `.format()` variable substitution
- **System prompt flow**: Assembled string → `ClaudeAgentOptions.system_prompt` → `claude_agent_sdk.query()`
- **Template variables**: `{prd_path}`, `{task_path}`, `{branch_name}`, `{reviews_dir}`, etc.

### Context Window Budget

Superpowers skills are verbose (1000-3000 tokens each). Key mitigation strategies:
- **Compact invariants**: Distill each methodology into 200-400 tokens of high-signal behavioral rules, not full methodology guides
- **Integrated, not appended**: Weave guidance into existing sections rather than adding large new blocks
- **Phase-appropriate**: Each instruction file only gets guidance relevant to that phase (principle of least privilege for prompt context)

### Files Modified

| File | Change |
|------|--------|
| `src/colonyos/instructions/implement.md` | Add TDD invariants, verification-before-completion, task decomposition guidance |
| `src/colonyos/instructions/implement_parallel.md` | Add TDD invariants, self-review step |
| `src/colonyos/instructions/fix.md` | Add systematic debugging protocol |
| `src/colonyos/instructions/ci_fix.md` | Add structured debugging for CI failures |

### Attribution

All adopted methodologies should include a comment in the PR description crediting superpowers (MIT licensed) as the source of inspiration. No verbatim copying — all content is rewritten for ColonyOS's autonomous agent context.

## 7. Success Metrics

1. **Reduced fix iterations**: Average fix-loop count per run decreases (measurable via `RunLog` data in `.colonyos/runs/`)
2. **Higher first-pass review approval**: More review phases return `approve` on the first round
3. **Better test coverage**: Implement phase produces more comprehensive tests (measurable by review personas noting fewer "missing test" findings)
4. **No token budget regression**: System prompt sizes stay within acceptable bounds (< 15% increase per phase)

## 8. Open Questions

1. **Measurement baseline**: Should we capture before/after metrics from real runs to quantify improvement? (Recommended: yes, run 5-10 identical feature requests before and after)
2. **Iteration**: After shipping the initial instruction improvements, should we consider adding superpowers' "per-task self-review" as a follow-up enhancement to `implement_parallel.md`?
3. **Upstream tracking**: Should we document the specific superpowers commit hash we studied, for future reference when re-syncing methodology improvements?

## 9. Persona Synthesis

### Areas of Strong Agreement (7/7 personas)

- Adopt methodologies, do not take a runtime dependency
- Vendor/adapt content into existing instruction templates
- TDD enforcement is the highest-value improvement
- Brainstorming, git worktrees, and code review skills are redundant with existing ColonyOS capabilities

### Areas of Moderate Agreement (5-6/7)

- Systematic debugging is high value (6/7)
- Verification-before-completion is high value (5/7)
- Improvements should be automatic/baked-in, not configurable (6/7 — Security engineer preferred opt-in with default off)

### Key Tension

- **Security engineer** wanted new capabilities gated behind config with default OFF, citing bypass-permissions risk. All other personas argued that if a methodology is good enough to adopt, it should be the default. **Resolution**: Since we are only improving the quality of existing instruction content (not adding new capabilities or execution paths), the security concern is addressed — there is no new attack surface, just better guidance within the existing trust boundary.

### Notable Insight (Karpathy)

Suggested "tiered injection" — compact invariants in the system prompt with detailed methodology available as a file the agent can `Read` on-demand. This is a good future optimization if context window budget becomes tight, but for the initial ship the improvements should be compact enough (200-400 tokens per file) to inline directly.
