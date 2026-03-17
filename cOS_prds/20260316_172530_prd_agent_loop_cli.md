# PRD: ColonyOS v2 — Autonomous Agent Loop CLI

**Author:** ColonyOS team
**Created:** 2026-03-16
**Status:** In Progress

---

## Introduction

ColonyOS is an installable Python CLI tool that orchestrates Claude Code sessions to autonomously plan and implement features in any repository. A developer runs `colonyos run "Add Stripe billing"` from their repo and walks away. ColonyOS handles the full cycle: PRD generation, task breakdown, implementation, self-review, and pull request creation — all with full repository context provided by Claude Code.

## Goals

1. Provide a single CLI command that turns a rough feature prompt into a shipped PR.
2. Leverage Claude Code as the execution layer so every phase (planning, coding, reviewing) has full repo awareness.
3. Make the tool installable via `pip install colonyos` and usable in any repository.
4. Support user-defined agent personas that shape how PRDs are authored.
5. Keep each phase isolated with independent budget caps and retry logic.
6. Produce timestamped PRD and task artifacts that serve as a chronological changelog.

## User Stories

- As a developer, I want to run `colonyos init` in my repo so that ColonyOS knows about my project, tech stack, and the expert personas that should review features.
- As a developer, I want to run `colonyos run "Add feature X"` and have a complete PR opened without further interaction.
- As a developer, I want to run `colonyos run --plan-only "Add feature X"` to get just the PRD and task breakdown without implementation.
- As a developer, I want to run `colonyos run --from-prd prds/xxx.md` to implement an existing PRD.
- As a developer, I want to see what ColonyOS is doing or has done via `colonyos status`.
- As a developer, I want to configure budget limits so I don't accidentally burn through API credits.
- As a team lead, I want to define personas (e.g. "Security Auditor", "Product Lead") during init so PRDs reflect diverse expert perspectives relevant to my project.

## Functional Requirements

1. `colonyos init` must interactively collect project info (name, description, tech stack) and guide the user through defining 3-5 agent personas (role, expertise, perspective). Results are saved to `.colonyos/config.yaml`.
2. `colonyos init --personas` must allow re-running just the persona setup.
3. `colonyos run "<prompt>"` must orchestrate three phases sequentially: Plan (PRD + tasks), Implement (branch + code + tests), Deliver (PR).
4. Each phase must invoke Claude Code as a separate session via `claude-agent-sdk`, passing phase-specific instruction templates and context from prior phases.
5. Each phase must respect a per-phase budget cap (`budget.per_phase` in config) and a total run budget (`budget.per_run`).
6. The Plan phase must produce a PRD in `prds/YYYYMMDD_HHMMSS_prd_<slug>.md` and a task file in `tasks/YYYYMMDD_HHMMSS_tasks_<slug>.md`.
7. The Implement phase must create a feature branch, write tests first, then implement code.
8. The Deliver phase must open a pull request against the repo's default branch.
9. `--plan-only` flag must stop execution after the Plan phase.
10. `--from-prd <path>` must skip the Plan phase and start from Implement using the specified PRD.
11. `colonyos status` must show current and recent run logs from `.colonyos/runs/`.
12. Instruction templates must ship with the package but be overridable via `.colonyos/instructions/` in the target repo.
13. Personas from config must be injected into Plan phase instructions so Claude Code uses them when generating and answering PRD questions.

## Non-Goals

- ColonyOS does not run as a persistent daemon or always-on service in v2. It is invoked per-prompt.
- ColonyOS does not auto-merge PRs. It opens them; humans approve.
- ColonyOS does not integrate with Slack, Linear, or other external triggers in v2. The input is a CLI prompt.
- ColonyOS does not manage CI/CD pipelines.

## Technical Considerations

- **Execution layer:** Claude Code CLI / `claude-agent-sdk` Python SDK. Each phase is a `query()` call with `ClaudeAgentOptions`.
- **Phase isolation:** Each phase gets a fresh Claude Code session. Artifacts (PRD path, task file path, branch name) are passed between phases by the orchestrator, not shared via session state.
- **Instructions as package data:** Markdown templates in `src/colonyos/instructions/` are included via `pyproject.toml` package-data config. They are read at runtime and passed as system prompts.
- **Config:** YAML file at `.colonyos/config.yaml` loaded with `pyyaml`. Defaults provided for all fields.
- **Naming:** Deterministic timestamped filenames for PRDs and tasks, carried over from v1.
- **Python 3.11+** required. Async orchestrator using `asyncio`.

## Success Metrics

1. A user can go from `pip install colonyos` + `colonyos init` + `colonyos run "..."` to an open PR in under 30 minutes for a medium-complexity feature.
2. All generated PRDs reference actual files and modules from the target repo (repo-aware, not generic).
3. Budget caps are respected — no phase exceeds its configured limit.
4. The tool works on any Python, JavaScript, Go, or Rust repository without project-specific configuration beyond init.

## Open Questions

1. Should the Implement phase be a single Claude Code session or split into per-task sessions?
2. What is the right default budget per phase? ($5 is a starting guess.)
3. Should `colonyos run` support a `--dry-run` mode that shows what it would do without invoking Claude Code?
4. How should the orchestrator handle Claude Code sessions that exit with errors mid-phase?
