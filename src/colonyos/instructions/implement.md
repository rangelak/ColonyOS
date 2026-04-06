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
