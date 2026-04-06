# PRD: Enable Dependency Installation in Pipeline Agents

## Introduction/Overview

ColonyOS pipeline agents currently have full Bash access with `bypassPermissions`, meaning they *can* technically install packages. However, every mutation-phase instruction template contains ambiguous language — "Do not add unnecessary dependencies" or "Do not introduce new dependencies unless absolutely necessary" — that causes LLM agents to **avoid installing dependencies altogether**, even when genuinely required by the feature being implemented.

This results in preventable pipeline failures: the implement agent writes code that imports a new library, adds it to `pyproject.toml` or `package.json`, but never runs `uv sync` or `npm install`. The verify phase then fails with `ModuleNotFoundError` or `Cannot find module`, and the pipeline burns fix iterations chasing a problem that was never about code quality.

**The fix is in the instruction templates, not the infrastructure.** Replace the ambiguous negative guidance with clear positive guidance that tells agents exactly when and how to install dependencies.

## Goals

1. **Eliminate dependency-related pipeline failures** — Agents should never fail because they were afraid to run an install command for a dependency the feature genuinely requires.
2. **Provide explicit mechanics** — Every mutation-phase instruction template should describe the exact workflow: add to manifest → run install command → verify import → commit lockfile changes.
3. **Maintain safety** — The review phase already checks for unnecessary dependencies. That is the guardrail, not a blanket prohibition in every phase template.
4. **Cover all mutation phases** — Implement, implement_parallel, fix, fix_standalone, ci_fix, verify_fix, thread_fix, and thread_fix_pr_review all need updated guidance.

## User Stories

1. **As a developer using ColonyOS**, I want the pipeline to automatically install new Python packages when a feature requires them, so the verify phase doesn't fail with `ModuleNotFoundError`.
2. **As a developer with a polyglot repo** (Python + Next.js), I want agents to know which package manager to use for each part of the project (uv/pip for Python, npm for web/), so they don't use the wrong tool.
3. **As a developer**, I want agents to always declare dependencies in manifest files (not bare `pip install`), so dependency changes are visible in the git diff and reviewable by the review personas.
4. **As a developer**, I want the pipeline to not install system-level packages (brew, apt) autonomously, as those changes have machine-wide blast radius.

## Functional Requirements

1. **FR-1: Update `base.md`** — Add a "Dependency Management" section to the base instructions that all phases inherit. This section should:
   - Explain that agents may install project-level dependencies when genuinely required
   - Require that dependencies are always declared in the project's manifest file (`pyproject.toml`, `package.json`, `Cargo.toml`, etc.) before running the install command
   - Specify the canonical install commands: `uv sync` / `uv pip install -e .` for Python, `npm install` for Node
   - Explicitly prohibit system-level package managers (brew, apt, yum) — if a system dependency is missing, report it as a blocker
   - Require checking the exit code of install commands before proceeding

2. **FR-2: Update `implement.md`** — Replace "Do not add unnecessary dependencies" (line 52) with positive guidance: "When a feature requires a new dependency, add it to the appropriate manifest file and run the project's install command. Do not add dependencies unrelated to the feature."

3. **FR-3: Update `implement_parallel.md`** — Add dependency installation guidance (currently has no mention of dependencies at all). Scope to the assigned task only.

4. **FR-4: Update fix-phase templates** — Replace "Do not introduce new dependencies unless absolutely necessary" in `fix.md`, `fix_standalone.md`, `ci_fix.md`, `verify_fix.md`, `thread_fix.md`, and `thread_fix_pr_review.md` with: "If resolving a finding requires a new dependency or if existing dependencies are not installed, add the dependency to the manifest file and run the install command. Do not add dependencies unrelated to the fix."

5. **FR-5: Update `auto_recovery.md`** — Add guidance that running the project's install command (`uv sync`, `npm install`) is a valid minimum recovery action when the failure is a missing dependency.

6. **FR-6: Update `review.md`** — Expand the "No unnecessary dependencies added" checklist item to also check: dependencies are declared in manifest files, lockfiles are committed, and no system-level packages were installed.

7. **FR-7: Update tests** — Ensure any tests that validate instruction template content are updated to reflect the new dependency guidance wording.

## Non-Goals

- **No orchestrator code changes** — This is purely an instruction template change. No changes to `orchestrator.py`, `agent.py`, or `config.py`.
- **No pre-phase install step** — Do not add automatic dependency installation at phase boundaries. Agents should install reactively when needed, not proactively on every phase.
- **No user configuration for package managers** — Detect from repo structure; defer config surface to v2.
- **No system-level package management** — brew, apt, yum are explicitly out of scope.
- **No dependency count caps or allowlists** — The review phase is the guardrail.

## Technical Considerations

### Files to Modify
- `src/colonyos/instructions/base.md` — Add new "Dependency Management" section
- `src/colonyos/instructions/implement.md` — Replace line 52
- `src/colonyos/instructions/implement_parallel.md` — Add dependency rule to Rules section
- `src/colonyos/instructions/fix.md` — Replace line 56
- `src/colonyos/instructions/fix_standalone.md` — Replace line 53
- `src/colonyos/instructions/ci_fix.md` — Replace line 55
- `src/colonyos/instructions/verify_fix.md` — Replace line 68
- `src/colonyos/instructions/thread_fix.md` — Replace line 71
- `src/colonyos/instructions/thread_fix_pr_review.md` — Replace line 76
- `src/colonyos/instructions/auto_recovery.md` — Add install as valid recovery action
- `src/colonyos/instructions/review.md` — Expand dependency checklist item

### Architecture Fit
The instruction templates are loaded by `_load_instruction(name)` in `orchestrator.py` and formatted with template variables via `_build_*_prompt()` functions. No template variable changes are needed — only the static text content of the markdown files changes.

### Existing Guardrails (Unchanged)
- **Review phase** (`review.md`) already checks "No unnecessary dependencies added" — this remains the enforcement point
- **Budget caps** prevent runaway install processes from consuming excessive resources
- **Phase timeouts** (default 1800s) prevent hung install commands from blocking the pipeline
- **Verify phase** runs the full test suite, catching broken installations

### Persona Consensus
All 7 expert personas (YC Partner, Steve Jobs, Jony Ive, Principal Systems Engineer, Linus Torvalds, Staff Security Engineer, Andrej Karpathy) unanimously agreed:
- The problem is in the instruction templates, not the infrastructure
- Replace ambiguous negative guidance with clear positive guidance
- No pre-phase install step needed
- No user configuration needed in v1
- The review phase is the proper guardrail
- System-level packages should be prohibited

Minor tension: The Security Engineer recommended a config-driven `dependency_install_commands` map. Consensus: detect from repo structure, defer config to v2.

## Success Metrics

1. **Zero dependency-related pipeline failures** — Features that require new packages should not fail at the verify phase with `ModuleNotFoundError` or `Cannot find module`.
2. **All new dependencies visible in git diff** — Every agent-installed dependency should appear in a manifest file (`pyproject.toml`, `package.json`) and its corresponding lockfile.
3. **No regression in review quality** — The review phase should continue to flag genuinely unnecessary dependencies.
4. **All existing tests pass** — No regressions from instruction template changes.

## Open Questions

1. Should we add a "Dependency Installation" section to the PRD template used in the plan phase, so the plan agent explicitly identifies required new dependencies upfront? (Low priority — can be a follow-up.)
2. Should the `verify.md` instructions tell the verify agent to check that lockfiles are committed and up-to-date with manifest files? (Medium priority — would catch agents who update `pyproject.toml` but forget to commit `uv.lock`.)
