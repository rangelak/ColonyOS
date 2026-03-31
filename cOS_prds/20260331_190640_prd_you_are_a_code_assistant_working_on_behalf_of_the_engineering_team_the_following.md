# PRD: Informative Slack Pipeline Notifications

## Introduction/Overview

ColonyOS posts status updates to Slack threads as it runs the plan -> implement -> review -> fix pipeline. Currently, these messages are cryptically terse — task completion messages show bare IDs like "Implement [1.0]" with no description, result summaries list IDs without context, and review round messages say "Requested changes: R2 Linus Torvalds" without saying *what* was blocked. Task outlines are flat semicolon-separated strings.

The data to make these messages informative **already exists** in the pipeline — task descriptions are stored in `task_results[task_id]["description"]`, review findings are structured with `FINDINGS:` bullet points and `SYNTHESIS:` paragraphs (per `src/colonyos/instructions/review.md`). This feature threads that existing data through to the Slack formatting functions.

## Goals

1. Every Slack message should let a non-technical reader understand *what happened* without leaving the thread
2. Task completion messages include the task description (e.g., "Implement [1.0] Frontend dependencies and type foundations")
3. Task result summaries show descriptions alongside IDs
4. Review round messages include a 1-2 line summary of what each reviewer blocked
5. Task outlines use Slack bullet formatting instead of semicolon-separated inline text
6. Zero additional LLM calls — all data is extracted from existing artifacts
7. Messages stay scannable — no walls of text

## User Stories

- **As an engineering lead**, I want to glance at the Slack thread and understand what each task did, so I don't have to open logs or task files.
- **As a product manager**, I want to see what reviewers flagged without reading full review artifacts, so I can judge whether fixes are on track.
- **As a developer**, I want the task list shown as a readable bulleted list, so I can quickly scan planned work.

## Functional Requirements

### FR-1: Task Completion Messages Include Description
The per-task `phase_header` call (orchestrator.py line 875) currently passes `f"Implement [{task_id}]"`. Change to include the task description, truncated to 72 chars:
```
:gear: Starting *Implement [1.0] Frontend dependencies and type foundations* phase ($1.25 budget, opus)
```
The `phase_complete` message inherits this via `_current_phase` on `SlackUI`.

### FR-2: Task Outline Uses Bullet Formatting
`_format_task_outline_note()` (orchestrator.py line 1317) currently joins with `"; "`. Change to use newline-separated bullet points with Slack mrkdwn:
```
*Implement tasks (8):*
• `1.0` Frontend dependencies and type foundations
• `2.0` Daemon health banner component
• `3.0` Queue page and component
• `4.0` Analytics page with charts
• `5.0` Enhanced Dashboard and improved components
• `6.0` Improved Phase Timeline
+2 more
```

### FR-3: Task Result Summary Includes Descriptions
`_format_implement_result_note()` (orchestrator.py line 1364) currently shows `Completed: \`1.0\`, \`2.0\``. Change to include descriptions from `task_results` artifacts:
```
*Task results:* 8 completed, 0 failed, 0 blocked.
:white_check_mark: *Completed:*
• `1.0` Frontend dependencies and type foundations — $0.58, 142s
• `2.0` Daemon health banner component — $0.45, 98s
• `3.0` Queue page and component — $0.62, 156s
```
Show up to 6 tasks with `+N more` for overflow. Include cost and duration when available.

### FR-4: Review Round Messages Include Finding Summaries
`_format_review_round_note()` (orchestrator.py line 1434) currently shows only reviewer names. Extract the `FINDINGS:` section from each reviewer's result text and include a condensed summary (first 2 findings per reviewer, truncated to 80 chars each):
```
Review round 1/5: 2 approved, 2 requested changes, 0 failed.

:white_check_mark: *Approved:* R1 Principal Systems Engineer, R4 Andrej Karpathy

:warning: *Requested changes:*
• *R2 Linus Torvalds:* [src/api.py]: Missing error handling in retry loop; [src/models.py]: Unused import
• *R3 Staff Security Engineer:* [src/config.py]: API key should use env var not hardcoded string
```

### FR-5: Sanitize All User-Derived Content
All task descriptions originate from user Slack messages and pass through LLM-generated task files. Review findings are LLM-generated and may echo secrets or internal paths from source code.

**Sanitization layers (both required):**
1. Apply `sanitize_untrusted_content()` (from `src/colonyos/sanitize.py`) to strip XML-like tags
2. Add a new `sanitize_for_slack()` function that escapes Slack mrkdwn metacharacters (`*`, `_`, `~`, `` ` ``, `>`) and neutralizes mention injection (`@here`, `@channel`, `<!channel>`, `<!everyone>`) and link injection (`<url|text>` patterns) in untrusted content. This prevents a malicious user from crafting Slack messages that, when reflected in status updates, phish other channel members.

**Truncation:** Cap total message length at 3,000 chars (well under Slack's 40,000 limit) with truncation indicators. Truncate review findings to prevent oversized messages and limit information leakage of internal architecture details.

## Non-Goals

- **No additional LLM calls** — we extract data from existing artifacts only
- **No Block Kit / rich Slack layouts** — stick with mrkdwn text formatting
- **No changes to terminal UI** — formatting functions serve both Slack and terminal; changes must remain compatible with both, or we split the formatting path
- **No changes to the review instruction template** — the `FINDINGS:` / `SYNTHESIS:` structure already exists
- **No per-message configuration** — all messages get the improved format

## Technical Considerations

### Data Already Available
- Task descriptions: stored in `task_results[task_id]["description"]` (orchestrator.py line 979) and `task_descriptions` dict (line 829)
- Review findings: structured output with `FINDINGS:` bullets and `SYNTHESIS:` paragraph (review.md lines 41-46)
- Cost/duration per task: stored in `task_results[task_id]["cost_usd"]` and `["duration_ms"]` (lines 977-978)

### Shared Formatting Functions (Terminal + Slack)
`_format_review_round_note()` and `_format_implement_result_note()` are called for both terminal progress display and Slack notes. Changes must not break terminal rendering. The simplest approach: the bullet formatting with `•` works in both contexts. If terminal output looks wrong, we can split into separate formatters.

### Review Findings Extraction
The review instruction template (review.md) requires structured output:
```
FINDINGS:
- [file path]: description of finding

SYNTHESIS:
Your overall assessment paragraph from your perspective.
```
We can extract both sections with simple string operations — find `FINDINGS:` line, collect subsequent `- ` prefixed lines for specific file-level issues; find `SYNTHESIS:` line and take the following paragraph for the reviewer's overall assessment (truncated to ~200 chars). No regex needed for the happy path; fall back to first non-empty line of text if neither section is found.

### Message Size Safety
Review texts can be 1000+ words. We truncate: max 2 findings per reviewer, max 80 chars per finding, max 3000 chars total per message. This keeps messages scannable.

### Key Files to Modify
- `src/colonyos/orchestrator.py` — `_format_task_outline_note()`, `_format_implement_result_note()`, `_format_review_round_note()`, phase_header call at line 875
- `tests/test_orchestrator.py` — new tests for all formatting functions

### Files NOT Modified
- `src/colonyos/slack.py` — SlackUI just passes through text; no changes needed
- `src/colonyos/instructions/review.md` — already has FINDINGS structure
- `src/colonyos/ui.py` — terminal UI; `slack_note()` is a no-op

## Persona Synthesis

### Unanimous Agreement (7/7)
- **Use existing data, no LLM calls** — task descriptions and review findings are already in the artifacts
- **Keep it simple** — modify 3-4 formatting functions, ship in one PR
- **Sanitize user-derived content** — descriptions come from user Slack messages
- **Truncate aggressively** — keep messages scannable, not encyclopedic

### Key Tensions
- **Bullet formatting**: Jony Ive and Steve Jobs strongly favor bullet lists with visual hierarchy (bold headers, emoji markers). Linus Torvalds prefers minimal changes. **Resolution**: Use bullet formatting for task lists and review summaries (clear user request), but keep the overall structure simple.
- **Review finding detail**: Karpathy noted the existing `SYNTHESIS:` section is effectively a TL;DR and should be extracted alongside `FINDINGS:` bullets. **Resolution**: Extract both — use FINDINGS bullets for specific file issues and SYNTHESIS (truncated to ~200 chars) for the reviewer's overall assessment. No changes to review.md needed.
- **Implement change summaries**: Karpathy suggested adding a `CHANGE_SUMMARY:` structured output requirement to the implement prompt. **Resolution**: Defer to v2 — requires changing implement instruction template and is a separate concern from formatting existing data.
- **Terminal compatibility**: Systems Engineer noted shared formatting functions serve both Slack and terminal. **Resolution**: Use `•` bullet character which renders well in both. Monitor for issues.

## Success Metrics

1. **Readability**: A person reading the Slack thread can answer "what did ColonyOS build?" and "what did reviewers flag?" without clicking any links
2. **No regressions**: All 336 existing tests pass
3. **Message length**: No Slack message exceeds 3,000 characters
4. **Zero new LLM calls**: Feature cost impact is $0.00

## Open Questions

1. Should we show file paths changed per task (from git diff)? Data exists but adds noise. **Recommendation**: Defer to v2.
2. Should the `+N more` threshold be configurable? **Recommendation**: No — hardcode at 6, iterate if users complain.
3. Should terminal output also get bullet formatting? **Recommendation**: Yes, use shared formatting since `•` renders in both contexts. Split later if needed.
