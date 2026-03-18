# ColonyOS Learnings Ledger


## Run: run-20260317_235155-03a2bb3fed
_Date: 2026-03-18 | Feature: add_github_issue_integration_to_colonyos_so_users_can_point__

- **[code-quality]** Docstrings and comments must stay in sync with code; renaming functions without updating docs creates lying documentation.
- **[testing]** Test function names get corrupted during bulk find-replace; verify test names remain valid after refactoring.
- **[code-quality]** Catch specific exception types (e.g., OSError, TimeoutExpired) instead of bare `except Exception` to avoid swallowing bugs.
- **[code-quality]** Use line-anchored regex (`^target:`) instead of substring checks (`"target:" in text`) when parsing structured files.
- **[architecture]** Extract duplicated inner functions (e.g., UI factories) into shared helpers rather than copy-pasting closures across methods.

## Run: run-20260318_001555-d784c3e835
_Date: 2026-03-18 | Feature: add_a_colonyos_stats_cli_command_that_reads_all_persisted_ru_

- **[code-quality]** Remove unused function parameters (e.g., accepted but ignored args) that mislead callers about behavior.
- **[style]** Move imports to module-level; imports inside loop bodies signal hasty implementation and reduce readability.
- **[architecture]** Keep feature branches single-purpose; unrelated changes increase rollback blast radius and pollute diffs.
- **[code-quality]** Delete unreachable code guards (e.g., filters redundant with an upstream glob); dead code misleads maintainers.
- **[code-quality]** Document implicit ordering contracts between components with comments to prevent silent breakage.
