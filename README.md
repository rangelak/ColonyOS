<p align="center">
  <img src="assets/logo.png" alt="ColonyOS" width="320" />
</p>

<h1 align="center">ColonyOS</h1>

<p align="center">
  <strong>Autonomous agent loop that turns prompts into shipped PRs.</strong>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> &middot;
  <a href="#how-it-works">How It Works</a> &middot;
  <a href="#cli-reference">CLI Reference</a> &middot;
  <a href="#configuration">Configuration</a> &middot;
  <a href="#architecture">Architecture</a>
</p>

---

ColonyOS is a CLI tool that orchestrates Claude agent sessions via the [Claude Agent SDK](https://docs.anthropic.com/en/docs/agent-sdk) to plan and implement features in any repository — with full codebase awareness. You give it a feature prompt, it generates a PRD, breaks it into tasks, implements the code, and opens a pull request. No hand-holding required.

## How It Works

```
colonyos run "Add Stripe billing integration"
```

ColonyOS runs five phases, each as a separate Claude agent session with full access to your repo:

| # | Phase | What happens |
|---|-------|-------------|
| 1 | **Plan** | Explores your codebase, generates a PRD with clarifying Q&A from your defined personas (running as parallel subagents), and produces a task breakdown. Outputs go to `cOS_prds/` and `cOS_tasks/`. |
| 2 | **Implement** | Creates a feature branch, writes tests first, then implements each task from the plan. Commits as it goes. |
| 3 | **Review / Fix Loop** | Reviewer-tagged personas each run an independent, parallel, read-only review session. If any request changes, a dedicated fix agent addresses findings, then reviewers re-run. Loop repeats up to `max_fix_iterations`. Artifacts go to `cOS_reviews/`. |
| 4 | **Decision Gate** | Reads all review artifacts and makes a **GO / NO-GO** verdict. NO-GO stops the pipeline before delivery. |
| 5 | **Deliver** | Pushes the branch and opens a pull request with a summary linking back to the PRD. |

Each phase is isolated with its own budget cap. If a phase fails, the run stops and logs what happened.

## Prerequisites

- **Python 3.11+**
- **Claude Code CLI** — installed and authenticated (`claude --version` should work)
- **Git** — the target repo must be a git repository
- **GitHub CLI** (`gh`) — for the deliver phase to open PRs

## Quickstart

```bash
pip install colonyos

cd your-project/
colonyos init          # interactive setup: project info + persona workshop
colonyos run "Add user authentication with JWT"
```

Or go fully autonomous — ColonyOS proposes its own features, then executes:

```bash
colonyos auto          # CEO agent picks a feature, then runs the full pipeline
colonyos auto --loop 5 # run up to 5 autonomous cycles back-to-back
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
Participate in code reviews? [Y/n]: Y

--- Persona 2 ---
Role: Product Lead
Expertise: User research, prioritization
Perspective: Thinks about user value and shipping incrementally
Participate in code reviews? [Y/n]: n

Config saved to .colonyos/config.yaml
```

Personas shape how PRDs are written. During the plan phase, each persona runs as a parallel subagent answering clarifying questions from their unique perspective. Personas with `reviewer: true` also participate in independent, parallel code reviews during the review/fix loop.

## CLI Reference

| Command | Description |
|---------|-------------|
| `colonyos init` | Interactive project + persona setup |
| `colonyos init --personas` | Re-run just the persona workshop |
| `colonyos run "feature prompt"` | Full pipeline: plan → implement → review → deliver |
| `colonyos run "..." --plan-only` | Stop after PRD + tasks |
| `colonyos run --from-prd cOS_prds/xxx.md` | Skip planning, implement an existing PRD |
| `colonyos auto` | Autonomous mode: CEO picks a feature, then runs the pipeline |
| `colonyos auto --loop N` | Run up to N autonomous cycles (max 10) |
| `colonyos status` | Show recent runs with cost breakdown |

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
    reviewer: true        # participates in code reviews
  - role: "Product Lead"
    expertise: "User research, prioritization"
    perspective: "Thinks about user value and shipping incrementally"
    # reviewer defaults to false — plan-phase only

model: opus
budget:
  per_phase: 5.00       # USD per Claude Code session
  per_run: 15.00        # USD total cap for a full run
phases:
  plan: true
  implement: true
  review: true           # parallel per-persona reviews + fix loop
  deliver: true          # set false to skip PR creation
branch_prefix: "colonyos/"
prds_dir: "cOS_prds"
tasks_dir: "cOS_tasks"
reviews_dir: "cOS_reviews"
proposals_dir: "cOS_proposals"
max_fix_iterations: 2    # how many review→fix cycles before decision gate
```

## Output Structure

ColonyOS creates `cOS_`-prefixed directories in your repo that serve as a timestamped changelog of autonomous work:

```
your-repo/
  cOS_prds/
    20260316_172530_prd_stripe_billing.md
    20260317_091200_prd_user_auth.md
  cOS_tasks/
    20260316_172530_tasks_stripe_billing.md
    20260317_091200_tasks_user_auth.md
  cOS_reviews/
    20260317_091200_review_round1_backend_engineer.md
    20260317_091200_review_round2_security_auditor.md
  cOS_proposals/
    20260317_155328_proposal_ceo_proposal.md
```

Run logs (costs, durations, session IDs) go to `.colonyos/runs/` which is gitignored by default.

## Architecture

```
src/colonyos/
  cli.py            # Click CLI entry point
  init.py           # Interactive persona workshop
  orchestrator.py   # Phase chaining: plan → implement → review → deliver
  agent.py          # Claude Agent SDK wrapper
  config.py         # .colonyos/config.yaml loader
  models.py         # Persona, PhaseResult, RunLog
  naming.py         # Deterministic timestamped filenames
  instructions/     # Markdown templates passed to Claude Code
    base.md         # Repo conventions
    plan.md         # PRD + task generation
    implement.md    # Test-first implementation
    review.md       # Per-persona review with structured verdict
    fix.md          # Staff+ engineer fix agent
    decision.md     # GO/NO-GO decision gate
    ceo.md          # Autonomous feature proposal
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
