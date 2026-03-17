# ColonyOS Learnings Ledger


## Run: run-20260317_235155-03a2bb3fed
_Date: 2026-03-18 | Feature: add_github_issue_integration_to_colonyos_so_users_can_point__

- **[code-quality]** Docstrings and comments must stay in sync with code; renaming functions without updating docs creates lying documentation.
- **[testing]** Test function names get corrupted during bulk find-replace; verify test names remain valid after refactoring.
- **[code-quality]** Catch specific exception types (e.g., OSError, TimeoutExpired) instead of bare `except Exception` to avoid swallowing bugs.
- **[code-quality]** Use line-anchored regex (`^target:`) instead of substring checks (`"target:" in text`) when parsing structured files.
- **[architecture]** Extract duplicated inner functions (e.g., UI factories) into shared helpers rather than copy-pasting closures across methods.
