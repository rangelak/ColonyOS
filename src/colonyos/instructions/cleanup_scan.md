# Cleanup Scan — AI Structural Analysis

You are performing a structural analysis of the codebase. Your task is to identify code quality issues, dead code, naming inconsistencies, and architectural improvements.

## Constraints

- **DO NOT modify any files.** This is an analysis-only task.
- **DO NOT create any commits.**
- **DO NOT touch files related to authentication, authorization, secrets, or input sanitization.**
- Output a structured markdown report only.

## Analysis Scope

Focus on these areas:

### 1. Dead Code Detection
- Unused imports
- Unreachable code paths
- Functions/methods that are never called
- Commented-out code blocks

### 2. Naming & Consistency
- Inconsistent naming conventions (camelCase vs snake_case mixing)
- Misleading variable/function names
- Unclear abbreviations

### 3. Architectural Suggestions
- Files that are too large and should be split
- Functions doing too many things (low cohesion)
- Tight coupling between modules
- Missing abstraction layers
- Duplicated logic that should be extracted

### 4. Code Quality
- Missing error handling
- Bare except clauses
- Magic numbers/strings that should be constants
- Missing type hints (in Python codebases)

## Scoring

For each finding, assign:
- **Impact** (1-5): How much would fixing this improve the codebase?
- **Risk** (1-5): How risky is the current state? (5 = likely to cause bugs)

## Output Format

Write a markdown report with this structure:

```markdown
# Structural Analysis Report

## Summary
- Total findings: N
- Critical (impact >= 4): N
- Files analyzed: N

## Findings

### 1. [Category] Brief description
- **File:** `path/to/file.py`
- **Impact:** N/5
- **Risk:** N/5
- **Details:** Description of the issue and suggested improvement.

### 2. [Category] ...
(repeat for each finding)

## Prioritized Action List

1. Highest priority action
2. ...
```

Sort findings by impact * risk score descending.
