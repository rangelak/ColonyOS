# Staff Security Engineer — Round 3 Review

**Branch:** `colonyos/the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn`
**Tests:** 3,379 passed, 0 failed
**Files changed:** 14 (12 instruction templates + 2 artifacts)
**Python code files changed:** 0

## Checklist

### Completeness
- [x] All 7 PRD functional requirements implemented (FR-1 through FR-7)
- [x] All 28 tasks in task file marked complete
- [x] No placeholder or TODO code remains

### Quality
- [x] All 3,379 tests pass
- [x] No linter errors introduced (no Python code changed)
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies added (no dependencies changed at all)
- [x] No unrelated changes included (bonus `review_standalone.md` consistency fix is appropriate)

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive database operations
- [x] Error handling present (step 3 of base.md workflow: "If the install command fails, stop and diagnose")

## Security Analysis

### Attack Surface Assessment

**No new attack surface introduced.** This is a pure instruction-template change — zero Python code files modified. The agents already had unrestricted Bash access via `bypassPermissions`. These changes only structure *how* that existing capability is exercised through a manifest-first workflow.

### Controls Present in the Change

1. **System-level escalation prohibited** — `base.md` explicitly blocks `brew`, `apt`, `yum`, `pacman`, `apk`. This is the right call: system-level package managers have machine-wide blast radius and could install arbitrary binaries.

2. **Manifest-first workflow** — Dependencies must be declared in reviewable manifest files (`pyproject.toml`, `package.json`, etc.) before installation. This creates an audit trail in the git diff.

3. **Lockfile commit requirement** — Step 4 of the `base.md` workflow requires committing lockfiles alongside manifest changes. This ensures the exact resolved versions are captured and reviewable.

4. **Review-phase enforcement** — Both `review.md` and `review_standalone.md` now carry an expanded checklist: "No unnecessary dependencies added; any new dependencies are declared in manifest files with lockfile changes committed; no system-level packages installed." This is the correct enforcement point — mutation phases are permissive with clear scoping, review phases are the guardrail.

5. **Scope containment** — Each phase-specific instruction scopes dependency installation to the task/fix at hand ("Do not add dependencies unrelated to the feature/fix/CI failure").

### Residual Risks (Non-blocking, v2 follow-ups)

1. **Package name authenticity** — Nothing prevents an agent from installing a typosquatted package (e.g., `reqeusts` instead of `requests`). A v2 enhancement could cross-reference against known-good package registries or the project's existing transitive dependency graph.

2. **Parallel worktree race conditions** — `implement_parallel.md` now permits dependency installation in isolated worktrees. If two parallel tasks add conflicting dependencies, the merge step could produce an inconsistent lockfile. Existing conflict resolution should handle this, but it's worth monitoring.

3. **Lockfile compliance monitoring** — The instructions *tell* agents to commit lockfiles, but there's no programmatic verification that they actually did. A v2 enhancement could add a post-implement check that lockfiles are consistent with manifests.

4. **Recovery scope** — `auto_recovery.md` now allows `uv sync`/`npm install` as a recovery action for missing-dependency failures. This is appropriately scoped to `ModuleNotFoundError`/`Cannot find module` patterns, not a blanket "run install on any failure."

### What I Verified

- Zero Python code changes in the diff — confirmed via `git diff main...HEAD -- '*.py'` (empty output)
- No secrets, credentials, or tokens in any changed file
- No new runtime dependencies or code paths
- All 3,379 tests pass
- The `review_standalone.md` bonus fix maintains consistency with `review.md` — both carry identical expanded checklist language

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/base.md]: Clean 5-step dependency management workflow with system-level package prohibition. Well-structured, inheritable by all phases. No security concerns.
- [src/colonyos/instructions/implement.md]: Negative framing correctly replaced with positive, scoped guidance. No injection vectors.
- [src/colonyos/instructions/implement_parallel.md]: Dependency guidance scoped to task ID — correct containment.
- [src/colonyos/instructions/review.md]: Expanded checklist gives reviewers clear, unambiguous criteria for manifest declaration, lockfile commits, and system-level package prohibition.
- [src/colonyos/instructions/review_standalone.md]: Consistent with review.md — good consistency fix.
- [src/colonyos/instructions/auto_recovery.md]: Recovery install scoped to ModuleNotFoundError/Cannot find module — appropriately narrow, not a blanket permission.
- [src/colonyos/instructions/fix.md]: Replacement language is clear and correctly scoped.
- [src/colonyos/instructions/fix_standalone.md]: Consistent with fix.md.
- [src/colonyos/instructions/ci_fix.md]: CI-specific scoping ("Do not add dependencies unrelated to the CI failure") is correct.
- [src/colonyos/instructions/verify_fix.md]: Conservative language ("Do not add new dependencies unless the fix genuinely requires one") is appropriate for this late-stage phase.
- [src/colonyos/instructions/thread_fix.md]: Consistent replacement pattern.
- [src/colonyos/instructions/thread_fix_pr_review.md]: Consistent replacement pattern.

SYNTHESIS:
This change is security-positive. The previous negative framing ("Do not add unnecessary dependencies") was paradoxically *less* secure because it caused agents to skip the install step entirely, leading to pipeline failures that burned fix iterations — iterations where agents might make more invasive changes trying to work around missing imports. The new approach channels dependency installation through a structured, auditable workflow: manifest first, install, verify exit code, commit lockfiles. The review phase serves as the enforcement checkpoint with an expanded, explicit checklist. System-level package managers are explicitly prohibited. Zero Python code was changed, so there is zero runtime risk. The residual concerns (typosquatting, parallel worktree lockfile races, lockfile compliance verification) are appropriate v2 follow-ups, not blockers. I approve this change.
