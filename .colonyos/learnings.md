# ColonyOS Learnings Ledger


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

## Run: run-20260329_213252-42be53518d
_Date: 2026-03-29 | Feature: when_we_implement_a_new_functionality_from_the_tasks_it_shou_

- **[architecture]** CLI god files (2000+ lines) must be decomposed into per-command modules; monolithic CLIs resist review and testing.
- **[testing]** Functions returning truthy for empty collections (e.g., `all([])`) silently pass; add explicit empty-input guards.
- **[architecture]** Feature branches must be scoped to a single PRD; bundling unrelated changes inflates diffs and obscures review.
- **[security]** Sibling API endpoints (list vs detail) must apply identical output sanitization; inconsistent coverage creates XSS gaps.
- **[code-quality]** Defined-but-unwired code paths (helpers, config fields, aliases) add maintenance cost; delete or integrate before merge.

## Run: run-20260329_225200-3d45c3c7a5
_Date: 2026-03-30 | Feature: the_following_github_issue_is_the_source_feature_description_

- **[code-quality]** Crash-recovery `finally` blocks using invalid stdlib checks (e.g., `os.get_inheritable` for fd liveness) mask the original error.
- **[code-quality]** Dead parameters accepted but never read inside a function mislead callers and signal incomplete refactoring.
- **[architecture]** Rich console renderers should accept a `Console` instance, not create their own, to enable test output capture.
- **[testing]** `useEffect` polling with stale closures (state in dependency array) causes interval churn; use `useRef` for latest value.
- **[security]** CORS allow-origin for dev hosts (e.g., localhost:5173) must be conditional on a dev/debug flag, not unconditional.

## Run: run-20260330_091744-320de775ff
_Date: 2026-03-30 | Feature: add_a_pr_outcome_tracking_system_that_monitors_the_fate_of_p_

- **[code-quality]** Duplicated logic (e.g., verdict regexes, duration formatting) across modules causes silent divergence; extract to shared utils.
- **[architecture]** Prompt templates using natural-language directory descriptions are fragile for LLMs; use explicit glob patterns and concrete paths.
- **[code-quality]** `from_dict()`/deserialization helpers that raise raw KeyError on malformed input need try/except with fallback defaults.
- **[testing]** Rich console renderers that create their own `Console()` instance break test output capture; accept console as a parameter.
- **[security]** External API string fields interpolated into XML/prompt structural attributes (not just body) must be escaped separately.

## Run: run-20260330_182656-36e04103ef
_Date: 2026-03-30 | Feature: you_are_a_code_assistant_working_on_behalf_of_the_engineerin_

- **[code-quality]** Single `os.write()` calls for serialization can exceed pipe/fd buffer limits; use `os.fdopen()` + buffered `.write()`.
- **[code-quality]** Optional config fields compared with `<`/`>` without None guards raise TypeError; validate non-None before arithmetic.
- **[architecture]** Superseded dataclasses kept alongside their replacements accumulate dead abstractions; remove the old type promptly.
- **[testing]** Auth token validation that catches network errors as "success" silently accepts any token when the server is unreachable.
- **[architecture]** Instruction/prompt templates describing file locations in prose are fragile; use explicit glob patterns or concrete paths.
- **[code-quality]** Single `os.write()` calls for serialization can exceed pipe/fd buffer limits; use `os.fdopen()` + buffered `.write()`.
- **[code-quality]** Optional config fields compared with `<`/`>` without None guards raise TypeError; validate non-None before arithmetic.
- **[architecture]** Superseded dataclasses kept alongside their replacements accumulate dead abstractions; remove the old type promptly.
- **[testing]** Auth validation that catches network errors as "success" silently accepts any token when the server is unreachable.
- **[code-quality]** Single `os.write()` for large payloads can exceed fd buffer limits; use `os.fdopen()` with buffered `.write()` instead.
- **[code-quality]** Optional config fields compared with arithmetic operators without None guards raise TypeError at runtime.
- **[architecture]** Superseded dataclasses kept alongside replacements accumulate dead abstractions; remove the old type promptly.
- **[testing]** Auth validation catching network errors as "success" silently accepts any token when the server is unreachable.

## Run: run-20260331_131622-df4825679a
_Date: 2026-03-31 | Feature: you_are_a_code_assistant_working_on_behalf_of_the_engineerin_

- **[security]** Format-string interpolation of untrusted LLM output (`str.format()`) causes KeyError crashes and config value leakage.
- **[code-quality]** Budget guard arithmetic must account for full fix-cycle cost (fix + review + decision), not just a single phase.
- **[security]** Fix-loop re-invocations of review agents must carry the same `allowed_tools` restrictions as the initial review call.
- **[code-quality]** Falsy-zero bugs (`max_budget or default`) silently discard explicit zero values; use `is None` checks for optional numerics.
- **[architecture]** Extract repeated fix-loop and cost-computation logic into dedicated helpers; inline duplication causes silent divergence.

## Run: run-20260401_130207-e353c24c35
_Date: 2026-04-01 | Feature: you_are_a_code_assistant_working_on_behalf_of_the_engineerin_

- **[architecture]** Retry loops polling external systems must confirm state refresh between iterations; re-fetching before propagation wastes cycles.
- **[code-quality]** Private aliases (`_fn = fn`) for brand-new functions under backward-compat claims add noise; pick one canonical name.
- **[code-quality]** LLM agent instruction templates should prohibit suppression annotations (`# type: ignore`, `# noqa`) as valid fixes.
- **[architecture]** Aggregation modules that dynamically enumerate categories from data avoid code changes when new variants are added.

## Run: run-20260402_003710-8eeeb1a6b1
_Date: 2026-04-02 | Feature: you_are_a_code_assistant_working_on_behalf_of_the_engineerin_

- **[architecture]** Pre-flight validation chains should order checks cheapest-first (local before network) to fail fast.
- **[architecture]** Persist run state before entering crash-prone loops so prior phase results survive unexpected termination.
- **[architecture]** New feature configs should default to disabled for backward-compatible, opt-in rollout.
- **[architecture]** Autonomous loops need two independent circuit breakers (budget + retry cap) to bound runaway execution.
- **[code-quality]** API calls fetching overlapping data (e.g., matrix builds) must deduplicate by natural key to avoid redundant work.

## Run: run-20260402_054259-44703b6686
_Date: 2026-04-02 | Feature: colonyos_daemon_py_recovery_context_previous_branch_colonyos_

- **[architecture]** Signal handlers must persist in-progress state transitions before exiting to enable crash recovery on restart.
- **[architecture]** Pre-flight validation chains should order checks by cost (cheapest first) to fail fast before expensive ops.
- **[code-quality]** Regex-based verdict parsing of LLM prose is fragile and cross-cutting; centralize in one module to limit drift.
- **[testing]** Factory functions accepting injectable timestamps/clocks enable deterministic testing of time-dependent paths.
- **[security]** Aggregate caps on concatenated untrusted input (beyond per-item limits) are needed to prevent prompt bloat attacks.

## Run: run-20260402_022155-d1ec4c42a0
_Date: 2026-04-02 | Feature: you_are_a_code_assistant_working_on_behalf_of_the_engineerin_

- **[security]** GitHub Actions pinned by commit SHA, not mutable tag, prevent supply chain attacks via tag rewriting.
- **[architecture]** Pre-flight validation steps should be ordered cheapest-first (local checks before remote API calls) to fail fast.
- **[security]** Aggregate char caps on external inputs (e.g., CI logs fed to LLMs) are needed to prevent prompt bloat attacks.
- **[code-quality]** Polling intervals should stop when the monitored resource reaches a terminal state to avoid unnecessary load.
- **[security]** SPA catch-all file-serving routes must validate resolved paths stay within the static asset root directory.

## Run: run-20260402_012507-47a62348e1
_Date: 2026-04-02 | Feature: you_are_a_code_assistant_working_on_behalf_of_the_engineerin_

- **[architecture]** Pre-flight validation chains should order checks cheapest-first (e.g., local auth before network calls) to fail fast efficiently.
- **[code-quality]** Run state must be persisted to disk before entering retry/fix loops so completed phase results survive mid-loop crashes.
- **[security]** Auth token comparison must use constant-time functions (e.g., `secrets.compare_digest`) to prevent timing side-channel attacks.
- **[security]** Write/mutate API capabilities should be gated behind an explicit opt-in flag (env var or config), not enabled by default.
- **[code-quality]** Tail-biased log truncation preserves error context better than head-biased for CI/build logs where failures appear last.

## Run: run-20260401_235107-7d1db511f2
_Date: 2026-04-02 | Feature: you_are_a_code_assistant_working_on_behalf_of_the_engineerin_

- **[architecture]** Public functions must validate own inputs (e.g., path traversal), not assume callers pre-validated; enforce at API boundary.
- **[code-quality]** Functions returning untagged unions (`str | list[str]`) for branching are fragile; use dedicated result dataclasses.
- **[architecture]** Read-only polling endpoints re-reading all files from disk per request need a TTL cache layer under frequent polling.
- **[code-quality]** `--json` CLI output should serialize the computed view model, not raw persisted data, to match terminal UI fields.
- **[security]** SPA catch-all routes serving static files must validate resolved paths stay within the dist directory via containment check.

## Run: run-20260405_233459-6fb22baa8d
_Date: 2026-04-06 | Feature: when_you_run_the_daemon_slack_watch_when_you_finish_a_featur_

- **[security]** Regex secret-redaction patterns must be ordered most-specific-first; generic patterns shadow specific ones causing partial leaks.
- **[architecture]** External API callers hitting rate-limited endpoints need client-side debounce; per-call flushing degrades under real load.
- **[code-quality]** Reusing enum values for semantically different operations (e.g., Phase.TRIAGE for summaries) corrupts cost attribution and telemetry.
- **[code-quality]** Bare `except Exception: pass` blocks swallow import and runtime errors silently; always log at debug level minimum.
- **[architecture]** Resource handles (DB connections, API clients) should be passed caller-to-callee, not reopened per function call.

## Run: run-20260406_102116-2f5769d446
_Date: 2026-04-06 | Feature: the_colonyos_agents_should_be_able_to_do_such_installations__

- **[code-quality]** Negative prohibitions in LLM instruction templates cause over-inhibition; replace with positive actionable step-by-step workflows.
- **[code-quality]** Error recovery handlers must reset all accumulated mutable state (buffers, timestamps, IDs) to prevent stale context in subsequent operations.
- **[architecture]** Programmatic output constraints (hard truncation, sanitization) must backstop LLM prompt instructions; models don't reliably obey format directives.
- **[code-quality]** Defensive try/except blocks must wrap all related operations in a group; leaving one call outside creates an inconsistent failure surface.
- **[architecture]** Sibling templates serving the same role (e.g., review.md vs review_standalone.md) must be updated atomically to prevent enforcement drift.
