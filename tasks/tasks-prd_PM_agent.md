## Relevant Files

- `ColonyOS/.cursor/rules/create_prd.mdc` - Existing PRD contract the PM workflow must target.
- `ColonyOS/.cursor/rules/generate_tasks.mdc` - Downstream task-generation contract this workflow must hand off into.
- `ColonyOS/tasks/prd_PM_agent.md` - Source PRD that defines the autonomous PM workflow requirements.
- `ColonyOS/tasks/tasks-prd_PM_agent.md` - Implementation task list derived from the PRD.
- `ColonyOS/README.md` - Current project context and likely place to align or document the PM workflow.
- `ColonyOS/app/` - Likely application area where the PM workflow UI, API, or orchestration entrypoint will live.
- `ColonyOS/lib/` - Likely location for workflow orchestration, persona selection, and artifact formatting helpers.
- `ColonyOS/lib/pm-workflow/` - Likely feature module for PM workflow domain logic if the codebase is organized by capability.
- `ColonyOS/lib/pm-workflow/*.test.ts` - Unit tests for PM workflow logic modules.

### Notes

- Unit tests should typically be placed alongside the code files they are testing.
- Use `npx jest [optional/path/to/test/file]` to run tests. Running without a path executes all tests found by the Jest configuration.
- Generated planning artifacts should remain operational outputs and should not be committed to git by default.
- v1 should stay scoped to PM artifact generation and handoff readiness, not coding-agent or orchestration automation.

## Tasks

- [ ] 1.0 Define the autonomous PM workflow contract and artifact boundaries
  - [ ] 1.1 Read `tasks/prd_PM_agent.md`, `README.md`, and the existing Cursor rules to extract the exact PM workflow inputs, outputs, and non-goals.
  - [ ] 1.2 Define the end-to-end PM workflow stages from raw prompt intake through clarifying questions, autonomous answers, PRD generation, risk classification, and task-generation handoff.
  - [ ] 1.3 Decide what data must be captured for each workflow run, including prompt, clarifying questions, persona assignments, answers, risk tier, escalation status, PRD body, and task-handoff metadata.
  - [ ] 1.4 Specify which artifacts are user-visible in v1 versus internal planning trace so the system exposes enough reasoning without turning output into noise.
  - [ ] 1.5 Document v1 boundaries clearly so the implementation does not drift into coding-agent, QA, review, release, or full validation-engine work.
- [ ] 2.0 Build the clarifying-question generation and autonomous-answer pipeline
  - [ ] 2.1 Implement logic that accepts a rough feature request and generates a bounded set of high-value clarifying questions before PRD creation.
  - [ ] 2.2 Create a persona-selection mechanism that routes each question to the most appropriate expert voice: senior designer, senior engineer, startup CEO, or YC partner.
  - [ ] 2.3 Implement autonomous answer generation for each question and store both the selected persona and the reasoning path alongside the answer.
  - [ ] 2.4 Add safeguards so the generated questions and answers stay concrete, opinionated, and directly useful for downstream implementation.
  - [ ] 2.5 Add test coverage for question generation, persona routing, and answer formatting, including edge cases where the initial user prompt is vague.
- [ ] 3.0 Implement PRD assembly using the existing `create_prd.mdc` structure
  - [ ] 3.1 Map the workflow outputs into the exact PRD sections required by `create_prd.mdc`, including overview, goals, user stories, requirements, non-goals, considerations, success metrics, and open questions.
  - [ ] 3.2 Build a formatter that produces a readable PRD suitable for a junior developer while preserving the autonomous clarifying-question trail.
  - [ ] 3.3 Decide whether the clarifying questions and autonomous answers should appear in the PRD body, attached metadata, or both in v1, and implement that decision consistently.
  - [ ] 3.4 Ensure the PRD output remains deterministic enough that the later task-generation flow can reliably consume it.
  - [ ] 3.5 Add tests that verify the generated PRD follows the expected structure and includes the required persona and reasoning data where intended.
- [ ] 4.0 Add risk-tier classification, escalation handling, and long-term memory hooks
  - [ ] 4.1 Define an initial v1 risk-tier taxonomy that distinguishes low-risk autonomous work from cases that require human involvement.
  - [ ] 4.2 Implement risk classification based on the generated planning artifact, touched systems, ambiguity level, and sensitivity of the requested work.
  - [ ] 4.3 Implement decision logic that marks whether the workflow may continue autonomously or should escalate to a human exception path.
  - [ ] 4.4 Design the data contract for storing rare human interventions so future runs can reuse that guidance as long-term memory.
  - [ ] 4.5 Add tests for risk-tier assignment and escalation decisions, especially around ambiguous, sensitive, or multi-system requests.
- [ ] 5.0 Prepare downstream handoff and persistence foundations for generated artifacts
  - [ ] 5.1 Define the artifact package that the downstream task-generation flow should receive after PRD creation, including any metadata needed for deterministic task derivation.
  - [ ] 5.2 Implement file or storage output boundaries for v1 so the system can emit generated artifacts cleanly without coupling them to git commits.
  - [ ] 5.3 Design a backend-friendly persistence shape that can later map to Supabase for multi-user support, stored artifacts, and long-term memory.
  - [ ] 5.4 Add placeholders or interfaces for future persistence adapters so local artifact output can evolve into backend-backed storage without rewriting the workflow core.
  - [ ] 5.5 Add integration-style tests or fixtures that verify a full PM workflow run produces the expected planning artifacts and a clean handoff payload.
