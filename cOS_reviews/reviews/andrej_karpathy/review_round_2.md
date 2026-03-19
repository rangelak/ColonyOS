# Review: `colonyos cleanup` — Andrej Karpathy (Round 2)

## Completeness

- [x] FR-1: `cleanup` command group with three subcommands (`branches`, `artifacts`, `scan`)
- [x] FR-2: `colonyos cleanup` with no subcommand prints help
- [x] FR-3: Lists local branches fully merged into default branch
- [x] FR-4: Filters by `branch_prefix`, supports `--all-branches`
- [x] FR-5: Rich-formatted table with name, last commit date, merge status
- [x] FR-6: Default dry-run, `--execute` to act
- [x] FR-7: `--include-remote` flag for remote pruning
- [x] FR-8: Never deletes current or default branch
- [x] FR-9: Checks for open PRs via `check_open_pr`
- [x] FR-10: Prints summary with counts and reasons
- [x] FR-11: Scans `.colonyos/runs/` for old artifacts
- [x] FR-12: Table with run ID, date, status, size
- [x] FR-13: Dry-run default, `--execute` to delete
- [x] FR-14: `--retention-days N` override
- [x] FR-15: Never deletes RUNNING runs
- [x] FR-16: Summary with count and MB reclaimed
- [x] FR-17: Static analysis for line counts, function counts, thresholds
- [x] FR-18: Rich table sorted by severity with complexity categories
- [x] FR-19: `--ai` flag for AI-powered scan using `run_phase` machinery
- [x] FR-20: AI scan output saved to `.colonyos/runs/cleanup_<timestamp>.md`
- [x] FR-21: `--refactor FILE` delegates to `colonyos run`
- [x] FR-22: `CleanupConfig` dataclass wired into `ColonyConfig`
- [x] FR-23: CLI flags override config values
- [x] FR-24: JSON audit log for all operations
- [x] FR-25: Cleanup logs prefixed `cleanup_` are skipped by artifact cleanup
- [x] FR-26: AI scan uses `cleanup_scan.md` instruction template with base constraints
- [x] FR-27: Instruction template explicitly forbids modifying auth/secrets files

## Quality Assessment

### What's done well

**Clean separation of deterministic vs. stochastic operations.** This is exactly right. Branch pruning and artifact deletion are pure `subprocess`/`pathlib` operations with zero LLM budget cost. The AI scan is gated behind `--ai` and uses the existing `run_phase` machinery with proper budget constraints. This is the correct architecture.

**Structured data types throughout.** `BranchInfo`, `ArtifactInfo`, `FileComplexity`, and their result containers are frozen dataclasses. This makes the code testable and composable. The audit log serialization is clean.

**Function-level regex patterns per language.** The `_FUNCTION_PATTERNS` dict with per-extension compiled regexes is a reasonable v1 approach. It's not a real AST parser, but the PRD explicitly says "no complexity scoring/grading" — raw metrics are sufficient.

**Prompt synthesis for `--refactor`.** The `synthesize_refactor_prompt()` function constructs a focused, actionable prompt with specific guidance based on scan results. This is treating prompts as structured programs rather than ad-hoc strings.

### Issues

1. **Minor: Rich markup nesting bug in `cli.py` scan display.** Line 2409 has a logic issue in category style rendering — when `cat_style` starts with `[` (like `[bold yellow]`), the string interpolation creates double-nested brackets `[[bold yellow]]`. This will render incorrectly in Rich. The `"large": "yellow"` case works fine, but the `"very-large"` and `"massive"` cases will look wrong.

2. **Minor: `_get_branch_last_commit_date` results not shown in table.** The branch cleanup table (line 2226) shows empty string for `Last Commit` on deleted branches. The date is available from the `BranchInfo` objects but `delete_branches()` returns only branch names in `deleted_local`, losing the date metadata. Consider returning full `BranchInfo` objects or looking them up.

3. **Observation: AI scan reuses `Phase.REVIEW` enum.** The AI scan in `cli.py:2451` uses `Phase.REVIEW` to invoke `run_phase_sync`. This is pragmatic — it gets the right model via `config.get_model(Phase.REVIEW)` — but semantically it's a scan, not a review. A dedicated `Phase.SCAN` would be cleaner but isn't worth blocking on for v1.

4. **Observation: No `--ai` tests in the test suite.** The AI scan path (lines 2432-2473 in cli.py) is not covered by tests. This is understandable since it involves calling the real agent, but a mock-based test verifying the prompt construction and report saving would be valuable.

## Safety

- [x] No secrets or credentials in committed code
- [x] No destructive operations without `--execute` safeguard
- [x] Error handling present for subprocess failures, file I/O, and JSON parsing
- [x] Cleanup logs are self-protecting (prefixed with `cleanup_` and explicitly skipped)
- [x] AI scan instruction template forbids modifying auth/secrets files
- [x] `check_open_pr` prevents deleting branches with active PRs

## Test Results

All 62 tests pass (0.25s). Coverage is comprehensive across config parsing, branch listing/safety/deletion, artifact listing/deletion, structural scanning, prompt synthesis, and audit logging. CLI integration tests cover all subcommands in both empty and populated scenarios.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/cli.py:2409]: Rich markup double-nesting bug for `very-large` and `massive` category display — `[bold yellow]` style is wrapped in additional brackets, producing `[[bold yellow]]` which won't render correctly
- [src/colonyos/cli.py:2226]: Branch last-commit-date metadata is lost in display table because `deleted_local` contains only branch names, not full `BranchInfo` objects
- [src/colonyos/cli.py:2432-2473]: AI scan path (`--ai` flag) has no test coverage — a mock-based test would prevent regressions
- [src/colonyos/cli.py:2451]: AI scan uses `Phase.REVIEW` enum which is semantically imprecise but functionally correct for v1

SYNTHESIS:
This is a well-architected implementation that correctly separates deterministic git/filesystem operations from stochastic LLM-powered analysis. The key design decision — making branch pruning and artifact cleanup zero-budget operations while gating AI analysis behind an explicit `--ai` flag — is exactly right. The code treats prompts with appropriate rigor: `cleanup_scan.md` is a structured instruction template with explicit constraints, and `synthesize_refactor_prompt()` constructs targeted prompts from scan metrics rather than vague instructions. The dry-run-by-default pattern with `--execute` opt-in is the correct safety posture for destructive operations. The two minor bugs (Rich markup nesting, lost date metadata in display) are cosmetic and don't affect correctness. The missing test coverage for the `--ai` path is the only notable gap, but since it delegates to the existing `run_phase` machinery which is tested elsewhere, the risk is contained. Ship it.
