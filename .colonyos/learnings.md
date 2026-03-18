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

## Run: run-20260318_154057-c28fc676a8
_Date: 2026-03-18 | Feature: add_a_colonyos_ci_fix_command_and_integrate_ci_awareness_int_

- **[security]** Sanitize user-controlled strings before interpolating into structured templates (XML, prompts) to prevent injection attacks.
- **[architecture]** Private (_prefixed) functions imported across module boundaries should be made public or moved to a shared module.
- **[testing]** Verify claimed test coverage actually exists in code; task descriptions listing tests don't guarantee implementation.
- **[code-quality]** Functions returning True for empty collections (e.g., `all_pass([])`) create silent semantic bugs; handle empty inputs explicitly.
- **[code-quality]** Silently swallowing network/IO failures (e.g., fetch, push) gives false confidence; log or propagate the error.

## Run: run-20260318_162724-2f8d605c2b
_Date: 2026-03-18 | Feature: add_a_colonyos_show_run_id_cli_command_that_renders_a_detail_

- **[architecture]** Return `str | list[str]` union types are fragile; use typed result dataclasses to make dispatch explicit and safe.
- **[code-quality]** CLI flag combinations that are logically useless (e.g., `--max-retries` without `--wait`) should auto-correct or warn the user.
- **[security]** Validate inputs at public function boundaries even when current callers pre-validate; defense-in-depth prevents future misuse.
- **[code-quality]** Implemented but never-called functions are dead code; wire them in or document them as forward-looking with a comment.
- **[style]** Duplicate near-identical branches (differing by one variable) should be collapsed into a single branch with a parameter.
