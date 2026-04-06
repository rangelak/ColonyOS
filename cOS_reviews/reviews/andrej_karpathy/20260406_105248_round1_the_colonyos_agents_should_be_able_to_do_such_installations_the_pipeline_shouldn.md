# Andrej Karpathy — Review Round 1

## Branch: `colonyos/the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn`

## PRD: Enable Dependency Installation in Pipeline Agents

### Test Results
- **3379 tests pass** — zero failures, zero regressions

---

### Checklist Assessment

#### Completeness
- [x] FR-1: `base.md` — New "Dependency Management" section added with all five required elements (manifest-first, canonical commands, system-level prohibition, exit code checking, lockfile commits)
- [x] FR-2: `implement.md` — Line 52 replaced with positive guidance including "Verify the import works before proceeding"
- [x] FR-3: `implement_parallel.md` — Dependency rule appended to Rules section, scoped to `{task_id}`
- [x] FR-4: All six fix-phase templates updated (`fix.md`, `fix_standalone.md`, `ci_fix.md`, `verify_fix.md`, `thread_fix.md`, `thread_fix_pr_review.md`)
- [x] FR-5: `auto_recovery.md` — Missing dependency recovery action added with concrete error examples
- [x] FR-6: `review.md` — Checklist item expanded to cover manifest declarations, lockfile commits, and system-level prohibition
- [x] FR-7: Tests — 3379 pass, no test content assertions needed updating (verified by task 1.1)
- [x] All 28 subtasks marked complete
- [x] No placeholder or TODO code

#### Quality
- [x] All 3379 tests pass
- [x] No linter errors (verified in task 5.2)
- [x] Code follows existing project conventions — markdown formatting, bullet style, and tone match surrounding content
- [x] No new dependencies added (this is a pure instruction text change)
- [x] No unrelated changes included — diff is exactly the 11 instruction files + PRD + task file

#### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive operations
- [x] Error handling: the base.md section explicitly requires checking exit codes and stopping on failure

---

### Findings

- **[src/colonyos/instructions/review_standalone.md]**: Still contains the old `"No unnecessary dependencies added"` without the expanded checklist language from FR-6. The PRD only specifies `review.md`, not `review_standalone.md`, so this is technically in-spec — but it creates an inconsistency. The standalone review path now applies a weaker dependency check than the full pipeline review. **Severity: low** — worth a fast-follow to align, not a blocker.

- **[src/colonyos/instructions/base.md]**: The Dependency Management section is well-structured as a numbered workflow (manifest → install → check → commit → scope). This is excellent prompt engineering — sequential numbered steps are far more reliably followed by LLMs than paragraph prose. The `**Prohibited**` callout with specific command names (`brew`, `apt`, `yum`, `pacman`, `apk`) is the right approach: explicit enumeration beats "system-level" abstraction for LLM compliance.

- **[src/colonyos/instructions/implement.md]**: The replacement text includes "Verify the import works before proceeding" — this is a good addition beyond the minimum PRD spec. It creates a self-check loop that catches failed installations before the agent moves on, reducing wasted downstream compute.

- **[src/colonyos/instructions/ci_fix.md]**: Notably, this template's replacement text has a slightly different structure from the other fix templates — it mentions "run the project's install command" before "add it to the manifest file first", which is the correct ordering for CI fixes where deps may already be in manifest but not installed. Good contextual differentiation.

- **[src/colonyos/instructions/auto_recovery.md]**: The recovery guidance includes concrete error signatures (`ModuleNotFoundError`, `Cannot find module`). This is important — LLM agents pattern-match on examples far more reliably than on abstract descriptions. Two examples is the sweet spot for few-shot in instructions.

- **[Consistency check]**: All phase-specific templates use language that's compatible with (not contradicting) the base instructions. The base says "You have full permission to install project-level dependencies when a feature or fix genuinely requires them" — each phase template then provides context-specific guidance on when that permission applies. No conflicts detected.

---

### Prompt Engineering Assessment

This change treats prompts as programs — the right mental model. Key observations:

1. **Positive > Negative framing**: Replacing "Do not add unnecessary dependencies" (vague, causes over-inhibition) with "When a feature requires a new dependency, add it to the manifest file and run the install command" (specific, actionable) is exactly the right fix. LLMs interpret prohibitions more broadly than intended; explicit permission with scope boundaries is more reliable.

2. **Structured workflow in base.md**: The 5-step numbered sequence gives the agent a deterministic procedure to follow. This is vastly more reliable than "use good judgment about dependencies." The manifest-first ordering prevents bare `pip install` drift.

3. **Scope anchoring per phase**: Each phase template anchors the dependency scope to the phase's purpose — "unrelated to the feature" (implement), "unrelated to the review findings" (fix), "unrelated to the CI failure" (ci_fix), "unrelated to task {task_id}" (parallel). This prevents cross-contamination without over-restricting.

4. **The review phase as guardrail**: Moving enforcement from every mutation phase (where it causes false negatives) to the review phase (where it's properly evaluated) is architecturally sound. You want the generative phases to be permissive and the evaluative phases to be strict.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/review_standalone.md]: Not updated with expanded dependency checklist — technically out of PRD scope but creates inconsistency with `review.md`. Low-priority fast-follow.
- [src/colonyos/instructions/base.md]: Dependency Management section is well-structured as numbered workflow — strong prompt engineering pattern for LLM compliance.
- [src/colonyos/instructions/implement.md]: "Verify the import works" addition creates useful self-check loop beyond minimum PRD spec.
- [src/colonyos/instructions/auto_recovery.md]: Concrete error signatures (ModuleNotFoundError, Cannot find module) leverage few-shot pattern matching effectively.

SYNTHESIS:
This is a clean, well-scoped prompt engineering change that fixes a real failure mode. The root cause analysis is correct: LLMs over-interpret prohibitions, and "Do not add unnecessary dependencies" was being parsed as "never install anything." The fix applies the right pattern — replace vague negative guidance with explicit positive procedures, anchor scope to each phase's purpose, and move enforcement to the review phase where cost-benefit analysis actually happens. The base.md workflow (manifest → install → check exit code → commit lockfile) gives agents a deterministic procedure instead of relying on judgment. All 3379 tests pass, no orchestrator code was touched (respecting the PRD's non-goals), and the diff is minimal — 11 instruction files changed with exactly the content the PRD specified. The one gap (`review_standalone.md` not updated) is out of PRD scope and low-severity. Ship it.
