# Plan Phase Instructions

You are generating a Product Requirements Document (PRD) and implementation task list for a feature request. You have full access to the repository.

## Process

### Step 1: Understand the Codebase

Before generating any planning artifacts, explore the repository:
- Read the README and any setup docs
- Understand the directory structure and key modules
- Identify the tech stack, frameworks, and patterns in use
- Note existing tests and how they're structured

### Step 2: Generate Clarifying Questions & Persona Q&A

Generate 6-10 clarifying questions about the feature request. Consider:

- **Problem/Goal**: What problem does this solve?
- **Scope**: What's in and out of scope?
- **Technical Fit**: How does this fit with the existing architecture?
- **User Impact**: Who benefits and how?
- **Risk**: What could go wrong?

{personas_block}

**IMPORTANT**: When persona subagents are available, call ALL of them IN PARALLEL using the Agent tool. Pass the full list of clarifying questions to each persona. Do NOT call them one at a time — invoke all Agent tools in a single response so they execute concurrently.

### Step 3: Write the PRD

Based on the codebase analysis and Q&A, write a PRD with these sections:

1. **Introduction/Overview** — What the feature is and why it matters
2. **Goals** — Specific, measurable objectives
3. **User Stories** — Narratives describing usage
4. **Functional Requirements** — Numbered list of what the feature must do
5. **Non-Goals** — What's explicitly out of scope
6. **Technical Considerations** — How this fits with existing code, dependencies, constraints
7. **Success Metrics** — How we measure success
8. **Open Questions** — Anything unresolved

The PRD must reference actual files, modules, and patterns from this repository. Generic PRDs are useless.

Save the PRD to: `{prds_dir}/{prd_filename}`

### Step 4: Generate Task List

Break the PRD into implementation tasks:

1. Generate 4-8 high-level parent tasks
2. Break each into actionable sub-tasks
3. For every code-change task, the first sub-task must be writing/updating tests
4. List all relevant files (existing files to modify and new files to create)

Save the task file to: `{tasks_dir}/{task_filename}`

### Output Format for Task File

```markdown
## Relevant Files

- `path/to/file.py` - Why this file is relevant
- `path/to/file_test.py` - Tests for file.py

## Tasks

- [ ] 1.0 Parent Task Title
  - [ ] 1.1 Write/update tests for ...
  - [ ] 1.2 Implement ...
- [ ] 2.0 Parent Task Title
  - [ ] 2.1 Write/update tests for ...
  - [ ] 2.2 Implement ...
```
