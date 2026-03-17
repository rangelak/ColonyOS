# Tasks: Autonomous CEO Stage ("colonyos auto")

## Relevant Files

- `src/colonyos/models.py` - Add `CEO` to `Phase` enum
- `src/colonyos/config.py` - Add `ceo_persona`, `vision`, `proposals_dir` fields to `ColonyConfig`; update `load_config`/`save_config`/`DEFAULTS`
- `src/colonyos/naming.py` - Add `ProposalNames` dataclass and `proposal_names()` function
- `src/colonyos/orchestrator.py` - Add `_build_ceo_prompt()` and `run_ceo()` functions for CEO phase execution
- `src/colonyos/cli.py` - Add `colonyos auto` command with `--no-confirm`, `--plan-only`, `--loop` options
- `src/colonyos/init.py` - Add optional vision collection during init flow
- `src/colonyos/instructions/ceo.md` - New instruction template for CEO phase (new file)
- `src/colonyos/instructions/base.md` - May need minor updates for `proposals_dir` reference
- `tests/test_ceo.py` - New test file for CEO-specific orchestrator logic (new file)
- `tests/test_naming.py` - Add tests for `proposal_names()` function
- `tests/test_config.py` - Add tests for new config fields (`ceo_persona`, `vision`, `proposals_dir`)
- `tests/test_cli.py` - Add tests for `colonyos auto` CLI command
- `tests/test_orchestrator.py` - Add tests for `_build_ceo_prompt()` and `run_ceo()`
- `.colonyos/config.yaml` - Example config showing new fields

## Tasks

- [x] 1.0 Extend data models for CEO phase
  - [x] 1.1 Write tests in `tests/test_config.py` for new `ceo_persona`, `vision`, and `proposals_dir` config fields (loading, saving, defaults)
  - [x] 1.2 Add `CEO = "ceo"` to `Phase` enum in `src/colonyos/models.py`
  - [x] 1.3 Add `ceo_persona: Persona | None`, `vision: str`, and `proposals_dir: str` fields to `ColonyConfig` in `src/colonyos/config.py` with defaults (`ceo_persona=None`, `vision=""`, `proposals_dir="cOS_proposals"`)
  - [x] 1.4 Update `load_config()` to parse `ceo_persona`, `vision`, and `proposals_dir` from YAML
  - [x] 1.5 Update `save_config()` to serialize the new fields
  - [x] 1.6 Add `"proposals_dir": "cOS_proposals"` to `DEFAULTS` dict
  - [x] 1.7 Run existing tests to verify no regressions

- [x] 2.0 Add proposal naming utilities
  - [x] 2.1 Write tests in `tests/test_naming.py` for `ProposalNames` dataclass and `proposal_names()` function
  - [x] 2.2 Add `ProposalNames` frozen dataclass to `src/colonyos/naming.py` with fields: `timestamp`, `slug`, `proposal_filename`
  - [x] 2.3 Add `proposal_names(feature_name, *, timestamp=None)` function following the `planning_names()` pattern, generating filenames like `{ts}_proposal_{slug}.md`
  - [x] 2.4 Run tests to verify

- [x] 3.0 Create CEO instruction template
  - [x] 3.1 Create `src/colonyos/instructions/ceo.md` with the CEO phase system prompt template
  - [x] 3.2 Template must include placeholders for: `{project_name}`, `{project_description}`, `{project_stack}`, `{vision}`, `{prds_dir}`, `{tasks_dir}`, `{reviews_dir}`, `{proposals_dir}`
  - [x] 3.3 Instructions must tell the CEO to: read all prior PRDs/tasks/reviews, analyze the codebase, identify the most impactful next feature, output a clear natural-language feature prompt with brief rationale
  - [x] 3.4 Include scope constraints: single-PR features, aligned with project stack, clear acceptance criteria, no infrastructure overhauls

- [x] 4.0 Implement CEO orchestration logic
  - [x] 4.1 Write tests in `tests/test_ceo.py` for `_build_ceo_prompt()` (verifies system prompt contains project info, vision, persona context) and `run_ceo()` (mocked `run_phase_sync`, verifies read-only tools, proposal artifact saving)
  - [x] 4.2 Add `_build_ceo_prompt(config: ColonyConfig, proposal_filename: str) -> tuple[str, str]` to `src/colonyos/orchestrator.py` — loads `ceo.md` template, formats with config context, returns (system_prompt, user_prompt)
  - [x] 4.3 Add default CEO persona constant: `DEFAULT_CEO_PERSONA = Persona(role="Product CEO", expertise="Product strategy, prioritization, user impact analysis", perspective="What is the single most impactful feature to build next that advances the project's goals?")`
  - [x] 4.4 Add `run_ceo(repo_root, config) -> tuple[str, PhaseResult]` function that: runs the CEO phase with read-only tools (`["Read", "Glob", "Grep"]`), extracts the proposed feature prompt from the result, saves the proposal artifact to `cOS_proposals/`, returns the prompt string and phase result
  - [x] 4.5 Ensure `run_ceo()` uses `config.ceo_persona or DEFAULT_CEO_PERSONA` for the CEO persona context
  - [x] 4.6 Run tests to verify

- [x] 5.0 Add `colonyos auto` CLI command
  - [x] 5.1 Write tests in `tests/test_cli.py` for `colonyos auto` command (mocked orchestrator, verifies `--no-confirm`, `--plan-only`, `--loop` flags, confirmation prompt behavior)
  - [x] 5.2 Add `auto` command to `cli.py` with options: `--no-confirm` (flag), `--plan-only` (flag), `--loop N` (int, default 1)
  - [x] 5.3 Implement command flow: load config -> run CEO phase -> display proposal -> prompt for confirmation (unless `--no-confirm`) -> if approved, call `run_orchestrator()` with CEO's prompt -> display results
  - [x] 5.4 Implement `--plan-only` behavior: run CEO phase, save proposal, display it, exit without triggering pipeline
  - [x] 5.5 Implement `--loop N` behavior: iterate N times, each iteration re-runs CEO phase (re-reading updated codebase), then runs full pipeline if approved
  - [x] 5.6 Ensure proper error handling: exit with helpful message if config not found, if CEO phase fails, or if user rejects proposal

- [x] 6.0 Update init flow for vision field
  - [x] 6.1 Write tests in `tests/test_init.py` for optional vision collection during init
  - [x] 6.2 Add optional vision prompt to `run_init()` in `src/colonyos/init.py`: ask user "Describe your project's vision and priorities (optional, press Enter to skip):"
  - [x] 6.3 Store the vision in config via `save_config()` if provided
  - [x] 6.4 Create `cOS_proposals/` directory during init alongside existing `cOS_prds/`, `cOS_tasks/`, `cOS_reviews/`
  - [x] 6.5 Add `cOS_proposals/` to `.gitignore` pattern (or verify existing `cOS_*/` pattern covers it)
  - [x] 6.6 Run tests to verify

- [x] 7.0 Integration testing and documentation
  - [x] 7.1 Write integration test in `tests/test_ceo.py` that verifies the full flow: CEO phase -> proposal saved -> prompt extracted -> passed to `run_orchestrator()` (all with mocked `run_phase_sync`)
  - [x] 7.2 Write test for `--loop` mode: verify each iteration re-reads codebase, respects iteration cap, accumulates costs correctly
  - [x] 7.3 Write test verifying CEO phase uses read-only tools only (no Write, Edit, Bash in allowed_tools)
  - [x] 7.4 Run full test suite (`pytest tests/`) to verify no regressions
  - [x] 7.5 Update `.colonyos/config.yaml` example to show `ceo_persona` and `vision` fields
