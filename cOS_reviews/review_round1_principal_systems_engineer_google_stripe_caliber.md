# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 1)

Here is my complete review:

---

## Review: Standalone `colonyos review <branch>` Command

### Systematic FR Assessment

I verified all 32 functional requirements from the PRD against the implementation:

- **FR-1 through FR-6** (CLI registration, arguments, options): ✅ All present in `cli.py` lines 323-330
- **FR-7 through FR-9** (Branch validation): ✅ `_validate_branch_exists()` validates local existence and rejects remote-style refs
- **FR-10 through FR-13** (Diff-aware review prompt): ✅ Template created, prompt builder works, 10k char truncation implemented, no PRD references
- **FR-14 through FR-17** (Parallel persona reviews): ✅ Reuses `_reviewer_personas()`, `run_phases_parallel_sync()`, correct tools, correct output format
- **FR-18 through FR-21** (Fix loop): ✅ Runs unless `--no-fix`, standalone fix prompt, write tools for fix agent, re-review after fix
- **FR-22 through FR-24** (Artifacts): ✅ Correct filenames with branch slug, summary file, decision artifact
- **FR-25** (Decision gate): ✅ Runs when `--decide` passed
- **FR-26 through FR-29** (Output/exit codes): ✅ Summary table printed, exit 0/1 logic correct for both review and decision modes
- **FR-30 through FR-31** (Budget): ✅ Per-phase and per-run guards present
- **FR-32** (No RunLog): ✅ No RunLog created

### Tests

All 358 tests pass. The new `test_standalone_review.py` (899 lines) provides comprehensive coverage across 10 test classes covering: branch validation, diff extraction, prompt building, orchestration, parallel execution, artifact filenames, summary printing, CLI flags, exit codes, budget enforcement, and fix failure edge cases.

### Findings

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py:840-844]: `subprocess.run` in `_validate_branch_exists()` has no timeout. If git hangs (corrupted repo, NFS stall), this blocks the process indefinitely. Same issue in `_get_branch_diff()` at line 864. Add `timeout=30` to both calls. This is a 3am-page-you-awake problem.
- [src/colonyos/orchestrator.py:870-872]: `_get_branch_diff` silently swallows git errors (only catches OSError, ignores non-zero return codes and stderr). If the merge base is invalid, the reviewer gets `(empty diff)` with no diagnostic. Consider logging stderr when `result.returncode != 0`.
- [src/colonyos/orchestrator.py:1145-1148]: Summary artifact persona-matching uses `len(phase_results) // len(reviewers)` which includes FIX/DECISION results in the count, then filters to only REVIEW results for the zip. This works today because `zip` truncates to the shorter list, but it's fragile — a refactor that changes the result structure could silently misalign personas with verdicts. Consider computing the multiplier from the filtered list length instead.
- [PRD inconsistency]: The persona consensus table states "Fix loop default: Review-only, `--fix` opt-in (7/7)" but FR-5 specifies fix-by-default with `--no-fix` to disable. The implementation follows FR-5 (fix runs by default). This is a documentation inconsistency in the PRD, not a code bug, but worth noting for future reference.

SYNTHESIS:
This is a clean, well-structured implementation that correctly extends the orchestrator without disrupting the existing pipeline. The architectural choice to reuse `_reviewer_personas()`, `run_phases_parallel_sync()`, `_collect_review_findings()`, and `_save_review_artifact()` is exactly right — it avoids duplication while keeping the standalone path decoupled via its own prompt builders and instruction templates. The new instruction templates are appropriately PRD-free. Budget enforcement follows the established guard pattern. Test coverage is thorough with 899 lines of tests covering all code paths including edge cases (fix failure, budget exhaustion, empty diff, no reviewers). The three subprocess timeout findings are non-blocking for initial ship but should be addressed before this sees CI/production use, as they represent unbounded blocking on external processes — the classic "works fine until it doesn't" reliability gap.