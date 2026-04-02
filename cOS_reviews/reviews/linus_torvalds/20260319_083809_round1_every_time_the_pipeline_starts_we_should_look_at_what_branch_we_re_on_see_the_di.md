# Review by Linus Torvalds (Round 1)

Now I have a complete picture. Let me write the review.

---

## Review: Git State Pre-flight Check

I've reviewed the full diff (923 lines added across 8 files), the PRD, and the task file. All 996 tests pass, including 68 new ones for preflight and github modules.

### What's Good

The core architecture is correct: procedural logic, not an LLM phase. The data structures are clean — `PreflightResult` is a simple dataclass with obvious fields, straightforward serialization, no inheritance abuse. The decision to fail fast with `click.ClickException` on dirty state is exactly right. The `check_open_pr()` function handles all error paths (timeout, `gh` not installed, bad JSON, non-zero exit) without panicking. The `--force` and `--offline` flags are wired through cleanly.

### Issues Found

**1. Duplicated subprocess patterns.** The "get current branch" and "check dirty state" logic is copy-pasted between `_preflight_check` and `_resume_preflight`. That's ~30 lines of identical code. Extract `_get_current_branch(repo_root)` and `_check_working_tree_clean(repo_root)` helper functions. When you copy-paste, you'll inevitably fix a bug in one and not the other.

**2. Silent swallow on OSError for `git status`.** If `git status --porcelain` throws `OSError`, the code sets `is_clean = True` and proceeds. That's *wrong*. If you can't even run `git status`, you're not in a git repository, or git isn't installed. That should be a hard error, not a "looks clean to me!" The same applies to the `rev-parse` fallback to `"unknown"` — if you can't determine the branch, you have no business proceeding.

**3. Inconsistent mock patching in tests.** Some tests patch `colonyos.orchestrator.subprocess.run`, others patch the global `subprocess.run`. The ones patching global `subprocess.run` work by accident because `validate_branch_exists` uses `subprocess.run` directly and would pick up the global mock. This is fragile — if someone refactors the import, half the tests break silently.

**4. Task 5.3 is incomplete.** The autonomous mode doesn't do `git checkout main && git pull --ff-only` before each iteration as specified. The `except click.ClickException` handler is necessary but insufficient — the PRD says "always ensure a clean working tree on `main` before starting" in auto mode.

**5. Task 7.3 is incomplete.** Manual testing wasn't done (understandable for CI, but it's unchecked).

**6. FR-8 partially implemented.** The PRD says resume preflight should verify "branch HEAD matches the RunLog's last known state" to detect tampering between runs. `_resume_preflight` only checks for clean working tree — no HEAD SHA comparison.

**7. Lazy import inside function body.** `from colonyos.github import check_open_pr` is imported inside `_preflight_check()`. This is presumably to avoid circular imports, but if that's the case, document *why*. If it's not circular, move it to the top of the file where it belongs.

**8. `call_count` variable in test is unused.** `test_fetch_timeout_degrades_gracefully` declares `call_count = 0` and never uses it. Dead code in tests is still dead code.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/orchestrator.py]: Duplicated "get branch" and "check clean" subprocess logic between `_preflight_check` and `_resume_preflight` — extract helper functions
- [src/colonyos/orchestrator.py]: `OSError` on `git status` silently sets `is_clean = True` — this should be a hard error, not silent success
- [src/colonyos/orchestrator.py]: Lazy import of `check_open_pr` inside function body without justification — move to module-level or document why
- [src/colonyos/orchestrator.py]: FR-8 partially implemented — `_resume_preflight` doesn't verify branch HEAD SHA against RunLog as specified
- [tests/test_preflight.py]: Inconsistent mock patching — some tests patch `colonyos.orchestrator.subprocess.run`, others patch global `subprocess.run`
- [tests/test_preflight.py]: Unused `call_count` variable in `test_fetch_timeout_degrades_gracefully`
- [src/colonyos/cli.py]: Task 5.3 incomplete — autonomous mode doesn't ensure starting from `main` with `git checkout main && git pull --ff-only` before iterations

SYNTHESIS:
The implementation is structurally sound — the right function in the right place doing the right checks. The data model is clean, the error messages are actionable, and the test coverage is solid at 349 lines. But there are real problems: silently swallowing `OSError` on `git status` and pretending the tree is clean is a correctness bug that defeats the entire purpose of a pre-flight safety check. The code duplication between the two preflight functions is a maintenance hazard. Two task items remain incomplete (5.3 auto-mode main checkout, FR-8 HEAD SHA verification). Fix the OSError handling, extract the duplicated helpers, and address the incomplete requirements. The bones are good — the execution needs another pass.
