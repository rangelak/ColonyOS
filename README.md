# ColonyOS

Autonomous agent loop that turns prompts into shipped PRs.

ColonyOS is a CLI tool that orchestrates Claude agent sessions via the [Claude Agent SDK](https://docs.anthropic.com/en/docs/agent-sdk) to plan and implement features in any repository — with full codebase awareness. You give it a feature prompt, it generates a PRD, breaks it into tasks, implements the code, and opens a pull request. No hand-holding required.

## How It Works

```
colonyos run "Add Stripe billing integration"
```

ColonyOS runs four phases, each as a separate Claude agent session with full access to your repo:

1. **Plan** — Explores your codebase, generates a PRD with clarifying Q&A from your defined personas (running as parallel subagents), and produces a task breakdown. Outputs go to `cOS_prds/` and `cOS_tasks/`.
2. **Implement** — Creates a feature branch, writes tests first, then implements each task from the plan. Commits as it goes.
3. **Review** — Each persona reviews the implementation in parallel, first per-task then a final holistic review. Review artifacts go to `cOS_reviews/`.
4. **Deliver** — Pushes the branch and opens a pull request with a summary linking back to the PRD.

Each phase is isolated with its own budget cap. If a phase fails, the run stops and logs what happened.

## Prerequisites

- **Python 3.11+**
- **Claude Code CLI** — installed and authenticated (`claude --version` should work). The Agent SDK uses it under the hood.
- **Git** — the target repo must be a git repository
- **GitHub CLI** (`gh`) — for the deliver phase to open PRs

## Quickstart

```bash
pip install colonyos

cd your-project/
colonyos init          # interactive setup: project info + persona workshop
colonyos run "Add user authentication with JWT"
```

## Setup: `colonyos init`

The init flow asks about your project and walks you through defining agent personas:

```
$ colonyos init

--- Project Info ---
Project name: MyApp
Brief description: B2B analytics platform
Tech stack: Python/FastAPI, React, PostgreSQL

--- Agent Personas ---
Define the expert personas who will review feature PRDs.

--- Persona 1 ---
Role: Senior Backend Engineer
Expertise: API design, database modeling, performance
Perspective: Thinks about scalability and data integrity

--- Persona 2 ---
Role: Product Lead
Expertise: User research, prioritization
Perspective: Thinks about user value and shipping incrementally

--- Persona 3 ---
Role: Security Auditor
Expertise: AuthN/AuthZ, OWASP, compliance
Perspective: Thinks about attack surfaces and data exposure

Config saved to .colonyos/config.yaml
```

Personas shape how PRDs are written. During the plan phase, Claude Code answers clarifying questions from each persona's perspective, giving diverse viewpoints grounded in your project's context.

## CLI Reference

```bash
colonyos init                              # interactive project + persona setup
colonyos init --personas                   # re-run just the persona setup

colonyos run "Add Stripe billing"          # full loop: plan + implement + deliver
colonyos run "Add Stripe billing" --plan-only   # stop after PRD + tasks
colonyos run --from-prd prds/xxx_prd.md    # skip planning, implement existing PRD

colonyos status                            # show recent runs with cost
```

## Configuration

Config lives at `.colonyos/config.yaml` in your repo. Created by `colonyos init`.

```yaml
project:
  name: "MyApp"
  description: "B2B analytics platform"
  stack: "Python/FastAPI, React, PostgreSQL"

personas:
  - role: "Senior Backend Engineer"
    expertise: "API design, database modeling, performance"
    perspective: "Thinks about scalability and data integrity"
  - role: "Product Lead"
    expertise: "User research, prioritization"
    perspective: "Thinks about user value and shipping incrementally"

model: opus
budget:
  per_phase: 5.00       # USD per Claude Code session
  per_run: 15.00        # USD total cap for a full run
phases:
  plan: true
  implement: true
  review: true           # persona-driven review of each task + holistic review
  deliver: true          # set false to skip PR creation
branch_prefix: "colonyos/"
prds_dir: "cOS_prds"
tasks_dir: "cOS_tasks"
reviews_dir: "cOS_reviews"
```

## Output Structure

ColonyOS creates three `cOS_`-prefixed directories in your repo that serve as a timestamped changelog:

```
your-repo/
  cOS_prds/
    20260316_172530_prd_stripe_billing.md
    20260317_091200_prd_user_auth.md
  cOS_tasks/
    20260316_172530_tasks_stripe_billing.md
    20260317_091200_tasks_user_auth.md
  cOS_reviews/
    20260317_091200_review_task_01_user_auth.md
    20260317_091200_review_final_user_auth.md
```

Run logs (costs, durations, session IDs) go to `.colonyos/runs/` which is gitignored by default.

## Architecture

```
src/colonyos/
  cli.py            # Click CLI entry point
  init.py           # Interactive persona workshop
  orchestrator.py   # Phase chaining: plan -> implement -> deliver
  agent.py          # Claude Agent SDK wrapper
  config.py         # .colonyos/config.yaml loader
  models.py         # Persona, PhaseResult, RunLog
  naming.py         # Deterministic timestamped filenames
  instructions/     # Markdown templates passed to Claude Code
    base.md         # Repo conventions
    plan.md         # PRD + task generation
    implement.md    # Test-first implementation
    review.md       # Self-review checklist
    deliver.md      # PR creation
```

Instructions are markdown templates shipped with the package. They're passed as system prompts to Claude Code sessions. Override them by placing custom versions in `.colonyos/instructions/` in your repo.

## Development

```bash
git clone https://github.com/rangelak/ColonyOS.git
cd ColonyOS
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest
pytest
```

## License

MIT
