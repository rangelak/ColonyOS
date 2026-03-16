## Relevant Files

- `.cursor/rules/create_prd.mdc` - PRD generation rule updated to use timestamp-based filenames and changelog headings.
- `.cursor/rules/generate_tasks.mdc` - Task generation rule updated to reuse the source PRD timestamp in task filenames.
- `.cursor/rules/track_work.mdc` - Work-tracking rule updated to require timestamp-based task file names.
- `START_HERE.md` - Reviewed for impact during this task; no changes required.
- `README.md` - Reviewed for impact during this task; no changes required.
- `tasks/20260316_110957_tasks_timestamp_naming_rule.md` - Task tracking for the timestamp naming convention update.
- `tasks/CHANGELOG.md` - Repository changelog updated to reflect the naming convention change and legacy numbering note.

### Notes

- New planning files should use `YYYYMMDD_HHMMSS` prefixes instead of sequential numbers.
- Legacy sequentially named planning files were initially left in place, then backfilled to timestamped filenames in a later cleanup task.
- `START_HERE.md` and `README.md` were reviewed and did not require updates because this task changes planning-file conventions, not project setup or runtime behavior.

## Tasks

- [x] 1.0 Replace sequential planning-file naming guidance with timestamp-based naming
  - [x] 1.1 Update the PRD rule to require filenames in the form `YYYYMMDD_HHMMSS_prd_[feature-name].md`.
  - [x] 1.2 Update the task-generation rule to require filenames in the form `YYYYMMDD_HHMMSS_tasks_[feature-name].md` and reuse the source PRD timestamp.
  - [x] 1.3 Update the work-tracking rule so newly created task files also follow the timestamp-based format.
- [x] 2.0 Align changelog guidance with the new naming convention
  - [x] 2.1 Replace "Sequential" wording with "Chronological" in `tasks/CHANGELOG.md`.
  - [x] 2.2 Add a new changelog entry documenting the timestamp naming convention update.
  - [x] 2.3 Record the initial decision to leave older sequential file names in place until a later cleanup task backfilled them.
