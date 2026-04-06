# Review by Staff Security Engineer (Round 3)

---

## Staff Security Engineer — Round 2 Review

**Branch:** `colonyos/the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn`
**Tests:** 3,379 passed, 0 failed
**Files changed:** 14 (11 instruction templates + 2 artifacts + 1 bonus `review_standalone.md`)

### Checklist Summary

| Category | Status |
|----------|--------|
| All 7 PRD functional requirements implemented | ✅ |
| All 28 tasks complete | ✅ |
| No placeholder/TODO code | ✅ |
| All tests pass | ✅ |
| No secrets in committed code | ✅ |
| No new code dependencies | ✅ |
| No injection vectors | ✅ |
| System-level packages prohibited | ✅ |

### Security Analysis

**No new attack surface.** This is a pure instruction-template change (0 code files). Agents already had unrestricted Bash access — these changes only structure *how* that existing capability is used via a manifest-first workflow.

Key security controls in the change:
- **System-level escalation blocked** — `brew`/`apt`/`yum`/`pacman`/`apk` explicitly prohibited in `base.md`
- **Bare `pip install` prevented** — manifest-first workflow ensures all deps appear in reviewable diffs
- **Audit trail** — lockfile commit requirement makes all dependency mutations visible
- **Review phase enforcement** — both `review.md` and `review_standalone.md` now check manifest declaration, lockfile commits, and system-level package prohibition

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/base.md]: Dependency Management section is well-structured with manifest-first workflow, but lacks guidance on verifying package name authenticity (v2 follow-up)
- [src/colonyos/instructions/auto_recovery.md]: Recovery install scoped to ModuleNotFoundError/Cannot find module — appropriately narrow
- [src/colonyos/instructions/review.md]: Expanded checklist now covers manifest declaration, lockfile commits, and system-level package prohibition — this is the correct enforcement point

SYNTHESIS:
This change is security-positive. The previous negative framing paradoxically degraded security by causing agents to skip installs entirely, leading to wasted fix iterations. The replacement implements defense-in-depth correctly: mutation phases have explicit, structured permission to install (manifest-first, exit code checking, lockfile commits), while the review phase serves as the enforcement layer. No new attack surface is created — agents already had unrestricted Bash access. The system-level package prohibition is the one genuinely new security control, and it's correctly placed in base instructions inherited by all phases. Ship it.
