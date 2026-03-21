# Tasks: AI-Assisted Setup for ColonyOS Init

## Relevant Files

- `src/colonyos/init.py` - Main init module; add `scan_repo_context()`, `run_ai_init()`, `_build_init_system_prompt()`, `_parse_ai_config_response()` functions
- `src/colonyos/cli.py` - CLI entry point; add `--manual` flag to `init` command, route default to AI-assisted mode
- `src/colonyos/config.py` - Config dataclasses and serialization; minor changes for optional `init_mode` telemetry field
- `src/colonyos/models.py` - Data models; add `RepoContext` dataclass
- `src/colonyos/persona_packs.py` - Persona pack definitions; add helper to serialize packs for prompt injection
- `src/colonyos/agent.py` - Claude Agent SDK wrapper; reused as-is for the init LLM call
- `src/colonyos/ui.py` - Rich terminal UI; add `render_config_preview()` for the confirmation panel
- `tests/test_init.py` - Tests for init module; add comprehensive tests for all new functions
- `tests/test_cli.py` - CLI tests; add tests for new `--manual` flag routing

## Tasks

- [x] 1.0 Add `RepoContext` dataclass and repo scanning
  - [x] 1.1 Write tests for `RepoContext` dataclass and `scan_repo_context()` function in `tests/test_init.py` — test detection of `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `README.md`, and fallback when no manifests exist
  - [x] 1.2 Add `RepoContext` dataclass to `src/colonyos/models.py` with fields: `name: str`, `description: str`, `stack: str`, `readme_excerpt: str`, `manifest_type: str`, `raw_signals: dict[str, str]`
  - [x] 1.3 Implement `scan_repo_context(repo_root: Path) -> RepoContext` in `src/colonyos/init.py` — deterministically read well-known manifest files (README.md, package.json, pyproject.toml, Cargo.toml, go.mod, requirements.txt, Gemfile), truncate each to 2000 chars, extract project name/description/stack signals via simple parsing (JSON for package.json, TOML for pyproject.toml, etc.)

- [x] 2.0 Build the LLM system prompt and response parser
  - [x] 2.1 Write tests for `_build_init_system_prompt()` and `_parse_ai_config_response()` in `tests/test_init.py` — test that the prompt contains pack keys, preset names, and defaults; test JSON parsing with valid response, malformed response, out-of-range pack key, and invalid model name
  - [x] 2.2 Add `packs_summary()` helper to `src/colonyos/persona_packs.py` that returns a serializable dict of all packs (key, name, description, persona roles) for prompt injection
  - [x] 2.3 Implement `_build_init_system_prompt(repo_context: RepoContext) -> str` in `src/colonyos/init.py` — compose a system prompt containing: the `RepoContext`, all persona packs (via `packs_summary()`), `MODEL_PRESETS`, `DEFAULTS` from config.py, and the expected JSON output schema (pack_key, preset_name, project.name/description/stack, vision)
  - [x] 2.4 Implement `_parse_ai_config_response(raw_text: str) -> ColonyConfig | None` in `src/colonyos/init.py` — extract JSON from the LLM response, validate `pack_key` against `pack_keys()`, validate `preset_name` against `MODEL_PRESETS`, construct `ColonyConfig` using `get_pack()` and existing dataclasses, return `None` on any parse/validation failure

- [x] 3.0 Implement the AI-assisted init flow
  - [x] 3.1 Write tests for `run_ai_init()` in `tests/test_init.py` — mock `run_phase_sync` to return a successful result with valid JSON, test fallback to manual on LLM failure, test fallback on JSON parse failure, test fallback when doctor check fails, test confirmation yes/no paths
  - [x] 3.2 Implement `run_ai_init(repo_root: Path, *, doctor_check: bool = False) -> ColonyConfig` in `src/colonyos/init.py`:
    - Run doctor pre-check (same as existing `run_init`)
    - Call `scan_repo_context(repo_root)`
    - Display "Using Claude Haiku to analyze your repo..." message with Rich spinner
    - Call `run_phase_sync(Phase.PLAN, prompt, cwd=repo_root, system_prompt=..., model="haiku", budget_usd=0.50, max_turns=3, allowed_tools=["Read", "Glob", "Grep"])`
    - Parse response via `_parse_ai_config_response()`
    - On success: render preview, prompt for confirmation
    - On confirmation: save config, create directories, update .gitignore (reuse existing logic from `run_init`)
    - On rejection or any failure: fall back to `run_init()` manual wizard with detected values as defaults
  - [x] 3.3 Display actual cost from `PhaseResult.cost_usd` after the LLM call completes

- [x] 4.0 Add Rich config preview panel
  - [x] 4.1 Write tests for `render_config_preview()` in `tests/test_init.py` — test that the panel renders project info, persona roles, model preset, and budget numbers
  - [x] 4.2 Implement `render_config_preview(config: ColonyConfig, pack_name: str, preset_name: str)` in `src/colonyos/init.py` (using Rich Console, Panel, Table) — show project name/description/stack, persona pack name with role list, model preset with phase assignments, budget per phase/per run, and a note that the config can be edited at `.colonyos/config.yaml`

- [x] 5.0 Wire up CLI routing with `--manual` flag
  - [x] 5.1 Write tests for CLI routing in `tests/test_cli.py` — test that `init` with no flags calls `run_ai_init`, `init --manual` calls `run_init`, `init --quick` still calls `run_init(quick=True)`, `init --personas` still calls `run_init(personas_only=True)`
  - [x] 5.2 Add `--manual` flag to the `init` Click command in `src/colonyos/cli.py`
  - [x] 5.3 Update routing logic: default (no flags) → `run_ai_init()`, `--manual` → existing `run_init()`, `--quick` and `--personas` → existing `run_init()` (unchanged)
  - [x] 5.4 Add mutual exclusivity check: `--manual` cannot be combined with `--quick` or `--personas`

- [x] 6.0 Pre-fill manual wizard with detected defaults on AI fallback
  - [x] 6.1 Write tests for fallback pre-fill in `tests/test_init.py` — test that when AI mode falls back to manual, the `click.prompt` defaults are populated with values from `RepoContext`
  - [x] 6.2 Add optional `defaults: RepoContext | None` parameter to `run_init()` in `src/colonyos/init.py` — when provided, use `defaults.name`/`defaults.description`/`defaults.stack` as the default values in `collect_project_info()`'s `click.prompt()` calls
  - [x] 6.3 Update `collect_project_info()` to accept optional default values: `collect_project_info(defaults: RepoContext | None = None) -> ProjectInfo`

- [x] 7.0 Error handling and edge cases
  - [x] 7.1 Write tests for error scenarios in `tests/test_init.py` — test auth failure fallback, network timeout fallback, malformed LLM response fallback, empty repo (no README, no manifests) still works
  - [x] 7.2 Add timeout handling: if the LLM call exceeds 30 seconds, cancel and fall back to manual
  - [x] 7.3 Ensure no partial state is created on failure — `.colonyos/` directory and `config.yaml` must only be created after successful confirmation
  - [x] 7.4 Add clear error messages for common failure modes (no API key, rate limited, credit balance low) using the existing `_friendly_error()` patterns from `agent.py`

- [x] 8.0 Update documentation and help text
  - [x] 8.1 Update the `init` command help string in `src/colonyos/cli.py` to mention AI-assisted mode as default and `--manual` for the classic wizard
  - [x] 8.2 Update the README.md Quickstart section to reflect the new default init experience
  - [x] 8.3 Add a brief note in CHANGELOG.md about the new AI-assisted init mode
