# ColonyOS

ColonyOS is an autonomous software engineering operating system for startups that want to automate coding without turning their repo into chaos. It coordinates specialized AI agents to plan, implement, test, review, and ship code through a deterministic, policy-driven workflow. Inspired by ant colonies, it replaces ad-hoc agent swarms with a structured pipeline that turns product requirements into production-ready pull requests.

## The Core Idea

Most teams start with the wrong question:

"What if we had a PM agent, a dev agent, a QA agent, a review agent, and a release agent all working at once?"

That sounds good in theory and usually fails in practice.

Role splitting alone does not create reliability. A swarm of agents editing the same codebase without hard rules just creates noisy diffs, duplicate work, flaky validation, and unclear ownership.

ColonyOS takes a different approach:

`planner/orchestrator -> isolated implementation -> deterministic verification -> constrained review -> merge gate`

The point is not to create agent personalities. The point is to create a controlled software factory where work moves through explicit states, each transition is auditable, and every merge is protected by deterministic checks.

## Design Principles

### 1. Workflow First, Agents Second

The workflow is the product. Agents are replaceable components.

If the system only works because a prompt is clever, it is fragile. If it works because state transitions, policies, scripts, and CI gates are well-defined, it is durable.

### 2. State Transitions Over Freeform Collaboration

A work item should move through explicit states:

`Backlog -> Ready Spec -> In Progress -> Tests Passing -> Review Approved -> Merge Ready -> Deployed`

Every state transition should be triggered by either:

- an agent action
- a deterministic system check
- a human approval for risky work

### 3. One Writer At A Time

Multiple agents can analyze the same task, but code changes should remain serialized. ColonyOS assumes isolated branches or sandboxed task environments and avoids multiple agents editing the same branch simultaneously.

### 4. Deterministic Gates Beat Prompt Memory

Agents forget things. Tooling should not.

Formatting, linting, typechecking, test execution, security checks, migration policy, and merge protection should be enforced by scripts, hooks, and CI rather than by asking models nicely.

### 5. Autonomy Is Tiered

Not all work deserves the same freedom. Docs, small refactors, and test debt can be highly automated. Auth, billing, infra, migrations, secrets, and sensitive customer-data paths should always be human-gated.

## What ColonyOS Is

ColonyOS is designed to be the orchestration layer for agent-driven software delivery. It should eventually provide:

- task intake from issues, tickets, or product requests
- spec generation with acceptance criteria and test plans
- task routing to specialized agents
- branch and pull request lifecycle management
- policy and risk classification
- deterministic validation before merge
- structured handoffs between agents
- audit trails, metrics, and retry/escalation logic

## What ColonyOS Is Not

ColonyOS is not:

- a loose multi-agent chatroom
- multiple agents editing `main` directly
- freeform coordination with no system of record
- a replacement for CI, branch protections, or human judgment
- a reason to skip scripts, tests, or security review

## The Minimal Viable Agent Set

ColonyOS starts with four core roles. That is enough separation of concerns without creating coordination hell.

### 1. PM / Spec Agent

Purpose:
Turn a feature request, bug report, or product idea into an implementation-ready engineering spec.

Responsibilities:

- define the goal and user impact
- narrow scope and list non-goals
- propose acceptance criteria
- outline a deterministic test plan
- estimate touched systems and likely files
- call out risk, edge cases, and rollback notes

Non-goal:
This agent does not write production code.

### 2. Dev Agent

Purpose:
Implement the approved spec in an isolated branch or sandbox.

Responsibilities:

- keep diffs minimal and scoped to the task
- follow repo-local instructions such as `AGENTS.md`
- summarize uncertainty explicitly
- hand off cleanly to QA and review

Constraints:

- should not invent scope beyond the spec
- should not merge code
- should prefer deterministic repo scripts over ad-hoc commands

### 3. QA / Test Agent

Purpose:
Assume the implementation is wrong until verified.

Responsibilities:

- add or improve tests
- create regression coverage for bug fixes
- run verification commands
- isolate flaky or failing cases
- produce a pass/fail report with reproduction steps

Constraints:

- may write tests
- should not silently rewrite production code unless explicitly permitted by policy or orchestrator

### 4. Review / Security Agent

Purpose:
Act as an adversarial reviewer before merge.

Responsibilities:

- review for correctness
- review for architecture fit
- review for maintainability
- review for performance and security risks
- identify hidden side effects and migration risk

Default behavior:
Prefer comments and change requests over silent fixes.

## Recommended System Architecture

ColonyOS should be built as a hybrid agent + CI orchestration system with four layers.

### Layer 1: Source Of Truth

Each product repo should expose sharp, deterministic affordances:

- a GitHub repository
- an issue tracker such as GitHub Issues or Linear
- repo-local instructions in `AGENTS.md`
- repeatable scripts for every important validation step

At minimum, product repos should standardize commands like:

```bash
make setup
make lint
make typecheck
make test
make test-e2e
make security
make verify
```

Nice-to-have commands:

```bash
make fix
make review-snapshot
```

Agents behave much better when the environment exposes explicit, deterministic actions instead of vague expectations.

### Layer 2: Orchestrator

The orchestrator is the control plane. It should:

- read the issue or approved spec
- choose the next agent
- pass narrow context
- classify task risk
- decide whether to continue, retry, or escalate
- manage branches, PR state, and merge readiness
- avoid writing code directly except in a tightly controlled fallback mode

This is the system that makes ColonyOS a software factory instead of a roleplay script.

### Layer 3: Worker Agents

Worker agents should receive narrow, structured inputs and produce narrow, structured outputs. They should not coordinate through long natural-language loops if that can be avoided.

### Layer 4: Deterministic Enforcement

The enforcement layer should live in CI and repository policy:

- protected branches
- required status checks
- lint
- typecheck
- unit tests
- integration tests
- build checks
- migration checks
- secrets scanning
- code scanning / SAST
- required approval rules for sensitive areas

The merge gate matters more than the prompt.

## The ColonyOS Workflow

### Feature Flow

1. A human creates an issue or product request.
2. The PM agent converts it into a spec.
3. The spec is approved by a human or policy gate.
4. The dev agent implements the task on an isolated branch.
5. The QA agent adds or strengthens tests and runs verification.
6. The review agent produces a structured review and risk report.
7. CI runs required checks.
8. If all gates pass, the PR becomes merge-ready.
9. A human merges, or low-risk classes may optionally use controlled auto-merge later.

### Bugfix Flow

1. A bug is reported.
2. The PM agent creates a minimal repro and acceptance criteria.
3. The dev agent produces the smallest valid fix.
4. The QA agent adds a regression test first or alongside the fix.
5. The review agent checks for side effects.
6. CI gates the merge.

### Autonomous Backlog Burn

This mode is intentionally narrow and only applies to low-risk task classes such as:

- docs
- small refactors
- test debt
- type fixes
- dead code cleanup
- low-risk UI polish

This mode should not apply to:

- auth
- billing
- infrastructure
- migrations
- security-sensitive code
- compliance-critical logic
- major architecture changes

## Structured Handoffs

Agents should communicate through machine-readable task contracts, not just prose. A handoff should preserve the current state, findings, commands run, and next action.

Example:

```json
{
  "task_id": "ENG-142",
  "role": "qa_agent",
  "input": {
    "spec_ref": "specs/ENG-142.md",
    "pr_branch": "agent/eng-142-dev",
    "changed_files": ["api/orders.py", "tests/test_orders.py"]
  },
  "output": {
    "status": "changes_requested",
    "findings": [
      {
        "severity": "high",
        "type": "missing_regression_test",
        "message": "Negative quantity path is untested"
      }
    ],
    "commands_run": [
      "make test",
      "pytest tests/test_orders.py -q"
    ],
    "next_action": "dev_agent"
  }
}
```

This is easier to audit, retry, and reason over than long agent-to-agent conversations.

## Repo Contract: `AGENTS.md`

Every product repo integrated with ColonyOS should include an `AGENTS.md` file that defines local rules and expectations. This is where the house rules live.

Suggested sections:

- project mission
- architecture overview
- stack overview
- coding conventions
- verification commands
- migration policy
- security rules
- file ownership or sensitive paths
- when to ask for human review
- forbidden actions
- expected PR output format

Example non-negotiables:

- never modify billing logic without human review
- never merge directly to `main`
- prefer minimal diffs
- add regression tests for bug fixes

## Autonomy Tiers

ColonyOS should make autonomy explicit instead of pretending every task is equally safe.

### Tier 1: Safe Autonomous

Allowed without approval:

- docs
- comments
- tests
- lint fixes
- narrow refactors
- dead code cleanup

### Tier 2: Guarded Autonomous

Allowed with PR + checks:

- standard feature work
- API handlers
- UI work
- internal tooling
- analytics

### Tier 3: Human-Gated

Always requires approval:

- auth and permissions
- billing and payments
- secrets and key management
- infrastructure and Terraform
- database migrations on production systems
- medical, legal, or compliance logic
- anything touching sensitive customer-data flows

## Operational Rules

ColonyOS should enforce a few blunt rules from day one:

- `main` is protected
- agents do not merge directly to `main`
- only one agent writes code for a task branch at a time
- every bug fix requires regression coverage
- every merge must satisfy deterministic repo validation
- risky paths require escalation
- humans remain the final authority for high-risk work

## Success Metrics

If ColonyOS is useful, it should improve delivery quality, not just generate more diff volume.

Track at least:

- task completion rate
- first-pass CI success
- review rejection rate
- human rework minutes
- escaped bugs
- median cycle time
- cost per merged PR
- rollback rate

Without these metrics, the system is just vibes.

## Recommended MVP Rollout

Do not build the full ant colony on day one. Start small and make it reliable first.

### Phase 1: Foundation

Set up:

- protected `main`
- required status checks
- CI pipeline
- `AGENTS.md`
- deterministic repo commands

### Phase 2: Single Dev Agent

Start with:

- one dev agent
- one review gate
- no autonomous merge
- low-risk issues only

### Phase 3: Add QA

Require:

- a test plan on each task
- regression coverage for bug fixes
- pass/fail verification reporting

### Phase 4: Add PM / Spec Generation

Make work begin from a generated spec and compare throughput and failure rates against tasks that skipped the spec step.

### Phase 5: Add Selective Autonomy

Allow:

- low-risk issue auto-assignment
- PR auto-open
- controlled automation around review preparation

Keep:

- human merge for guarded and high-risk tasks

## Opinionated Product Thesis

ColonyOS should not be built as "a company of agents" that talk freely and hope for the best.

It should be built as:

- a workflow engine
- a task contract
- a policy system
- a validation layer
- a set of specialized workers plugged into that system

The agents are interchangeable.
The workflow is the moat.

## Near-Term Build Direction

The best first version of ColonyOS is probably a separate orchestration repo with:

- a state machine
- task queue
- role definitions and prompts
- branch / PR lifecycle management
- GitHub integration
- policy and risk rules
- run logs and metrics

Open-ended multi-agent chat platforms can still be useful later as operator interfaces, notification layers, or control surfaces. They should not be the foundation unless the platform itself is the product.

## Local Python Environment

For local Python tooling, create and use a virtual environment in the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

When done:

```bash
deactivate
```

Run the PM workflow prototype:

```bash
./.venv/bin/python scripts/run_pm_workflow.py "Your feature request here"
```
