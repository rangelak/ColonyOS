# Strategic Directions

_Generated: 2026-03-27 | Iteration: 3_

## The Landscape

The autonomous coding agent space has graduated from "AI pair programming" to **"AI IS the company."** The hottest projects aren't just wiring LLMs to git — they're building organizational primitives: org charts, budgets, governance, and goal alignment. Superpowers (118K stars) proved that a structured skills-and-workflow methodology makes agents dramatically more reliable, while Paperclip (35K stars) pushed the frontier toward orchestrating entire zero-human companies with budgets and hierarchies. The energy is now in three places: **skills frameworks** that make agents methodical (Superpowers, oh-my-claudecode), **company-as-code orchestrators** that model businesses not just codebases (Paperclip, Claw-Empire), and **multi-agent coordination layers** (RuFlo, oh-my-claudecode) that run 10-100 agents in parallel. The winners all share one trait: they impose process discipline on agents, not just prompts.

## Projects Worth Studying

- **[Superpowers](https://github.com/obra/superpowers)** (118K stars): The defining skills framework. Its killer insight: agents must follow a **mandatory workflow** (brainstorm → plan → TDD → subagent execution → code review → finish), not suggestions. See `skills/subagent-driven-development` for how it dispatches fresh subagents per task with two-stage review (spec compliance, then code quality). ColonyOS's pipeline mirrors this — study how Superpowers makes each skill auto-trigger based on context.

- **[Paperclip](https://github.com/paperclipai/paperclip)** (35K stars): "If OpenClaw is an employee, Paperclip is the company." Org charts, per-agent budgets, heartbeat-based delegation, and a ticket system with immutable audit logs. The **governance model** (you're the board — approve hires, override strategy, pause agents) is exactly what ColonyOS needs for enterprise trust. Study their goal-alignment architecture: every task traces back to the company mission.

- **[oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode)** (13.5K stars): Multi-agent orchestration as a Claude Code plugin. Their `team` pipeline (`team-plan → team-prd → team-exec → team-verify → team-fix loop`) is remarkably similar to ColonyOS's flow. The `/deep-interview` command uses Socratic questioning to clarify requirements before execution — a pattern ColonyOS could adopt for `colonyos auto` to produce better PRDs.

- **[RuFlo](https://github.com/ruvnet/ruflo)** (27K stars): Enterprise-grade swarm orchestration with a Q-Learning router that learns which agents handle which tasks best. Self-learning/self-optimizing agent architecture with 130+ skills. The learning loop (agents improve routing over time from outcomes) is the most sophisticated adaptive system in the space.

- **[Cline](https://github.com/cline/cline)** (59K stars): Best-in-class permission UX — agents propose, humans approve with one click. See `src/core/Cline.ts` for the balance between autonomy and oversight. Proves that progressive-disclosure trust models beat binary "full auto / full manual" switches.

- **[gptme](https://github.com/gptme/gptme)** (4.2K stars): Lean, terminal-native agent with persistent autonomous mode. Its simplicity is instructive — a single-agent CLI that does files, shell, and browser well. Shows that a clean `pip install` + immediate productivity path matters more than feature count for adoption.

- **[Claw-Empire](https://github.com/GreenSheep01201/claw-empire)** (870 stars): Local-first agent office simulator with pixel-art UI. Agents work in **isolated git worktrees**, attend meetings, and produce deliverables. The visual metaphor (you're the CEO, agents are employees in an office) makes orchestration intuitive. Small but shows where the UX frontier is heading.

- **[AutoGen](https://github.com/microsoft/autogen)** (56K stars): Microsoft's multi-agent framework. Their `agentchat/` models agent conversations as first-class entities. The "manager + specialist" pattern maps directly to ColonyOS's CEO + persona reviews. Mature, well-documented, enterprise-backed.

## Patterns & Ideas

- **Mandatory workflows beat optional suggestions.** Superpowers' biggest lesson: skills auto-trigger based on context, agents can't skip steps. ColonyOS's pipeline already does this — lean in harder. Make the process the product.

- **Company primitives, not just agent primitives.** Paperclip models budgets, org charts, governance, and goal alignment. ColonyOS has personas — consider adding budget tracking (cost per feature), goal hierarchies (company mission → epic → task), and governance (approval gates for risky changes).

- **Subagent-per-task with fresh context.** Both Superpowers and oh-my-claudecode dispatch a clean subagent for each task rather than accumulating context in one long session. This prevents context pollution and makes failures isolated. ColonyOS's worktree-per-feature approach is the right foundation.

- **Self-improving routing.** RuFlo's Q-Learning router adapts which agent handles which task based on outcomes. ColonyOS's memory system could feed a similar loop: track which personas succeed/fail on which task types, then route accordingly.

- **Socratic requirements gathering.** oh-my-claudecode's `/deep-interview` and Superpowers' `brainstorming` skill both force clarification before execution. The best autonomous systems spend more time on "what" before touching "how."

- **Heartbeat + audit trail for trust.** Paperclip's heartbeat system (agents wake, check work, report) and immutable ticket logs make autonomous operation auditable. Enterprise adoption requires "show me what happened and why."

## User's North Star

add inspiration from https://github.com/obra/superpowers# and https://github.com/paperclipai/paperclip and the current directions document

## Watch Out For

- **Process rigidity killing iteration speed.** Superpowers enforces a strict workflow, but some users report it's too heavy for small fixes. ColonyOS should support both "full ceremony" (PRD → implement → review → PR) and "fast path" (direct agent for quick changes) — and make it easy to switch between them.

- **Agent sprawl without clear decision-makers.** crewAI and AutoGen both learned: hierarchical orchestration (manager decides) beats flat (everyone votes). ColonyOS has the CEO agent — ensure it remains the single source of truth for "what do we build next" even as the system scales.

- **Demo-ware syndrome.** Impressive GIFs, broken on real repos. Paperclip and Claw-Empire are visually stunning but nascent on real workloads. ColonyOS already builds itself — this is the strongest proof point. Publish metrics from real-world runs (cost per feature, success rate, time to PR) to build enterprise trust.
