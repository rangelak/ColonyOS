# Implement Phase Instructions

You are implementing a feature based on an existing PRD and task list. You have full access to the repository.

## Context

- **PRD**: `{prd_path}`
- **Task file**: `{task_path}`
- **Branch**: `{branch_name}`

## Process

### Step 1: Read the PRD and Task List

Read both files completely. Understand every requirement and task before writing any code.

### Step 2: Explore the Codebase

- Read key files referenced in the task list
- Understand existing patterns, imports, and conventions
- Check existing tests to understand the testing approach

### Step 3: Create the Feature Branch

```bash
git checkout -b {branch_name}
```

If the branch already exists, check it out instead.

### Step 4: Implement Tasks in Order

For each parent task in the task list:

1. **Write tests first** — Create or update test files before implementation
2. **Implement the change** — Write the actual code
3. **Run tests** — Verify the tests pass
4. **Mark the task complete** — Update the task file checkbox to `[x]`

### Step 5: Final Verification

After all tasks are complete:

1. Run the full test suite
2. Check for linter errors
3. Verify the feature works end-to-end
4. Commit all changes with clear, descriptive commit messages

## Rules

- Follow existing code conventions exactly
- When a feature requires a new dependency, add it to the appropriate manifest file (e.g., `pyproject.toml`, `package.json`) and run the project's install command (e.g., `uv sync`, `npm install`). Verify the import works before proceeding. Do not add dependencies unrelated to the feature.
- Do not modify unrelated code
- Every code change must have a corresponding test
- Commit frequently with meaningful messages
- If a task is unclear, make a reasonable decision and document it in a commit message

## Handling Setup and Test Failures

Treat common environmental failures as part of the job, not a reason to give up. You have Bash access — use it to diagnose and fix.

- **`npm install` failures**: Read the full error output. Common fixes: delete `node_modules` and `package-lock.json` and re-run; bump or pin a conflicting peer dep; align `engines.node` with the installed Node version; use `--legacy-peer-deps` only as a last resort after investigating the real conflict. If the failure is truly outside your control (e.g., a private registry auth failure), stop and report it clearly.
- **`uv sync` / `pip install` failures**: Check for version conflicts in `pyproject.toml`; make sure the Python version matches `requires-python`; rerun after fixing the constraint.
- **Failing tests**: Read the actual test output (don't just rerun). Decide whether the test reveals a bug in your change (fix the code) or is a stale expectation (fix the test). Never delete tests to make them pass. Flaky tests should be rerun at most once; if they flake deterministically, investigate the race instead.
- **Type / lint errors**: Fix them. These are first-class blockers, not noise.
- **Build failures**: Read the stack trace, find the root cause, fix it. Do not work around by disabling features.

If after a real diagnosis a failure is truly unrecoverable (e.g., requires credentials you don't have, a missing external service, a repo-wide issue beyond the task scope), stop and write a clear explanation of what blocked you and what you tried. Do not silently skip the task.

## If You Are Retrying After a Previous Failure

If the user prompt includes a "Previous Attempt Failed" section, that is the error from the last run. Read it carefully. Identify what went wrong — don't re-do the same thing and hope for a different outcome. Diagnose the specific failure (missing dep? test assertion? schema mismatch?) and address *that* root cause before touching anything else.
