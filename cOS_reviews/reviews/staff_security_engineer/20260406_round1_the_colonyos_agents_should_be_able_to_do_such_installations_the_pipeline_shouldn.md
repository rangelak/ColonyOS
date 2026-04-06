# Staff Security Engineer — Review Round 1

## Branch
`colonyos/the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn`

## PRD
`cOS_prds/20260406_102116_prd_the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn.md`

## Test Results
3,379 tests pass. No regressions.

---

## Checklist Assessment

### Completeness
- [x] FR-1: `base.md` — Dependency Management section added with manifest-first workflow, canonical install commands, exit code checking, system-level package prohibition
- [x] FR-2: `implement.md` — Negative guidance replaced with positive actionable guidance
- [x] FR-3: `implement_parallel.md` — Dependency rule added, scoped to `{task_id}`
- [x] FR-4: All 6 fix-phase templates updated (`fix.md`, `fix_standalone.md`, `ci_fix.md`, `verify_fix.md`, `thread_fix.md`, `thread_fix_pr_review.md`)
- [x] FR-5: `auto_recovery.md` — Missing-dependency recovery action added
- [x] FR-6: `review.md` — Dependency checklist expanded to cover manifest declarations, lockfile commits, and system-level package prohibition
- [x] FR-7: Tests — No content-asserting tests existed that needed updating; all 3,379 pass
- [x] All tasks marked complete
- [x] No placeholder or TODO code

### Quality
- [x] All tests pass (3,379)
- [x] Code follows existing template conventions
- [x] No unnecessary dependencies added (no code dependencies at all — template-only changes)
- [x] No unrelated changes included
- [x] No orchestrator/agent/config code modified (confirmed via `git diff`)

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive operations
- [x] Error handling guidance present (step 3: "Check the exit code")

---

## Security-Specific Analysis

### Threat: Malicious dependency injection via instruction manipulation
The templates now explicitly grant agents permission to install packages. This is the correct call — agents already had `bypassPermissions` Bash access, so the capability was always there. The templates merely remove the ambiguity that caused agents to skip installations.

**Mitigations in place:**
1. **Manifest-first requirement** — Dependencies must be declared in `pyproject.toml` / `package.json` before install, making them visible in git diffs and reviewable
2. **Review phase checklist** expanded to verify manifest declarations, lockfile commits, and absence of system-level packages
3. **System-level package prohibition** is explicit and well-worded ("report it as a blocker rather than attempting to install it")
4. **Scoping** — Each phase-specific template scopes dependency installation to the current task/fix/feature, not blanket permission

### Threat: Supply chain attack via typosquatted package
The templates don't include guidance on verifying package authenticity (e.g., checking download counts, verifying maintainers). This is an acceptable gap for v1 — the review phase serves as a human-readable checkpoint where reviewers can spot suspicious packages in the diff. A v2 improvement could add "verify the package is the well-known, widely-used library" guidance.

### Threat: Post-install script execution
Running `npm install` or `uv sync` executes arbitrary post-install scripts from packages. This is inherent to package managers and not a new risk introduced by these changes — agents could already run these commands. The existing phase timeout (1800s) and budget caps bound the blast radius.

### Note: `pip install` not mentioned as canonical command
Good design decision. The templates specify `uv sync` / `uv pip install -e .` for Python, avoiding bare `pip install` which would bypass the manifest-first workflow. This prevents phantom dependencies that aren't tracked in version control.

### Note: No allowlist mechanism
The PRD explicitly calls this a non-goal ("No dependency count caps or allowlists — The review phase is the guardrail"). I agree with deferring this. A config-driven allowlist would add complexity without proportional security benefit given that the review phase inspects every dependency change.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/base.md]: Dependency Management section is well-structured. The system-level package prohibition is clear and explicit. The manifest-first workflow ensures all dependency changes are auditable in git.
- [src/colonyos/instructions/review.md]: Expanded checklist correctly adds manifest declaration, lockfile commit, and system-level package checks — this is the right enforcement point.
- [src/colonyos/instructions/auto_recovery.md]: Recovery guidance correctly scopes install-as-recovery to specific error signatures (ModuleNotFoundError, Cannot find module), preventing agents from running install commands as a shotgun debugging tactic.
- [all templates]: No template references `pip install` directly — only `uv sync` / `uv pip install -e .` — which correctly enforces manifest-first workflow for Python.

SYNTHESIS:
This is a clean, well-scoped change that addresses a real operational pain point without expanding the agent's actual capability surface. The agents already had unrestricted Bash access; the only change here is replacing ambiguous negative guidance ("don't add unnecessary dependencies") with explicit positive guidance ("here's exactly when and how to install"). From a security perspective, the key properties are preserved: all dependency changes are manifest-tracked and git-visible, the review phase has an expanded checklist to catch issues, system-level packages are explicitly prohibited, and install commands are scoped to the current task. The 11-file changeset touches only instruction templates with no code changes to the orchestrator, agent, or config modules. All 3,379 tests pass. Ship it.
