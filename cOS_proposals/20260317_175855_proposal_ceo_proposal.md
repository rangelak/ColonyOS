Now I have a comprehensive understanding of the project. Let me formulate my proposal.

## Proposal: Standalone Review Command (`colonyos review <branch>`)

### Rationale
ColonyOS has a powerful multi-persona parallel review pipeline with an iterative fix loop, but it's locked inside the full plan→implement→review→deliver flow. Users can't leverage this review capability independently — for example, to review human-written code, code from other AI tools, or PRs from teammates. Adding a standalone `colonyos review` command unlocks the project's highest-quality subsystem as an independently useful tool, dramatically expanding the addressable use cases and providing a low-commitment entry point for new users who aren't ready to hand over the full pipeline.

### Feature Request
Add a `colonyos review <branch>` command that runs only the review/fix loop and optional decision gate on any existing branch, without requiring a prior ColonyOS run or PRD.

**Specific requirements:**

1. **New CLI command**: `colonyos review <branch>` — accepts a branch name as a positional argument. Runs the parallel per-persona review, fix loop (if `--fix` flag is passed), and decision gate against the diff between `<branch>` and the base branch (main/master). Supports the existing `-v/--verbose` and `-q/--quiet` flags.

2. **Optional PRD reference**: `colonyos review <branch> --prd <path>` — when provided, reviewers assess the implementation against the PRD (same as in the full pipeline). When omitted, reviewers assess the diff on its own merits using the branch's commit messages and changed files as context.

3. **Optional fix loop**: `colonyos review <branch> --fix` — when provided, runs the fix agent when reviewers request changes, then re-reviews (using the existing `max_fix_iterations` config). Without `--fix`, the command is read-only and just produces review artifacts.

4. **PRD-less review prompt**: Add a new instruction template `src/colonyos/instructions/review_standalone.md` that instructs the reviewer to assess a branch diff without a PRD. It should tell the reviewer to: read all changed files on the branch vs. the base, assess code quality, correctness, test coverage, and potential issues from their persona's perspective, and produce a structured verdict (same `VERDICT: approve` or `VERDICT: request-changes` format).

5. **Base branch detection**: Auto-detect the base branch by checking for `main`, then `master`, then falling back to `HEAD~1`. Allow override with `--base <branch>`.

6. **Review artifacts**: Save review files to `cOS_reviews/` using the existing `_save_review_artifact` pattern, with filenames like `review_standalone_{branch_slug}_round{N}_{persona_slug}.md`. Save the decision gate output as `decision_standalone_{branch_slug}.md`.

7. **Run logging**: Create a run log entry with a `review-` prefix run ID (e.g., `review-20260317-abc1234567`). Log the review and optional fix/decision phases. The status command should show these alongside regular runs.

8. **Exit code**: Exit 0 if all reviewers approve (or decision gate says GO), exit 1 if any reviewer requests changes (or decision gate says NO-GO). This makes the command usable in CI pipelines.

9. **Tests**: Add unit tests for: CLI argument parsing (branch, --prd, --fix, --base flags), base branch detection logic, PRD-less review prompt construction, review artifact naming, and exit code behavior based on verdicts.

**Acceptance criteria:**
- `colonyos review my-feature-branch` runs parallel persona reviews on the branch diff and saves review artifacts
- `colonyos review my-feature-branch --prd cOS_prds/xxx.md` reviews against a specific PRD
- `colonyos review my-feature-branch --fix` enables the fix loop when reviewers request changes
- `colonyos review my-feature-branch --base develop` overrides the base branch
- Review artifacts are saved to `cOS_reviews/` with `standalone` in the filename
- A run log entry is created and visible in `colonyos status`
- Exit code 0 on approval, 1 on request-changes / NO-GO
- All existing tests continue to pass
- New tests cover argument parsing, base branch detection, prompt construction, artifact naming, and exit codes
