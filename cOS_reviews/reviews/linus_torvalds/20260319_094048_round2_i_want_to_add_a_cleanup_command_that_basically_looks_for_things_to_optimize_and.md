# Review by Linus Torvalds (Round 2)

Now let me write the review. I've read the PRD, the full diff across all 9 files, the task file, and verified all 1087 tests pass.

---

Here's my review as Linus Torvalds:

## Review: `colonyos cleanup` Implementation

I've read every line of the diff. All 1087 tests pass. Let me be direct about what I found.

### What's done right

The data structures are clean. `BranchInfo`, `ArtifactInfo`, `FileComplexity` — frozen dataclasses where appropriate, mutable ones documented as to *why* they're mutable. That's good. The code tells you what it does through its types.

The separation between `cleanup.py` (logic) and `cli.py` (presentation) is correct. The module follows the established `doctor.py` pattern. No new dependencies. Subprocess calls have timeouts. Error handling is fail-closed for the GitHub PR check — that's exactly right.

The dry-run default with `--execute` opt-in is properly implemented: in dry-run mode the code never touches git or the filesystem, it just populates the result lists.

### Issues

**1. `list_merged_branches` uses `removeprefix("* ")` but the original code used `lstrip("* ")`**

Looking at the test `test_handles_star_marker_branch`, the comment says:
> would appear if lstrip("* ") mangled "main"

So they clearly *fixed* this from `lstrip` to `removeprefix`. Good — this is the correct fix. The test proves it. No issue here after closer inspection.

**2. `list_stale_artifacts` only handles JSON files, not directories**

The PRD (FR-11, FR-16) says "Scan `.colonyos/runs/` for completed run **directories**" and "N run **directories** removed, M MB reclaimed." But the implementation scans for `.json` files only. The CLI summary says "artifact(s)" not "directories." This is actually *pragmatic* — the actual runs are stored as JSON files, not directories in this codebase — but the PRD language is misleading. The implementation matches reality, not the PRD's wording. Fine.

**3. `_SKIP_DIRS` contains `"*.egg-info"` which is a glob pattern, not a directory name**

```python
_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".colonyos", ".next", "coverage", ".eggs", "*.egg-info",
})
```

The `os.walk` filtering does `d not in _SKIP_DIRS` — exact string comparison. No directory is literally named `*.egg-info`. The actual pattern is something like `colonyos.egg-info`. This skip entry is dead code that does nothing. Minor, but sloppy.

**4. `scan_file_complexity` line counting has an edge case**

```python
line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
```

Empty file returns `0` lines. A file with just `"x"` (no newline) returns 1. A file with `"x\n"` returns 1. That's correct. Fine.

**5. The `--ai` scan path in `cli.py` is dense but functional**

It composes `base.md + cleanup_scan.md` as the system prompt. The instruction template (FR-26) properly inherits base constraints and (FR-27) explicitly forbids touching auth/secrets files. The `allowed_tools` correctly restricts to read-only tools. No issue.

**6. `_categorize_complexity` uses `>= 1` for LARGE, meaning exactly-at-threshold files are flagged**

This is a design choice. The PRD says "files exceeding configurable thresholds." A file of *exactly* 500 lines with `max_lines=500` gets flagged. The ratio is `500/500 = 1.0`, which hits `>= 1`. The test `test_exact_threshold` explicitly verifies this. Debatable whether "exactly at threshold" means "exceeding" but the test documents the decision. Acceptable.

**7. `branch_retention_days` in config is defined but never used**

`CleanupConfig.branch_retention_days` exists (default 0) but `list_merged_branches` and `delete_branches` have no age-based filtering logic. The field is parsed, validated, round-tripped through config save/load, but never read in any functional code path. This is dead configuration. The PRD's FR-3 says "fully merged into the default branch" (merge-based, not age-based), and Open Question #3 explicitly defers age-based heuristics. So this config field is premature — it exists for a feature that doesn't exist yet. I'd prefer not shipping dead config, but it's documented in the PRD as intentionally deferred, and the default is 0 (meaning "merged-only"), so it won't confuse users.

**8. No CHANGELOG update**

Task 8.4 says "Update CHANGELOG.md with the new cleanup command" and is checked complete, but the diff shows no changes to any CHANGELOG file. Either the file doesn't exist (in which case the task shouldn't have been marked done) or it was missed.

**9. `save_config` only serializes cleanup section when values differ from defaults**

This is correct — it follows the same sparse-serialization pattern used by other config sections. No issue.

### Overall Assessment

The code is straightforward, correctly structured, and well-tested (169 new tests, all passing, covering edge cases like git command failures, permission errors, and empty directories). The data structures are right. The separation of concerns is right. The safety model (dry-run default, fail-closed PR checks, never-delete-current-branch) is right.

The `*.egg-info` in `_SKIP_DIRS` is a bug (it'll never match anything). The `branch_retention_days` config field is dead code. The CHANGELOG wasn't updated despite the task claiming it was. These are real but minor issues — none of them affect correctness of the core functionality.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/cleanup.py]: `_SKIP_DIRS` contains `"*.egg-info"` which is a glob pattern, not a literal directory name — this entry will never match in the `os.walk` filter and is dead code. Should be a concrete pattern like checking `.endswith(".egg-info")`.
- [src/colonyos/cleanup.py]: `branch_retention_days` config field is defined, parsed, validated, and persisted but never consumed by any functional code path. Dead configuration for a feature that doesn't exist yet.
- [CHANGELOG.md]: Task 8.4 is marked complete ("Update CHANGELOG.md") but no CHANGELOG changes appear in the diff.

SYNTHESIS:
This is a clean, well-structured implementation. The data types are clear, the module boundaries are correct, the safety invariants (dry-run default, fail-closed PR checks, never-delete-current/default-branch) are properly enforced and tested. 169 new tests all pass, and the existing 918 tests show no regressions. The code follows established project patterns (standalone module called from CLI, Rich tables for output, config dataclasses with defaults). The three findings are minor — a dead skip pattern, a premature config field, and a missing CHANGELOG entry. None compromise correctness or safety. Ship it.
