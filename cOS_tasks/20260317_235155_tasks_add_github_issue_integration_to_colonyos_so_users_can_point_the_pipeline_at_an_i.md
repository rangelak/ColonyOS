# Tasks: GitHub Issue Integration for ColonyOS

## Relevant Files

- `src/colonyos/github.py` - **New file**: GitHub issue fetching, parsing, and formatting module
- `tests/test_github.py` - **New file**: Tests for the github module
- `src/colonyos/models.py` - Add `source_issue` and `source_issue_url` fields to `RunLog`
- `tests/test_models.py` - Update tests for RunLog serialization with new fields
- `src/colonyos/cli.py` - Add `--issue` flag to `run` command, update `status` display
- `tests/test_cli.py` - Tests for `--issue` flag validation and status display
- `src/colonyos/orchestrator.py` - Update `_build_plan_prompt`, `_build_deliver_prompt`, `_build_ceo_prompt`, `_save_run_log`, `_load_run_log`, and `run()` to thread `source_issue` through the pipeline
- `tests/test_orchestrator.py` - Tests for issue-aware prompt building and run log persistence
- `tests/test_ceo.py` - Tests for CEO prompt with open issues context
- `src/colonyos/instructions/deliver.md` - No changes needed (deliver prompt is built dynamically in orchestrator.py)

## Tasks

- [x] 1.0 Create GitHub issue fetching module (`src/colonyos/github.py`)
  - [x] 1.1 Write tests for `parse_issue_ref()` — bare integers, full URLs, invalid formats, edge cases (negative numbers, non-numeric, malformed URLs)
  - [x] 1.2 Write tests for `fetch_issue()` — mock `subprocess.run` for success, issue not found, auth failure, timeout, closed issue warning
  - [x] 1.3 Write tests for `format_issue_as_prompt()` — issue with body only, issue with comments, comment truncation at 8K chars, label formatting, closed issue warning text
  - [x] 1.4 Write tests for `fetch_open_issues()` — mock `subprocess.run` for success, empty list, `gh` failure (should return empty list, not raise)
  - [x] 1.5 Implement `GitHubIssue` dataclass with fields: `number`, `title`, `body`, `labels`, `comments`, `state`, `url`
  - [x] 1.6 Implement `parse_issue_ref(ref: str) -> int` — extract issue number from integer string or GitHub URL via regex
  - [x] 1.7 Implement `fetch_issue(issue_ref: str | int, repo_root: Path) -> GitHubIssue` — call `gh issue view <N> --json number,title,body,labels,comments,state,url`, parse JSON, return dataclass. Fail fast with `click.ClickException` on errors. Warn on closed issues.
  - [x] 1.8 Implement `format_issue_as_prompt(issue: GitHubIssue) -> str` — build structured prompt with title, body, labels, and truncated comments (first 5, max 8K chars) wrapped in `<github_issue>` delimiters
  - [x] 1.9 Implement `fetch_open_issues(repo_root: Path, limit: int = 20) -> list[GitHubIssue]` — call `gh issue list --json number,title,labels,state --limit N`, return list. Catch all errors and return empty list (non-blocking).

- [x] 2.0 Add `source_issue` fields to `RunLog` model
  - [x] 2.1 Write tests for `RunLog` serialization/deserialization with `source_issue` and `source_issue_url` fields (both present and `None`)
  - [x] 2.2 Add `source_issue: int | None = None` and `source_issue_url: str | None = None` fields to `RunLog` dataclass in `models.py`

- [x] 3.0 Update orchestrator to thread `source_issue` through pipeline
  - [x] 3.1 Write tests for `_build_plan_prompt` with `source_issue` — verify system prompt contains issue number and URL, verify user prompt wrapping
  - [x] 3.2 Write tests for `_build_deliver_prompt` with `source_issue` — verify system prompt contains `Closes #N` instruction
  - [x] 3.3 Write tests for `_build_ceo_prompt` with open issues injection — verify user prompt contains `## Open Issues` section
  - [x] 3.4 Write tests for `_save_run_log` and `_load_run_log` with `source_issue` fields
  - [x] 3.5 Update `_build_plan_prompt` signature to accept optional `source_issue: int | None` and `source_issue_url: str | None`. When present, append issue reference to system prompt and wrap user prompt in `<github_issue>` delimiters with preamble.
  - [x] 3.6 Update `_build_deliver_prompt` signature to accept optional `source_issue: int | None`. When present, append `Closes #N` instruction to system prompt.
  - [x] 3.7 Update `_build_ceo_prompt` to call `fetch_open_issues()` and inject results into user prompt as `## Open Issues` section after changelog. Wrap in try/except so failures are non-blocking.
  - [x] 3.8 Update `_save_run_log` to persist `source_issue` and `source_issue_url` in JSON output
  - [x] 3.9 Update `_load_run_log` to restore `source_issue` and `source_issue_url` from JSON (using `.get()` with `None` defaults for backward compatibility)
  - [x] 3.10 Update `run()` function signature to accept `source_issue: int | None = None` and `source_issue_url: str | None = None`. Thread these through to `RunLog`, `_build_plan_prompt`, and `_build_deliver_prompt`.

- [x] 4.0 Add `--issue` flag to CLI `run` command
  - [x] 4.1 Write tests for `--issue` flag: bare number, full URL, mutual exclusivity with `--from-prd` and `--resume`, composability with positional `prompt` argument, missing `--issue` and no prompt error
  - [x] 4.2 Add `--issue` option to `run` command in `cli.py` with `type=str, default=None`
  - [x] 4.3 Implement validation: `--issue` is mutually exclusive with `--from-prd` and `--resume`
  - [x] 4.4 Implement issue fetching flow: call `parse_issue_ref()`, `fetch_issue()`, `format_issue_as_prompt()`. If positional `prompt` is also provided, append it as `## Additional Context`.
  - [x] 4.5 Pass `source_issue` and `source_issue_url` through to `run_orchestrator()`

- [x] 5.0 Update `colonyos status` to display source issue
  - [x] 5.1 Write tests for status output with `source_issue_url` present in run log JSON
  - [x] 5.2 Update status command to read `source_issue` and `source_issue_url` from run log data and display before prompt preview (format: `#42 https://...`)

- [x] 6.0 CEO open issues integration
  - [x] 6.1 Write tests for CEO prompt with open issues (mock `fetch_open_issues` returning issues, returning empty list, raising exception)
  - [x] 6.2 Update `_build_ceo_prompt` to inject open issues context into user prompt
  - [x] 6.3 Update CEO instruction text to mention open issues consideration: "Consider these open issues as candidates. You may cite one with `Issue: #N` in your proposal, or propose a novel feature."

- [x] 7.0 End-to-end integration validation
  - [x] 7.1 Write integration test: `colonyos run --issue 42` with mocked `gh` and mocked `run_orchestrator` — verify full data flow from CLI flag to orchestrator call with correct `source_issue` fields
  - [x] 7.2 Write integration test: `colonyos run --issue https://github.com/org/repo/issues/42` — verify URL parsing and same data flow
  - [x] 7.3 Write integration test: `colonyos run --issue 42 "focus on backend"` — verify prompt composition with additional context
  - [x] 7.4 Write test: `colonyos run --issue 42 --from-prd path` — verify mutual exclusivity error
  - [x] 7.5 Write test: graceful error when `gh` returns non-zero exit code (auth failure, issue not found)
