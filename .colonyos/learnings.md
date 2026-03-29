# ColonyOS Learnings Ledger


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

## Run: run-20260326_164228-66f1eba7a9
_Date: 2026-03-26 | Feature: add_memory_to_the_system_https_github_com_thedotmack_claude__

- **[code-quality]** Character-count string truncation can split multi-byte UTF-8 sequences; use byte-aware or grapheme-aware slicing.
- **[testing]** Tests tightly coupled to implementation internals (e.g., retry counts, timing) break on refactors; assert observable behavior.
- **[code-quality]** Status enums and process exit codes must agree semantically; COMPLETED status with non-zero exit misleads callers.
- **[security]** Security-sensitive conditions (e.g., author mismatch) should be hard gates requiring `--force`, not silent warnings.
- **[code-quality]** Redaction blocklist helpers need inline comments listing which fields are excluded and why to prevent silent drift.

## Run: run-20260327_171407-a3191077da
_Date: 2026-03-27 | Feature: add_support_for_auto_inside_the_tui_the_tui_should_be_the_de_

- **[architecture]** Feature branches bundling unrelated changes (CI/CD, install scripts, versioning) inflate diffs and increase review risk.
- **[architecture]** CI-provider-specific logic (e.g., GitHub Actions state/conclusion values) must document the assumed provider explicitly.
- **[architecture]** Unbounded collection endpoints (queue add) without configurable size caps risk runaway resource consumption.
- **[code-quality]** Unused imports left after refactoring signal incomplete cleanup; remove promptly to avoid misleading readers.

## Run: run-20260329_155000-bedecbf76f
_Date: 2026-03-29 | Feature: colonyos_needs_to_be_fully_autonomous_we_deploy_it_to_a_proj_

- **[architecture]** Config/state must be reloaded between loop iterations; stale config from startup causes silent behavioral drift.
- **[code-quality]** Deserialization from user-editable files must handle missing/extra keys gracefully, not raise raw KeyError/TypeError.
- **[code-quality]** Utility helpers (e.g., duration formatting) copy-pasted within a file instead of calling existing functions accumulate drift.
- **[security]** State-mutating operations (add, clear, delete) on persistent files need append-only audit logging for traceability.
- **[security]** Persistent state files created with default umask need explicit restrictive permissions when scope expands beyond single user.
