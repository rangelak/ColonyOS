# Implement Parallel Phase Instructions

You are implementing a **single task** as part of a parallel implementation. Other agents are working on other tasks concurrently in their own worktrees.

## Context

- **Task ID**: `{task_id}`
- **Task description**: {task_description}
- **Worktree path**: `{worktree_path}`
- **PRD**: `{prd_path}`
- **Task file**: `{task_file}`
- **Base branch**: `{base_branch}`

## Constraints

1. **Scope**: Only implement the changes for task `{task_id}`. Do not modify files unrelated to this task.
2. **Isolation**: You are working in an isolated git worktree. Do not worry about other tasks; they are being handled by other agents.
3. **No dependencies**: All tasks you depend on have already been completed. Build on top of that work.

## Process

### Step 1: Read the PRD and Task List

Read `{prd_path}` to understand the overall feature requirements.
Read `{task_file}` to understand the full task list and find your specific task.

### Step 2: Understand Your Task

Find task `{task_id}` in the task list. Understand:
- What needs to be implemented
- Which files will likely be affected
- How this task fits into the overall feature

### Step 3: Explore the Codebase

Before writing any code:
- Read key files referenced in the task
- Understand existing patterns, imports, and conventions
- Check existing tests to understand the testing approach

### Step 4: Write Tests First

Create or update test files before implementing the actual code. Tests should:
- Cover the expected behavior of your changes
- Follow existing test patterns in the codebase
- Be runnable independently

### Step 5: Implement the Change

Write the actual implementation code. Follow:
- Existing code conventions exactly
- The project's style guide
- Patterns established in similar files

### Step 6: Verify

After implementing:
1. Run the tests for the files you modified
2. Ensure tests pass
3. Check for linter errors if a linter is configured

### Step 7: Commit

Make a single commit with a clear, descriptive message:
- Start with a verb (Add, Update, Fix, etc.)
- Reference the task ID in the message
- Keep the message concise but descriptive

Example: `Add rate limiting middleware (task {task_id})`

## Rules

- Do NOT create a PR - that will be handled after all tasks complete
- Do NOT push to the remote - that will be handled by the orchestrator
- Do NOT modify code unrelated to your task
- Do NOT implement tasks that are not {task_id}
- ALWAYS write tests for new functionality
- ALWAYS follow existing code conventions
