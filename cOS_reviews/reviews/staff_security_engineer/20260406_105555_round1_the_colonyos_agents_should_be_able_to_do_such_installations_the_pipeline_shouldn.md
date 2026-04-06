# Review by Staff Security Engineer (Round 1)

## Review Complete — Staff Security Engineer

**VERDICT: approve**

### Summary

This is a clean, well-scoped instruction-template-only change (11 markdown files, 0 code files). All 3,379 tests pass. No orchestrator, agent, or config code was modified.

**Key security findings:**

1. **No new capability surface** — Agents already had unrestricted Bash access via `bypassPermissions`. These changes only replace ambiguous negative guidance with explicit positive guidance.

2. **Audit trail preserved** — The manifest-first workflow ensures all dependency changes appear in `pyproject.toml`/`package.json` diffs, making them reviewable. Lockfile commits are required.

3. **Review phase hardened** — The `review.md` checklist was correctly expanded to verify manifest declarations, lockfile commits, and absence of system-level packages.

4. **System-level packages explicitly prohibited** — Clear language: "report it as a blocker rather than attempting to install it."

5. **No bare `pip install`** — Only `uv sync`/`uv pip install -e .` referenced, enforcing manifest-tracked installations.

6. **Recovery scoped correctly** — `auto_recovery.md` ties install-as-recovery to specific error signatures (`ModuleNotFoundError`, `Cannot find module`), not blanket debugging.

**Acceptable gap for v2:** No typosquatting/supply-chain verification guidance, but the review phase serves as a human-readable checkpoint. A follow-up could add "verify the package is the well-known library" guidance.

Review artifact saved to `cOS_reviews/reviews/staff_security_engineer/20260406_round1_the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn.md`.
