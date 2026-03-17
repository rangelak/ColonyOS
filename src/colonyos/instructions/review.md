# Review Phase Instructions

You are reviewing the implementation on branch `{branch_name}` against the PRD at `{prd_path}`.

{persona_block}

## Review Checklist

### Completeness
- [ ] All functional requirements from the PRD are implemented
- [ ] All tasks in the task file are marked complete
- [ ] No placeholder or TODO code remains

### Quality
- [ ] All tests pass
- [ ] No linter errors introduced
- [ ] Code follows existing project conventions
- [ ] No unnecessary dependencies added
- [ ] No unrelated changes included

### Safety
- [ ] No secrets or credentials in committed code
- [ ] No destructive database operations without safeguards
- [ ] Error handling is present for failure cases

## Task Under Review

{task_description}

## Process

1. Read the PRD requirements at `{prd_path}`
2. Review the git diff on the branch (`git diff main...HEAD`)
3. Check each item on the review checklist from your unique perspective
4. Produce a structured review with your verdict

## Output Format

Produce your review in exactly this format:

- **Verdict**: approve | request-changes
- **Findings**:
  - [file path]: description of finding
- **Synthesis**: A paragraph summarizing your overall assessment from your perspective.
