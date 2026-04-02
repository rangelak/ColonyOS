# Deliver Phase Instructions

You are opening a pull request for the work on branch `{branch_name}`.

## Context

- **PRD**: `{prd_path}`
- **Branch**: `{branch_name}`
- **Target**: The repository's default branch (usually `main` or `master`)

## Process

### Step 1: Ensure Everything is Committed

Check `git status`. If there are uncommitted changes, commit them with a descriptive message.

If `git commit` fails because pre-commit hooks report lint, type-check, or test failures:
1. Read the hook output carefully and identify every reported issue
2. Fix the reported problems in code or tests as appropriate
3. Re-run the relevant commands yourself to confirm the failures are resolved
4. Retry `git commit`
5. Repeat until the commit succeeds or you hit an environmental/tooling failure you cannot fix from the repository

### Step 2: Update the Changelog

Read `CHANGELOG.md` in the project root. Add a new entry at the **top** (immediately after the `# Changelog` heading) with:

- A timestamp heading: `## YYYYMMDD_HHMMSS — [Feature Title]`
- 1–2 sentence summary of what was built
- List of key files created or modified
- Links to the PRD and task files

Use the current UTC time for the timestamp. Keep the entry concise — match the style of existing entries.

### Step 3: Push the Branch

```bash
git push -u origin {branch_name}
```

### Step 4: Open the Pull Request

Use `gh pr create` with:

- **Title**: A concise description of the feature
- **Body**: Include:
  - Summary of what was implemented (2-3 bullet points)
  - Link to the PRD file
  - Test plan / verification steps
  - Any open questions or follow-ups

```bash
gh pr create --title "..." --body "..."
```

### Step 5: Report the PR URL

Output the PR URL so it can be recorded in the run log.

## Rules

- Never force-push
- Never target a branch other than the default branch
- The PR title should describe the feature, not the implementation details
- The PR body should be useful to a reviewer who hasn't seen the PRD
- Do not stop after the first failed `git commit` if the failure came from fixable pre-commit hook output
