# Review by Staff Security Engineer (Round 1)

Good. Now I have a complete picture. Let me write the review.

---

## Security Review: Auto-Pull on Branch Switch

### Assessment

I've reviewed the full diff (925 lines added across 10 files) against the PRD requirements from the perspective of a Staff Security Engineer.

**Checklist:**

- [x] **FR-1**: `pull_branch()` helper added to `recovery.py` using `git pull --ff-only` with upstream check
- [x] **FR-2**: `restore_to_branch()` calls `pull_branch()` after checkout, failures logged as warnings
- [x] **FR-3**: Base-branch checkout in `orchestrator.py:4204` pulls after checkout, raises `PreflightError` on failure
- [x] **FR-4**: Preflight replaces fetch+warn with actual pull
- [x] **FR-5**: All pull calls gated by `offline` flag
- [x] **FR-6**: Thread-fix path (`run_thread_fix` at line 3770) does NOT call `pull_branch` — verified by source inspection and test
- [x] **FR-7**: `_ensure_on_main()` refactored to use shared `pull_branch()`, respects offline
- [x] **FR-8**: Upstream check via `git rev-parse --abbrev-ref @{upstream}` before pulling
- [x] **FR-9**: Structured logging with branch name on success/failure
- [x] All 72 relevant tests pass
- [x] No secrets or credentials in committed code
- [x] No destructive git operations — `--ff-only` fails safely on diverged state
- [x] Error handling present for all failure cases

**Security-specific findings:**

1. **`_git()` helper uses `capture_output=True`** — good, prevents stderr from leaking credential prompts to the terminal. Git credential helpers won't be able to prompt interactively through this path.

2. **`--ff-only` is the correct choice** — it fails if local history has diverged rather than silently discarding local commits (which `fetch + reset --hard` would do). This prevents a class of attacks where a malicious remote could silently replace local work.

3. **Thread-fix SHA integrity preserved** — the thread-fix flow is correctly excluded. This is the most security-critical exclusion: pulling in thread-fix would allow a force-push to change the code being reviewed after the SHA was recorded, defeating the tampering check.

4. **`restore_to_branch()` never-raises contract preserved** — the pull is wrapped in a `try/except Exception` catch-all, which means even if `pull_branch` somehow raises (despite its own error handling), the daemon won't crash. This is important for availability.

5. **No injection vectors** — `pull_branch()` doesn't accept arbitrary branch names or remote URLs. It pulls the current branch's configured upstream, which limits the attack surface.

6. **Minor observation**: The `pull_branch()` function's `timeout` parameter defaults to `_DEFAULT_GIT_TIMEOUT` (30s based on the test). The upstream check uses a hardcoded `timeout=10`. Both are reasonable. However, note that `git pull` can trigger credential helpers, hooks, or SSH connections — the 30s timeout is the main defense against hanging. This is acceptable for v1.

VERDICT: approve

FINDINGS:
- [src/colonyos/recovery.py]: `pull_branch()` correctly checks for upstream tracking branch before pulling, uses `--ff-only` to prevent silent history rewriting, and handles timeouts. Well-designed from a security standpoint.
- [src/colonyos/recovery.py]: `restore_to_branch()` wraps pull in catch-all exception handler, preserving the never-raises contract — critical for daemon availability.
- [src/colonyos/orchestrator.py]: Thread-fix path at line 3770+ correctly excludes `pull_branch` — SHA integrity check remains intact against force-push tampering.
- [src/colonyos/orchestrator.py]: Base-branch checkout hard-fails on pull failure (PreflightError), which is the correct security posture — better to fail loudly than start from stale/potentially compromised state.
- [src/colonyos/cli.py]: `_ensure_on_main()` now respects offline mode, closing a gap where network calls could occur in air-gapped environments.
- [tests/]: Comprehensive test coverage including offline mode, no-upstream, timeout, thread-fix exclusion, and never-raises contract verification. 72 tests pass.

SYNTHESIS:
From a security perspective, this implementation is sound. The use of `--ff-only` is the correct defensive choice — it fails on diverged history rather than silently discarding local commits, which prevents a class of supply-chain attacks where a compromised remote could rewrite history during a pull. The most critical security invariant — that thread-fix does NOT pull, preserving SHA integrity checks against force-push tampering — is correctly maintained and verified by both source-inspection tests and negative assertions. The `_git()` helper's `capture_output=True` prevents credential prompts from leaking to stdout. All network operations are properly gated behind the offline flag, and the 30-second timeout provides a reasonable defense against hanging connections. The implementation adds no new attack surface and actually improves the security posture by ensuring pipelines operate on the latest verified state of the base branch.
