# Tasks: ColonyOS v2 — Autonomous Agent Loop CLI

**PRD:** `prds/20260316_172530_prd_agent_loop_cli.md`
**Created:** 2026-03-16
**Status:** In Progress

## Relevant Files

- `src/colonyos/__init__.py` - Package root
- `src/colonyos/__main__.py` - `python -m colonyos` entry point
- `src/colonyos/cli.py` - Click CLI: init, run, status commands
- `src/colonyos/config.py` - .colonyos/config.yaml loader with defaults
- `src/colonyos/models.py` - WorkItem, PhaseResult, RunLog dataclasses
- `src/colonyos/naming.py` - Deterministic timestamped filename generation
- `src/colonyos/agent.py` - Claude Code SDK wrapper (run_phase)
- `src/colonyos/orchestrator.py` - Phase chaining: plan -> implement -> deliver
- `src/colonyos/instructions/base.md` - Base repo conventions instructions
- `src/colonyos/instructions/plan.md` - Plan phase instructions
- `src/colonyos/instructions/implement.md` - Implement phase instructions
- `src/colonyos/instructions/review.md` - Self-review instructions
- `src/colonyos/instructions/deliver.md` - Deliver/PR phase instructions
- `pyproject.toml` - Package config with console_scripts entry point
- `tests/test_config.py` - Config loading tests
- `tests/test_naming.py` - Naming utility tests
- `tests/test_orchestrator.py` - Orchestrator tests (mocked agent)
- `tests/test_cli.py` - CLI command tests
- `README.md` - Project documentation

## Tasks

- [x] 1.0 Scaffold package structure
  - [x] 1.1 Create `src/colonyos/` with `__init__.py`, `__main__.py`
  - [x] 1.2 Write `pyproject.toml` with console_scripts entry (`colonyos`)
  - [x] 1.3 Write `requirements.txt` with dependencies

- [x] 2.0 Build config module
  - [x] 2.1 Write tests for config loading, defaults, persona parsing
  - [x] 2.2 Implement `config.py`: load `.colonyos/config.yaml`, merge with defaults
  - [x] 2.3 Implement `models.py`: Persona, ProjectConfig, PhaseResult, RunLog dataclasses

- [x] 3.0 Build Claude Code agent wrapper
  - [x] 3.1 Write tests for agent wrapper (mocked SDK)
  - [x] 3.2 Implement `agent.py`: `run_phase()` with budget control, result collection, error handling

- [x] 4.0 Write instruction templates
  - [x] 4.1 Write `base.md`: repo conventions, output structure rules
  - [x] 4.2 Write `plan.md`: PRD + task generation with persona injection
  - [x] 4.3 Write `implement.md`: test-first, branching, coding instructions
  - [x] 4.4 Write `review.md`: self-review checklist
  - [x] 4.5 Write `deliver.md`: PR creation instructions

- [x] 5.0 Build orchestrator
  - [x] 5.1 Write tests for phase chaining (mocked agent)
  - [x] 5.2 Implement `orchestrator.py`: plan -> implement -> deliver with artifact passing
  - [x] 5.3 Implement retry logic for failed phases

- [x] 6.0 Build interactive init with persona workshop
  - [x] 6.1 Implement project info collection (name, description, stack)
  - [x] 6.2 Implement persona definition flow (role, expertise, perspective)
  - [x] 6.3 Save config to `.colonyos/config.yaml`
  - [x] 6.4 Create `prds/` and `tasks/` directories
  - [x] 6.5 Update `.gitignore` with `.colonyos/runs/`

- [x] 7.0 Build CLI
  - [x] 7.1 Write tests for CLI commands
  - [x] 7.2 Implement `colonyos init` command with persona workshop
  - [x] 7.3 Implement `colonyos run` command with --plan-only and --from-prd flags
  - [x] 7.4 Implement `colonyos status` command
  - [x] 7.5 Implement `naming.py` (carried over and adapted)

- [x] 8.0 Write tests
  - [x] 8.1 Test config loading with defaults and overrides
  - [x] 8.2 Test naming utilities
  - [x] 8.3 Test orchestrator with mocked agent
  - [x] 8.4 Test CLI commands

- [x] 9.0 Write documentation
  - [x] 9.1 Write README.md: what, quickstart, architecture, config reference, prerequisites
