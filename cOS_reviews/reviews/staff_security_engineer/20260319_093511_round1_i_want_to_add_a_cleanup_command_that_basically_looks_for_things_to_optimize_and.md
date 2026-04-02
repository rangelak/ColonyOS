# Review by Staff Security Engineer (Round 1)

All 54 tests pass. Now I have a comprehensive picture. Let me produce my review.

---

## Security Review: `colonyos cleanup` Implementation

### Assessment from Staff Security Engineer Perspective

I've reviewed the full implementation: `cleanup.py` (597 lines), CLI additions in `cli.py` (320 lines), `config.py` changes (62 lines), `cleanup_scan.md` instruction template, and 577 lines of tests (54 tests, all passing).

---

### Completeness

| Requirement | Status | Notes |
|---|---|---|
| FR-1 (command group with 3 subcommands) | ✅ | `branches`, `artifacts`, `scan` |
| FR-2 (help on bare `cleanup`) | ✅ | `invoke_without_command=True` |
| FR-3–FR-10 (branch cleanup) | ✅ | Merged detection, prefix filter, dry-run, remote, safety checks |
| FR-11–FR-16 (artifact cleanup) | ✅ | Retention, dry-run, RUNNING protection, summary |
| FR-17–FR-21 (structural scan) | ✅ | Static analysis, `--ai`, `--refactor` delegation |
| FR-22–FR-23 (configuration) | ✅ | `CleanupConfig` with CLI overrides |
| FR-24 (audit logging) | ✅ | JSON logs written for all operations |
| FR-25 (cleanup log self-protection) | ✅ | `cleanup_` prefix skipped in `list_stale_artifacts` |
| FR-26 (AI scan inherits base constraints) | ⚠️ | See finding below |
| FR-27 (AI scan forbids auth/secrets files) | ✅ | Explicit in `cleanup_scan.md` |

### Security Findings

**FINDING 1 — Medium: AI scan instruction does NOT inherit `base.md` constraints (FR-26 violation)**
- `[src/colonyos/cli.py]` lines 1169-1171: The `--ai` scan reads `cleanup_scan.md` directly as the system prompt. It does **not** compose it with the `base.md` instruction template that contains the critical safety constraints (no direct main commits, no force-push, no destructive git operations). The PRD explicitly requires this at FR-26. While `cleanup_scan.md` says "DO NOT modify any files" and "DO NOT create any commits", it lacks the full base constraints (e.g., no force-push, branch naming rules, budget respect). The AI agent gets `allowed_tools=["Read", "Glob", "Grep", "Agent"]` which limits blast radius, but this is still a defense gap.

**FINDING 2 — Low: `shutil` imported but unused in `cleanup.py`**
- `[src/colonyos/cleanup.py]` line 16: `import shutil` is imported but never used. This is dead code — minor, but it hints at potential future use of `shutil.rmtree` which would be a higher-risk operation (recursive directory deletion vs. `path.unlink()` for individual files).

**FINDING 3 — Positive: Branch name not sanitized before shell injection**
- `[src/colonyos/cleanup.py]` lines 253, 268: Branch names are passed as list elements to `subprocess.run()`, not via shell=True. This is the correct pattern — no shell injection vector. ✅

**FINDING 4 — Positive: Dry-run-by-default is properly enforced**
- All destructive operations (`delete_branches`, `delete_artifacts`) require explicit `execute=True`. CLI requires `--execute` flag. This is the correct safety posture. ✅

**FINDING 5 — Positive: Open PR protection works correctly**
- `check_branch_safety()` reuses the existing `check_open_pr` from `github.py` and treats failures conservatively (logs warning, continues — meaning the branch is NOT protected on failure). This is a debatable design choice but the broad `except Exception` on line 213 means `check_open_pr` failures don't block cleanup, they just silently let deletion proceed.

**FINDING 6 — Low: Bare `except Exception` in PR check could silently bypass safety**
- `[src/colonyos/cleanup.py]` line 213: `except Exception as exc` in `check_branch_safety()` means if `check_open_pr` raises any exception (network error, auth error, rate limit), the branch is treated as safe to delete. A stricter approach would treat GitHub API failures as "skip" rather than "proceed". This is a fail-open design in a safety check.

**FINDING 7 — Informational: Audit log timestamp race condition**
- `[src/colonyos/cleanup.py]` lines 584-590: `write_cleanup_log` calls `datetime.now()` twice — once for the filename and once for the `timestamp` field. These could theoretically differ by a second on the boundary. Minor, not exploitable.

**FINDING 8 — Positive: No secrets, credentials, or sensitive data in committed code**
- No `.env` files, API keys, tokens, or credentials found in the diff. ✅

**FINDING 9 — Positive: `--refactor` delegates to full pipeline**
- The `--refactor` flag correctly delegates to `run_orchestrator()` which runs the full Plan/Implement/Review/Decision/Deliver pipeline. No shortcutting of review gates. This is exactly the right security posture for autonomous code changes. ✅

**FINDING 10 — Positive: `git branch -d` (not `-D`) used for deletion**
- `[src/colonyos/cleanup.py]` line 254: Uses `-d` (safe delete, only works for merged branches) rather than `-D` (force delete). This is the correct, conservative choice. ✅

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/cli.py]: AI scan system prompt (lines 1169-1171) does not compose with `base.md` instruction template, violating FR-26. The `cleanup_scan.md` is used standalone without inheriting the base safety constraints (no force-push, branch naming, budget rules).
- [src/colonyos/cleanup.py]: `import shutil` on line 16 is unused dead code.
- [src/colonyos/cleanup.py]: `check_branch_safety()` line 213 uses fail-open design — when GitHub API check fails (network error, rate limit), the branch is treated as safe to delete rather than skipped. Consider fail-closed: return a skip reason like "unable to verify PR status" on exception.

SYNTHESIS:
This is a well-structured, security-conscious implementation that gets the critical design decisions right: dry-run by default, `git branch -d` (not `-D`), subprocess list-based invocation (no shell injection), proper delegation of refactoring to the full review pipeline, and self-protecting audit logs. The test coverage is solid at 54 tests covering all core functions. The two actionable findings are: (1) the AI scan instruction must compose with `base.md` per FR-26 — this is a real defense-in-depth gap since the AI agent could theoretically violate base constraints not repeated in `cleanup_scan.md`, and (2) the `check_branch_safety` GitHub check should fail-closed rather than fail-open, since silently proceeding with deletion when we can't verify PR status defeats the purpose of the safety check. Neither is a critical security vulnerability given the existing mitigations (allowed_tools restriction, merged-only branch targeting), but both represent defense-in-depth gaps that should be fixed before merge.
