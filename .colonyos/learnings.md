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

## Run: run-20260318_164532-71a1390a74
_Date: 2026-03-18 | Feature: add_a_colonyos_queue_command_that_accepts_multiple_feature_p_

- **[security]** Exception messages persisted verbatim may leak secrets from tracebacks; redact or truncate before writing to disk.
- **[architecture]** Register signal/cleanup handlers before marking mutable state transitions to prevent crash-orphaned resources.
- **[code-quality]** Use enums instead of plain strings for fields with a fixed set of valid values to enable type-checking.
- **[architecture]** Extract feature logic from CLI entry-point files into dedicated modules; god files (>500 LOC) hinder review and testing.
- **[testing]** Test cross-command integration points; a subcommand passing its own tests doesn't guarantee correct parent output.

## Run: run-20260318_173116-0d7234c9e5
_Date: 2026-03-18 | Feature: i_think_we_should_add_some_sort_of_ui_for_managing_all_this__

- **[security]** Resolve user-supplied file paths and verify they stay within the allowed base directory to prevent path traversal.
- **[architecture]** Hand-maintained type mirrors across languages (e.g., TS types for Python models) drift silently; generate or validate via shared schema.
- **[code-quality]** Manual serialization helpers that enumerate fields silently drop new fields; co-locate serialization with the data model.
- **[security]** HTTP error handlers forwarding raw exception messages to clients can leak internal filesystem paths and stack details.

## Run: run-20260318_233254-2ac1052a17
_Date: 2026-03-19 | Feature: the_ui_tests_are_failing_on_the_ci_there_is_no_module_found__

- **[code-quality]** Config loaded once before a long-running loop goes stale; reload configuration at the start of each iteration.
- **[code-quality]** Deserialization via direct key access (`d["key"]`) crashes on corrupted data; use `.get()` with defaults for resilience.
- **[security]** CORS allowed-origins must be scoped per environment; leaving dev-server origins in production builds weakens isolation.
- **[architecture]** Mutable state files (queues, logs) lack append-only audit trails; add forensic logging for add/remove operations.
- **[code-quality]** Reusable format/parse helpers (e.g. duration formatting) get copy-pasted instead of importing the shared utility.

## Run: run-20260319_081958-46cf575c9d
_Date: 2026-03-19 | Feature: every_time_the_pipeline_starts_we_should_look_at_what_branch_

- **[architecture]** CLI god files (>2000 LOC) must be split proactively; extract each subcommand's helpers into dedicated modules.
- **[security]** Use allowlist serialization (explicit field inclusion) instead of blocklist (pop sensitive fields) to prevent leaking new fields.
- **[testing]** CLI entry points (flags, import guards, argument parsing) need dedicated unit tests separate from the underlying logic tests.
- **[code-quality]** Polling intervals using setInterval with stale closures cause subtle bugs; use refs or re-subscribe on dependency changes.
- **[architecture]** Prompt templates should use concrete glob patterns instead of natural-language directory descriptions to reduce ambiguity.

## Run: run-20260319_152207-801fef63d9
_Date: 2026-03-19 | Feature: you_are_a_code_assistant_working_on_behalf_of_the_engineerin_

- **[architecture]** Verdict regex duplication across modules (cli vs orchestrator) — this is about duplicating business logic regex across modules. Existing entries menti
- **[code-quality]** Console/resource creation inside helpers instead of accepting as parameter — dependency injection pattern.
- **[security]** Prompt templates should prohibit LLM "cheat" fixes like `# type: ignore` or `# noqa`.
- **[architecture]** Budget cap logic relying on optional config fields having non-None defaults is fragile.
- **[code-quality]** Helpers that create their own Console/logger instances instead of accepting them as parameters break testability and consistency.
- **[architecture]** Business-logic regexes duplicated across modules drift silently; extract to a single shared constant or function.
- **[security]** Prompt templates sent to LLMs should explicitly prohibit suppression-based "fixes" like `# type: ignore` or `# noqa`.
- **[code-quality]** Optional config fields assumed non-None without guards cause crashes when defaults are absent; validate at load time.
- **[code-quality]** Helpers that create their own Console/logger instead of accepting one as a parameter break testability and consistency.
- **[architecture]** Business-logic regexes duplicated across modules drift silently; extract to a shared constant or function.
- **[security]** Prompt templates should explicitly prohibit suppression-based "fixes" like `# type: ignore` or `# noqa`.
- **[code-quality]** Optional config fields assumed non-None without guards cause crashes when defaults are missing; validate at load.
- **[code-quality]** Helpers that create their own I/O resources (e.g. Console) instead of accepting them as params reduce testability.
- **[architecture]** Business-logic regexes duplicated across modules drift silently; extract to a shared constant or function.
- **[security]** Prompt templates should prohibit LLM suppression-only fixes like `# type: ignore` or `# noqa`.
- **[code-quality]** Optional config fields assumed non-None without validation cause crashes when defaults are absent.
- **[code-quality]** Helpers that create own I/O resources (Console, logger) instead of accepting them as params reduce testability.
- **[architecture]** Business-logic regexes duplicated across modules drift silently; extract shared constants.
- **[security]** Prompt templates should explicitly prohibit suppression-only fixes like `# type: ignore` or `# noqa`.
- **[code-quality]** Optional config fields assumed non-None without guards crash when defaults are missing; validate at load time.
- **[code-quality]** Helpers that instantiate their own I/O resources (Console, logger) instead of accepting params reduce testability.
- **[architecture]** Business-logic regexes duplicated across modules drift silently; extract to a shared constant.
- **[security]** Prompt templates should explicitly prohibit suppression-only fixes like `# type: ignore` or `# noqa`.
- **[code-quality]** Optional config fields assumed non-None without validation crash when defaults are absent; validate at load time.
- **[code-quality]** Helpers that instantiate their own I/O resources instead of accepting them as parameters reduce testability.
- **[architecture]** Business-logic regexes duplicated across modules drift silently; extract to a shared constant.
- **[security]** Prompt templates should prohibit suppression-only fixes like `# type: ignore` or `# noqa`.
- **[code-quality]** Optional config fields assumed non-None without guards crash when defaults are absent; validate at load time.
- **[code-quality]** Helpers that instantiate their own I/O resources instead of accepting them as parameters reduce testability.
- **[architecture]** Business-logic regexes copied across modules drift silently; extract to a single shared constant.
- **[security]** Prompt templates should prohibit suppression-only fixes like `# type: ignore` or `# noqa`.
- **[code-quality]** Optional config fields assumed non-None without guards crash when defaults are absent; validate at load time.
- **[code-quality]** Helpers that instantiate their own I/O resources instead of accepting them as parameters reduce testability.
- **[architecture]** Business-logic regexes copied across modules drift silently; extract to a single shared constant.
- **[security]** Prompt templates should prohibit suppression-only fixes like `# type: ignore` or `# noqa`.
- **[code-quality]** Optional config fields assumed non-None without guards crash when defaults are absent; validate at load time.
- **[code-quality]** Helpers that instantiate own I/O resources instead of accepting them as params reduce testability.
- **[architecture]** Business-logic regexes copied across modules drift silently; extract to a single shared constant.
- **[security]** Prompt templates should prohibit suppression-only fixes like `# type: ignore` or `# noqa`.
- **[code-quality]** Optional config fields assumed non-None without guards crash when defaults are absent; validate at load.
- **[code-quality]** Helpers that instantiate own I/O resources instead of accepting them as params reduce testability.
- **[architecture]** Business-logic regexes copied across modules drift silently; extract to a single shared constant.
- **[security]** Prompt templates should prohibit suppression-only fixes like `# type: ignore` or `# noqa`.
- **[code-quality]** Optional config fields assumed non-None without guards crash when defaults are absent; validate at load.
- **[code-quality]** Helpers that create own I/O objects (Console, logger) instead of accepting them as params hurt testability.
- **[architecture]** Business-logic regexes copied across modules drift silently; extract to one shared constant.
- **[security]** Prompt templates should prohibit suppression-only fixes like `# type: ignore` or `# noqa`.
- **[code-quality]** Optional config fields assumed non-None without guards crash when defaults are missing; validate at load time.
- **[code-quality]** Helpers creating own I/O objects (Console, logger) instead of accepting params hurt testability.
- **[architecture]** Business-logic regexes copied across modules drift silently; extract to one shared constant.
- **[security]** Prompt templates should prohibit suppression-only fixes like `# type: ignore` or `# noqa`.
- **[code-quality]** Optional config fields assumed non-None without guards crash when defaults are missing; validate at load.
- **[code-quality]** Helpers creating own I/O objects (Console, logger) instead of accepting params hurt testability.
- **[architecture]** Business-logic regexes copied across modules drift silently; extract to one shared constant.
- **[security]** Prompt templates must prohibit suppression-only fixes like `# type: ignore` or `# noqa`.
- **[code-quality]** Optional config fields assumed non-None without guards crash when defaults are missing; validate at load.

## Run: run-20260320_025613-33b2772034
_Date: 2026-03-20 | Feature: add_a_colonyos_pr_review_pr_number_command_that_monitors_git_

- **[testing]** Verify phases must not be skipped; stochastic model outputs need structural validation before deployment.
- **[code-quality]** State capture (e.g., HEAD SHA) must happen before branch restoration in finally blocks to avoid wrong values.
- **[architecture]** IDs generated at API boundaries must be threaded through to internal components; don't let internals re-generate.
- **[testing]** Token/auth verification must target endpoints that actually require authentication to catch invalid tokens.
- **[architecture]** Implemented functions must be wired into call sites; untested integration paths are effectively dead code.

## Run: run-20260320_041029-963bfe43be
_Date: 2026-03-20 | Feature: add_a_parallel_implement_mode_that_spawns_multiple_agent_ses_

- **[code-quality]** `finally` blocks restoring state must capture return values before cleanup; calling getters after state change returns wrong data.
- **[testing]** Missing test coverage for phases/code paths explicitly required by PRDs often indicates the code itself was never implemented.
- **[architecture]** Separate deterministic logic (git checks, validation) from LLM calls to avoid wasting compute on closed-form answers.
- **[code-quality]** Use `removeprefix("* ")` not `lstrip("* ")` when stripping known prefixes; lstrip removes any matching chars.
- **[security]** Fail-closed on external API errors (GitHub, network) is the correct default; fail-open creates silent security gaps.

## Run: run-20260320_011056-33ff47e4ff
_Date: 2026-03-20 | Feature: add_a_parallel_progress_tracker_that_provides_real_time_visi_

- **[architecture]** Finally blocks that restore state (e.g., git checkout) must run after capturing post-operation values like HEAD SHA.
- **[testing]** Auth token verification must hit an auth-required endpoint; testing against public endpoints always succeeds.
- **[code-quality]** Defined-but-unused constants (e.g., blocklists) signal divergence between intent and implementation; delete or wire them in.
- **[architecture]** LLM pipeline outputs require a structural verification gate (e.g., tests) before push; skipping creates unvalidated deployments.
