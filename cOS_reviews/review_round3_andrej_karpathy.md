# Review by Andrej Karpathy (Round 3)

I now have a comprehensive picture of the implementation. Let me compile my review.

---

## Review: Per-Phase Model Override Configuration

**Reviewer**: Andrej Karpathy  
**Branch**: `colonyos/add_per_phase_model_override_configuration_to_colonyos_currently_config_yaml_has`

### Checklist Assessment

- [x] **FR-1**: `phase_models: dict[str, str]` on `ColonyConfig` ✓
- [x] **FR-2**: `VALID_MODELS: frozenset` ✓
- [x] **FR-3**: `get_model(phase)` with fallback ✓
- [x] **FR-4**: Parse `phase_models` from YAML ✓
- [x] **FR-5**: Validate model values at load time ✓
- [x] **FR-6**: Validate phase keys against `Phase` enum ✓
- [x] **FR-7**: Serialize `phase_models` only when non-empty ✓
- [x] **FR-8**: `model: str | None = None` on `PhaseResult` ✓
- [x] **FR-9**: Populate `PhaseResult.model` in all 3 return paths of `run_phase()` ✓
- [x] **FR-10**: All `config.model` → `config.get_model(Phase.XXX)` in orchestrator (22 call sites, 0 remaining `config.model` references) ✓
- [x] **FR-11**: All `ui.phase_header()` calls pass per-phase model ✓
- [x] **FR-12**: No changes needed to `ui.py` ✓
- [x] **FR-13**: Model preset selection in interactive init ✓
- [x] **FR-14**: Quick mode defaults to cost-optimized ✓
- [x] **FR-15**: Persist `phase_models` in generated config ✓
- [x] **FR-16**: `ModelUsageRow` dataclass ✓
- [x] **FR-17**: `compute_model_usage()` ✓
- [x] **FR-18**: `model_usage` on `StatsResult` ✓
- [x] **FR-19**: `render_model_usage()` integrated into `render_dashboard()` ✓
- [x] **FR-20**: `model` in PhaseResult serialization, backward-compatible with `.get("model")` → `None` ✓

**Tests**: 361 passed, 0 failed  
**Remaining `config.model`** in orchestrator: 0  
**No TODOs or placeholder code**  
**No new dependencies**

---

VERDICT: approve

FINDINGS:
- [src/colonyos/init.py]: The Cost-optimized preset omits `decision: "haiku"` that the PRD specifies ("haiku for decision/learn/deliver"). Instead, decision falls back to the global `sonnet` default. This is actually a *better* choice than the PRD — the implementation correctly identifies decision as a `_SAFETY_CRITICAL_PHASES` member and keeps it at sonnet. The PRD's own Open Questions section (#2) acknowledged this concern. This is a thoughtful deviation.
- [src/colonyos/config.py]: The `_SAFETY_CRITICAL_PHASES` warning for haiku on review/decision/fix is a good addition not explicitly required by the PRD. It uses `logger.warning()` which is non-blocking — exactly the right level of guardrail. A stochastic model producing a "ship it" review on haiku could be catastrophic in a pipeline running with `bypassPermissions`.
- [src/colonyos/config.py]: `get_model()` is a clean one-liner (`phase_models.get(phase.value, self.model)`) — the right level of simplicity for a precedence rule. No over-engineering.
- [src/colonyos/stats.py]: The `<legacy>` sentinel for old run logs without a `model` field is a clean backward-compat choice. It surfaces in the dashboard so users can see which data predates the feature rather than silently lumping it with a default model.
- [src/colonyos/init.py]: The Cost-optimized preset uses `model: "sonnet"` as the global default with only `implement: "opus"` overridden upward. This is the right design — default to the cheaper model and override upward for capability-hungry phases, rather than defaulting to opus and overriding downward everywhere. It means adding a new phase in the future gets sonnet by default, not opus.
- [tests/]: Comprehensive test coverage across all layers — config validation (invalid models, invalid phases, round-trip), model propagation through orchestrator, stats aggregation, init presets. 222+ new test lines in test_config.py alone.

SYNTHESIS:
This is a well-executed feature that treats the model routing configuration with the rigor of a program, not a setting. The key design decisions are correct: fail-fast validation at config load time (not phase execution time — catching a typo 30 minutes into a run would be infuriating), a hardcoded allowlist over arbitrary strings (V1 is the right time for constraints, not flexibility), and the single-method `get_model()` resolution that makes the precedence rule trivially auditable. The safety-critical phase warning is exactly the right intervention — it doesn't block the user but makes the cost/risk tradeoff legible. The one deviation from the PRD (keeping decision at sonnet instead of haiku in the cost-optimized preset) is a case where the implementation is smarter than the spec, which is the correct direction for disagreements to flow. The structured output from the model — `PhaseResult.model` — creates a clean data trail that makes the stats dashboard possible without any heuristics. Clean work.