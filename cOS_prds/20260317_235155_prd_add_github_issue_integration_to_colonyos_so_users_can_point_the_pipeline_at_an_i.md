# PRD: GitHub Issue Integration for ColonyOS

## Source Issue

This feature was proposed directly via CLI feature request (no linked GitHub issue).

## Introduction/Overview

ColonyOS currently requires users to write feature prompts from scratch on the command line. This feature adds a `--issue` flag to `colonyos run` that lets users point the pipeline at an existing GitHub issue, automatically fetching the issue's title, body, and metadata to construct the prompt. This bridges the gap between GitHub's issue tracker (where feature requests and bugs are already documented) and ColonyOS's autonomous development pipeline.

Additionally, the CEO phase in `colonyos auto` will be enriched with awareness of open GitHub issues, enabling it to ground its feature proposals in real user-reported work.

## Goals

1. **Zero-friction issue-to-PR pipeline**: A user should be able to run `colonyos run --issue 42` and get a complete PR that references and auto-closes the issue.
2. **Traceability**: Every issue-triggered run should be traceable back to its source issue in the run log, status output, and generated PR.
3. **CEO backlog awareness**: The autonomous CEO should be able to see open issues and factor them into its feature proposals.
4. **No new dependencies**: Use the existing `gh` CLI (already a checked prerequisite in `doctor.py`) for all GitHub API interactions.

## User Stories

1. **As a developer**, I want to run `colonyos run --issue 42` so that the pipeline builds exactly what's described in issue #42 without me re-typing the requirements.
2. **As a developer**, I want to run `colonyos run --issue https://github.com/org/repo/issues/42` so that I can paste an issue URL directly from my browser.
3. **As a developer**, I want the generated PR to contain `Closes #42` so the issue auto-closes when the PR merges.
4. **As a developer**, I want `colonyos status` to show which runs were triggered by issues so I can trace work back to its origin.
5. **As a project maintainer**, I want the CEO's autonomous proposals to reference open issues so it prioritizes real user-reported work alongside novel ideas.
6. **As a developer**, I want to append additional context to an issue-triggered run (e.g., `colonyos run --issue 42 "Focus on the backend API"`) so I can steer the pipeline's focus.

## Functional Requirements

### FR-1: `--issue` CLI Flag on `colonyos run`

- Accept `--issue <value>` where value is either an integer (issue number) or a full GitHub issue URL.
- When `--issue` is provided without a positional `prompt`, the issue content becomes the full prompt.
- When `--issue` is provided WITH a positional `prompt`, the issue content is the base and the prompt is appended as `## Additional Context`.
- `--issue` is mutually exclusive with `--from-prd` and `--resume`.
- **File**: `src/colonyos/cli.py` — `run` command (line 215-273)

### FR-2: GitHub Issue Fetching Module (`src/colonyos/github.py`)

- New module with a `GitHubIssue` dataclass: `number`, `title`, `body`, `labels`, `comments`, `state`, `url`.
- `fetch_issue(issue_ref: str | int, repo_root: Path) -> GitHubIssue`: Uses `gh issue view <number> --json number,title,body,labels,comments,state,url` via `subprocess.run`. Parses the JSON response into the dataclass.
- `parse_issue_ref(ref: str) -> int`: Extracts the issue number from either a bare integer string or a full GitHub URL (e.g., `https://github.com/owner/repo/issues/42`). Raises `ValueError` for invalid formats.
- `format_issue_as_prompt(issue: GitHubIssue) -> str`: Builds a rich prompt string with the issue title, full body, label context, and comment summary (first 5 comments, capped at 8,000 characters, with truncation marker).
- `fetch_open_issues(repo_root: Path, limit: int = 20) -> list[GitHubIssue]`: Uses `gh issue list --json number,title,labels,state --limit 20` to fetch open issues for CEO context.
- Fail fast with `click.ClickException` on `gh` errors (auth failure, issue not found, network error). No retries.
- Warn (via `click.echo` to stderr) but proceed if the issue is closed.

### FR-3: Plan Phase Enhancement

- When an issue is the source, inject the issue number and URL into the plan prompt so the PRD references it.
- The system prompt addition: `"This feature request originates from GitHub issue #{number} ({url}). The generated PRD must include a '## Source Issue' section linking back to the issue."`
- **File**: `src/colonyos/orchestrator.py` — `_build_plan_prompt` (line 119-137)

### FR-4: Deliver Phase Enhancement

- When the run was triggered by an issue, inject `source_issue` context into the deliver prompt.
- The deliver system prompt addition: `"This implementation addresses GitHub issue #{number}. The PR body MUST include 'Closes #{number}' to auto-close the issue on merge. Reference the issue in the summary section."`
- **File**: `src/colonyos/orchestrator.py` — `_build_deliver_prompt` (line 291-307)

### FR-5: RunLog Tracking

- Add `source_issue: int | None = None` and `source_issue_url: str | None = None` fields to the `RunLog` dataclass.
- Persist these fields in the run log JSON via `_save_run_log`.
- Restore these fields in `_load_run_log` for resume support.
- **File**: `src/colonyos/models.py` — `RunLog` (line 82-101)
- **File**: `src/colonyos/orchestrator.py` — `_save_run_log` (line 481-530), `_load_run_log` (line 558-608)

### FR-6: Status Display Enhancement

- When a run log has `source_issue_url`, display it in `colonyos status` output alongside the prompt preview.
- Format: `#42 (https://github.com/org/repo/issues/42)` before the prompt preview.
- **File**: `src/colonyos/cli.py` — `status` command (line 769-796)

### FR-7: CEO Issue Awareness

- Add `fetch_open_issues()` helper in `src/colonyos/github.py`.
- In `_build_ceo_prompt`, call `fetch_open_issues` and inject the list into the CEO user prompt as a `## Open Issues` section after the changelog.
- The CEO instruction should say: "Consider these open issues as candidates. You may select one as the basis for your proposal (cite it with `Issue: #N`), or propose a novel feature if no open issue is high-impact enough."
- If `fetch_open_issues` fails (e.g., `gh` not authenticated), log a warning and proceed without issue context — this is non-blocking.
- **File**: `src/colonyos/orchestrator.py` — `_build_ceo_prompt` (line 354-389)

### FR-8: Error Handling

- `gh` not installed or not authenticated: Fail fast with clear message referencing `colonyos doctor`.
- Issue not found (404): Fail fast with "Issue #N not found in this repository."
- Closed issue: Print warning to stderr, proceed with the run.
- Invalid issue reference format: Fail fast with usage hint showing accepted formats.

## Non-Goals (Out of Scope for v1)

1. **Cross-repo issues**: Only issues from the current repo are supported. Users working with external repo issues should `cd` into that repo.
2. **Label-based pipeline routing**: Labels are included as prompt context but do not influence pipeline behavior (e.g., `bug` label does not trigger a different plan template).
3. **Autonomous CEO issue selection on `auto`**: The CEO sees open issues as context but the `auto` command does not get an `--issue` or `--from-issues` flag in v1. This is a separate feature with its own trust/security considerations.
4. **Issue comment summarization**: Comments are truncated by character count, not summarized by an LLM pre-processing step.
5. **Issue state filtering**: Closed issues are allowed with a warning — the tool trusts the user's judgment.
6. **Prompt sanitization/injection defense beyond structural separation**: Issue content flows into the user prompt slot (never the system prompt), wrapped in `<github_issue>` delimiters with an explicit instruction to treat it as a feature description. This matches the existing trust model where the positional `prompt` argument has the same trust level.

## Technical Considerations

### Architecture Fit

- **New module**: `src/colonyos/github.py` follows the existing pattern of small, focused modules (`doctor.py`, `naming.py`, `learnings.py`). It handles all `gh` subprocess interactions for issues.
- **Dataclass pattern**: `GitHubIssue` follows the existing `frozen=True` dataclass pattern used by `Persona`, `PersonaPack`, `ProjectInfo` in `models.py`. Placed in `github.py` to keep `models.py` focused on pipeline state.
- **Subprocess pattern**: Follows `doctor.py`'s pattern — `subprocess.run` with `capture_output=True, text=True, timeout=10`, no `shell=True`.
- **Prompt injection defense**: Issue content is wrapped in `<github_issue>...</github_issue>` delimiters and placed in the user prompt, never interpolated into system prompt templates. A preamble instructs the agent to treat the content as a feature description only.

### Data Flow

```
CLI (--issue 42) → parse_issue_ref() → fetch_issue() → format_issue_as_prompt()
  → run_orchestrator(prompt, source_issue=42, source_issue_url=url)
    → _build_plan_prompt() injects issue context
    → _build_deliver_prompt() injects "Closes #42"
    → _save_run_log() persists source_issue fields
```

### Key Dependencies

- `gh` CLI (already validated in `doctor.py` line 54-71)
- No new Python dependencies

### Backward Compatibility

- `RunLog.source_issue` defaults to `None`, so existing run logs remain valid.
- `_load_run_log` uses `.get()` with defaults for the new fields.
- The `--issue` flag is fully optional — existing `colonyos run "prompt"` workflow is unchanged.

### Persona Consensus & Tensions

**Strong agreement across all 7 personas:**
- Current repo only (no cross-repo support)
- Fail fast on `gh` errors (no retries)
- Show full clickable URL in status output
- No label-based pipeline routing in v1
- Allow closed issues with a warning
- CEO retains freedom to propose novel features (issues are additive context, not a constraint)

**Areas of tension:**
- **Comments**: Linus/YC say skip comments entirely in v1; Systems Engineer/Karpathy say include first 5 with truncation; Security says comments are injection vectors. **Decision**: Include issue body verbatim, cap comments at first 5 / 8K chars with truncation marker, wrap in structural delimiters.
- **`--issue` + `prompt` composability**: Jobs initially said issue IS the prompt; YC said ship `--issue` alone first. Others (Ive, Systems, Karpathy) said allow both. **Decision**: Allow composing `--issue` with a positional prompt for additional context — this follows the existing `--from-prd` pattern and costs nothing.
- **CEO autonomous issue picking**: YC says it's the killer use case; Security says it's a trust boundary expansion. **Decision**: v1 gives the CEO read-only awareness of open issues as context. Autonomous picking is deferred to v2 with its own threat model.

## Success Metrics

1. `colonyos run --issue 42` successfully fetches the issue, builds a prompt, and runs the full pipeline end-to-end.
2. Generated PRs contain `Closes #42` and the issue is auto-closed on merge.
3. `colonyos status` displays source issue URLs for issue-triggered runs.
4. The CEO prompt includes open issues when `gh` is available (verified via test).
5. Unit test coverage for: `parse_issue_ref`, `fetch_issue`, `format_issue_as_prompt`, `fetch_open_issues`, CLI flag validation, RunLog serialization with new fields, status display with issue context.
6. Graceful degradation when `gh` is not authenticated (CEO phase continues without issue context; `run --issue` fails fast with clear error).

## Open Questions

1. **Comment author filtering**: Should we filter comments to only include those from the issue author or repo collaborators (as the Security Engineer suggested)? Deferred to v2 — v1 includes first N comments regardless of author.
2. **Token budget for comments**: The 8K character cap is a heuristic. Should this be configurable in `.colonyos/config.yaml`? Deferred — can be added if users hit issues.
3. **`auto --from-issues` flag**: Should a future version of `colonyos auto` let the CEO explicitly draw from the issue backlog with its own CLI flag and confirmation gate? Likely yes, but requires its own PRD.
