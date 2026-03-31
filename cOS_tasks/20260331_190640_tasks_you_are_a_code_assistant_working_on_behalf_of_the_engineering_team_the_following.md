# Tasks: Informative Slack Pipeline Notifications

## Relevant Files

- `src/colonyos/orchestrator.py` - Contains all formatting functions: `_format_task_outline_note()` (line 1317), `_format_implement_result_note()` (line 1364), `_format_review_round_note()` (line 1434), `_format_fix_iteration_extra()` (line 1471), phase_header call (line 875), `_format_task_ids()` (line 1359)
- `tests/test_orchestrator.py` - Existing test file for orchestrator; needs new tests for all formatting functions
- `src/colonyos/slack.py` - SlackUI class (line 520); no changes needed but reference for understanding message flow
- `src/colonyos/sanitize.py` - `sanitize_untrusted_content()` function (line 21); needs new `sanitize_for_slack()` to escape mrkdwn metacharacters and mention/link injection
- `tests/test_sanitize.py` - Needs tests for new `sanitize_for_slack()` function
- `src/colonyos/instructions/review.md` - Review output format template showing FINDINGS/SYNTHESIS structure; no changes needed
- `src/colonyos/models.py` - `PhaseResult` model (line 157); artifacts dict carries task results

## Tasks

- [x] 1.0 Add tests for all Slack formatting functions (test foundation)
  depends_on: []
  - [x] 1.1 Add parametrized tests for `_format_task_outline_note()` covering: empty list, 1 task, 6 tasks (at limit), 8 tasks (overflow with `+N more`), long descriptions (>72 chars truncation). Verify output uses `•` bullet format with newlines.
  - [x] 1.2 Add parametrized tests for `_format_implement_result_note()` covering: all completed, mixed completed/failed/blocked, fallback branch (no task_results dict), tasks with descriptions and cost/duration data. Verify descriptions appear in output.
  - [x] 1.3 Add parametrized tests for `_format_review_round_note()` covering: all approved, mixed approved/changes/failed, review text with FINDINGS section, review text without FINDINGS section. Verify finding summaries appear in output.
  - [x] 1.4 Add a test for `_extract_review_findings_summary()` (new helper) covering: well-formatted FINDINGS section, missing FINDINGS section (fallback to first line), empty text, very long findings (truncation).
  - [x] 1.5 Add a test that verifies no single formatted message exceeds 3,000 characters when given pathologically long inputs.

- [ ] 2.0 Reformat task outline to use bullet list (FR-2)
  depends_on: []
  - [ ] 2.1 Modify `_format_task_outline_note()` in `orchestrator.py` (line 1317) to output newline-separated bullet points with `•` prefix instead of `"; ".join()`. Add bold header `*Implement tasks (N):*` on its own line. Keep 72-char truncation and `+N more` overflow.
  - [ ] 2.2 Run existing tests to verify no regressions.

- [ ] 3.0 Include task descriptions in completion and result messages (FR-1, FR-3)
  depends_on: []
  - [ ] 3.1 Modify the `phase_header` call at orchestrator.py line 875 to include the truncated task description: `f"Implement [{task_id}] {short_desc}"` where `short_desc` is the description truncated to 60 chars. Apply `sanitize_untrusted_content()` to the description.
  - [ ] 3.2 Modify `_format_implement_result_note()` (line 1364) to include task descriptions from `task_results` artifacts. For each completed/failed/blocked task, show `• \`{task_id}\` {description}` with optional `— ${cost:.2f}, {secs}s` suffix for tasks that have cost/duration. Use `•` bullets and newlines. Cap at 6 tasks per category with `+N more`.
  - [ ] 3.3 Modify `_format_task_ids()` (line 1359) or create a new `_format_task_ids_with_descriptions()` helper that accepts a `task_results` dict and renders task IDs with descriptions.

- [ ] 4.0 Add review finding summaries to review round messages (FR-4)
  depends_on: []
  - [ ] 4.1 Create a new helper `_extract_review_findings_summary(text: str, max_findings: int = 2, max_chars: int = 80) -> list[str]` that extracts findings from review result text. Strategy: find `FINDINGS:` line, collect subsequent `- ` prefixed lines, truncate each to `max_chars`. If no FINDINGS section found, extract first non-empty line as fallback. If `SYNTHESIS:` section exists, use its first sentence as an alternative fallback.
  - [ ] 4.2 Modify `_format_review_round_note()` (line 1434) to include finding summaries for reviewers who requested changes. For each reviewer in `requested_changes`, call `_extract_review_findings_summary()` on their result text and append findings as sub-bullets. Add approved reviewer list with `:white_check_mark:` prefix and changes list with `:warning:` prefix for visual hierarchy.
  - [ ] 4.3 Ensure the function signature change is backward-compatible: add `results` data to the existing parameters (results are already passed, just not used for finding extraction — the full text is in `result.artifacts["result"]`).

- [ ] 5.0 Add message size safety and sanitization (FR-5)
  depends_on: [2.0, 3.0, 4.0]
  - [ ] 5.1 Add a new `sanitize_for_slack(text: str) -> str` function in `src/colonyos/sanitize.py` that escapes Slack mrkdwn metacharacters (`*`, `_`, `~`, `` ` ``, `>` at line start) in untrusted content, and neutralizes mention injection (`@here`, `@channel`, `<!channel>`, `<!everyone>`) and link markup (`<url|text>` patterns). Add corresponding tests in `tests/test_sanitize.py`.
  - [ ] 5.2 Add a helper `_truncate_slack_message(text: str, max_chars: int = 3000) -> str` in `orchestrator.py` that truncates messages at the nearest newline boundary before `max_chars` and appends `\n_(truncated)_` if truncated.
  - [ ] 5.3 Apply `sanitize_for_slack()` (for user-derived descriptions) and `sanitize_untrusted_content()` (for LLM text) to all untrusted content before including in formatted messages. Ensure they're called in `_format_task_outline_note()`, `_format_implement_result_note()`, `_format_review_round_note()`, and the phase_header call at line 875.
  - [ ] 5.4 Apply `_truncate_slack_message()` at the call sites where `impl_ui.slack_note()` and `review_header_ui.slack_note()` are invoked (lines 4396, 4421, 4455, 4608).

- [ ] 6.0 Integration verification and full test run
  depends_on: [1.0, 2.0, 3.0, 4.0, 5.0]
  - [ ] 6.1 Run the full test suite (`pytest tests/`) and verify all 336+ tests pass with zero regressions.
  - [ ] 6.2 Verify the new tests from task 1.0 all pass against the implementations from tasks 2.0-5.0.
  - [ ] 6.3 Manually verify sample output of each formatting function looks correct in both terminal and Slack mrkdwn contexts (add a debug script or print statements if needed, then remove).
  - [ ] 6.4 Update any docstrings on modified functions to reflect the new output format.
