# PRD: Per-Phase Model Override Configuration

## 1. Introduction/Overview

ColonyOS currently uses a single `model` field in `.colonyos/config.yaml` that applies uniformly to all pipeline phases (CEO, Plan, Implement, Review, Fix, Decision, Learn, Deliver). This means users pay opus-level pricing even for mechanical phases like Deliver or Learn where a lighter model is perfectly adequate.

This feature adds a `phase_models` configuration dict that lets users assign different Claude models to different phases, while keeping the top-level `model` as a fallback default. The goal is to match model capability to task complexity — opus for deep reasoning (Plan, Implement), sonnet for structured judgment (Review, Fix), and haiku for mechanical tasks (Decision, Learn, Deliver) — yielding significant cost savings without quality degradation.

### Persona Consensus Summary

All seven expert personas were consulted. Key areas of agreement and tension:

**Strong agreement:**
- **Fail-fast validation**: All personas unanimously agree model names should be validated at config load time, not at phase execution time. A typo discovered 30 minutes into a run after burning budget on earlier phases is unacceptable.
- **Backward compatibility**: Treat missing `phase_models` as empty dict — existing configs work unchanged with zero migration.
- **Binary presets in init**: Two presets ("quality-first" and "cost-optimized") during `colonyos init`, not an interactive per-phase picker. Power users edit YAML directly.
- **Stats need both metrics**: Show both cost-per-model and invocation-count-per-model in `colonyos stats`.
- **PhaseResult needs model field**: The `PhaseResult` dataclass currently lacks a `model` field — this is a prerequisite for any stats work.

**Tension areas:**
- **Allowlist vs. arbitrary strings**: Steve Jobs, Linus Torvalds, Karpathy, and Security all favor a hardcoded allowlist (`opus`, `sonnet`, `haiku`). Michael Seibel and the Systems Engineer prefer arbitrary strings with soft warnings to avoid breaking on new model releases. Jony Ive proposes a middle ground: allowlist of short names plus acceptance of `claude-*` patterns for version-pinned IDs.
- **Security concern on review phase**: The Security Engineer warns that letting users downgrade the Review/Decision phases to haiku undermines the pipeline's safety gates, since those phases run with `permission_mode="bypassPermissions"`. No other persona raised this concern, but it's worth noting.
- **Resolution**: We adopt the hardcoded allowlist approach for V1 (simpler, safer, better error messages). Adding new models is a one-line change. A `VALID_MODELS` constant makes this easy to extend.

## 2. Goals

1. **Cost reduction**: Enable 50-70% cost savings on pipeline runs by routing low-complexity phases to cheaper models.
2. **Quality matching**: Let users assign model capability to phase complexity rather than one-size-fits-all.
3. **Zero-migration backward compatibility**: Existing configs without `phase_models` behave identically to today.
4. **Observability**: Track which model ran each phase so users can evaluate cost/quality tradeoffs via `colonyos stats`.
5. **Easy onboarding**: Offer sensible presets during `colonyos init` so users don't need to hand-tune YAML.

## 3. User Stories

1. **As a cost-conscious developer**, I want to use haiku for Deliver and Learn phases so I don't spend opus money on mechanical tasks.
2. **As a quality-focused team lead**, I want to use opus for all phases without configuring anything, knowing the default behavior is unchanged.
3. **As a new user running `colonyos init`**, I want to pick between "Quality-first" and "Cost-optimized" presets without thinking about individual phase models.
4. **As an operations person reviewing `colonyos stats`**, I want to see cost breakdowns by model to evaluate whether cost-optimized presets are working.
5. **As a developer editing `config.yaml`**, I want clear validation errors if I typo a model name rather than discovering it mid-run.

## 4. Functional Requirements

### Config Layer (`config.py`)
- **FR-1**: Add `phase_models: dict[str, str]` field to `ColonyConfig` (default: empty dict).
- **FR-2**: Add `VALID_MODELS: frozenset = {"opus", "sonnet", "haiku"}` constant.
- **FR-3**: Add `get_model(phase: Phase) -> str` method on `ColonyConfig` that returns `self.phase_models.get(phase.value, self.model)`.
- **FR-4**: Parse `phase_models` from YAML in `load_config()` via `raw.get("phase_models", {})`.
- **FR-5**: Validate all model values (both `model` and every value in `phase_models`) against `VALID_MODELS` at load time. Raise `ValueError` with the invalid name and list of valid options.
- **FR-6**: Validate that `phase_models` keys are valid `Phase` enum values.
- **FR-7**: Serialize `phase_models` in `save_config()` only when non-empty.

### Model Layer (`models.py`)
- **FR-8**: Add `model: str | None = None` field to `PhaseResult` dataclass.

### Agent Layer (`agent.py`)
- **FR-9**: Populate `PhaseResult.model` with the model string used for that phase execution.

### Orchestrator Layer (`orchestrator.py`)
- **FR-10**: Replace all `model=config.model` call sites (~15 occurrences) with `model=config.get_model(Phase.XXX)`.
- **FR-11**: Update all `ui.phase_header()` calls to pass the resolved per-phase model instead of `config.model`.

### UI Layer (`ui.py`)
- **FR-12**: No changes needed — `phase_header()` already accepts a `model` parameter and displays it. The change is in the caller (orchestrator) passing the correct per-phase model.

### CLI / Init (`init.py`)
- **FR-13**: Add model preset selection to `colonyos init` interactive flow: "Quality-first (opus everywhere)" vs "Cost-optimized (opus for implement, sonnet for plan/review/fix, haiku for decision/learn/deliver)".
- **FR-14**: In quick mode, default to cost-optimized preset.
- **FR-15**: Persist selected `phase_models` in the generated config.

### Stats (`stats.py`)
- **FR-16**: Add `ModelUsageRow` dataclass with fields: `model`, `invocations`, `total_cost`, `avg_cost`.
- **FR-17**: Add `compute_model_usage()` function that groups `PhaseResult` entries by model.
- **FR-18**: Add `model_usage: list[ModelUsageRow]` to `StatsResult`.
- **FR-19**: Add `render_model_usage()` function and integrate into `render_dashboard()`.

### Run Log Serialization
- **FR-20**: Include `model` field in `PhaseResult` serialization to run log JSON files. Backward-compatible: missing field defaults to `None` when loading old logs.

## 5. Non-Goals

- **CLI `--model` flag override**: A `--model` flag that overrides all phases for a single run is useful but out of scope for V1. The config file is the single source of truth for now.
- **Minimum model floor for security-critical phases**: The Security Engineer suggested enforcing a minimum model for Review/Decision phases. This is a good idea but adds complexity; we'll revisit if users report quality issues.
- **Config schema versioning**: Adding a `version` field to config.yaml for migration paths. Not needed for this additive change.
- **Full model ID support**: Supporting versioned model IDs like `claude-opus-4-20250514`. V1 uses short names only (`opus`, `sonnet`, `haiku`).

## 6. Technical Considerations

### Existing Code Patterns
- `load_config()` (line 108 of `config.py`) already uses `.get()` with defaults for every field — `phase_models` follows the same pattern.
- `save_config()` (line 150) conditionally includes optional fields (e.g., `ceo_persona` on line 200) — `phase_models` follows the same pattern.
- `run_phase()` in `agent.py` (line 27) already accepts `model: str | None` — no signature change needed.
- `PhaseResult` (line 60 of `models.py`) is a mutable dataclass — adding `model` is straightforward.
- The orchestrator has ~15 `model=config.model` call sites (lines 463, 959, 1024, 1059, 1136, 1265, 1303, 1364, 1423, 1445, 1495) that need updating.

### Precedence Rule
The model resolution order is: `phase_models[phase.value]` → `config.model` (global default). This is implemented in a single `get_model()` method on `ColonyConfig`.

### Backward Compatibility
- Existing configs without `phase_models` → empty dict → all phases use `config.model` → identical behavior.
- Old run logs without `model` in `PhaseResult` → field defaults to `None` → stats gracefully handles missing data.

### Dependencies
- No new dependencies required.
- All changes are within the existing `colonyos` package.

## 7. Success Metrics

1. **Test coverage**: All new code has corresponding tests; all existing tests pass.
2. **Config round-trip**: `save_config → load_config` preserves `phase_models` exactly.
3. **Fallback correctness**: `get_model(Phase.X)` returns phase-specific model when configured, global default otherwise.
4. **Stats accuracy**: `colonyos stats` shows model usage breakdown when `PhaseResult.model` is populated.
5. **Init UX**: `colonyos init` offers preset selection in under 2 additional prompts.

## 8. Open Questions

1. **Should `colonyos init --quick` default to cost-optimized or quality-first?** The proposal says cost-optimized, but existing behavior is uniform model. Defaulting to quality-first preserves backward compatibility for automated setups.
2. **Should we warn when a user assigns haiku to Review or Decision phases?** The Security Engineer raised valid concerns about safety gates. A non-blocking warning could be a good middle ground.
3. **Should the CEO phase be included in presets?** The CEO phase is only used in `colonyos auto` mode; it's unclear whether users think about it during init.
