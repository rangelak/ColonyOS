<p align="center">
  <img src="assets/logo.png" alt="ColonyOS" width="320" />
</p>

<h1 align="center">ColonyOS</h1>

<p align="center">
  <strong>The fully autonomous AI pipeline that builds itself.</strong>
</p>

<p align="center">
  <a href="https://github.com/rangelak/ColonyOS/actions/workflows/ci.yml"><img src="https://github.com/rangelak/ColonyOS/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://pypi.org/project/colonyos/"><img src="https://img.shields.io/pypi/v/colonyos?color=blue" alt="PyPI version" /></a>
  <a href="https://github.com/rangelak/ColonyOS/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11%20|%203.12-blue" alt="Python 3.11 | 3.12" /></a>
</p>

<p align="center">
  <a href="#installation">Installation</a> · <a href="#quickstart">Quickstart</a> · <a href="#how-it-works">How It Works</a> · <a href="#cli-reference">CLI</a> · <a href="#configuration-reference">Config</a> · <a href="#slack-integration">Slack</a> · <a href="#web-dashboard">Dashboard</a> · <a href="#architecture">Architecture</a>
</p>

---

ColonyOS is an autonomous software engineering pipeline. Give it a feature description — or let its built-in CEO agent decide what to build — and it writes a PRD, implements the code with tests, runs parallel multi-persona code reviews, fixes issues, and opens a pull request. No human in the loop.

Under the hood it orchestrates [Claude](https://www.anthropic.com/claude) agent sessions via the [Claude Agent SDK](https://docs.anthropic.com/en/docs/agent-sdk) with full codebase awareness. Point it at any repo and let it work.

**ColonyOS builds itself.** Every feature, fix, and review in this repo was proposed, implemented, and shipped by ColonyOS agents running on their own codebase.

---

## Installation

### Prerequisites

| Dependency | Why | Check |
|---|---|---|
| **Python 3.11+** | Runtime | `python3 --version` |
| **Claude Code CLI** | Agent execution engine | `claude --version` |
| **Git** | Branch/commit operations | `git --version` |
| **GitHub CLI** | PR creation, issue fetching | `gh auth status` |

> Don't have Claude Code CLI yet? See [Setting up Claude Code](#setting-up-claude-code) below.

### Install ColonyOS

```bash
# Recommended — handles everything (installs pipx if needed, then colonyos)
curl -sSL https://raw.githubusercontent.com/rangelak/ColonyOS/main/install.sh | sh
```

Or install directly if you already have pip:

```bash
pip install colonyos
```

### Optional extras

```bash
# Slack integration (Socket Mode listener)
pip install "colonyos[slack]"

# Web dashboard (local FastAPI + React UI)
pip install "colonyos[ui]"

# Development (tests, pre-commit hooks, dashboard)
pip install "colonyos[dev]"
```

### Verify your environment

```bash
colonyos doctor
```

This checks Python version, Claude Code CLI authentication, Git, GitHub CLI, and optional dependencies. Fix anything it flags before continuing.

---

## Quickstart

### 1. Initialize a project

```bash
cd your-project/
colonyos init
```

By default, an AI assistant reads your repo, detects your tech stack, and proposes a complete configuration for you to confirm with a single "y". For the classic interactive wizard:

```bash
colonyos init --manual
```

For zero-prompt setup:

```bash
colonyos init --quick --name "MyApp" --description "B2B analytics" --stack "Python/FastAPI"
```

### 2. Run the pipeline

**Directed mode** — you choose what to build:

```bash
colonyos run "Add a health check endpoint"
```

**From a GitHub issue:**

```bash
colonyos run --issue 42
```

**Autonomous mode** — the CEO agent decides what to build:

```bash
colonyos auto
```

**Long-running autonomous loop** — walk away for the day:

```bash
colonyos auto --loop 50 --max-hours 24 --max-budget 500 --no-confirm
```

That's it. ColonyOS generates a PRD, implements the code with tests, runs multi-persona code review, and opens a pull request.

---

## How It Works

ColonyOS runs a multi-phase pipeline where each phase is an isolated Claude agent session with its own instruction template and budget cap.

```mermaid
flowchart LR
    CEO["🧠 CEO\nPropose"] --> Plan["📋 Plan\nPRD + Tasks"]
    Plan --> Impl["⚡ Implement\nCode + Tests"]
    Impl --> Verify["✅ Verify\nRun Tests"]
    Verify --> Review["🔍 Review / Fix\nLoop"]
    Review --> Decision{"🎯 Decision\nGate"}
    Decision -->|GO| Deliver["🚀 Deliver\nPush + PR"]
    Decision -->|NO-GO| Stop["⛔ Stopped"]
```

| Phase | What happens |
|---|---|
| **CEO** *(auto mode only)* | Reviews the strategic directions landscape doc (if present), analyzes the project and its history (`CHANGELOG.md`), then proposes the single highest-impact feature. Optionally refreshes directions after each proposal. |
| **Plan** | Explores the codebase, generates a PRD with clarifying Q&A from your defined personas (running as parallel subagents), and produces a task breakdown. |
| **Implement** | Creates a feature branch, writes tests first, then implements each task. Commits incrementally. |
| **Verify** *(optional)* | Runs your test command (e.g. `pytest`, `npm test`). Failed tests trigger implement retries with failure context before the expensive review phase. |
| **Review / Fix Loop** | Reviewer personas run independent, parallel, read-only reviews. If any request changes, a Staff+ fix agent addresses findings, then reviewers re-run. Repeats up to `max_fix_iterations`. |
| **Decision Gate** | Reads all review artifacts and makes a **GO / NO-GO** verdict. NO-GO halts the pipeline. |
| **Deliver** | Pushes the branch, opens a PR linking back to the PRD, and updates `CHANGELOG.md`. |
| **Learn** | Extracts patterns from review artifacts and persists them to `.colonyos/learnings.md` for future runs. |

### Review / Fix loop detail

```mermaid
flowchart TD
    Start["Start Review Round"] --> Parallel["Parallel Persona Reviews\n(read-only, concurrent)"]
    Parallel --> Check{"All\napprove?"}
    Check -->|Yes| Gate["Decision Gate"]
    Check -->|No| Fix["Fix Agent\nAddress Findings"]
    Fix --> Budget{"Budget &\niterations\nremaining?"}
    Budget -->|Yes| Parallel
    Budget -->|No| Gate
```

---

## CLI Reference

### Getting started

| Command | Description |
|---|---|
| `colonyos doctor` | Check all prerequisites and environment health |
| `colonyos init` | AI-assisted setup (default) — reads repo, proposes config |
| `colonyos init --manual` | Classic interactive wizard |
| `colonyos init --quick` | Zero-prompt setup with defaults |
| `colonyos init --personas` | Re-run just the persona workshop |
| `colonyos status` | Show recent runs, loop summaries, and cost breakdown |
| `colonyos directions` | View CEO strategic directions |
| `colonyos directions --regenerate` | Regenerate directions from scratch |
| `colonyos directions --static` | Lock directions (CEO reads but never rewrites) |
| `colonyos directions --auto-update` | Unlock directions to evolve each CEO iteration |

### Running the pipeline

| Command | Description |
|---|---|
| `colonyos run "prompt"` | Directed mode — plan, implement, review, deliver |
| `colonyos run "prompt" --plan-only` | Stop after PRD + tasks (no code) |
| `colonyos run --from-prd PATH` | Skip planning, implement an existing PRD |
| `colonyos run --issue NUMBER` | Use a GitHub issue as the feature prompt |
| `colonyos run --resume RUN_ID` | Resume a failed run from the last successful phase |
| `colonyos run --offline` | Skip remote git checks (preflight) |
| `colonyos run --force` | Bypass preflight warnings |

### Autonomous mode

| Command | Description |
|---|---|
| `colonyos auto` | CEO proposes a feature and the pipeline builds it |
| `colonyos auto --loop N` | Run N autonomous cycles back-to-back |
| `colonyos auto --max-hours H` | Stop loop after H wall-clock hours |
| `colonyos auto --max-budget USD` | Stop loop after USD aggregate spend |
| `colonyos auto --no-confirm` | Skip human approval of CEO proposals |
| `colonyos auto --propose-only` | CEO proposes but does not execute |
| `colonyos auto --resume-loop` | Resume the most recent interrupted loop |

### Code review

| Command | Description |
|---|---|
| `colonyos review BRANCH` | Standalone multi-persona review on any branch |
| `colonyos review --base BRANCH` | Base branch to diff against (default: `main`) |
| `colonyos review --no-fix` | Review only, skip the fix loop |
| `colonyos review --decide` | Run the decision gate after reviews |

### Execution queue

| Command | Description |
|---|---|
| `colonyos queue add "p1" "p2" --issue 42` | Enqueue prompts and/or GitHub issues |
| `colonyos queue start` | Process pending items sequentially |
| `colonyos queue start --max-cost N` | Aggregate USD cap for the queue |
| `colonyos queue start --max-hours N` | Wall-clock cap for the queue |
| `colonyos queue status` | Show queue state |
| `colonyos queue clear` | Remove all pending items |
| `colonyos queue unpause` | Unpause the queue after a circuit breaker trip |

### CI fix

| Command | Description |
|---|---|
| `colonyos ci-fix PR_NUMBER` | Fetch CI failure logs and auto-fix the code |
| `colonyos ci-fix PR --wait` | Fix, then wait for CI re-run to pass |
| `colonyos ci-fix PR --max-retries N` | Retry the fix-push-wait cycle up to N times |

### Analytics & inspection

| Command | Description |
|---|---|
| `colonyos stats` | Aggregate analytics dashboard (cost, duration, failures) |
| `colonyos stats --last N` | Limit to the N most recent runs |
| `colonyos stats --phase NAME` | Drill into a specific phase |
| `colonyos show RUN_ID` | Detailed single-run inspection |
| `colonyos show RUN_ID --json` | Machine-readable JSON output |
| `colonyos show RUN_ID --phase NAME` | Inspect a specific phase within a run |

### Codebase maintenance

| Command | Description |
|---|---|
| `colonyos cleanup branches` | List merged `colonyos/` branches (dry-run) |
| `colonyos cleanup branches --execute` | Delete merged branches |
| `colonyos cleanup branches --include-remote` | Also prune from origin |
| `colonyos cleanup artifacts` | List stale run artifacts beyond retention |
| `colonyos cleanup artifacts --execute` | Delete stale artifacts |
| `colonyos cleanup artifacts --retention-days N` | Override retention period (default: 30) |
| `colonyos cleanup scan` | Find large files, long functions, dead code |
| `colonyos cleanup scan --ai` | AI-powered qualitative analysis |

### Slack & Dashboard

| Command | Description |
|---|---|
| `colonyos watch` | Watch Slack channels and trigger runs from messages |
| `colonyos watch --dry-run` | Log triggers without executing |
| `colonyos watch --max-hours N` | Wall-clock limit for the watcher |
| `colonyos watch --max-budget N` | Aggregate USD spend limit |
| `colonyos ui` | Launch the local web dashboard |
| `colonyos ui --port N` | Custom port (default: 7400) |
| `colonyos ui --no-open` | Don't auto-open the browser |

### Global flags

| Flag | Applies to | Description |
|---|---|---|
| `-v` / `--verbose` | `run`, `auto` | Stream agent text alongside tool activity |
| `-q` / `--quiet` | `run`, `auto` | Suppress the streaming UI |

---

## Configuration Reference

Configuration lives at `.colonyos/config.yaml`, created by `colonyos init`.

### Project & personas

```yaml
project:
  name: "MyApp"
  description: "B2B analytics platform"
  stack: "Python/FastAPI, React, PostgreSQL"

personas:
  - role: "Senior Backend Engineer"
    expertise: "API design, database modeling, performance"
    perspective: "Thinks about scalability and data integrity"
    reviewer: true        # participates in code reviews (default: false)
  - role: "Product Lead"
    expertise: "User research, prioritization"
    perspective: "Thinks about user value and shipping incrementally"
    # reviewer defaults to false — plan-phase only
```

Personas are the expert panel that reviews your code and asks clarifying questions during planning. Mark `reviewer: true` on personas you want in the review loop.

### Model selection

```yaml
model: opus                  # global default: opus | sonnet | haiku

# Per-phase overrides — route mechanical phases to cheaper models
phase_models:
  plan: sonnet
  implement: opus
  review: opus
  fix: sonnet
  deliver: haiku
  ceo: opus
  verify: haiku
  learn: haiku
```

Using per-phase overrides can reduce costs by 50–70% while keeping `opus` for deep reasoning tasks.

### Budget & safety caps

```yaml
budget:
  per_phase: 5.00            # USD per Claude agent session
  per_run: 15.00             # USD total cap for a full pipeline run
  max_duration_hours: 8.0    # wall-clock cap for autonomous loops
  max_total_usd: 500.0       # aggregate spend cap for autonomous loops
```

### Pipeline phases

```yaml
phases:
  plan: true
  implement: true
  review: true               # parallel per-persona reviews + fix loop
  deliver: true              # set false to skip PR creation

max_fix_iterations: 2        # review/fix cycles before decision gate
auto_approve: true           # skip human confirmation in autonomous mode
```

### Strategic directions

```yaml
directions_auto_update: true   # false = directions stay read-only between iterations
```

The CEO agent reads `.colonyos/directions.md` before every proposal for landscape context, inspiration from similar projects, and the user's north star goals. Generate it with `colonyos directions --regenerate`.

When `directions_auto_update` is `true` (default), a lightweight agent refreshes the document after each CEO proposal. Set to `false` if you prefer to hand-curate your directions and keep them static.

### Verification gate

```yaml
verification:
  verify_command: "pytest --tb=short -q"   # auto-detected by `colonyos init`
  max_verify_retries: 2
  verify_timeout: 120                       # seconds
```

Runs your test suite between implement and review. Failed tests trigger implement retries with failure context — catching bugs before the expensive review phase.

### CI fix

```yaml
ci_fix:
  enabled: false             # set true to auto-fix CI failures in deliver phase
  max_retries: 2             # retry fix-push-wait cycle
  wait_timeout: 600          # seconds to wait for CI re-run
  log_char_cap: 12000        # truncate CI logs sent to the fix agent
```

### Cross-run learnings

```yaml
learnings:
  enabled: true
  max_entries: 100
```

After each run, the pipeline extracts patterns from review artifacts and persists them to `.colonyos/learnings.md`. Future implement and fix phases see these learnings as context, enabling the pipeline to self-improve across iterations.

### Codebase cleanup

```yaml
cleanup:
  branch_retention_days: 0       # 0 = prune all merged colonyos/ branches
  artifact_retention_days: 30    # run logs older than this are stale
  scan_max_lines: 500            # flag files exceeding this line count
  scan_max_functions: 20         # flag files with more functions than this
```

### Branch & directory naming

```yaml
branch_prefix: "colonyos/"
prds_dir: "cOS_prds"
tasks_dir: "cOS_tasks"
reviews_dir: "cOS_reviews"
proposals_dir: "cOS_proposals"
```

---

## Slack Integration

ColonyOS can listen to Slack channels and trigger pipeline runs from messages — your team can request features or report bugs directly in Slack without context-switching.

### 1. Create a Slack app

The fastest way is with the included manifest — it pre-configures all scopes, events, and Socket Mode in one step:

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App** → **From an app manifest**.
2. Select your workspace.
3. Choose **YAML** and paste the contents of [`slack-app-manifest.yaml`](slack-app-manifest.yaml) from this repo.
4. Click **Create**.

<details>
<summary>Manual setup (without manifest)</summary>

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**.
2. **OAuth & Permissions** — add these Bot Token Scopes:
   - `app_mentions:read` — detect `@ColonyOS` mentions
   - `channels:history` — read channel messages
   - `chat:write` — post progress updates
   - `reactions:read` — detect emoji triggers (if using reaction mode)
   - `reactions:write` — acknowledge messages with reactions
3. **Socket Mode** — enable Socket Mode and generate an **App-Level Token** with the `connections:write` scope.
4. **Event Subscriptions** — subscribe to bot events: `app_mention`, `message.channels`, `reaction_added`.

</details>

### 2. Install the app and grab tokens

1. In your Slack app settings, go to **Settings** → **Socket Mode** → generate an **App-Level Token** with `connections:write` scope. Copy the `xapp-...` token.
2. Go to **Install App** → **Install to Workspace** and authorize. Copy the **Bot User OAuth Token** (`xoxb-...`).

### 3. Set environment variables

```bash
export COLONYOS_SLACK_BOT_TOKEN="xoxb-your-bot-token"
export COLONYOS_SLACK_APP_TOKEN="xapp-your-app-level-token"
```

### 4. Configure ColonyOS

Add a `slack` section to `.colonyos/config.yaml`:

```yaml
slack:
  enabled: true
  channels:
    - bugs                   # channel names (with or without #) or IDs
    - feature-requests
  trigger_mode: mention          # mention | reaction | slash_command
  auto_approve: false            # require human approval before executing
  max_runs_per_hour: 3           # rate limit
  allowed_user_ids: []           # empty = allow all workspace members
  daily_budget_usd: 50.0         # optional daily spend cap
  max_queue_depth: 20            # max pending items from Slack
  max_consecutive_failures: 3    # pause watcher after N consecutive failures
```

### 5. Start the watcher

```bash
# Install the Slack extra if you haven't
pip install "colonyos[slack]"

# Start watching
colonyos watch
```

The watcher runs as a long-lived process using Slack Bolt SDK with Socket Mode (no public URL required). When someone mentions `@ColonyOS fix the login bug` in a configured channel, the watcher sanitizes the input, triggers a pipeline run, and posts threaded progress updates back to the Slack thread.

**Trigger modes:**

| Mode | How it works |
|---|---|
| `mention` | `@ColonyOS <prompt>` in any configured channel |
| `reaction` | Add a specific emoji reaction to any message |
| `slash_command` | `/colonyos <prompt>` (requires slash command setup in Slack app config) |

---

## Web Dashboard

ColonyOS includes a local web dashboard for monitoring runs, viewing costs, and managing configuration.

```bash
pip install "colonyos[ui]"
colonyos ui
```

This starts a FastAPI server at `http://localhost:7400` serving a React + Tailwind SPA. The dashboard provides:

- **Run history** with phase-by-phase timelines
- **Cost trend charts** across runs
- **Inline configuration editing** (config, personas)
- **Run launching** from the browser
- **Artifact previews** (PRDs, reviews, proposals)

The dashboard is localhost-only and supports bearer token authentication for write operations.

---

## Output Structure

ColonyOS creates `cOS_`-prefixed directories in your repo as a timestamped audit trail:

```
your-repo/
├── CHANGELOG.md                                    # auto-updated by deliver phase
├── cOS_prds/
│   └── 20260317_172530_prd_stripe_billing.md       # generated PRDs
├── cOS_tasks/
│   └── 20260317_172530_tasks_stripe_billing.md     # task breakdowns
├── cOS_reviews/
│   ├── decisions/
│   │   └── 20260317_decision_stripe_billing.md     # GO/NO-GO verdicts
│   └── reviews/
│       ├── linus_torvalds/
│       │   └── 20260317_review_stripe_billing.md
│       └── staff_security_engineer/
│           └── 20260317_review_stripe_billing.md
├── cOS_proposals/
│   └── 20260317_proposal_ceo_proposal.md           # CEO proposals
└── .colonyos/
    ├── config.yaml                                 # project configuration
    ├── directions.md                               # CEO landscape & inspiration doc
    ├── learnings.md                                # cross-run learnings
    └── runs/                                       # run logs (gitignored)
        └── run-20260317-abc123.json
```

The CEO reads `CHANGELOG.md` and `directions.md` before proposing new features — the changelog avoids duplicating past work, while directions provide landscape context and inspiration from similar projects. Run logs (costs, durations, session IDs) and loop state go to `.colonyos/runs/`, which is gitignored.

---

## Architecture

```
src/colonyos/
├── cli.py              # Click CLI — all commands, REPL mode, welcome banner
├── init.py             # Interactive setup wizard, persona packs, --quick mode
├── orchestrator.py     # Phase chaining: CEO → Plan → Implement → Verify → Review → Deliver → Learn
├── agent.py            # Claude Agent SDK wrapper, parallel execution support
├── config.py           # .colonyos/config.yaml loader + validation
├── directions.py       # CEO strategic directions — generation, updates, display
├── models.py           # Persona, PhaseResult, RunLog, LoopState, QueueItem
├── naming.py           # Deterministic timestamped filenames, slug generation
├── persona_packs.py    # Prebuilt persona packs (startup, backend, fullstack, opensource)
├── ui.py               # Rich streaming terminal UI, phase progress display
├── stats.py            # Aggregate analytics computation + Rich rendering
├── show.py             # Single-run inspector (data layer + render layer)
├── doctor.py           # Prerequisite validation (Python, Claude, Git, GitHub CLI)
├── github.py           # GitHub issue fetching, PR helpers
├── ci.py               # CI failure detection, log retrieval, fix agent
├── cleanup.py          # Branch pruning, artifact cleanup, structural scan
├── slack.py            # Slack Bolt listener, dedup, threaded replies
├── server.py           # FastAPI API for the web dashboard
├── learnings.py        # Cross-run learning extraction + persistence
├── sanitize.py         # Input sanitization for untrusted content (Slack, issues)
├── instructions/       # Markdown templates passed as system prompts
│   ├── ceo.md          # Autonomous feature proposal
│   ├── directions_gen.md  # Landscape doc generation prompt
│   ├── plan.md         # PRD + task generation with persona Q&A
│   ├── implement.md    # Test-first implementation
│   ├── review.md       # Per-persona structured review with VERDICT output
│   ├── fix.md          # Staff+ engineer fix agent
│   ├── decision.md     # GO/NO-GO decision gate
│   ├── deliver.md      # Branch push + PR creation
│   ├── verify_fix.md   # Test failure fix instructions
│   ├── ci_fix.md       # CI failure fix instructions
│   ├── learn.md        # Learning extraction
│   ├── cleanup_scan.md # Structural analysis
│   ├── review_standalone.md
│   ├── fix_standalone.md
│   └── decision_standalone.md
└── web_dist/           # Pre-built Vite SPA (React + Tailwind)
```

Instruction templates are shipped with the package. Override any of them by placing a file with the same name in `.colonyos/instructions/` in your repo.

---

## Security Model

ColonyOS runs Claude Code sessions with `bypassPermissions` enabled — the agent has full read/write/execute access within your repository. This is by design: the agent needs to create branches, write code, run tests, and push to GitHub.

**What this means for you:**

- **Only run ColonyOS on repos where you trust the agent to modify files.**
- Use budget caps (`per_run`, `max_total_usd`) to limit blast radius.
- Review generated PRs before merging, just as you would for any contributor.
- Slack integration sanitizes all incoming messages to mitigate prompt injection, but treat it as defense-in-depth, not a guarantee.
- Long-running loops with `auto_approve: true` amplify the scope of autonomous action — set conservative budget and time caps.

---

## Development

```bash
git clone https://github.com/rangelak/ColonyOS.git
cd ColonyOS
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

The `[dev]` extra installs `pytest`, `pre-commit`, and the dashboard dependencies. A pre-commit hook runs `pytest` before every commit to prevent regressions.

### Releasing

ColonyOS uses tag-based automated releases. The version is derived from git tags via [setuptools-scm](https://github.com/pypa/setuptools-scm) — there is no hardcoded version string.

```bash
git tag v0.2.0
git push origin v0.2.0
# CI automatically: runs tests → builds → publishes to PyPI → creates GitHub Release
```

---

## Setting up Claude Code

ColonyOS requires the Claude Code CLI as its execution engine. If you don't have it yet:

**1. Install Node.js** (required by Claude Code):

```bash
# macOS
brew install node

# Linux (Debian/Ubuntu)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

**2. Install Claude Code CLI:**

```bash
npm install -g @anthropic-ai/claude-code
```

**3. Authenticate:**

```bash
claude
# Follow the prompts to connect your Anthropic account
```

**4. Install GitHub CLI** (needed for PR creation and issue fetching):

```bash
# macOS
brew install gh

# Linux (Debian/Ubuntu)
sudo apt install gh
```

**5. Authenticate GitHub CLI:**

```bash
gh auth login
```

**6. Verify everything:**

```bash
claude --version
gh auth status
colonyos doctor
```

---

## License

[MIT](LICENSE) — Rangel Milushev
