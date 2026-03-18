# Tasks: Per-Phase Model Override Configuration

## Relevant Files

- `src/colonyos/config.py` - Add `phase_models` field to `ColonyConfig`, `VALID_MODELS` constant, `get_model()` method, parsing in `load_config()`, serialization in `save_config()`, validation logic
- `src/colonyos/models.py` - Add `model: str | None` field to `PhaseResult` dataclass
- `src/colonyos/agent.py` - Populate `PhaseResult.model` with the model used during execution
- `src/colonyos/orchestrator.py` - Replace ~15 `model=config.model` call sites with `model=config.get_model(Phase.XXX)`, update `phase_header()` calls
- `src/colonyos/init.py` - Add model preset selection (quality-first vs cost-optimized) to interactive and quick init flows
- `src/colonyos/stats.py` - Add `ModelUsageRow` dataclass, `compute_model_usage()`, `render_model_usage()`, integrate into dashboard
- `tests/test_config.py` - Tests for `phase_models` parsing, validation, `get_model()` fallback, round-trip serialization
- `tests/test_models.py` - Tests for `PhaseResult.model` field, serialization backward compat
- `tests/test_orchestrator.py` - Tests for model propagation to `run_phase()` calls
- `tests/test_stats.py` - Tests for `compute_model_usage()` and rendering
- `tests/test_init.py` - Tests for preset selection in init flow

## Tasks

- [x]1.0 Config layer: `phase_models` field, `VALID_MODELS`, `get_model()` method
  - [x]1.1 Write tests in `tests/test_config.py`: `TestPhaseModels` class with tests for:
    - `get_model()` returns phase-specific model when configured
    - `get_model()` falls back to `config.model` when phase not in `phase_models`
    - `get_model()` falls back to `config.model` when `phase_models` is empty
    - `load_config()` parses `phase_models` from YAML
    - `load_config()` defaults to empty dict when `phase_models` absent (backward compat)
    - `load_config()` raises `ValueError` on invalid model name in `phase_models`
    - `load_config()` raises `ValueError` on invalid model name in top-level `model`
    - `load_config()` raises `ValueError` on invalid phase key in `phase_models`
    - `save_config()` serializes `phase_models` when non-empty
    - `save_config()` omits `phase_models` when empty
    - Full round-trip: save then load preserves `phase_models` exactly
    - `VALID_MODELS` contains expected values
  - [x]1.2 Add `VALID_MODELS: frozenset[str] = frozenset({"opus", "sonnet", "haiku"})` constant to `config.py`
  - [x]1.3 Add `phase_models: dict[str, str] = field(default_factory=dict)` to `ColonyConfig` dataclass (after `model` field, line 59)
  - [x]1.4 Add `get_model(self, phase: Phase) -> str` method to `ColonyConfig`
  - [x]1.5 Update `load_config()` to parse `phase_models` from YAML and validate model values and phase keys
  - [x]1.6 Update `save_config()` to serialize `phase_models` (only when non-empty)

- [x]2.0 Model layer: Add `model` field to `PhaseResult`
  - [x]2.1 Write tests in `tests/test_models.py`: verify `PhaseResult` accepts `model` kwarg, defaults to `None`, and backward-compatible with old serialized data missing the field
  - [x]2.2 Add `model: str | None = None` field to `PhaseResult` dataclass in `models.py` (after `session_id` field, line 66)

- [x]3.0 Agent layer: Populate `PhaseResult.model` on execution
  - [x]3.1 Write test verifying `run_phase()` returns `PhaseResult` with `model` field set to the model passed in
  - [x]3.2 Update `run_phase()` in `agent.py` to set `model=model` on all `PhaseResult` return paths (success path line 138, error path line 104, no-result path line 116)

- [x]4.0 Orchestrator layer: Use per-phase model resolution
  - [x]4.1 Write tests in `tests/test_orchestrator.py` verifying that `run_phase_sync` is called with the correct per-phase model (mock `config.get_model()`)
  - [x]4.2 Replace all `model=config.model` occurrences in `orchestrator.py` with `model=config.get_model(Phase.XXX)` where XXX is the appropriate phase enum:
    - Line 463: CEO phase → `config.get_model(Phase.CEO)`
    - Line 959: Review phase (in review_calls loop) → `config.get_model(Phase.REVIEW)`
    - Line 1024: Fix phase → `config.get_model(Phase.FIX)`
    - Line 1059: Decision phase → `config.get_model(Phase.DECISION)`
    - Line 1136: Learn phase → `config.get_model(Phase.LEARN)`
    - Line 1265: Plan phase (standalone review) → `config.get_model(Phase.PLAN)`
    - Line 1303: Implement phase → `config.get_model(Phase.IMPLEMENT)`
    - Line 1364: Review phase (standalone review loop) → `config.get_model(Phase.REVIEW)`
    - Line 1423: Fix phase (standalone review loop) → `config.get_model(Phase.FIX)`
    - Line 1445: Decision phase (standalone) → `config.get_model(Phase.DECISION)`
    - Line 1495: Deliver phase → `config.get_model(Phase.DELIVER)`
  - [x]4.3 Update all `ui.phase_header()` calls to pass `config.get_model(Phase.XXX)` instead of `config.model`:
    - Line 455: CEO → `config.get_model(Phase.CEO)`
    - Line 1011-1013: Fix → `config.get_model(Phase.FIX)`
    - Line 1045-1047: Decision → `config.get_model(Phase.DECISION)`
    - Line 1125: Learn → `config.get_model(Phase.LEARN)`
    - Line 1248: Plan → `config.get_model(Phase.PLAN)`
    - Line 1294: Implement → `config.get_model(Phase.IMPLEMENT)`
    - Line 1328-1330: Review → `config.get_model(Phase.REVIEW)`
    - Line 1411-1413: Fix (standalone loop) → `config.get_model(Phase.FIX)`
    - Line 1436: Decision (standalone) → `config.get_model(Phase.DECISION)`
    - Line 1482: Deliver → `config.get_model(Phase.DELIVER)`

- [x]5.0 CLI / Init: Model preset selection
  - [x]5.1 Write tests in `tests/test_init.py` verifying:
    - Interactive init presents preset menu and sets `phase_models` accordingly
    - Quick init sets cost-optimized `phase_models` by default
    - "Quality-first" preset results in empty `phase_models` (all phases use top-level model)
    - "Cost-optimized" preset sets expected per-phase overrides
  - [x]5.2 Define `MODEL_PRESETS` dict in `init.py` with "Quality-first" (empty dict, model=opus) and "Cost-optimized" (phase_models with opus/sonnet/haiku assignments)
  - [x]5.3 Add preset selection prompt to interactive init flow (after model prompt, ~line 214)
  - [x]5.4 Update quick init to apply cost-optimized preset by default (~line 167)
  - [x]5.5 Ensure `phase_models` is passed through to `ColonyConfig` in all init code paths

- [x]6.0 Stats: Model usage breakdown
  - [x]6.1 Write tests in `tests/test_stats.py` for:
    - `compute_model_usage()` groups phases by model correctly
    - `compute_model_usage()` handles missing model field (old logs) gracefully
    - `render_model_usage()` produces expected Rich output
    - Integration into `compute_stats()` and `render_dashboard()`
  - [x]6.2 Add `ModelUsageRow` dataclass to `stats.py` with fields: `model: str`, `invocations: int`, `total_cost: float`, `avg_cost: float`
  - [x]6.3 Add `model_usage: list[ModelUsageRow]` field to `StatsResult`
  - [x]6.4 Implement `compute_model_usage(runs: list[dict]) -> list[ModelUsageRow]`
  - [x]6.5 Integrate `compute_model_usage()` into `compute_stats()`
  - [x]6.6 Implement `render_model_usage()` and add to `render_dashboard()`

- [x]7.0 Run log serialization: Backward-compatible `model` in PhaseResult
  - [x]7.1 Write test verifying old run log JSON without `model` field loads correctly (field defaults to None)
  - [x]7.2 Verify `_save_run_log()` in orchestrator serializes the `model` field in phase entries (this should work automatically if `PhaseResult` has the field and existing serialization uses `__dict__` or similar)

- [x]8.0 Integration verification
  - [x]8.1 Run full test suite (`pytest tests/`) to confirm no regressions
  - [x]8.2 Manual smoke test: create a config with `phase_models`, run `colonyos stats` to verify model breakdown renders
  - [x]8.3 Manual smoke test: run `colonyos init` and verify preset selection works
