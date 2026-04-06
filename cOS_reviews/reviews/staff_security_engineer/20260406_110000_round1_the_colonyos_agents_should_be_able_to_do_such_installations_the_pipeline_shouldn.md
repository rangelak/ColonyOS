# Review — Staff Security Engineer, Round 1

## Branch
`colonyos/the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn`

## Test Results
3,379 passed, 0 failed.

## Checklist

### Completeness
- [x] All 7 functional requirements from the PRD are implemented
- [x] All 28 tasks marked complete
- [x] No placeholder or TODO code remains

### Quality
- [x] All tests pass (3,379)
- [x] No linter errors introduced
- [x] Code follows existing project conventions (markdown instruction templates only)
- [x] No unnecessary dependencies added (zero code changes, zero new dependencies)
- [x] No unrelated changes included

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive database operations
- [x] Error handling present (step 3: "If the install command fails, stop and diagnose")

## Security Assessment

### Attack Surface Analysis

**No new capability surface created.** This change modifies 11 markdown instruction templates and 0 code files. Agents already had unrestricted Bash access via `bypassPermissions` — these templates only replace ambiguous negative guidance ("Do not add unnecessary dependencies") with structured positive guidance (manifest-first, install, verify, commit lockfile).

### Threat Model Review

1. **Malicious instruction injection via dependency guidance** — LOW RISK. The dependency management section in `base.md` is static template text loaded by `_load_instruction()`, not user-controllable. No template variables (`{branch_name}`, etc.) appear in the new dependency management section. An attacker cannot inject arbitrary install commands through this path.

2. **Supply-chain poisoning via typosquatted packages** — ACCEPTABLE RISK for v1. The templates say "add it to the manifest file" but don't verify the package is the well-known library vs. a typosquat. However, the review phase checklist now explicitly requires reviewers to verify "any new dependencies are declared in manifest files with lockfile changes committed" — making dependency additions visible in diffs. This is the correct layer for human/LLM review. A v2 enhancement could add "verify the package is the well-known, widely-used library" guidance.

3. **System-level package escalation** — MITIGATED. The `base.md` section explicitly enumerates prohibited commands (`brew`, `apt`, `yum`, `pacman`, `apk`) and directs agents to "report it as a blocker rather than attempting to install it." This is clear, actionable, and covers the major system package managers.

4. **Bare `pip install` without manifest tracking** — MITIGATED. The workflow mandates "manifest first" with specific file types (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`), and the canonical install commands (`uv sync`, `uv pip install -e .`, `npm install`) all operate from manifests. No template mentions bare `pip install <package>`.

5. **Audit trail for dependency changes** — STRONG. Step 4 requires committing lockfile changes alongside manifest changes. This means every dependency addition appears in the git diff, making it reviewable by both the review-phase personas and human developers in the PR.

6. **Recovery phase abuse** — LOW RISK. The `auto_recovery.md` addition scopes install-as-recovery to specific error signatures (`ModuleNotFoundError`, `Cannot find module`), not blanket "try installing things." This is appropriately narrow.

### Defense-in-Depth Layers (All Preserved)

| Layer | Status |
|-------|--------|
| Manifest-first workflow (new) | Added in `base.md` |
| Review phase checklist (hardened) | `review.md` + `review_standalone.md` both expanded |
| System package prohibition (new) | Explicit in `base.md` |
| Phase timeouts (existing) | Unchanged — 1800s default |
| Budget caps (existing) | Unchanged |
| Verify phase (existing) | Full test suite still runs |

### Consistency Check

Both `review.md` and `review_standalone.md` now carry identical expanded dependency checklist wording: "No unnecessary dependencies added; any new dependencies are declared in manifest files with lockfile changes committed; no system-level packages installed." This was fixed in the fix iteration and is correct.

### Recommendations for v2 (Non-blocking)

1. Add guidance: "Verify the package name matches the well-known, widely-used library (not a typosquat)" — to either `base.md` or `review.md`.
2. Add `verify.md` instruction to check lockfiles are committed and up-to-date (PRD Open Question #2).
3. Consider a config-driven `allowed_install_commands` map for repos with non-standard toolchains.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/base.md]: Dependency management section is well-structured with manifest-first workflow, explicit system-package prohibition, and exit-code checking. No template variables in the new section eliminates injection risk.
- [src/colonyos/instructions/auto_recovery.md]: Recovery install guidance is appropriately scoped to specific error signatures (ModuleNotFoundError, Cannot find module).
- [src/colonyos/instructions/review.md]: Expanded checklist correctly covers manifest declaration, lockfile commits, and system-package prohibition — this is the right enforcement layer.
- [src/colonyos/instructions/review_standalone.md]: Now matches review.md wording, ensuring both review paths enforce the same dependency verification criteria.

SYNTHESIS:
This is a clean, security-positive change. From a supply-chain security perspective, the key insight is that the previous "Do not add unnecessary dependencies" wording was counterproductively reducing security — it caused agents to skip install commands entirely, leading to pipeline failures that burned fix iterations on non-issues. The new approach is more secure because it channels all dependency additions through a manifest-first workflow that creates an auditable git diff, while the review phase serves as the enforcement checkpoint. The explicit prohibition of system-level package managers addresses the highest-risk attack vector (machine-wide state modification). No new code paths, no new capabilities, no secrets — just better prompt engineering that happens to also improve the security posture.
