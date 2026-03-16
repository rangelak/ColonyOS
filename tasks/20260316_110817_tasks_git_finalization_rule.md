## Relevant Files

- `.cursor/rules/git_finalize_on_request.mdc` - Always-apply rule defining the default branch, commit, push, and PR flow when the user explicitly asks to finalize work.
- `.cursor/rules/update_entry_docs.mdc` - Entry-doc maintenance rule reviewed during this task; no changes required.
- `START_HERE.md` - Reviewed for impact during this task; no changes required.
- `README.md` - Reviewed for impact during this task; no changes required.
- `tasks/20260316_110817_tasks_git_finalization_rule.md` - Task tracking for the git finalization workflow rule.
- `tasks/CHANGELOG.md` - Repository changelog updated with this rule addition.

### Notes

- This rule intentionally does not authorize automatic commits or pushes without user approval.
- `START_HERE.md` and `README.md` were reviewed and did not require updates because this task changes agent workflow policy, not project setup or runtime behavior.

## Tasks

- [x] 1.0 Define a persistent git finalization workflow rule
  - [x] 1.1 Add an always-apply Cursor rule describing the default branch, commit, push, and PR flow for explicit finalization requests.
  - [x] 1.2 Keep the rule aligned with existing safety requirements by forbidding automatic commits, pushes, or PR creation without explicit user approval.
  - [x] 1.3 Specify branch reuse behavior and the need to ask when remote state or branch strategy is unclear.
- [x] 2.0 Track the rule change in repository planning docs
  - [x] 2.1 Create a dedicated task log entry for the new git workflow rule.
  - [x] 2.2 Update `tasks/CHANGELOG.md` with the new rule and affected files.
  - [x] 2.3 Review `START_HERE.md` and `README.md` and record that no updates were needed for this task.
