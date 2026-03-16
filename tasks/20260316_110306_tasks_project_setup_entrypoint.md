## Relevant Files

- `START_HERE.md` - Practical local setup guide and runtime entrypoint for the current repository.
- `README.md` - High-level product thesis; now points readers to the startup guide first.
- `.cursor/rules/update_entry_docs.mdc` - Always-apply rule requiring review and maintenance of `START_HERE.md` and `README.md` after meaningful work.
- `tasks/20260316_110306_tasks_project_setup_entrypoint.md` - Task tracking for this setup and documentation pass.
- `tasks/CHANGELOG.md` - Repository-wide implementation log updated with this work.

### Notes

- Local setup for this pass used the repo-scoped `.venv` as required by workspace rules.
- Dependencies were installed from `requirements.txt`.
- `./.venv/bin/python -m pytest -v` passed after setup.

## Tasks

- [x] 1.0 Audit the repository's current setup flow and real runtime entrypoints
  - [x] 1.1 Inspect the package structure, CLI wrapper, environment requirements, and existing documentation.
  - [x] 1.2 Identify the safest command path a new developer should use to run the current project.
  - [x] 1.3 Verify local setup expectations for `.venv`, dependencies, tests, and OpenAI configuration.
- [x] 2.0 Create a practical startup guide for the current project state
  - [x] 2.1 Write a `START_HERE.md` file that explains what the repo does today versus what is still future-state.
  - [x] 2.2 Document the exact setup, test, and run commands a new developer should use.
  - [x] 2.3 Document the main entrypoint files and output artifacts so the repo is easier to navigate.
- [x] 3.0 Align repository docs and work-tracking with the new setup entrypoint
  - [x] 3.1 Update `README.md` to direct people to the practical startup guide.
  - [x] 3.2 Record this work in the task log and repository changelog.
- [x] 4.0 Add a persistent maintenance rule for entrypoint docs
  - [x] 4.1 Create an always-apply Cursor rule that forces review of `START_HERE.md` and `README.md` after meaningful completed tasks.
  - [x] 4.2 Define when the docs must be updated so setup, runtime, and project-status changes do not leave onboarding stale.
