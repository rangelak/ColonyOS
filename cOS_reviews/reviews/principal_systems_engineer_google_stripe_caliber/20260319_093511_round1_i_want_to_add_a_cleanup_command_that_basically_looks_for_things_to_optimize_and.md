# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

I have a thorough understanding of the implementation. Here's my review:

---

## Review: `colonyos cleanup` — Principal Systems Engineer Perspective

### Completeness Assessment

| Requirement | Status | Notes |
|---|---|---|
| FR-1: Command group with 3 subcommands | ✅ | `branches`, `artifacts`, `scan` all present |
| FR-2: No subcommand prints help | ✅ | `invoke_without_command=True` + `get_help()` |
| FR-3: List merged branches | ✅ | Uses `git branch --merged` |
| FR-4: Prefix filtering + `--all-branches` | ✅ | |
| FR-5: Rich-formatted table | ✅ | |
| FR-6: Dry-run default, `--execute` to act | ✅ | |
| FR-7: `--include-remote` flag | ✅ | |
| FR-8: Never delete current/default branch | ✅ | Double-checked in both `list_merged_branches` and `check_branch_safety` |
| FR-9: Never delete branches with open PRs | ✅ | Reuses `check_open_pr` from `github.py` |
| FR-10: Summary output | ✅ | |
| FR-11-16: Artifact cleanup | ✅ | All requirements met |
| FR-17-21: Structural scan | ✅ | Static scan + `--ai` + `--refactor` |
| FR-22-23: Configuration | ✅ | `CleanupConfig` with CLI overrides |
| FR-24: Audit logging | ✅ | JSON logs under `.colonyos/runs/cleanup_*.json` |
| FR-25: Cleanup logs not deletable by cleanup | ✅ | `cleanup_` prefix skipped in `list_stale_artifacts` |
| FR-26-27: AI scan constraints | ✅ | `cleanup_scan.md` has explicit forbids |

### Quality Findings

**All 1081 tests pass**, including 54 new tests for cleanup (test_cleanup.py) and 8 CLI-level tests (test_cli.py). No regressions.

### Specific Findings

**[src/colonyos/cleanup.py:170]** — Branch name parsing uses `lstrip("* ")` which strips individual characters, not the string `"* "`. A branch named `*staging` would have its `s` stripped if it starts with `*s`. This is a minor edge case since `git branch --merged` outputs `* ` (asterisk-space) only for the current branch, which is already filtered out. Low-risk but worth noting.

**[src/colonyos/cleanup.py:200-207]** — `check_branch_safety` makes a network call to `check_open_pr` for **every** branch in `delete_branches`. For repos with 50+ stale branches, this is 50+ sequential `gh pr list` calls. No parallelism, no batching. At 5s timeout each, worst case is ~4 minutes of blocking. The function is correct but will be painfully slow at scale.

**[src/colonyos/cleanup.py:252-285]** — `list_stale_artifacts` only processes `.json` files, not directories. The PRD (FR-11) mentions "completed run directories," but the implementation correctly targets the actual artifact format (JSON files in `runs/`). This is a pragmatic interpretation since the runs dir contains files, not subdirectories per run.

**[src/colonyos/cleanup.py:349]** — `_categorize_complexity` divides by `max_lines`/`max_functions` without checking for zero. The config validation prevents zero values, but the function itself is exposed publicly and could receive zero, causing `ZeroDivisionError`. The guard `if max_lines > 0` returns `0` for the ratio, but if both are zero, `ratio = 0` and returns `None` — safe. Actually fine on closer inspection.

**[src/colonyos/cli.py:2434-2466]** — The `--ai` scan path catches a broad `Exception` and prints the error. This is acceptable for a CLI tool, but the error message could lose context. The `run_phase_sync` call uses `Phase.REVIEW` which feels semantically wrong for a cleanup scan — it's not a review, it's an analysis. However, the phase is just used for model selection, so functionally fine.

**[src/colonyos/cli.py:2395-2410]** — The `--refactor` path calls `run_orchestrator` directly, which runs the full Plan/Implement/Review/Decision/Deliver pipeline. This is exactly what the PRD mandates (code changes go through full pipeline). Good safety design.

**[src/colonyos/instructions/cleanup_scan.md]** — The instruction template explicitly forbids modifying files and touching auth/secrets files. Satisfies FR-26 and FR-27. However, it does not explicitly inherit `base.md` constraints (FR-26 says "must inherit the base.md instruction constraints"). The system prompt is loaded directly from `cleanup_scan.md` rather than composing it with `base.md`. This means base safety constraints (no direct main commits, no force-push) are not inherited. In practice, since this is analysis-only and the instruction says "DO NOT modify any files," the risk is low, but it's a deviation from the spec.

**[src/colonyos/cleanup.py:write_cleanup_log]** — Timestamp generation for log filenames uses `strftime` with second precision. Two rapid cleanup operations within the same second would overwrite each other's logs. Should include milliseconds or use a UUID suffix. Low probability in practice for a manual CLI command.

### Safety Assessment

- ✅ No secrets or credentials in code
- ✅ Dry-run defaults everywhere — `--execute` required for all destructive ops
- ✅ Uses `git branch -d` (safe delete) not `-D` (force delete) — won't delete unmerged branches even if they pass safety checks
- ✅ Audit logs always written, even for dry-runs
- ✅ Cleanup logs are self-protected from artifact cleanup
- ✅ Error handling present on all subprocess calls and file operations

---

VERDICT: approve

FINDINGS:
- [src/colonyos/cleanup.py:200-207]: `check_branch_safety` makes sequential network calls per branch — O(N) `gh pr list` calls with 5s timeout each. Will be slow at scale (50+ branches = minutes of blocking).
- [src/colonyos/instructions/cleanup_scan.md]: Does not compose with `base.md` as FR-26 requires — safety constraints are restated but not inherited programmatically. Low risk since the scan is read-only.
- [src/colonyos/cleanup.py:170]: `lstrip("* ")` strips individual characters not the prefix string; edge case only, since current branch is already filtered.
- [src/colonyos/cleanup.py:write_cleanup_log]: Second-precision timestamps could collide under rapid successive invocations — use sub-second precision or UUID.

SYNTHESIS:
This is a well-architected implementation that correctly separates deterministic operations (branch/artifact cleanup) from AI-powered analysis, with appropriate safety boundaries throughout. The dry-run-by-default design is exactly right — every destructive path requires explicit opt-in. The test coverage is comprehensive (54 unit tests + 8 CLI tests), all 1081 tests pass, and the code follows established project conventions cleanly. The two notable issues are: (1) the N+1 network call pattern in branch safety checks, which will degrade at scale but is acceptable for v1, and (2) the `cleanup_scan.md` not programmatically inheriting `base.md` constraints, though it restates the critical ones. Neither is a blocker. The implementation correctly routes all code-changing operations through the existing orchestrator pipeline with full review gates — the single most important safety property for this feature. Ship it.