# PRD: Autonomous PM Workflow for ColonyOS

## Clarifying Questions And Autonomous Answers

### 1. What is the main goal of this workflow?
**Answer:** `E. All of the above`

**Answered by:** CEO of an insanely fast-growing startup

**Reasoning:** The workflow should not optimize for just one local outcome like better specs or less founder involvement. It should improve the entire planning-to-execution pipeline: better specs, lower ambiguity, higher coding-agent success, and a standardized way work enters the system.

### 2. Who is the primary user of this PM workflow?
**Answer:** `E. Mixed audience`

**Answered by:** YC partner

**Reasoning:** The system serves multiple actors at once: founder/operator, coding agents, future internal teams, and eventually external users. Designing it for a single persona would weaken the orchestration value.

### 3. What should the PM agent produce as its main artifact?
**Answer:** `A. Traditional PRD`, following `ColonyOS/.cursor/rules/create_prd.mdc`

**Answered by:** CEO of an insanely fast-growing startup

**Reasoning:** The first version should follow the current contract exactly so the workflow remains simple and deterministic. More advanced artifacts can be layered on later.

### 4. How autonomous should the clarification step be?
**Answer:** The full process should be documented. Questions should be asked, and each one should be answered autonomously by the most appropriate expert voice:
- a super senior designer who worked at Apple or Airbnb
- a super senior engineer at Google
- the CEO of an insanely fast-growing startup
- a YC partner

**Answered by:** YC partner

**Reasoning:** This preserves rigor without requiring human intervention, while making the chain of reasoning inspectable.

### 5. What is the desired quality bar?
**Answer:** Same as above in Question 4.

**Answered by:** CEO of an insanely fast-growing startup

**Reasoning:** The bar is not "helpful assistant." The bar is elite product, design, engineering, and company-building judgment.

### 6. What should happen after the PRD is generated?
**Answer:** There should be another flow following `ColonyOS/.cursor/rules/generate_tasks.mdc`.

**Answered by:** Super senior engineer at Google

**Reasoning:** The PM workflow should hand off into task generation as a separate deterministic phase.

### 7. What should the validation step check before work is sent to the coding agent?
**Answer:** For now, just output the files.

**Answered by:** CEO of an insanely fast-growing startup

**Reasoning:** v1 should prioritize artifact generation over building a heavy validation engine too early.

### 8. Should the PM workflow support risk tiers?
**Answer:** Yes. The system should categorize work by risk tier and determine whether a human needs to be involved. Human involvement should be rare. When it does happen, the system should store that decision in long-term memory.

**Answered by:** YC partner

**Reasoning:** This creates a path to autonomy without losing institutional learning.

### 9. What is out of scope for v1?
**Answer:** Everything except PM.

**Answered by:** CEO of an insanely fast-growing startup

**Reasoning:** The first release should prove the PM lane in isolation before expanding to coding, review, QA, release, or orchestration infrastructure.

### 10. Where should generated artifacts live?
**Answer:** The system should have a backend so it can support multiple users. A Supabase-backed project is the right early direction.

**Answered by:** Super senior engineer at Google

**Reasoning:** Local files are fine for prototyping, but the real system needs multi-tenant persistence, artifact storage, and long-term memory.

### 11. Should generated planning artifacts be committed to git?
**Answer:** No.

**Answered by:** CEO of an insanely fast-growing startup

**Reasoning:** These are operational artifacts, not source-of-truth code artifacts.

### 12. What is the success metric for this feature?
**Answer:** `E. All of the above`

**Answered by:** YC partner

**Reasoning:** The PM workflow should improve planning quality, reduce ambiguity, speed up execution, and increase first-pass implementation quality.

---

## Introduction/Overview

ColonyOS needs an autonomous PM workflow that can take a rough product or feature request, generate the clarifying questions a world-class team would ask, answer those questions autonomously with strong judgment, and produce a high-quality PRD for downstream execution.

This feature is intended to be the first operational agent inside ColonyOS. Its job is not to code. Its job is to reduce ambiguity before coding starts. The workflow should document the full reasoning path, including the questions asked and the expert persona best suited to answer each one, then produce a PRD in the existing format defined by `ColonyOS/.cursor/rules/create_prd.mdc`.

After the PRD is created, a separate downstream flow should generate implementation tasks using `ColonyOS/.cursor/rules/generate_tasks.mdc`. For now, the system only needs to output the generated planning artifacts.

## Goals

- Create a fully autonomous PM workflow that does not require human clarification for normal requests.
- Preserve the rigor of a clarifying-question step while allowing the agent to answer those questions itself.
- Produce a PRD that follows the existing `create_prd.mdc` contract.
- Capture and expose the reasoning process behind the PRD.
- Use differentiated expert personas to answer questions with stronger judgment.
- Provide a clean handoff point into a later task-generation flow.
- Support risk-tier classification so the system can determine when human involvement is required.
- Build toward a multi-user backend with persistent long-term memory for rare human interventions.
- Keep generated planning artifacts out of git by default.

## User Stories

- As a founder/operator, I want to give ColonyOS a rough feature idea and receive a high-quality PRD without needing to answer follow-up questions manually.
- As a coding agent, I want a planning artifact that is clear, explicit, and less ambiguous so I can implement with higher confidence.
- As a future task-generation agent, I want the PRD to follow a predictable structure so I can derive actionable implementation tasks from it.
- As a future orchestration system, I want risk tiers and long-term memory for escalations so the platform can improve over time.
- As a future multi-user platform operator, I want planning data stored in a backend so the system can support many users and persistent workflows.

## Functional Requirements

1. The system must accept an initial user prompt describing a feature, workflow, or product idea.
2. The system must generate clarifying questions before producing the PRD.
3. The system must document the clarifying questions as part of the planning process.
4. The system must answer the clarifying questions autonomously rather than waiting for human input.
5. The system must dynamically select the most appropriate expert voice for each answer.
6. The supported expert voices must include:
   - a super senior designer with Apple or Airbnb quality judgment
   - a super senior engineer with Google-level systems judgment
   - the CEO of an insanely fast-growing startup
   - a YC partner
7. The system must include the selected expert role for each autonomous answer.
8. The system must generate a PRD using the structure defined in `ColonyOS/.cursor/rules/create_prd.mdc`.
9. The system must keep the PRD clear, explicit, and understandable to a junior developer.
10. The PRD must describe the feature, its goals, user stories, functional requirements, non-goals, design considerations, technical considerations, success metrics, and open questions.
11. The system must be able to hand off into a separate task-generation flow using `ColonyOS/.cursor/rules/generate_tasks.mdc`.
12. For v1, the system must only output the generated planning artifacts and does not need to perform full validation or coding handoff automation.
13. The system must classify work into risk tiers.
14. The system must determine whether a human should be involved based on the risk tier.
15. Human involvement should be rare and treated as an exception path.
16. When a human is involved, the system must store their decision or guidance in long-term memory for future reference.
17. The architecture must support a backend suitable for multiple users.
18. The backend direction should support persistent storage, user separation, and long-term memory.
19. Generated artifacts should not be committed to git by default.

## Non-Goals (Out of Scope)

- Implementing the coding agent.
- Implementing the QA agent.
- Implementing the review agent.
- Implementing the release agent.
- Building the full validation engine in v1.
- Building the full orchestration backend in v1.
- Solving all multi-agent coordination in this phase.
- Auto-merging or executing code changes.
- Human-heavy approval loops as the default operating model.

## Design Considerations

- The workflow should feel rigorous, not magical.
- The clarifying questions should make the system look thoughtful and senior, not generic.
- The autonomous answers should be opinionated and concrete.
- Persona selection should feel intentional and tied to the type of question being answered.
- The final PRD should remain simple and readable, even if the internal reasoning is sophisticated.
- The process should expose enough reasoning to build trust without turning every artifact into an unreadable wall of analysis.
- The output should be useful both to a human operator and to downstream agents.

## Technical Considerations

- The PRD generation flow should continue to follow `ColonyOS/.cursor/rules/create_prd.mdc`.
- The downstream task flow should follow `ColonyOS/.cursor/rules/generate_tasks.mdc`.
- The current implementation should focus only on the PM workflow.
- Generated artifacts should be treated as operational outputs rather than versioned product code.
- The system should move toward a backend-backed architecture rather than purely local file generation.
- Supabase is an appropriate starting point for backend infrastructure because it can support authentication, storage, and long-term memory primitives for multiple users.
- Risk-tier metadata should be stored alongside artifacts so future agents can determine whether escalation is required.
- Long-term memory should store rare human interventions so the system improves over time and does not repeatedly escalate the same class of issue.

## Success Metrics

- Increased coding-agent implementation accuracy.
- Faster spec-to-code cycle time.
- Fewer ambiguous or incomplete implementation requests.
- Higher first-pass output quality from downstream agents.
- Lower frequency of unnecessary human interruptions.
- Better reuse of past human guidance through long-term memory.
- Consistent production of high-quality PRDs from weak initial prompts.

## Open Questions

- What exact risk-tier taxonomy should be used in v1?
- What should the schema for long-term human-memory entries look like?
- Should clarifying questions and autonomous answers be embedded in the PRD body or stored as separate metadata alongside it?
- How much of the autonomous reasoning should be exposed to end users versus stored as internal planning trace?
- What is the exact artifact format passed into the later task-generation flow?
- When Supabase is introduced, what data model should separate users, projects, PRDs, tasks, and memory records?
- At what point should the validation step evolve from "output files only" to an actual pre-coding gate?