# Changelog

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
