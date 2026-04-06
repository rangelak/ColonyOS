# Review — Principal Systems Engineer (Google/Stripe caliber), Round 2

**Branch:** `colonyos/the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn`
**PRD:** `cOS_prds/20260406_102116_prd_the_colonyos_agents_should_be_able_to_do_such_installations_the_pipeline_shouldn.md`

## Test Results

**3,379 tests pass.** All 28 tasks complete across 5 task groups. Zero Python code changes — this is a pure instruction-template change.

## Checklist

### Completeness
- [x] **FR-1** `base.md` — Dependency Management section added with manifest-first workflow, canonical commands (uv/npm/cargo/go), system-level prohibition, exit code checking, lockfile commit requirement.
- [x] **FR-2** `implement.md` — Old "Do not add unnecessary dependencies" replaced with positive guidance scoped to the feature.
- [x] **FR-3** `implement_parallel.md` — Dependency rule added to Rules section, scoped to `{task_id}`.
- [x] **FR-4** Fix-phase templates — All six updated (`fix.md`, `fix_standalone.md`, `ci_fix.md`, `verify_fix.md`, `thread_fix.md`, `thread_fix_pr_review.md`). Each uses appropriate context-specific framing.
- [x] **FR-5** `auto_recovery.md` — Missing-dependency install added as valid minimum recovery action with error signature examples.
- [x] **FR-6** `review.md` — Expanded checklist: manifest declaration, lockfile commits, no system-level packages.
- [x] **FR-7** Tests — 3,379 pass. No test content needed updating (no tests asserted on the old instruction wording).
- [x] **Bonus:** `review_standalone.md` also updated for consistency (fix iteration 1).

### Quality
- [x] All tests pass (3,379/3,379)
- [x] No linter errors (pre-commit hooks pass per commit history)
- [x] Code follows project conventions — instruction templates match existing markdown formatting
- [x] No unnecessary dependencies added — zero dependency changes
- [x] No unrelated changes included — diff is 14 files, all on-topic

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive database operations
- [x] Error handling: system-level package prohibition is explicit; exit code checking is required; install failures are a "stop and diagnose" condition

## Systems Engineer Assessment

### What I like

**1. The layering is correct.** `base.md` provides the canonical workflow (the "how"), mutation-phase templates grant scoped permission (the "when"), and `review.md` is the enforcement point (the "check"). This is the same permit → scope → audit pattern you'd use for IAM policies. No phase contradicts another.

**2. Scope anchoring per phase.** Each template ties the dependency scope to its operational context:
- `implement.md`: "unrelated to the feature"
- `ci_fix.md`: "unrelated to the CI failure"
- `thread_fix.md`: "unrelated to the fix request"

This prevents scope creep without requiring a blanket prohibition. An agent in the CI-fix phase won't add a feature dependency, and an implement agent won't add debugging tools.

**3. Recovery path is defined.** `auto_recovery.md` now handles the `ModuleNotFoundError` → `uv sync` path, which was likely the most common failure mode. This eliminates a full pipeline retry for a 2-second fix.

**4. No code changes.** The blast radius of this change is exactly zero for runtime behavior — only the prompt text changes. If the new wording causes unexpected agent behavior, reverting is a single commit.

### What I'd watch in production

**1. No idempotency guarantee on `npm install`.** If an agent runs `npm install` in a worktree during parallel implement and two worktrees share `node_modules` via symlink or mount, you get a race condition. Not a bug in *this* change — the parallel implement already has this risk — but the new instructions make it more likely to trigger. Worth a follow-up to verify worktree isolation.

**2. Missing `--frozen-lockfile` guidance.** The instructions tell agents to run `uv sync` and `npm install`, but in a CI-fix context you might want `npm ci` (which respects the lockfile exactly). For v1 this is fine — the review phase catches drift — but for v2, consider phase-specific install commands.

**3. No observability on install actions.** When an agent installs a dependency, there's no structured log entry. If a pipeline run adds 5 packages, the only way to discover this is reading the git diff. A future improvement could emit a structured event (e.g., `{"event": "dependency_installed", "package": "...", "manifest": "..."}`) for pipeline analytics.

None of these are blockers. They're operational considerations for the next iteration.

## Verdict

This is a clean, minimal, correctly-layered change that solves a real pipeline failure mode without introducing new risk. The instruction hierarchy is sound, the scope boundaries are appropriate per phase, and the review-phase guardrail is properly hardened.

VERDICT: approve

FINDINGS:
- [src/colonyos/instructions/base.md]: Dependency Management section is well-structured with the correct manifest-first → install → verify → commit workflow. Covers Python, Node, Rust, Go.
- [src/colonyos/instructions/implement.md]: Old negative guidance correctly replaced with positive, feature-scoped guidance.
- [src/colonyos/instructions/ci_fix.md]: Good differentiation — "run the install command" for existing deps vs "add to manifest first" for new deps. Context-appropriate.
- [src/colonyos/instructions/auto_recovery.md]: Recovery action correctly scoped to specific error signatures (ModuleNotFoundError, Cannot find module), not a blanket "install everything."
- [src/colonyos/instructions/review.md]: Checklist expanded to enforce manifest declaration + lockfile commits + no system packages. This is the right enforcement layer.
- [src/colonyos/instructions/review_standalone.md]: Fixed in iteration 1 to match review.md. Good consistency.

SYNTHESIS:
From a systems reliability perspective, this change eliminates a class of preventable pipeline failures (dependency-not-installed) by replacing ambiguous negative guidance with a clear, auditable workflow. The architecture follows permit-scope-audit layering: base.md grants permission with constraints, each phase template scopes to its operational context, and review.md enforces at the gate. No runtime code is modified, making the blast radius zero and rollback trivial. The 3,379 passing tests confirm no regressions. I'd recommend shipping this and monitoring the first 10-20 pipeline runs for unexpected install behavior, then following up on worktree isolation for parallel installs and phase-specific install commands (npm ci vs npm install). Approve.
