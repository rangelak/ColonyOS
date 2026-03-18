# Review by Andrej Karpathy (Round 1)

Now I have a complete picture. Let me produce the review.

---

## Review: Per-Phase Model Override Configuration

### Completeness Assessment

| Requirement | Status | Notes |
|---|---|---|
| **FR-1** `phase_models` field on `ColonyConfig` | ✅ | `dict[str, str]`, default empty dict |
| **FR-2** `VALID_MODELS` frozenset | ✅ | `frozenset({"opus", "sonnet", "haiku"})` |
| **FR-3** `get_model(phase)` method | ✅ | Clean one-liner with `.get()` fallback |
| **FR-4** Parse `phase_models` from YAML | ✅ | Via `raw.get("phase_models", {})` |
| **FR-5** Validate model values at load time | ✅ | Both global and per-phase validated |
| **FR-6** Validate phase keys | ✅ | Checked against `Phase` enum values |
| **FR-7** Conditional serialization | ✅ | Only written when non-empty |
| **FR-8** `model` field on `PhaseResult` | ✅ | `model: str | None = None` |
| **FR-9** Populate `PhaseResult.model` in agent | ✅ | Set in all 3 return paths |
| **FR-10** Replace `config.model` in orchestrator | ✅ | Zero `config.model` refs remain; ~22 `config.get_model()` call sites |
| **FR-11** Update `phase_header()` calls | ✅ | All pass resolved per-phase model |
| **FR-12** UI layer (no changes needed) | ✅ | Correct — callers updated instead |
| **FR-13** Init preset selection | ✅ | Quality-first / Cost-optimized menu |
| **FR-14** Quick mode defaults to cost-optimized | ✅ | `MODEL_PRESETS["Cost-optimized"]` |
| **FR-15** Persist `phase_models` | ✅ | Via `save_config()` |
| **FR-16** `ModelUsageRow` dataclass | ✅ | |
| **FR-17** `compute_model_usage()` | ✅ | Groups by model, handles missing as "unknown" |
| **FR-18** `model_usage` on `StatsResult` | ✅ | |
| **FR-19** `render_model_usage()` + dashboard integration | ✅ | Conditionally rendered when non-empty |
| **FR-20** `model` in PhaseResult serialization | ✅ | Backward-compat: old logs → `None` → "unknown" in stats |

### Quality Checks

- ✅ **284 tests pass**, 0 failures
- ✅ Tests cover: validation (invalid model, invalid phase key), fallback logic, round-trip serialization, backward compat, model usage stats, init presets
- ✅ No `config.model` references remain in orchestrator — complete migration
- ✅ No commented-out code, no TODOs
- ✅ No new dependencies
- ✅ Follows existing code patterns (`.get()` with defaults, conditional serialization, dataclass style)

### Safety

- ✅ No secrets or credentials
- ✅ Error handling present — `ValueError` with clear messages on invalid config
- ✅ Backward compatibility preserved — missing `phase_models` → empty dict → identical behavior

---

VERDICT: approve

FINDINGS:
- [src/colonyos/config.py]: Clean implementation of `VALID_MODELS`, `get_model()`, and fail-fast validation. The one-liner `get_model()` is exactly right — a single point of model resolution. Validation at load time means a typo like `phase_models: {implement: "opuss"}` blows up immediately, not 20 minutes into a run after burning budget. This is correct.
- [src/colonyos/agent.py]: `model` is populated in all three return paths (success, exception, no-result-message). Good — no silent None leakage.
- [src/colonyos/orchestrator.py]: All ~22 `config.model` references replaced with `config.get_model(Phase.XXX)`. Zero stragglers. The mechanical nature of this change (each call site just swaps the accessor) means low defect risk. The `phase_header()` calls also pass the resolved model, so the UI shows what actually ran.
- [src/colonyos/init.py]: The `MODEL_PRESETS` dict is a clean, declarative structure. Cost-optimized preset wisely keeps opus for implement (the creative/generative phase) and downgrades mechanical phases. Quick mode defaulting to cost-optimized is the right call — users who care about cost are the ones using `--quick` in CI.
- [src/colonyos/stats.py]: `compute_model_usage()` gracefully handles old logs (missing `model` → "unknown"). The `ModelUsageRow` gives users both invocation count and cost per model, which is exactly what you need to evaluate whether the cost-optimized preset is working.
- [tests/test_config.py]: Comprehensive `TestPhaseModels` class with 11 tests covering: valid models constant, get_model fallback, load/save/roundtrip, invalid model rejection, invalid phase key rejection, backward compat. This is thorough.
- [src/colonyos/init.py]: Minor observation: the `personas_only` branch doesn't carry forward `phase_models` from the existing config (line 209-222). If a user runs `colonyos init --personas-only`, their `phase_models` config would be silently dropped. This is pre-existing behavior for other fields too (e.g., `learnings`), so it's not a regression, but worth noting for a future fix.

SYNTHESIS:
This is a well-executed, mechanically clean feature that does one thing and does it right: route different models to different pipeline phases via a single `get_model()` resolution point. The architecture is correct — a single method on `ColonyConfig` is the right abstraction level, not a service class or middleware pattern. The fail-fast validation at config load time is exactly what you want for a system where a bad config discovered mid-run wastes real money. The hardcoded `VALID_MODELS` allowlist is the right V1 call — it trades flexibility for safety and clear error messages. The test coverage is comprehensive, all 284 tests pass, and the backward compatibility story is airtight (empty dict → same behavior). The only nit is the `personas_only` init path dropping `phase_models`, but that's a pre-existing pattern, not a regression. Ship it.