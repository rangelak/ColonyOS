# PRD: Developer Onboarding, README Overhaul & Long-Running Autonomous Loops

**Date**: 2026-03-17
**Status**: Draft
**Author**: ColonyOS Plan Phase

---

## 1. Introduction / Overview

ColonyOS is a fully autonomous AI pipeline that builds itself. While the core pipeline is powerful — CEO → Plan → Implement → Review/Fix → Decision → Deliver — three friction points prevent it from reaching its potential:

1. **Onboarding friction**: New developers face a prerequisite wall (Python 3.11+, Claude Code CLI, Git, GitHub CLI) with no automated validation. When something is missing, they discover it deep inside a failed agent session.
2. **README lacks "proof of life"**: The README is structurally solid but reads like documentation, not a product showcase. It's missing visual proof (terminal GIFs, badges), social proof (wall of self-built PRs), and the emotional resonance that makes a developer stop scrolling.
3. **Artificial loop cap**: `MAX_LOOP_ITERATIONS = 10` in `src/colonyos/cli.py` (line 44) prevents 24+ hour autonomous runs. There are no time-based budget caps or loop-level persistence, making long-running sessions both impossible and unsafe.

This PRD addresses all three as a unified "developer experience" initiative.

## 2. Goals

1. **Sub-5-minute onboarding**: A developer with Claude Code authenticated should go from `pip install colonyos` to first `colonyos run` invocation in under 2 minutes of human effort.
2. **Zero-confusion prerequisites**: A new `colonyos doctor` command validates all dependencies and provides actionable fix instructions before any pipeline run can fail silently.
3. **README as a product showcase**: Add badges, hero terminal recording reference, "Built by ColonyOS" wall of PRs, and a "Zero to PR" narrative that makes the project irresistible.
4. **24+ hour autonomous runs**: Remove the hard iteration cap, add time-based and aggregate budget caps, persist loop state to disk, and enable auto-resume on crash.
5. **Quick-start init path**: Add `colonyos init --quick` that picks sensible defaults (first persona pack, default budgets) with zero interactive prompts.

## 3. User Stories

**US-1**: As a developer who just heard about ColonyOS, I want to run `colonyos doctor` and immediately see which prerequisites I'm missing with exact install commands, so I don't waste 15 minutes debugging a cryptic error.

**US-2**: As a developer evaluating ColonyOS, I want the README to show me a terminal recording of the tool building a feature end-to-end, badges proving it's maintained, and links to PRs it actually shipped on itself, so I trust it enough to try it.

**US-3**: As a power user, I want to run `colonyos auto --loop 50 --max-hours 24 --max-budget 500` and walk away for a day, knowing the system will checkpoint after each iteration, respect my budget/time caps, and auto-resume if a single iteration fails.

**US-4**: As a developer in a hurry, I want to run `colonyos init --quick` and skip the interactive persona workshop entirely, so I can get to my first run in 60 seconds.

**US-5**: As a developer running ColonyOS overnight, I want to see a summary of what happened when I come back — how many iterations completed, total cost, which PRs were opened — via `colonyos status --loop`.

## 4. Functional Requirements

### 4.1 `colonyos doctor` Command

- **FR-1**: Add a new `doctor` Click command in `src/colonyos/cli.py` that checks:
  - Python version ≥ 3.11
  - `claude --version` is reachable (implies Claude Code CLI installed)
  - `git --version` is reachable
  - `gh auth status` returns success (implies GitHub CLI installed and authenticated)
  - `.colonyos/config.yaml` exists and is parseable (if in a project directory)
- **FR-2**: Each check prints a green checkmark (✓) or red X (✗) with the exact install/fix command on failure.
- **FR-3**: `colonyos doctor` exits with code 0 if all checks pass, code 1 if any fail.
- **FR-4**: `colonyos init` should run doctor checks as its first action and refuse to proceed if hard prerequisites (Python, claude, git) are missing.

### 4.2 `colonyos init --quick` Flag

- **FR-5**: Add a `--quick` flag to `colonyos init` in `src/colonyos/init.py` that:
  - Skips the interactive persona workshop
  - Uses the first persona pack ("Startup Team") as default
  - Uses all default config values from `src/colonyos/config.py` `DEFAULTS`
  - Still requires project name, description, and stack (auto-detected from repo if possible)
- **FR-6**: After init completes (quick or interactive), print a concrete copy-pasteable next-step command, e.g., `colonyos run "Add a health check endpoint"`.

### 4.3 README Overhaul

- **FR-7**: Add a badges bar below the logo: PyPI version, license (MIT), Python version, build status placeholder.
- **FR-8**: Add a "Zero to PR" hero section immediately after the tagline showing the 3-command flow with expected timeline.
- **FR-9**: Add a "Built by ColonyOS" section with links to actual PRs and PRDs that the pipeline shipped on its own repo.
- **FR-10**: Add a "Prerequisites" quick-check block: `pip install colonyos && colonyos doctor`.
- **FR-11**: Add a `colonyos doctor` section to the CLI Reference table.
- **FR-12**: Recommend `pipx install colonyos` as the preferred install method for global CLI usage.
- **FR-13**: Add a "Philosophy" or "Why ColonyOS?" section explaining the self-improvement thesis.
- **FR-14**: Add a "New to Claude Code?" collapsible section at the bottom for developers who need to set up prerequisites from scratch.

### 4.4 Long-Running Autonomous Loops

- **FR-15**: Remove or raise `MAX_LOOP_ITERATIONS = 10` cap in `src/colonyos/cli.py` line 44. Replace with a configurable default (e.g., 100) that can be overridden by `--loop N` with no hard ceiling.
- **FR-16**: Add `max_duration_hours: float` field to `BudgetConfig` in `src/colonyos/config.py` (default: 8.0). The auto loop checks elapsed wall-clock time at the start of each iteration and exits gracefully if exceeded.
- **FR-17**: Add `max_total_usd: float` field to `BudgetConfig` (default: 500.0). The auto loop checks aggregate cost across all iterations and exits gracefully if exceeded.
- **FR-18**: Add CLI flags `--max-hours` and `--max-budget` to the `auto` command that override config values for a single session.
- **FR-19**: Persist loop state to `.colonyos/runs/loop_state.json` after each iteration, tracking: current iteration, total iterations requested, aggregate cost, start time, list of completed run IDs.
- **FR-20**: Add `colonyos auto --resume-loop` flag that reads the loop state file and continues from the last completed iteration.
- **FR-21**: Within the auto loop, when a single iteration fails, log the failure, persist loop state, and continue to the next iteration (with the failed run marked as resumable) rather than calling `sys.exit(1)`.
- **FR-22**: Add a heartbeat file (`.colonyos/runs/heartbeat`) that the orchestrator touches every 60 seconds during active phases, allowing external monitoring tools to detect hangs.

### 4.5 Enhanced Status for Long Runs

- **FR-23**: Extend `colonyos status` to show loop-level summaries when a loop state file exists: iterations completed/total, aggregate cost, elapsed time, PRs opened.

## 5. Non-Goals

- **NG-1**: Docker-based setup — adds complexity for filesystem/git/credential access that contradicts friction reduction. Revisit post-v1.0.
- **NG-2**: Homebrew formula — premature at v0.1.0, maintenance overhead without proven demand.
- **NG-3**: npx-style one-liner — ColonyOS is a Python tool for Python-native developers.
- **NG-4**: Built-in telemetry — no silent data collection; observability is local-only via run logs.
- **NG-5**: Redesigning the interactive `colonyos init` flow — the persona workshop is already well-designed; we're adding `--quick` as an alternative, not replacing it.
- **NG-6**: Daemon/service mode — long runs stay as foreground processes; users can use `tmux`/`screen`/`nohup` for backgrounding.
- **NG-7**: Auto-installing prerequisites — `colonyos doctor` diagnoses and directs; it does not install software on the user's behalf.

## 6. Technical Considerations

### Existing Code Impact

| File | Change |
|------|--------|
| `src/colonyos/cli.py` | Add `doctor` command (~50 LOC), add `--quick` passthrough to init, remove `MAX_LOOP_ITERATIONS` hard cap, add `--max-hours`/`--max-budget`/`--resume-loop` flags to `auto`, add loop state persistence, modify error handling in auto loop |
| `src/colonyos/config.py` | Add `max_duration_hours` and `max_total_usd` to `BudgetConfig` dataclass, update `DEFAULTS`, update `_parse_budget` |
| `src/colonyos/init.py` | Add `--quick` flag handling, add doctor pre-check call, add post-init next-step suggestion |
| `src/colonyos/models.py` | Add `LoopState` dataclass for loop persistence |
| `README.md` | Full overhaul: badges, hero section, Zero to PR, Built by ColonyOS, philosophy, doctor reference, collapsible Claude Code setup guide |
| `tests/test_cli.py` | Tests for `doctor` command, `--quick` init, raised loop cap, `--max-hours`, `--max-budget`, `--resume-loop`, loop state persistence |
| `tests/test_config.py` | Tests for new `BudgetConfig` fields, backward compatibility with configs missing new fields |
| `tests/test_init.py` | Tests for `--quick` flag behavior, doctor pre-check |

### Dependencies

- No new Python dependencies required. `subprocess` handles prerequisite checks. `time.time()` handles elapsed clock.
- The heartbeat file uses simple `Path.touch()` — no external process needed.

### Backward Compatibility

- Existing `.colonyos/config.yaml` files without `max_duration_hours` or `max_total_usd` must work with sensible defaults (8 hours, $500).
- Existing `--loop N` behavior preserved; just the hard cap removed.
- `colonyos doctor` is additive — no existing commands change behavior.

### Security Considerations (per Staff Security Engineer)

- `colonyos doctor` must not cache or store credentials — only test liveness.
- Long-running sessions with `auto_approve: true` and `bypassPermissions` amplify the blast radius of any agent misbehavior. Time and budget caps are essential safety nets.
- The README should explicitly mention the `bypassPermissions` trust model so developers give informed consent.

## 7. Success Metrics

| Metric | Target |
|--------|--------|
| Time from `pip install` to first `colonyos run` invocation (prerequisites pre-met) | < 2 minutes human effort |
| Time from `pip install` to first `colonyos run` invocation (from scratch) | < 10 minutes human effort |
| `colonyos doctor` catches 100% of missing prerequisites | All 4 checks pass/fail correctly |
| Maximum autonomous loop duration supported | 24+ hours |
| Loop crash recovery | Auto-continue to next iteration; failed runs marked resumable |
| README includes visual proof | At minimum: badges, terminal recording placeholder, wall of PRs section |

## 8. Open Questions

1. **Terminal recording format**: Should we use asciinema, VHS (charmbracelet), or a simple GIF? VHS is reproducible from a tape file checked into the repo, which fits the "builds itself" narrative.
2. **Auto-detection for `--quick`**: Should `colonyos init --quick` attempt to auto-detect project name/stack from `pyproject.toml`, `package.json`, or `Cargo.toml`?
3. **Heartbeat monitoring**: Should `colonyos status` also read the heartbeat file and warn if a running loop appears stalled (heartbeat > 5 minutes old)?
4. **Budget defaults for long runs**: Is $500 / 8 hours the right default, or should we be more conservative (e.g., $100 / 4 hours) for safety?
5. **`--resume-loop` vs automatic**: Should loop auto-resume be opt-in (`--resume-loop`) or the default behavior of `colonyos auto` when a loop state file exists?

## 9. Persona Synthesis

### Areas of Strong Consensus (All 7 Personas Agree)

- **Build `colonyos doctor`**: Every persona rated this as essential. ~50 lines of code that eliminates an entire class of first-run failures. Documentation alone is insufficient.
- **README needs proof, not more docs**: Terminal recording/GIF, badges, and a "Built by ColonyOS" wall of PRs. The content depth is fine; the emotional resonance and social proof are missing.
- **Remove the hard iteration cap**: Replace `MAX_LOOP_ITERATIONS = 10` with configurable time and budget caps. The cap is a blunt instrument; budget/time guards are the real safety mechanism.
- **Don't redesign `colonyos init`**: The persona workshop is well-designed. Add `--quick` as a fast path, but leave the interactive flow alone.
- **Target Claude Code users first**: Don't try to onboard people who've never heard of Anthropic. The core audience already has Claude Code; optimize for them.
- **No Docker/Homebrew yet**: Premature at v0.1.0. `pip install` (or `pipx install`) is correct for the audience. Docker adds credential/filesystem complexity that contradicts the goal.
- **Add `--quick` to init**: Zero interactive prompts path using first persona pack and defaults.
- **Persist loop state**: The auto loop has no durable state between iterations — if it crashes at iteration 47, you lose the loop position. Write a checkpoint file after each iteration.

### Areas of Tension

- **Docker for security** (Security Engineer) vs. **Docker adds friction** (everyone else): The Security Engineer noted that Docker could sandbox agent sessions with `bypassPermissions`, enforcing least privilege structurally. All other personas said Docker is premature and adds more problems than it solves. **Resolution**: Document the `bypassPermissions` trust model in the README. Revisit Docker as an optional "hardened mode" post-v1.0.
- **Auto-resume vs. manual resume** (Karpathy, Systems Engineer): Karpathy and the Systems Engineer suggested the loop should auto-resume failed iterations by default. The Security Engineer cautioned that auto-resume can't distinguish "transient blip" from "agent stuck in a destructive loop." **Resolution**: Auto-continue to the *next* iteration on failure (don't retry the failed one). Mark the failed run as resumable for manual intervention.
- **Budget default conservatism**: Michael Seibel suggested no default cap is needed for power users. The Security Engineer wanted $100/4 hours as a conservative default. **Resolution**: Default to $500/8 hours — aggressive enough to be useful, conservative enough to prevent surprise bills. Power users raise it deliberately.
