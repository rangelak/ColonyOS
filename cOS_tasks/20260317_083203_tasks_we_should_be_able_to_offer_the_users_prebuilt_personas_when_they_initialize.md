# Tasks: Prebuilt Persona Templates for `colonyos init`

## Relevant Files

- `src/colonyos/models.py` - Add `PersonaPack` dataclass alongside existing `Persona`
- `src/colonyos/persona_packs.py` - **New file.** Prebuilt pack definitions and lookup functions
- `src/colonyos/init.py` - Modify init flow to present pack selection before custom persona collection
- `src/colonyos/cli.py` - No changes expected (init command already delegates to `run_init`)
- `src/colonyos/config.py` - No changes expected (packs flatten to persona lists before saving)
- `src/colonyos/orchestrator.py` - No changes expected (consumes `list[Persona]` unchanged)
- `tests/test_persona_packs.py` - **New file.** Tests for pack definitions, validation, and lookup
- `tests/test_init.py` - **New file.** Tests for init flow with pack selection (mocked click prompts)
- `tests/test_config.py` - Existing config tests; verify no regressions

## Tasks

- [x] 1.0 Add `PersonaPack` data model
  - [x] 1.1 Write tests for `PersonaPack` dataclass in `tests/test_persona_packs.py` — test frozen immutability, field types, tuple of `Persona` instances
  - [x] 1.2 Add `PersonaPack` dataclass to `src/colonyos/models.py` with fields: `key: str`, `name: str`, `description: str`, `personas: tuple[Persona, ...]`

- [x] 2.0 Create prebuilt persona packs module
  - [x] 2.1 Write tests in `tests/test_persona_packs.py` — test that `PACKS` is non-empty, all packs have unique keys, all packs have 3-5 personas, `get_pack(key)` returns correct pack, `get_pack("nonexistent")` returns `None`, all `pack_keys()` match `PACKS`
  - [x] 2.2 Create `src/colonyos/persona_packs.py` with:
    - A `PACKS: tuple[PersonaPack, ...]` constant containing 4 packs: `startup`, `backend`, `fullstack`, `opensource`
    - Each pack with 3-5 curated `Persona` instances with thoughtful role/expertise/perspective
    - `get_pack(key: str) -> PersonaPack | None` lookup function
    - `pack_keys() -> list[str]` convenience function
  - [x] 2.3 Define the "Startup Team" pack — personas focused on product-market fit, velocity, technical pragmatism, user experience, and security basics
  - [x] 2.4 Define the "Backend/API" pack — personas focused on API design, database modeling, reliability/SRE, security, and performance
  - [x] 2.5 Define the "Full-Stack Web" pack — personas focused on frontend UX, backend architecture, DevOps/CI, accessibility, and product thinking
  - [x] 2.6 Define the "Open Source Library" pack — personas focused on API surface design, documentation/DX, backward compatibility, security/supply-chain, and community/adoption

- [x] 3.0 Add pack selection to init flow
  - [x] 3.1 Write tests in `tests/test_init.py` — test `select_persona_pack()` returns pack personas when a pack is chosen, returns `None` when "Custom" is chosen, test integration with `collect_personas()` (pack selected, then no custom additions), test integration with `collect_personas()` (pack selected, then custom additions on top)
  - [x] 3.2 Implement `select_persona_pack() -> list[Persona] | None` in `src/colonyos/init.py`:
    - Display numbered menu: each pack's name + description, plus a final "Custom (define your own)" option
    - On pack selection: display the pack's personas, ask for confirmation
    - If confirmed, return the pack's persona list
    - If "Custom" selected, return `None`
  - [x] 3.3 Modify `run_init()` in `src/colonyos/init.py` to call `select_persona_pack()` before `collect_personas()`:
    - If pack selected: ask "Add custom personas on top?" (default no). If yes, call `collect_personas(existing=pack_personas)`. If no, use pack personas directly.
    - If custom selected: call `collect_personas(existing)` as today
  - [x] 3.4 Ensure the `personas_only=True` path also goes through the pack selection flow (same logic)

- [x] 4.0 End-to-end testing and validation
  - [x] 4.1 Write an end-to-end CLI test in `tests/test_cli.py` — invoke `colonyos init` with simulated input selecting a prebuilt pack, verify config.yaml contains the pack's personas
  - [x] 4.2 Run the full test suite (`pytest`) and verify zero regressions in existing tests (`test_config.py`, `test_naming.py`, `test_orchestrator.py`, `test_cli.py`)
  - [ ] 4.3 Manual smoke test: run `colonyos init` interactively, select a pack, verify config output; run again with `--personas`, switch to a different pack, verify config updated

- [x] 5.0 Documentation and polish
  - [x] 5.1 Update the `colonyos init` help text in `src/colonyos/cli.py` if needed to mention prebuilt personas
  - [x] 5.2 Add inline docstrings to `persona_packs.py` and new functions in `init.py`
