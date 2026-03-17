# Changelog

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
