Now I have a comprehensive understanding of the project. Let me synthesize my findings and produce the proposal.

---

## Proposal: Standalone `colonyos review <branch>` Command

### Rationale
ColonyOS has a powerful parallel multi-persona review infrastructure (concurrent reviewer agents, fix loop, decision gate), but it's only accessible as part of the full pipeline. A standalone review command would make ColonyOS useful for reviewing *any* branch — human-written code, Dependabot PRs, code from other AI tools — dramatically expanding the tool's utility beyond its own pipeline. This feature was previously attempted and reverted (artifacts remain in `cOS_reviews/` and `cOS_prds/`), and the existing PRD at `cOS_prds/20260317_180029_prd_add_a_colonyos_review_branch_command...` provides a solid foundation. With all the review infrastructure already built, this is high-impact, low-risk, and well-scoped.

### Feature Request
Add a `colonyos review <branch>` CLI command that runs only the review/fix loop and optional decision gate against an arbitrary Git branch, without requiring a PRD or running the full pipeline. This enables ColonyOS to function as a standalone multi-persona code review tool.

**Specific requirements:**

1. **New CLI command**: `colonyos review <branch>` where `<branch>` is the Git branch to review. The command should accept `--base <branch>` (default: `main`) to specify the comparison base, `-v/--verbose` and `-q/--quiet` flags (matching existing commands), and `--no-fix` to skip the fix loop and only produce review artifacts.

2. **Branch validation**: Before running, verify the target branch exists locally (using `git branch --list`). If not found, print a helpful error suggesting `git fetch` or `git checkout`. Also verify the base branch exists.

3. **Diff-aware review prompt**: Build a review prompt that includes the `git diff <base>...<branch>` output (or a summary if the diff exceeds a size limit, e.g., 10,000 chars). The review instruction should tell each persona to focus on the changes in this diff rather than reviewing the entire codebase. Create a new instruction template `src/colonyos/instructions/review_standalone.md` for this purpose.

4. **Parallel persona reviews**: Reuse the existing `_reviewer_personas()`, `_build_persona_review_prompt()` (or a new standalone variant), and `run_phases_parallel_sync()` infrastructure. Each reviewer persona runs concurrently with read-only codebase access, producing a VERDICT (approve/request-changes) and structured findings, exactly as in the pipeline review phase.

5. **Optional fix loop**: Unless `--no-fix` is passed, if any reviewer requests changes, run the existing fix agent loop (up to `max_fix_iterations` from config) followed by re-review, exactly as the pipeline does. The fix agent should work on the target branch.

6. **Review artifacts**: Save all review artifacts to `{reviews_dir}/` with filenames like `review_standalone_{branch_slug}_round{N}_{persona_slug}.md`. Also save a summary file `review_standalone_{branch_slug}_summary.md` listing all verdicts and key findings.

7. **Decision gate**: After reviews complete, optionally run the decision gate (controlled by `--decide` flag, default off for standalone reviews) to produce a GO/NO-GO verdict.

8. **No RunLog integration**: Since this isn't a full pipeline run, don't create a RunLog entry. Just track cost via the phase results and print a cost summary at the end.

9. **Exit codes**: Exit 0 if all reviewers approve, exit 1 if any reviewer requests changes (after fix loop exhaustion). This enables CI integration: `colonyos review feature-branch || echo "Review failed"`.

10. **Budget enforcement**: Use the existing `per_phase` budget for each reviewer session and the `per_run` budget as the total cap for the entire review command.

11. **Tests**: Add tests for: branch validation, diff extraction and truncation, standalone review prompt building, parallel review execution (mocked), fix loop integration, artifact saving with correct filenames, exit code logic, `--no-fix` flag behavior, and `--base` flag handling.

**Acceptance criteria:**
- `colonyos review my-feature-branch` runs parallel persona reviews against the branch
- Review artifacts are saved to the configured reviews directory
- `--no-fix` skips the fix loop
- `--base develop` changes the comparison base from `main`
- Exit code 0 when all approve, 1 when changes requested
- Budget is enforced across all review sessions
- All existing tests continue to pass
- New tests cover branch validation, prompt building, parallel execution, artifact saving, and exit codes
