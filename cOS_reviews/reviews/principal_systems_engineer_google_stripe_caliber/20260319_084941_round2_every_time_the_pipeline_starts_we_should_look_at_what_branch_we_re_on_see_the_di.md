# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 2)

Now I have a complete picture. Let me write the review.

---

## Review: Principal Systems Engineer Perspective

### Completeness Assessment

**FR-1** ✅ `_preflight_check()` added to `orchestrator.py`, called before agent phases  
**FR-2** ✅ Dirty working tree check with `git status --porcelain`, raises `ClickException`  
**FR-3** ✅ Branch existence check + open PR detection via `gh pr list`  
**FR-4** ✅ `git fetch origin main` with 5s timeout, `rev-list` count, graceful degradation  
**FR-5** ✅ `PreflightResult` dataclass in `models.py` with all specified fields  
**FR-6** ✅ `PreflightResult` stored on `RunLog`, serialized/deserialized  
**FR-7** ✅ `_ensure_on_main` + `ClickException` catch in `_run_single_iteration`  
**FR-8** ✅ `_resume_preflight` with clean-tree check and HEAD SHA comparison  
**FR-9** ✅ `--offline` flag on both `run` and `auto` CLI commands  
**FR-10** ✅ `--force` flag on `run` CLI command  

All 10 functional requirements have corresponding implementations and 37 dedicated tests pass, plus all 174 existing orchestrator/CEO tests continue to pass.

### Critical Findings

**1. `_check_working_tree_clean` is fail-open on non-zero returncode**

In `orchestrator.py:74-82`, the function reads `result.stdout` without checking `result.returncode`. If `git status --porcelain` exits non-zero (corrupt index, permission errors, lock file contention), stdout will be empty → function returns `(True, "")` → pipeline proceeds believing the tree is clean. The docstring explicitly promises "fail-closed" behavior but the code doesn't deliver it. This is a data-loss vector: the exact scenario the PRD was designed to prevent.

**2. Resume HEAD SHA check will always false-positive after implementation**

The `head_sha` is recorded during the initial preflight (before any agent phases). After the implement phase creates commits, HEAD changes. If the run is interrupted during review/deliver and the user does `--resume`, the loaded `log.preflight.head_sha` will be the pre-implementation SHA. The current HEAD will be post-implementation. `_resume_preflight` will raise "HEAD SHA has diverged" — blocking the resume that it should allow. This makes the SHA tamper-detection feature a footgun: it catches the normal case (implementation modified the branch) instead of the exceptional case (someone force-pushed between runs).

**3. Auto-mode `ClickException` catch is over-broad**

In `cli.py:98-105`, the `try/except click.ClickException` wraps the entire `run_orchestrator()` call. Any `ClickException` raised deep in plan/implement/review/deliver phases will be caught, labeled as `"preflight-fail-iter-{iteration}"`, and silently swallowed. This masks real failures and corrupts the audit trail — a phase failure during implementation looks identical to a dirty-tree preflight rejection in the loop state.

**4. `_ensure_on_main` ignores checkout returncode**

In `cli.py:31-38`, `subprocess.run(["git", "checkout", "main"])` only catches `OSError` and `TimeoutExpired`. If `git checkout main` exits with returncode 1 (branch doesn't exist, merge conflicts), execution continues silently to `git pull --ff-only` on whatever branch is checked out. In auto mode, this means the pipeline could build on a stale feature branch — the exact problem the PRD exists to prevent.

### Minor Findings

- No timeouts on `git status --porcelain` or `git rev-parse` calls — these could hang on NFS-mounted repos
- `test_offline_skips_network` has `AssertionError` (correct spelling, but using a runtime error as a test assertion is fragile — `pytest.fail()` would be clearer)
- The `warnings` list in `PreflightResult` uses a mutable default (`field(default_factory=list)`) which is correct for dataclasses, but the `to_dict()` method defensively copies it — good

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/orchestrator.py:74-82]: `_check_working_tree_clean` does not check `result.returncode` — fail-open on git errors, contradicts docstring promise of fail-closed behavior. If git status exits non-zero, empty stdout is treated as "clean tree".
- [src/colonyos/orchestrator.py:192-203]: `head_sha` is recorded pre-implementation but checked on resume post-implementation. After implement phase creates commits, resume will always see "divergence" and block. Need to update `preflight.head_sha` after each phase that modifies the branch, or record it at run-log save time.
- [src/colonyos/cli.py:89-105]: `except click.ClickException` catches all ClickExceptions from `run_orchestrator()`, not just preflight failures. Non-preflight failures are mislabeled as `preflight-fail-iter-N` in loop state, masking real phase failures in auto mode.
- [src/colonyos/cli.py:31-38]: `_ensure_on_main` does not check `result.returncode` from `git checkout main`. A failed checkout (rc=1) proceeds silently to pull on the wrong branch.

SYNTHESIS:
The architecture is sound — procedural pre-flight with fail-fast semantics is the right call, and the separation of `_preflight_check` vs `_resume_preflight` is clean. The data model additions are minimal and well-serialized. However, there are two correctness bugs that would cause real operational pain: the fail-open `git status` check undermines the entire safety premise (PRD Goal #2: "Prevent data loss"), and the HEAD SHA check makes `--resume` unreliable after any successful implementation phase. The over-broad exception catch in auto mode would make 3am debugging harder, not easier — you'd see "preflight-fail" in the logs when the actual failure was a review-phase crash. Fix the returncode checks, move SHA recording to post-phase save points (or just record it when saving the run log rather than at preflight time), and narrow the auto-mode catch to a dedicated `PreflightError` subclass.