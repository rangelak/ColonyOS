# Review: Enable Dependency Installation in Pipeline Agents

**Reviewer:** Principal Systems Engineer (Google/Stripe caliber)
**Branch:** `colonyos/the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn`
**Tests:** 3,379 passed, 0 failed

## Checklist

| Category | Status |
|----------|--------|
| All 7 PRD functional requirements implemented | Pass |
| All tasks marked complete | Pass |
| No placeholder/TODO code | Pass |
| All tests pass (3,379) | Pass |
| No Python code changes (instruction-only) | Pass |
| No secrets in committed code | Pass |
| No new runtime dependencies | Pass |
| No unrelated changes | Pass |
| Error handling present | N/A (no code) |

## FR Coverage

| Requirement | File(s) Modified | Status |
|-------------|-----------------|--------|
| FR-1: base.md Dependency Management section | base.md (+20 lines) | Complete |
| FR-2: implement.md positive guidance | implement.md (line 52) | Complete |
| FR-3: implement_parallel.md guidance | implement_parallel.md (+1 line) | Complete |
| FR-4: Fix-phase templates (6 files) | fix.md, fix_standalone.md, ci_fix.md, verify_fix.md, thread_fix.md, thread_fix_pr_review.md | Complete |
| FR-5: auto_recovery.md install action | auto_recovery.md (+3 lines) | Complete |
| FR-6: review.md expanded checklist | review.md + review_standalone.md | Complete |
| FR-7: Tests updated | No test changes needed — 3,379 pass | Complete |

## Detailed Assessment

### What works well

1. **Correct diagnosis, minimal fix.** This is purely static instruction text — zero Python code changes, zero runtime risk. The blast radius of a bad deploy is exactly zero because this only affects future LLM agent behavior, not running infrastructure.

2. **Inheritance model is sound.** The 5-step workflow in `base.md` is inherited by all phases. Phase-specific overrides provide context-appropriate scoping (e.g., "Do not add dependencies unrelated to task {task_id}" in implement_parallel). This is the right layering.

3. **Enforcement at the right boundary.** Mutation phases are permissive ("you may install"). The review phase is the guardrail ("check manifest declaration, lockfile commits, no system-level packages"). This is the correct architecture — you want agents to act confidently during implementation and catch mistakes during review.

4. **Bonus: review_standalone.md consistency.** The PRD didn't call this out, but the implementation correctly updated the standalone review template to match, preventing a divergence bug where standalone reviews would use stale criteria.

### Operational concerns (non-blocking, v2)

1. **No observability on install compliance.** There's no structured signal when an agent installs a dependency. If we want to measure whether the fix actually reduced `ModuleNotFoundError` failures, we'd need to parse phase logs. Consider adding a structured event (e.g., `dependency_installed: {package, manifest, phase}`) to the phase result in a future iteration.

2. **Parallel worktree race conditions.** In `implement_parallel.md`, multiple agents in separate worktrees could simultaneously modify the same `pyproject.toml` and run `uv sync`. The merge step handles file conflicts, but lockfile conflicts are notoriously messy (binary-ish diffs). Worth monitoring in practice — may need a "reinstall after merge" step in the conflict resolution phase.

3. **Package name hallucination.** LLMs can hallucinate package names (e.g., `pip install python-dotenv` vs `pip install dotenv`). The manifest-first workflow mitigates this (the install will fail and the agent is told to stop), but a v2 improvement could verify the package exists in the registry before writing it to the manifest.

4. **No `verify.md` update.** Open Question #2 in the PRD asks whether `verify.md` should check lockfile freshness. It doesn't, and that's fine for v1, but it means an agent could update `pyproject.toml`, forget `uv sync`, and the verify phase wouldn't specifically catch the lockfile staleness (it would catch the `ModuleNotFoundError` though, so the failure mode is still detectable).

### What I'd watch at 3am

Nothing. This change has zero runtime impact. It modifies static text files that are loaded into LLM prompts. The worst case is an agent misinterprets the new guidance — which would be caught by the review phase or the verify phase's test suite. There are no race conditions, no database operations, no API surface changes, no authentication changes.
