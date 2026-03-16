# Deliver Phase Instructions

You are opening a pull request for the work on branch `{branch_name}`.

## Context

- **PRD**: `{prd_path}`
- **Branch**: `{branch_name}`
- **Target**: The repository's default branch (usually `main` or `master`)

## Process

### Step 1: Ensure Everything is Committed

Check `git status`. If there are uncommitted changes, commit them with a descriptive message.

### Step 2: Push the Branch

```bash
git push -u origin {branch_name}
```

### Step 3: Open the Pull Request

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

### Step 4: Report the PR URL

Output the PR URL so it can be recorded in the run log.

## Rules

- Never force-push
- Never target a branch other than the default branch
- The PR title should describe the feature, not the implementation details
- The PR body should be useful to a reviewer who hasn't seen the PRD
