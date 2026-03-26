# ColonyOS Learnings Ledger


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

## Run: run-20260319_230625-dbdcda5b59
_Date: 2026-03-19 | Feature: can_we_make_colonyos_setup_choice_one_where_an_assistant_set_

- **[code-quality]** Fixed-length error truncation can bisect redacted tokens, creating apparent credential leaks in persisted logs.
- **[architecture]** Budget/quota enforcement must pre-check remaining capacity before starting work; post-only checks allow one full overshoot.
- **[style]** Float equality/inequality comparisons for budget thresholds are fragile due to IEEE 754 rounding; use epsilon tolerance.
- **[code-quality]** Placeholder values (SHA256 hashes, URLs) shipped in release artifacts cause install failures; gate releases on validation.

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

## Run: run-20260323_190105-e2ce90ba80
_Date: 2026-03-23 | Feature: give_me_fucking_awesome_ux_that_is_a_fucking_amazing_experie_

- **[code-quality]** API endpoints returning fabricated IDs before the real ID is created cause downstream 404s; thread actual IDs end-to-end.
- **[security]** Inconsistent output sanitization across sibling API routes (e.g., one list endpoint sanitizes, its detail endpoint doesn't) creates gaps.
- **[style]** First-party module imports deferred inside function bodies for non-optional deps signal hasty code; keep at module top-level.
- **[code-quality]** `encodeURIComponent` encodes `/` to `%2F`, breaking APIs with path-style route params; use a path-aware encoding helper.
- **[code-quality]** Frontend error handling must distinguish network failures from HTTP API errors to surface meaningful messages to users.

## Run: run-20260326_134656-6634005688
_Date: 2026-03-26 | Feature: no_right_now_the_direct_agent_path_is_basically_stateless_be_

- **[security]** External API string fields interpolated into prompt/XML delimiters must be escaped to prevent structure injection.
- **[style]** Underscore-prefixed functions imported across module boundaries break encapsulation; make public or extract shared.
- **[code-quality]** Functions returning True for empty collections (e.g., `all_checks_pass([])`) silently mask missing-data edge cases.
- **[style]** Lockfiles (package-lock.json) must be committed, not gitignored, to ensure reproducible builds across contributors.
- **[architecture]** CLI flags with implicit dependencies (e.g., `--max-retries` requiring `--wait`) must validate co-constraints at parse time.
