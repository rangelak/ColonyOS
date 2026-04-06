# Review — Principal Systems Engineer (Google/Stripe caliber), Round 3

**Branch:** `colonyos/the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn`
**PRD:** `cOS_prds/20260406_102116_prd_the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn.md`
**Test suite:** 3,379 passed, 0 failed

---

## Checklist Assessment

### Completeness
- [x] **FR-1 (base.md):** New "Dependency Management" section added with manifest-first workflow, canonical install commands (uv/npm/cargo/go), system-level prohibition, exit code checking, lockfile commit requirement. All five sub-requirements covered.
- [x] **FR-2 (implement.md):** Negative "Do not add unnecessary dependencies" replaced with positive guidance including manifest + install + verify workflow.
- [x] **FR-3 (implement_parallel.md):** Dependency rule added to Rules section, scoped to `{task_id}`.
- [x] **FR-4 (fix-phase templates):** All six files updated — `fix.md`, `fix_standalone.md`, `ci_fix.md`, `verify_fix.md`, `thread_fix.md`, `thread_fix_pr_review.md`. Each replacement is contextually appropriate for the phase.
- [x] **FR-5 (auto_recovery.md):** Missing-dependency recovery action added with `ModuleNotFoundError` / `Cannot find module` as trigger conditions.
- [x] **FR-6 (review.md):** Checklist item expanded to check manifest declaration, lockfile commits, and no system-level packages. Also applied to `review_standalone.md` for consistency (good catch, not in PRD but correct).
- [x] **FR-7 (tests):** All 3,379 tests pass. No test content assertions broke.
- [x] All tasks in task file marked complete.
- [x] No placeholder or TODO code.

### Quality
- [x] All 3,379 tests pass.
- [x] No linter errors (per previous rounds).
- [x] Code follows existing project conventions — markdown instruction templates, same formatting style.
- [x] No new dependencies added (this change adds zero dependencies).
- [x] No unrelated changes included. The `review_standalone.md` update is the only file not explicitly in the PRD, but it's the correct parallel change to `review.md`.

### Safety
- [x] No secrets or credentials in committed code.
- [x] No destructive database operations.
- [x] Error handling: the base.md workflow explicitly requires checking install command exit codes before proceeding.

---

## Systems Engineering Assessment

### What I looked for

1. **Failure modes at 3am:** The primary failure this fixes — agent writes `import foo`, adds to `pyproject.toml`, skips `uv sync`, verify phase fails with `ModuleNotFoundError` — is well-addressed. The base.md section is structured as a numbered checklist (manifest → install → check → commit lockfile → scope), which is the format LLMs follow most reliably.

2. **Race conditions in parallel implement:** `implement_parallel.md` runs multiple agents in separate worktrees concurrently. Two agents could both add dependencies to the same manifest file, causing merge conflicts. The current change scopes each agent to "dependencies unrelated to task {task_id}" which is correct — the conflict resolution phase already handles manifest merge conflicts. No new race condition introduced.

3. **Blast radius:** Zero code changes. This is purely static instruction text. The worst case if the new wording is suboptimal is the same as today — the agent either installs or doesn't install, and the review phase catches unnecessary additions. The change is safe to ship and easy to iterate on.

4. **Debuggability:** Lockfile commit requirement (step 4 in base.md) means every dependency change is visible in `git diff`. The review phase checklist now explicitly checks for this. If an agent adds a bad dependency, the review artifacts will surface it.

5. **API surface / composability:** The base.md section acts as a shared subroutine inherited by all phases. Phase-specific templates override with contextual scoping ("unrelated to the feature" / "unrelated to the CI failure" / "unrelated to task {task_id}"). This is the correct layering — shared base + phase-specific overrides.

### Non-blocking observations (v2 follow-ups)

- **Lockfile freshness in verify.md:** The PRD's Open Question #2 is worth pursuing. The verify agent could check `uv lock --check` or `npm ls` to catch manifest/lockfile drift.
- **Worktree isolation for parallel installs:** When two parallel agents both run `uv sync` in separate worktrees, they share the same virtualenv (if using a shared `.venv`). This is an existing issue, not introduced by this change, but worth hardening.
- **Install command timeout:** Phase timeouts (1800s) apply, but a `npm install` with a bad registry URL could hang for minutes before failing. A per-command timeout hint in the instructions could help.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/base.md]: Clean 5-step dependency management workflow added. Manifest-first, exit code checking, lockfile commits, system-level prohibition all present. Correct architectural choice to put shared guidance here.
- [src/colonyos/instructions/implement.md]: Negative prohibition replaced with positive actionable guidance. Scoped correctly to feature.
- [src/colonyos/instructions/implement_parallel.md]: Dependency rule added, scoped to {task_id}. Correct for parallel execution context.
- [src/colonyos/instructions/fix.md, fix_standalone.md]: Consistent replacement. Both correctly reference "review findings" as scope.
- [src/colonyos/instructions/ci_fix.md]: Appropriately scoped to "CI failure" — includes the important case of running install when modules are missing.
- [src/colonyos/instructions/verify_fix.md]: Conservative wording ("Do not add new dependencies unless the fix genuinely requires one") appropriate for this late-pipeline phase.
- [src/colonyos/instructions/thread_fix.md, thread_fix_pr_review.md]: Consistent with other fix phases, scoped to "fix request".
- [src/colonyos/instructions/auto_recovery.md]: Good addition — names the specific error patterns (ModuleNotFoundError, Cannot find module) that should trigger install as recovery.
- [src/colonyos/instructions/review.md, review_standalone.md]: Expanded checklist item covers manifest declaration, lockfile commits, and system-level prohibition. Both review templates are now consistent (fix from iteration 1).

SYNTHESIS:
This is a textbook prompt engineering fix for an LLM over-inhibition bug. The architectural approach is sound: shared base instructions define the workflow, mutation phases grant positive permission scoped to their context, and the review phase is the enforcement layer. Zero code changes means zero runtime risk. The 14-file diff is minimal, consistent, and precisely targeted at the PRD requirements. All 3,379 tests pass. The change is safe to ship and will measurably reduce wasted fix iterations caused by dependency installation avoidance. Approve without reservations.
