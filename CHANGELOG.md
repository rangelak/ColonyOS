# Changelog

## 20260318_000500 — GitHub Issue Integration

Added `--issue` flag to `colonyos run` that fetches a GitHub issue (by number or URL)
and uses it as the pipeline prompt. The CEO autonomous phase now sees open issues as
context for its proposals. Issue-triggered runs produce PRs with `Closes #N` for
auto-close on merge, and `colonyos status` displays source issue URLs.

**Created:**
- `src/colonyos/github.py` — `GitHubIssue` dataclass, `fetch_issue()`, `parse_issue_ref()`, `format_issue_as_prompt()`, `fetch_open_issues()`
- `tests/test_github.py` — Unit tests for all GitHub module functions

**Modified:**
- `src/colonyos/cli.py` — `--issue` flag on `run` command, status display with issue URLs
- `src/colonyos/orchestrator.py` — Plan/deliver/CEO prompts enriched with issue context
- `src/colonyos/models.py` — `RunLog.source_issue` and `source_issue_url` fields
- `tests/test_cli.py`, `tests/test_orchestrator.py`, `tests/test_ceo.py`, `tests/test_models.py` — Extended tests

**PRD:** `cOS_prds/20260317_235155_prd_add_github_issue_integration_to_colonyos_so_users_can_point_the_pipeline_at_an_i.md`
**Tasks:** `cOS_tasks/20260317_235155_tasks_add_github_issue_integration_to_colonyos_so_users_can_point_the_pipeline_at_an_i.md`

## 20260317_215200 — Pre-commit hook for test suite

Added a `pre-commit` hook that runs `pytest` before every commit to prevent
regressions from being committed.

**Created:**
- `.pre-commit-config.yaml` — Local hook running `pytest --tb=short -q`

**Modified:**
- `pyproject.toml` — Added `[project.optional-dependencies] dev` with `pre-commit` and `pytest`

## 20260317_214623 — CEO Past-Work Context via CHANGELOG

Moved `CHANGELOG.md` to the project root, backfilled 8 missing feature entries,
and wired the changelog into the CEO prompt so proposals never duplicate past work.
The deliver phase now auto-updates the changelog after each run. CEO proposal
output renders as styled Markdown in the terminal.

**Moved:**
- `cOS_tasks/CHANGELOG.md` → `CHANGELOG.md` (project root)

**Modified:**
- `src/colonyos/orchestrator.py` — `_build_ceo_prompt()` accepts `repo_root`, reads `CHANGELOG.md`, injects into user prompt
- `src/colonyos/instructions/ceo.md` — Simplified Step 2 to reference injected changelog; added "Builds Upon" output section
- `src/colonyos/instructions/deliver.md` — New Step 2: update `CHANGELOG.md` after each run
- `src/colonyos/cli.py` — CEO proposal rendered with `rich.markdown.Markdown` inside a `Panel`
- `tests/test_ceo.py` — Updated for new `repo_root` param; added changelog injection tests

## 20260317_200233 — Cross-Run Learnings System

Added an automatic learnings extraction system that mines review artifacts after each
completed run, persists patterns to `.colonyos/learnings.md`, and injects them as
context into future implement and fix phases. Enables the pipeline to self-improve
across iterations.

**Created:**
- `src/colonyos/learnings.py` — `extract_learnings()`, `load_learnings()`, `save_learnings()`, ledger management
- `tests/test_learnings.py` — Unit tests for extraction, persistence, and injection

**Modified:**
- `src/colonyos/orchestrator.py` — Learn phase wired after deliver; learnings injected into implement/fix prompts
- `src/colonyos/config.py` — `learnings` config section (`enabled`, `max_entries`)
- `src/colonyos/cli.py` — `status` command shows learnings count
- `src/colonyos/models.py` — `Phase.LEARN` enum value

**PRD:** `cOS_prds/20260317_200233_prd_add_a_cross_run_learnings_system_that_automatically_extracts_patterns_from_revie.md`
**Tasks:** `cOS_tasks/20260317_200233_tasks_add_a_cross_run_learnings_system_that_automatically_extracts_patterns_from_revie.md`

## 20260317_200000 — Auto-approve config + README rebrand

Added `auto_approve` config setting for unattended CEO-driven runs and rebranded
the README to position ColonyOS as a fully autonomous self-building pipeline.

**Changes:**
- `src/colonyos/config.py` — Added `auto_approve: bool` field to `ColonyConfig`, parsed from YAML, serialized back
- `src/colonyos/cli.py` — `auto` command checks `config.auto_approve or no_confirm` to skip human confirmation
- `.colonyos/config.yaml` — Added `auto_approve: true` (dogfood: this repo runs fully autonomous)
- `README.md` — New tagline ("The fully autonomous AI pipeline that builds itself"), Mermaid pipeline diagrams, autonomous-first copy, expanded CLI reference
- `assets/logo.png` — Added project logo
- `tests/test_config.py` — Added `TestAutoApprove` class (default, parse, roundtrip)
- `tests/test_cli.py` — Added tests for `auto_approve` config skipping confirmation and prompting when false

## 20260317_192516 — Standalone `colonyos review <branch>` command

Added a `colonyos review <branch>` CLI command that runs only the review/fix loop
against an arbitrary Git branch, without requiring a PRD or task file. Enables
ColonyOS as a lightweight standalone multi-persona code review tool.

**Created:**
- `src/colonyos/instructions/review_standalone.md` — Standalone review instruction template
- `src/colonyos/instructions/fix_standalone.md` — Standalone fix instruction template
- `src/colonyos/instructions/decision_standalone.md` — Standalone decision instruction template

**Modified:**
- `src/colonyos/cli.py` — Added `review` command with `--base`, `--no-fix`, `--decide` options
- `src/colonyos/orchestrator.py` — Added `run_review_standalone()` function
- `tests/test_cli.py` — Tests for the review command

**PRD:** `cOS_prds/20260317_192516_prd_add_a_colonyos_review_branch_cli_command_that_runs_only_the_review_fix_loop_and.md`
**Tasks:** `cOS_tasks/20260317_192516_tasks_add_a_colonyos_review_branch_cli_command_that_runs_only_the_review_fix_loop_and.md`

## 20260317_183545 — Post-Implement Verification Gate

Added a configurable verification gate between implement and review that runs a
user-specified test command (e.g., `pytest`, `npm test`) via subprocess. Failed
tests trigger implement retries with failure context before the expensive review
phase fires.

**Created:**
- `src/colonyos/instructions/verify_fix.md` — Verify-fix instruction template
- `tests/test_verify.py` — Full unit tests for the verification loop

**Modified:**
- `src/colonyos/models.py` — `Phase.VERIFY` enum value
- `src/colonyos/config.py` — `VerificationConfig` dataclass (`verify_command`, `max_verify_retries`, `verify_timeout`)
- `src/colonyos/orchestrator.py` — `run_verify_loop()` wired between implement and review
- `src/colonyos/init.py` — Auto-detect test runner during `colonyos init` (`_detect_test_command`)
- `tests/test_config.py`, `tests/test_init.py`, `tests/test_orchestrator.py` — Extended tests

**PRD:** `cOS_prds/20260317_183545_prd_add_a_configurable_post_implement_verification_gate_that_runs_the_project_s_test.md`
**Tasks:** `cOS_tasks/20260317_183545_tasks_add_a_configurable_post_implement_verification_gate_that_runs_the_project_s_test.md`

## 20260317_180000 — Review/fix loop redesign: per-persona parallel reviews + fix agent

Replaced the monolithic subagent-based review with independent per-persona parallel
sessions and a dedicated fix agent loop. Reviews are now fast, focused, and configurable.

**Architecture change:**
- Old: 1 session per task with 7 subagents nested → holistic review → decision → fix loop
- New: N reviewer personas run in parallel via asyncio.gather → if request-changes, fix agent runs → re-review → decision gate

**Changes:**
- `src/colonyos/models.py` — Added `reviewer: bool = False` field to `Persona` dataclass
- `src/colonyos/config.py` — Parse/serialize `reviewer` in `_parse_personas`, `_parse_persona`, `save_config`
- `src/colonyos/init.py` — Ask "Should this persona participate in code reviews?" during persona collection
- `src/colonyos/agent.py` — Added `run_phases_parallel()` and `run_phases_parallel_sync()` for concurrent phase execution
- `src/colonyos/orchestrator.py` — Deleted `_build_review_persona_agents`, `_format_review_personas_block`, per-task review loop; added `_reviewer_personas`, `_build_persona_review_prompt`, `_extract_review_verdict`, `_collect_review_findings`; rewrote Phase 3 as review/fix loop
- `src/colonyos/instructions/review.md` — Persona identity baked into template (`{reviewer_role}`, `{reviewer_expertise}`, `{reviewer_perspective}`); structured VERDICT output required
- `src/colonyos/instructions/fix.md` — Staff+ Google Engineer identity; uses `{findings_text}` from reviewer findings
- `.colonyos/config.yaml` — Tagged 4 personas as reviewers; added `proposals_dir`, `max_fix_iterations`
- `tests/test_orchestrator.py` — Full rewrite for new parallel review + fix loop architecture
- `tests/test_config.py` — Added `TestReviewerField` class
- `tests/test_ceo.py` — Updated integration test for parallel review mocking

## 20260317_173500 — Welcome banner with ASCII ant and commands

Added a Claude Code–style welcome banner when running `colonyos` with no subcommand.
Shows an ASCII ant mascot, the ColonyOS logo in big letters, version/model info,
working directory, and a command reference.

**Changes:**
- `src/colonyos/cli.py` — Added `_show_welcome()` function with rich Panel/Table layout; changed `app` group to `invoke_without_command=True` with `@click.pass_context` to show banner when no subcommand given

## 20260317_172645 — Rich Streaming Terminal UI

Added a streaming terminal UI using the `rich` library that shows real-time agent
activity during pipeline execution. Each phase renders tool calls as they happen,
and parallel reviews show per-persona prefixed output.

**New:**
- `src/colonyos/ui.py` — `PhaseUI` class with streaming callbacks (tool_start, tool_input_delta, tool_done, text_delta, turn_complete); `NullUI` no-op for tests/quiet mode; `TOOL_DISPLAY` mapping for extracting primary args from partial JSON
- `-v/--verbose` flag on `run` and `auto` — streams agent text alongside tool activity
- `-q/--quiet` flag on `run` and `auto` — suppresses streaming UI
- `rich>=13.0` added to `pyproject.toml`

**Modified:**
- `src/colonyos/agent.py` — `run_phase()` accepts `ui` param; enables `include_partial_messages` when ui present; processes `StreamEvent` (content_block_start/delta/stop) and `AssistantMessage` for turn counting
- `src/colonyos/orchestrator.py` — `run()` and `run_ceo()` accept `verbose`/`quiet`; creates `PhaseUI` per phase; parallel reviews get `PhaseUI(prefix="[Role] ")`; falls back to `_log()` when ui is None
- `src/colonyos/cli.py` — Added `-v`/`-q` flags to `run` and `auto` commands; passed through to orchestrator and `_run_single_iteration`

**PRD:** `cOS_prds/20260317_172645_prd_rich_streaming_terminal_ui_for_agent_phases.md`
**Tasks:** `cOS_tasks/20260317_172645_tasks_rich_streaming_terminal_ui_for_agent_phases.md`

## 20260317_163656 — Developer Onboarding & Long-Running Autonomous Loops

Added `colonyos doctor` for prerequisite validation, overhauled the README with
badges and visual proof, and removed the artificial loop cap to enable 24+ hour
autonomous runs with time-based budget caps.

**Created:**
- `src/colonyos/doctor.py` — Prerequisite checks (Python, Claude Code CLI, Git, GitHub CLI)

**Modified:**
- `src/colonyos/cli.py` — `doctor` command; `--loop` removed iteration cap, added time-based budget enforcement
- `src/colonyos/init.py` — `check_prereqs()` runs at start of `colonyos init`
- `README.md` — Badges, terminal GIF placeholder, "wall of self-built PRs" section
- `tests/test_cli.py`, `tests/test_init.py` — Tests for doctor and prereq checks

**PRD:** `cOS_prds/20260317_163656_prd_i_want_this_to_be_super_easy_to_set_up_if_you_re_a_dev_you_should_be_able_to_be.md`
**Tasks:** `cOS_tasks/20260317_163656_tasks_i_want_this_to_be_super_easy_to_set_up_if_you_re_a_dev_you_should_be_able_to_be.md`

## 20260317_155508 — Resume Failed Runs (`--resume`)

Added `--resume <run-id>` flag to `colonyos run` that resumes a previously failed
run from the next phase after the last successfully completed one. Saves cost by
skipping phases that already succeeded.

**Modified:**
- `src/colonyos/cli.py` — `--resume` flag on `run` command; validates resumable state
- `src/colonyos/orchestrator.py` — `run()` accepts `skip_phases` set; `_compute_next_phase()` for resume logic
- `src/colonyos/models.py` — `RunLog` tracks per-phase completion status
- `src/colonyos/cli.py` — `status` command shows `[resumable]` next to failed runs

**PRD:** `cOS_prds/20260317_155508_prd_add_a_resume_run_id_flag_to_colonyos_run_that_resumes_a_previously_failed_run_fr.md`
**Tasks:** `cOS_tasks/20260317_155508_tasks_add_a_resume_run_id_flag_to_colonyos_run_that_resumes_a_previously_failed_run_fr.md`

## 20260317_150000 — Address persona review findings + decision gate

Addressed all CRITICAL/HIGH findings from the 7-persona review of the CEO stage.
Added a decision gate between review and deliver that gives a GO/NO-GO verdict.

**Fixes:**
- `src/colonyos/naming.py` — Truncate slugs to 80 chars max (fixes OSError: File name too long)
- `src/colonyos/orchestrator.py` — `_extract_feature_prompt` uses case-insensitive regex, handles ### terminators, strips code fences
- `src/colonyos/orchestrator.py` — Proposal only saved on success; removed "save your proposal" from CEO prompt
- `src/colonyos/cli.py` — CEO phase recorded in RunLog; `_print_run_summary` helper extracted; success check before display
- `src/colonyos/cli.py` — `--loop` capped at 10 iterations with aggregate budget enforcement via `per_run`
- `src/colonyos/cli.py` — `--plan-only` renamed to `--propose-only` on `auto` command
- `src/colonyos/init.py` — Preserves `ceo_persona` when re-running init

**New features:**
- `src/colonyos/instructions/decision.md` — Decision gate instruction template
- `src/colonyos/orchestrator.py` — `_build_decision_prompt`, `_extract_verdict`, wired between review and deliver
- `src/colonyos/models.py` — `Phase.DECISION` enum value
- Pipeline now: plan → implement → review → **decision gate** → deliver

## 20260317_133813 — Autonomous CEO Stage (`colonyos auto`)

Added `colonyos auto` command where an AI CEO persona analyzes the project, its
history, and strategic direction to autonomously decide what to build next. The
CEO's output feeds directly into the Plan → Implement → Review → Deliver pipeline.

**Created:**
- `src/colonyos/instructions/ceo.md` — CEO instruction template with project analysis and proposal format

**Modified:**
- `src/colonyos/cli.py` — `auto` command with `--no-confirm`, `--propose-only`, `--loop` flags
- `src/colonyos/orchestrator.py` — `run_ceo()` function, `_build_ceo_prompt()`, `_extract_feature_prompt()`
- `src/colonyos/config.py` — `ceo_persona` and `proposals_dir` config fields
- `.colonyos/config.yaml` — CEO persona definition and vision statement
- `tests/test_ceo.py` — Integration tests for the CEO phase

**PRD:** `cOS_prds/20260317_133813_prd_autonomous_ceo_stage.md`
**Tasks:** `cOS_tasks/20260317_133813_tasks_autonomous_ceo_stage.md`

## 20260317_100000 — Add iconic personas + parallel subagent Q&A

Added Steve Jobs, Jony Ive, Linus Torvalds, and Andrej Karpathy as personas.
Replaced Elon Musk and Sindre Sorhus. Each persona now runs as a separate
Agent SDK subagent during the plan phase, so all 7 personas answer clarifying
questions in parallel rather than sequentially in a single session.

**Changes:**
- `.colonyos/config.yaml` — 7 personas (was 5), fixed stack reference
- `src/colonyos/orchestrator.py` — `_build_persona_agents()` creates `AgentDefinition` per persona,
  `_format_personas_block()` now lists subagent keys and instructs parallel invocation
- `src/colonyos/agent.py` — accepts `agents` kwarg, adds `Agent` to allowed tools when subagents present
- `src/colonyos/instructions/plan.md` — explicit instruction to call all persona agents in parallel
- `tests/test_orchestrator.py` — tests for `_build_persona_agents`, `_persona_slug`, subagent plumbing

## 20260317_090603 — Persona Review Phase & cOS_ Directory Prefix

Added a multi-persona review phase between Implement and Deliver. Every defined
persona reviews completed tasks and performs a holistic assessment. All ColonyOS
output directories now use the `cOS_` prefix (`cOS_prds/`, `cOS_tasks/`, `cOS_reviews/`)
to clearly namespace agent-generated artifacts.

**Created:**
- `src/colonyos/instructions/review.md` — Review instruction template
- `cOS_reviews/` — Review artifact output directory

**Modified:**
- `src/colonyos/orchestrator.py` — Review phase wired between implement and deliver; per-persona reviews
- `src/colonyos/config.py` — Default directories changed to `cOS_prds`, `cOS_tasks`; added `reviews_dir: cOS_reviews`
- `.colonyos/config.yaml` — Updated directory defaults
- `tests/test_orchestrator.py` — Tests for review phase

**PRD:** `cOS_prds/20260317_090603_prd_persona_review_phase_and_cos_directory_prefix.md`
**Tasks:** `cOS_tasks/20260317_090603_tasks_persona_review_phase_and_cos_directory_prefix.md`

## 20260317_083203 — Prebuilt Persona Templates for `colonyos init`

Added curated persona packs ("Startup Team", "Enterprise Backend", "Frontend/Design",
etc.) that users can select during `colonyos init` instead of defining custom personas
from scratch. Reduces onboarding friction from ~12 prompts to 1 selection.

**Modified:**
- `src/colonyos/init.py` — `_PERSONA_PACKS` dict with curated templates; selection prompt during init
- `tests/test_init.py` — Tests for persona pack selection
- `tests/test_cli.py` — CLI integration tests for init with packs

**PRD:** `cOS_prds/20260317_083203_prd_we_should_be_able_to_offer_the_users_prebuilt_personas_when_they_initialize.md`
**Tasks:** `cOS_tasks/20260317_083203_tasks_we_should_be_able_to_offer_the_users_prebuilt_personas_when_they_initialize.md`

## 20260316_180500 — Migrate to Claude Agent SDK

Replaced `claude-code-sdk` (0.0.25) with the renamed `claude-agent-sdk` (0.1.49).
The old SDK had a critical incompatibility: it couldn't parse `rate_limit_event` messages
from the Claude Code CLI, causing `MessageParseError` and preventing `ResultMessage` from
being received. The new SDK handles all message types natively.

**Changes:**
- `src/colonyos/agent.py` — Rewrote to use `ClaudeAgentOptions` (was `ClaudeCodeOptions`),
  removed `MessageParseError` workaround, removed `got_assistant_msg` fallback logic.
  Now uses `max_budget_usd` option directly instead of custom budget handling.
- `pyproject.toml` — Dependency changed from `claude-code-sdk>=0.0.25` to `claude-agent-sdk>=0.1.49`
- `requirements.txt` — Same dependency update
- `README.md` — References updated from "Claude Code SDK" to "Claude Agent SDK"
- `tasks/20260316_172530_tasks_agent_loop_cli.md` — Added task 10.0 for SDK migration

## 20260316_172530 — ColonyOS v2: Clean Slate Build

Full rewrite of ColonyOS from a standalone Python CLI to an installable tool
orchestrating Claude Agent SDK sessions with full repo awareness.

**Created:**
- `src/colonyos/` — Full package: cli, config, agent, orchestrator, init, models, naming
- `src/colonyos/instructions/` — Markdown templates for each phase
- `tests/` — Unit tests for config, naming, orchestrator, CLI
- `prds/20260316_172530_prd_agent_loop_cli.md` — Self-referential PRD
- `tasks/20260316_172530_tasks_agent_loop_cli.md` — Implementation task list
- `.colonyos/config.yaml` — Project config with 5 expert personas
- `README.md` — Full documentation
- `pyproject.toml`, `requirements.txt` — Package configuration
