# Strategic Directions

_Generated: 2026-03-27 | Iteration: 4_

## The Landscape

The autonomous coding agent market has stratified into three clear tiers:
**foundation orchestrators** like crewAI and AutoGen that provide the
multi-agent primitives, **full-stack autonomous devs** like OpenHands, Cline,
and Aider that own the issue-to-PR loop, and **persona/memory systems** like
gstack, mem0, and OpenClaw that make agents sharper over time. The hottest
pattern right now is **persona-driven specialization**. Garry Tan's gstack and
similar systems prove that focused, opinionated roles outperform generic
"do-everything" agents when the work gets real. At the same time, the earlier
wave of **skills frameworks** and **company-as-code orchestrators** still
matters. Superpowers showed that mandatory workflows make agents more reliable,
while Paperclip pushed toward org charts, budgets, governance, and
goal-tracking. ColonyOS should treat the new three-tier framing as an
extension of those earlier lessons, not a replacement.

ColonyOS should position itself at the intersection of these layers as **the
autonomous company**: not just a coding agent, but a full-stack autonomous
software company with strong persona specialization, memory that compounds
across runs, extensibility points that let the system grow beyond the core
pipeline, and governance primitives that make the company legible and
controllable.

## Projects Worth Studying

1. **[OpenClaw](https://github.com/thedotmack/openclaw)** (328K stars): The
   Skills Registry model is the main lesson. ColonyOS needs first-class
   extension points so new capabilities can plug in as composable skills rather
   than one-off hardcoded phases.

2. **[gstack](https://github.com/zyapman/gstack)** (33K stars): The clearest
   proof that persona-driven specialization works. Its opinionated role design
   is the most direct inspiration for ColonyOS's CEO, planner, implementer,
   reviewer, and fix loops.

3. **[OpenHands](https://github.com/All-Hands-AI/OpenHands)** (69K stars):
   Sandboxed execution plus real benchmark pressure. The key takeaway is that
   true autonomy requires isolated execution environments and measurable
   real-world performance, not just flashy demos.

4. **[Cline](https://github.com/cline/cline)** (59K stars): Best-in-class
   permission UX. Cline shows that progressive human oversight beats binary
   "manual vs full-auto" switches for trust and adoption.

5. **[AutoGen](https://github.com/microsoft/autogen)** (56K stars): Still the
   reference for structured multi-agent conversations. The manager-plus-specialist
   pattern maps directly to ColonyOS's hierarchical orchestration model.

6. **[mem0](https://github.com/mem0ai/mem0)** (51K stars): Memory
   stratification is the lesson here. Episodic memory and semantic memory need
   to be treated as separate systems once the project history gets large.

7. **[crewAI](https://github.com/crewAIInc/crewAI)** (47K stars): Strong
   role-task-crew hierarchy. Useful for understanding how to make roles,
   assignments, and delegation first-class rather than implicit.

8. **[Aider](https://github.com/Aider-AI/aider)** (42K stars): Repo maps solve
   context-window exhaustion better than just throwing larger models at the
   problem. ColonyOS should eventually build or adopt a comparable repo-map
   abstraction.

## Additional Prior Directions To Keep

- **[Superpowers](https://github.com/obra/superpowers)**: Still one of the most
  important projects in the space even if it is not in the "8 verified to
  study" list above. Its core lesson is that **mandatory workflow discipline**
  beats optional best-practice suggestions. ColonyOS should keep learning from
  its subagent-driven development flow and auto-triggered skills model.

- **[Paperclip](https://github.com/paperclipai/paperclip)**: The strongest
  reference for **company primitives** like budgets, heartbeats, governance,
  and mission alignment. ColonyOS should keep borrowing from this if the goal
  is "AI is the company," not just "AI helps write code."

- **[oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode)**:
  Worth preserving because its `team-plan -> team-prd -> team-exec ->
  team-verify -> team-fix` loop is very close to ColonyOS's own orchestration
  shape, and its Socratic requirement-clarification pattern is still highly
  relevant.

- **[RuFlo](https://github.com/ruvnet/ruflo)**: Keep this in view for
  self-improving routing. Its learning-based agent selection is still one of
  the best references for how ColonyOS could evolve persona/task routing over
  time.

- **[gptme](https://github.com/gptme/gptme)**: Important as a reminder that a
  clean terminal-native UX and a lightweight install path matter for adoption,
  not just architecture sophistication.

- **[Claw-Empire](https://github.com/GreenSheep01201/claw-empire)**: Still
  useful as a UX frontier reference. Even if it is not yet a mature benchmark
  for real codebase execution, the office/CEO metaphor remains instructive for
  how to make orchestration legible to humans.

## Patterns & Ideas

- **Persona specialization beats general agents.** The strongest systems are
  built from clear, opinionated roles with crisp responsibilities.

- **Memory stratification is non-negotiable at scale.** Episodic run history,
  semantic repository knowledge, and distilled learnings should not all live in
  the same bucket.

- **Skills and tools as extension points unlock ecosystem growth.** OpenClaw's
  extensibility model is a reminder that ColonyOS should not try to ship every
  capability in the core binary.

- **Mandatory workflows beat optional suggestions.** This remains the central
  Superpowers lesson and should stay core to ColonyOS thinking. The pipeline
  should feel like the product, not just scaffolding around prompts.

- **Sandboxing unlocks true autonomy.** OpenHands proves that serious
  autonomous execution requires isolation. Worktrees are a start, but stronger
  sandboxing is the long-term direction.

- **Repo maps beat brute-force context stuffing.** Aider's approach is the best
  answer to context-window exhaustion and should inform how ColonyOS feeds code
  structure into agents.

- **Permission UX matters as much as model quality.** Cline shows that humans
  trust systems that expose risky actions clearly and let them intervene at the
  right granularity.

- **Company primitives, not just agent primitives.** Paperclip is still the
  key reference here. ColonyOS should keep moving toward budgets, governance,
  audit trails, and mission-to-task traceability.

## User's North Star

add inspiration from https://github.com/obra/superpowers# and https://github.com/paperclipai/paperclip and the current directions document

The document should preserve that north star while positioning ColonyOS as
**the autonomous company**: a system that combines persona specialization,
durable memory, extensible skills, stronger sandboxing, and explicit company
primitives into a coherent organization that can decide, build, review, fix,
and ship with minimal human intervention.

## Watch Out For

- **Context window exhaustion.** This becomes a hard wall without repo maps,
  memory stratification, and sharper retrieval.

- **Agent sprawl without a clear decision-maker.** A flat swarm looks cool in a
  demo and then degenerates into confusion. ColonyOS should keep the CEO and
  orchestrator layers as the explicit decision authority.

- **Demo-ware that fails on real codebases.** Benchmark theater is cheap.
  ColonyOS should keep proving itself on its own repository and surface real
  metrics over vanity claims.

- **Over-specialization without extension points.** Personas are powerful, but
  hardcoding every role into the core product will eventually slow iteration.

- **Autonomy without isolation.** If ColonyOS wants to move from "helpful agent"
  to "walk away and come back to a PR," stronger sandboxing becomes mandatory.
