# Staff Security Engineer — Round 2 Review

**Branch:** `colonyos/the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn`
**PRD:** `cOS_prds/20260406_102116_prd_the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn.md`
**Tests:** 3,379 passed, 0 failed

---

## Checklist Assessment

### Completeness
- [x] **FR-1** `base.md` — Dependency Management section added with manifest-first workflow, canonical install commands, exit code checking, lockfile commit requirement, and system-level package prohibition
- [x] **FR-2** `implement.md` — Negative "Do not add unnecessary dependencies" replaced with positive install guidance
- [x] **FR-3** `implement_parallel.md` — Dependency rule added, scoped to `{task_id}`
- [x] **FR-4** All six fix-phase templates updated: `fix.md`, `fix_standalone.md`, `ci_fix.md`, `verify_fix.md`, `thread_fix.md`, `thread_fix_pr_review.md`
- [x] **FR-5** `auto_recovery.md` — Missing dependency install added as valid recovery action
- [x] **FR-6** `review.md` — Expanded checklist: manifest declaration, lockfile commits, no system-level packages
- [x] **FR-7** `review_standalone.md` — Same expanded checklist (consistency fix from Round 1)
- [x] All 28 tasks marked complete in task file

### Quality
- [x] 3,379 tests pass
- [x] No linter errors (verified in prior rounds)
- [x] Follows existing template conventions — same markdown structure, same Rules section patterns
- [x] Zero new code dependencies — this is a pure instruction-template change (11 `.md` files + 2 artifacts)
- [x] No unrelated changes

### Safety — Security-Specific Assessment
- [x] **No secrets or credentials** in committed code
- [x] **No injection vectors** — all new content is static markdown text with no template variables except the pre-existing `{task_id}` in `implement_parallel.md`
- [x] **No new attack surface** — agents already had unrestricted Bash via `bypassPermissions`; these changes only structure *how* that existing capability is used
- [x] **System-level escalation blocked** — `brew`, `apt`, `yum`, `pacman`, `apk` explicitly prohibited in `base.md`
- [x] **Bare `pip install` prevented** — manifest-first workflow means all dependency changes appear in git diffs
- [x] **Audit trail preserved** — lockfile commit requirement (step 4) ensures all dependency mutations are reviewable
- [x] **Review phase is the enforcement layer** — both `review.md` and `review_standalone.md` now check for manifest declaration, lockfile commits, and system-level package prohibition

## Security Analysis

### Threat: Malicious instruction injection via dependency templates
**Risk: None.** The new Dependency Management section in `base.md` is static text. It contains no template variables (`{...}`) that could be influenced by user input or PR content. The only template variable in the diff is `{task_id}` in `implement_parallel.md`, which pre-existed.

### Threat: Supply-chain attacks (typosquatting, dependency confusion)
**Risk: Acceptable.** Agents could theoretically install a typosquatted package. However: (1) the manifest-first workflow ensures the package name appears in `pyproject.toml`/`package.json` diffs, making it visible to reviewers; (2) the review phase explicitly checks for unnecessary dependencies; (3) this risk existed before this change — agents could already run `pip install` via Bash.

### Threat: Privilege escalation via system-level packages
**Risk: Mitigated.** The explicit prohibition on `brew`/`apt`/`yum`/`pacman`/`apk` in `base.md` is inherited by all phases. This is a soft control (LLM instruction compliance), but it matches the existing security model where all agent constraints are instruction-based.

### Threat: Recovery phase abuse
**Risk: Low.** The `auto_recovery.md` change is narrowly scoped: install is only suggested when the failure is `ModuleNotFoundError` or `Cannot find module`. This doesn't expand the recovery agent's actual capabilities.

## Non-Blocking Recommendations (v2)

1. **Typosquat verification** — Add guidance for agents to verify package names against the canonical registry before installing
2. **Lockfile freshness check in verify.md** — The verify phase should confirm lockfiles are committed and consistent with manifests
3. **Config-driven install commands** — Allow projects to specify their exact install commands in `colonyos.toml` rather than relying on agent detection
4. **Worktree isolation for parallel installs** — When `implement_parallel` agents install dependencies concurrently, lockfile conflicts are possible; worktree isolation would prevent this

---

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/base.md]: Dependency Management section is well-structured with manifest-first workflow, but lacks guidance on verifying package name authenticity (v2 follow-up)
- [src/colonyos/instructions/auto_recovery.md]: Recovery install scoped to ModuleNotFoundError/Cannot find module — appropriately narrow
- [src/colonyos/instructions/review.md]: Expanded checklist now covers manifest declaration, lockfile commits, and system-level package prohibition — this is the correct enforcement point

SYNTHESIS:
This change is security-positive. The previous negative framing ("Do not add unnecessary dependencies") paradoxically degraded security by causing agents to skip installs entirely, leading to wasted fix iterations where agents would thrash on ModuleNotFoundError without understanding they were allowed to install. The replacement implements defense-in-depth correctly: mutation phases have explicit, structured permission to install (manifest-first, exit code checking, lockfile commits), while the review phase serves as the enforcement layer checking that all dependency changes are legitimate, declared in manifests, and committed with lockfiles. No new attack surface is created — agents already had unrestricted Bash access. The system-level package prohibition is the one genuinely new security control, and it's correctly placed in the base instructions inherited by all phases. Ship it.
