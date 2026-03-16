# PRD: ColonyOS Next-Phase Roadmap and Agent-Ready Implementation Plan

## Clarifying Questions And Autonomous Answers

### 1. What single business or product outcome should this next phase optimize for above all others—e.g. shipping a demo quickly, proving technical feasibility, enabling external users, or generating revenue—and what are you explicitly willing to delay or drop to protect that outcome?
**Answer:** Optimize this phase for enabling a small set of external users to complete the core workflow end-to-end in production and return to use it again. To protect that outcome, explicitly delay revenue features (billing, plans, invoicing), broad customization, non-core integrations, advanced admin/reporting, and any scalability/reliability work beyond what is required to support the first 10 design-partner accounts.  
**Answered by:** CEO of an insanely fast-growing startup  
**Reasoning:** Repeated successful usage by real external users is the fastest proof of product value and the highest-leverage input to both roadmap quality and future revenue. Shipping a demo or overbuilding platform/infrastructure creates false positives and burns time without validating that the product solves a real problem for real users.

### 2. Which concrete user segment is this phase for first—internal developers, early design partners, open-source contributors, or end users—and which adjacent segment are we intentionally not serving yet even if they request features?
**Answer:** This phase is for early design partners: 5–10 external teams who have the problem acutely, can give weekly feedback, and will tolerate rough edges in exchange for solving it now. We are explicitly not serving broad end users yet—even if they request onboarding polish, self-serve admin, or edge-case workflows—because those features optimize for scale before we have a repeatable, high-intensity use case.  
**Answered by:** YC partner  
**Reasoning:** Design partners create the fastest PMF loop: they expose real pain, force prioritization on must-have value, and give us credible signal on retention and pull. Serving end users now would fragment the roadmap into support and UX surface area instead of deepening the core product that earns repeated use.

### 3. What is the smallest deliverable that would count as a successful 'next phase' launch, and which tempting items that feel core to ColonyOS must be declared out of scope so agent-driven implementation does not sprawl?
**Answer:** The smallest successful next-phase launch is: users can define a Colony from a Git repo plus a single YAML spec, trigger one agent-driven implementation task against that repo, review a deterministic plan/diff in the UI, approve it, and have a PR opened with logs, status, and rollback to the pre-run branch state. Explicitly out of scope for this phase: multi-agent orchestration, autonomous deploys to production, natural-language Colony creation without the YAML contract, plugin/marketplace architecture, cross-repo or monorepo-wide coordination, long-running memory/personalization, custom model routing, real-time collaboration, permissions granularity beyond admin/member, and full observability/analytics beyond basic run logs.  
**Answered by:** CEO of an insanely fast-growing startup  
**Reasoning:** This is the narrowest slice that proves the core loop—specify, execute, review, and land code safely—which is the only metric that matters for validating ColonyOS. Everything else is attractive but non-essential platform surface area that will slow shipping and obscure whether agent-driven implementation actually works.

### 4. When you say 'roadmap and implementation plan,' what exact artifacts do you expect as outputs—e.g. milestone plan, architecture doc, prioritized backlog, task graph for coding agents, acceptance criteria—and which of those are mandatory versus nice to have?
**Answer:** Mandatory outputs are: (1) a milestone plan with owners, sequencing, dependencies, and target dates; (2) a prioritized backlog of epics and stories with clear scope boundaries; (3) an implementation plan that includes system architecture decisions, API/data model changes, rollout plan, and key risks; and (4) acceptance criteria for every story plus a task graph broken down enough for coding agents to execute independently. Nice-to-have outputs are wireframes, migration/runbooks, test plans beyond story-level acceptance criteria, and KPI instrumentation specs unless the feature changes core metrics or production data flows—in that case rollout/migration and instrumentation become mandatory.  
**Answered by:** CEO of an insanely fast-growing startup  
**Reasoning:** These four artifacts are the minimum set that turns a roadmap into something buildable without back-and-forth: what ships when, what gets built first, how it works, and how we know it’s done. Everything else is support material and should only be required when the implementation touches user experience ambiguity, production safety, or the primary metric.

### 5. How much decision-making authority should coding agents have during execution: can they only implement pre-approved tasks, or may they propose architecture changes, modify interfaces, and create follow-on work without human approval, and where is the hard boundary?
**Answer:** Coding agents may autonomously implement only pre-approved tasks and may create follow-on work items as proposals, but they may not merge or execute any architecture change, public/internal interface change, schema/migration, dependency change, security/privacy/auth logic change, production config/infrastructure change, or scope expansion without explicit human approval. Hard boundary: agents can make local code changes that preserve the approved API/contract and acceptance criteria; anything that changes system behavior outside the task’s defined module or creates irreversible cost/risk must stop and request approval.  
**Answered by:** YC partner  
**Reasoning:** This maximizes execution speed on low-risk work while keeping product, reliability, and security judgment with humans where mistakes compound. The line should be drawn at blast radius: local implementation autonomy is fine, cross-boundary decisions are not.

### 6. What quality bar must agent-produced work meet before it is considered merge-ready—covering tests, documentation, security review, performance, and code style—and which of those standards can be relaxed for speed in this phase?
**Answer:** Merge-ready means: all unit/integration tests covering changed paths pass in CI with no flaky failures; any user-visible or operational change includes the minimal docs/update notes needed for the next engineer or operator to use it; no new high/critical security findings, no secrets/unsafe auth patterns, and any external input or permissions change gets a focused security review; performance must show no material regression on the hot path the change touches; and code must pass the repo’s formatter, linter, and type checks with no style-only debates. For this phase, we can relax exhaustive test breadth beyond changed/risk-adjacent paths, polished end-user documentation, and deep performance optimization if there is no measured regression; we do not relax CI pass/fail, basic security hygiene/review for risky changes, or automated code-style gates.  
**Answered by:** CEO of an insanely fast-growing startup  
**Reasoning:** The bar should protect production safety and team velocity, not chase completeness. Keep the non-negotiables to anything that prevents breakage, security incidents, or review thrash, and defer work that does not move the current milestone.

### 7. Who will own the work after agents generate it—founder, internal engineer, contractor, or community maintainers—and what level of readability, documentation, and operational context is required so that handoff is not dependent on the original agent session?
**Answer:** The founder or an internal engineer will own all generated work after handoff; contractors may execute scoped follow-on tasks, but no deliverable may require community-maintainer stewardship. Every artifact must be self-sufficient for cold handoff: production-readable code, inline comments only where logic is non-obvious, a README with setup/run/test/deploy steps, an ADR or design note for major decisions, and operational context covering config, dependencies, failure modes, rollback, and ownership so another engineer can take over without access to the original agent session.  
**Answered by:** super senior engineer (Google-level systems judgment)  
**Reasoning:** This sets a single accountable owner inside the company and avoids the operational ambiguity and support risk of community ownership. Requiring complete handoff documentation and operational context makes the output durable, reviewable, and maintainable by any competent engineer without hidden agent state.

### 8. What evidence would convince you that this phase succeeded: a shipped feature, successful user workflows, benchmark gains, partner feedback, contributor velocity, or something else—and what specific threshold separates 'good enough to proceed' from 'needs another iteration'?
**Answer:** Success for this phase is defined by end-to-end user workflow completion in production: at least 90% of targeted workflows complete without manual intervention, p95 latency and error rate stay within existing SLOs, and there are zero Sev-1/Sev-2 regressions for 14 consecutive days after rollout. 'Good enough to proceed' means all three thresholds are met on the agreed rollout cohort; anything below 90% completion, any SLO breach, or any Sev-1/Sev-2 incident triggers another iteration before expansion.  
**Answered by:** super senior engineer (Google-level systems judgment)  
**Reasoning:** A shipped feature or positive qualitative feedback is not sufficient because they do not prove the system contract holds under real usage. Workflow completion plus operational guardrails gives a deterministic go/no-go gate that measures both user value and production safety.

### 9. Which failure mode worries you most for an agent-led next phase—incorrect architecture choices, security issues, hidden maintenance cost, runaway scope, weak product-market fit, or IP/compliance concerns—and what precaution would you accept even if it slows delivery?
**Answer:** Weak product-market fit is the failure mode that matters most; if users are not repeatedly delegating meaningful work to the agent, every architecture and delivery optimization is wasted. I would require a hard stage-gate before broader rollout: ship only one narrow, high-frequency workflow with human approval on every consequential action, and do not expand scope until we see sustained weekly retention and repeated voluntary usage from the target users.  
**Answered by:** YC partner  
**Reasoning:** Agent products fail most often because teams automate too much before proving users trust and need the behavior in a real workflow. The acceptable slowdown is forced narrowness plus approval checkpoints, because that buys real signal on pull, trust, and task value before the system becomes expensive and hard to unwind.

### 10. How much product and system design is already fixed versus intentionally open: are there existing UX patterns, architectural principles, or interface contracts that agents must preserve, and where do you want exploration instead of consistency?
**Answer:** Fixed: preserve the existing chat-first interaction model, left-nav/session history pattern, message composer behavior, streaming-response pattern, design tokens, typography/spacing scale, accessibility bar (WCAG 2.1 AA), API auth/error envelope, event schema, and agent/tool interface contracts already used in production. Open: explore within agent-specific workflows, result rendering for new capabilities, secondary navigation inside agent experiences, and orchestration patterns behind the scenes—as long as they do not break shared primitives, telemetry, or backwards compatibility for existing clients.  
**Answered by:** super senior designer (Apple/Airbnb caliber)  
**Reasoning:** Consistency is mandatory anywhere users build muscle memory or engineers depend on stable contracts; changing those creates disproportionate cognitive and implementation cost. Exploration should happen at the task layer, where we can improve usefulness and differentiation without fragmenting the core product or platform.

### 11. What is the current technical starting point—repo maturity, languages, frameworks, deployment targets, CI/CD, test coverage, and known constraints—and which technical choices are non-negotiable versus available for agents to revisit?
**Answer:** Current starting point is unknown and must be treated as greenfield until a repo audit is completed; agents must first produce a baseline inventory covering repository topology, primary languages, framework/runtime versions, build/package managers, deployment targets/environments, CI/CD pipelines, test suites with approximate coverage, secrets/config handling, observability, and open operational constraints. Non-negotiable: preserve existing production deployment platform, CI provider, security/compliance controls, and any externally committed APIs/data schemas if they already exist; everything else—internal libraries, framework upgrades, test tooling, repo structure, and developer workflow—may be revisited only behind compatibility boundaries and a migration plan.  
**Answered by:** super senior engineer (Google-level systems judgment)  
**Reasoning:** Assuming stack details without an audit creates hidden integration and delivery risk; a deterministic inventory is the minimum contract needed for an implementation-ready PRD. Locking only externally coupled and operationally critical surfaces preserves safety while leaving room to improve internal technical choices incrementally.

---

## Introduction/Overview

This PRD defines the next phase of ColonyOS as a narrow, production-ready workflow for early design partners. The objective is not a broad platform launch. It is to prove that external teams can repeatedly use ColonyOS to safely delegate one meaningful implementation task from a Git repository and YAML Colony spec through review and PR creation.

The deliverable for this phase has two parts:
1. A buildable planning package for humans and coding agents: milestone plan, prioritized backlog, implementation plan, story acceptance criteria, and agent-executable task graph.
2. The product capability being planned: define Colony from repo + YAML, run one agent task, review deterministic plan/diff in UI, approve, open PR, view logs/status, and roll back to pre-run branch state.

All work must preserve existing product primitives and minimize scope to fit 5–10 design-partner accounts.

## Goals

- Enable 5–10 design-partner teams to complete the core workflow end-to-end in production.
- Validate repeated usage and weekly retention for one narrow, high-frequency workflow.
- Produce an agent-ready roadmap and implementation plan with enough precision for Claude Code or Cursor agents to execute scoped tasks independently.
- Maintain production safety through approval gates, rollback, test coverage on changed paths, and no SLO regressions.
- Preserve existing UX and API contracts already in production.

## User Stories

- As a design-partner admin, I can create a Colony using a Git repo and one YAML spec.
- As a design-partner member, I can trigger one approved implementation task against that repo.
- As a user, I can review a deterministic execution plan and proposed diff before code is finalized into a PR.
- As a user, I can explicitly approve or reject the proposed change before any consequential action proceeds.
- As a user, I can see run status, logs, and final outcome in the UI.
- As an operator, I can roll the repo back to its pre-run branch state if the run fails or is rejected.
- As an engineer reviewing agent output, I can understand code, risks, setup, and rollback without access to the original agent session.
- As a product owner, I can evaluate success by workflow completion, retention, SLO compliance, and incident-free rollout.

## Functional Requirements

1. The system must produce a baseline repo and platform audit before implementation planning proceeds, including topology, stack, CI/CD, environments, tests, config/secrets handling, observability, and constraints.
2. The system must produce a milestone plan with owners, sequencing, dependencies, and target dates.
3. The system must produce a prioritized backlog of epics and stories with explicit in-scope and out-of-scope boundaries.
4. The system must produce an implementation plan covering architecture decisions, API and data model changes, rollout plan, and key risks.
5. The system must produce acceptance criteria for every story and a task graph granular enough for coding agents to execute independently.
6. The system must support defining a Colony from exactly one Git repository and one YAML specification.
7. The system must support triggering exactly one agent-driven implementation task per run within the approved workflow scope.
8. The system must present a deterministic plan and proposed diff in the UI before approval.
9. The system must require explicit human approval before opening a PR or taking any other consequential action.
10. The system must open a PR containing the approved code changes and retain associated logs and status.
11. The system must preserve the ability to roll back to the pre-run branch state for each run.
12. The system must expose basic run logs and status sufficient for users and operators to diagnose success or failure.
13. The system must preserve existing chat-first UX, left-nav/session history, message composer, streaming behavior, design tokens, accessibility bar, API auth/error envelope, event schema, and existing agent/tool contracts.
14. The system must restrict coding agents to pre-approved tasks only and require human approval for architecture changes, interface changes, schema changes, dependency changes, auth/security/privacy changes, production config/infrastructure changes, and scope expansion.
15. The system must require all downstream implementation tasks to follow a tests-first approach: failing tests for the defined behavior must be written before implementation code is added or modified.
16. The system must treat merge readiness as requiring passing CI for changed-path unit/integration tests, required docs/update notes, automated style/type gates, and no new high/critical security findings.
17. The system must require focused security review for any change affecting external input handling, permissions, or auth-related behavior.
18. The system must require handoff artifacts sufficient for cold ownership transfer, including README updates, major decision notes, operational context, rollback notes, and ownership.
19. The system must support rollout to only the agreed design-partner cohort before broader expansion.
20. The system must block scope expansion until success metrics are met on the rollout cohort.

## Non-Goals (Out of Scope)

- Billing, plans, invoicing, and monetization features
- Broad customization
- Non-core integrations
- Advanced admin/reporting
- Scalability/reliability work beyond first 10 design-partner accounts
- Multi-agent orchestration
- Autonomous production deploys
- Natural-language Colony creation without YAML
- Plugin or marketplace architecture
- Cross-repo or monorepo-wide coordination
- Long-running memory or personalization
- Custom model routing
- Real-time collaboration
- Permissions beyond admin/member
- Full observability/analytics beyond basic run logs

## Design Considerations

- Preserve existing product consistency where users already have muscle memory.
- Keep the experience chat-first and embedded within current navigation and session patterns.
- Make review and approval the central UX moment; users must clearly understand plan, diff, status, and next action.
- Maintain WCAG 2.1 AA compliance.
- Explore only within agent-specific result rendering and workflow-specific secondary navigation.

## Technical Considerations

- Treat the current codebase as unknown until a formal audit is completed.
- Preserve existing production deployment platform, CI provider, security/compliance controls, and externally committed APIs/data schemas.
- Any revisiting of internal tooling, repo structure, framework versions, or developer workflow must remain behind compatibility boundaries and include a migration plan if adopted.
- Prefer narrow blast radius and reversibility in all changes.
- Use human approval checkpoints to control risk from agent-generated work.
- Handoff quality is mandatory because the founder/internal engineer owns the result after generation.

## Success Metrics

- At least 90% of targeted workflows complete end-to-end in production without manual intervention.
- p95 latency remains within existing SLOs during the rollout.
- Error rate remains within existing SLOs during the rollout.
- Zero Sev-1 or Sev-2 regressions for 14 consecutive days after rollout.
- Evidence of repeated voluntary use by design partners on the narrow workflow before expansion.

## Open Questions

- What is the actual current repo and system inventory after audit?
- Which exact high-frequency workflow will be the single launch workflow for design partners?
- Who are the named owners for milestones and review gates?
- What are the current baseline SLO values for latency and error rate?
- What exact approval UX copy and status taxonomy best fit existing product patterns?
- What minimum instrumentation is required if this phase changes core metrics or production data flows?
- What is the exact rollback boundary if multiple branches or ephemeral environments are involved?
- Which stories, if any, require migration/runbooks to be upgraded from nice-to-have to mandatory after audit?
