# Review Phase Instructions

You are reviewing the implementation on branch `{branch_name}` against the PRD at `{prd_path}`.

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

## Process

1. Read the PRD requirements
2. Review the git diff on the branch (`git diff main...HEAD`)
3. Run the test suite
4. Check each item on the review checklist
5. If issues are found, fix them directly and commit

## Output

After review, provide a summary:
- Requirements met: X/Y
- Tests: pass/fail
- Issues found and fixed: list
- Remaining concerns: list (if any)
