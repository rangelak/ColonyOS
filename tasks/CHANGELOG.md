# Changelog

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
