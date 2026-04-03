## Proposal: Per-Phase Model Configuration

### Rationale
ColonyOS currently uses a single Claude model for all phases, but phases have vastly different complexity requirements. The IMPLEMENT phase benefits from Opus-level reasoning, while REVIEW, DECISION, and LEARN phases can use Sonnet or Haiku at a fraction of the cost. Enabling per-phase model selection could reduce autonomous loop costs by 50-70%, directly enabling longer `--loop` runs within the same budget — the single biggest lever for making autonomous operation practical.

### Builds Upon
- "Rich Streaming Terminal UI" (UI already shows per-phase info; model name can be displayed)
- "Autonomous CEO Stage (`colonyos auto`)" (autonomous loops are the primary beneficiary of cost reduction)
- "`colonyos stats` Aggregate Analytics Dashboard" (stats already tracks per-phase costs; model info enriches analytics)

### Feature Request
Add per-phase model override configuration to ColonyOS. Currently `config.yaml` has a single top-level `model: opus` field. Extend this so users can specify a model per phase while keeping the top-level `model` as the default fallback.

**Config format:**
```yaml
model: opus              # default for all phases
phase_models:            # optional per-phase overrides
  ceo: sonnet
  plan: opus
  implement: opus
  review: sonnet
  fix: sonnet
  decision: haiku
  learn: haiku
  deliver: haiku
```

**Implementation details:**
1. Add a `phase_models: dict[str, str]` field to `ColonyConfig` in `config.py`, parsed from the `phase_models` YAML key. Default is empty dict (all phases use `config.model`).
2. Add a `get_model(phase: Phase) -> str` method on `ColonyConfig` that returns `phase_models.get(phase.value, self.model)`.
3. Update `run_phase()` in `agent.py` to accept a `model` parameter and pass it to `ClaudeAgentOptions`.
4. Update all `run_phase()` call sites in `orchestrator.py` to use `config.get_model(phase)`.
5. Update `PhaseUI` streaming output to show the model being used for each phase (e.g., `[IMPLEMENT · opus]` vs `[REVIEW · sonnet]`).
6. Update `colonyos init` to offer a "Cost-optimized" preset that sets sensible defaults (opus for implement, sonnet for plan/review/fix, haiku for decision/learn/deliver) vs "Quality-first" (opus everywhere).
7. Include the model used in `PhaseResult` (add `model: str | None` field to `models.py`) so `colonyos stats` can show cost-per-model breakdowns.
8. Serialize `phase_models` in `save_config()` and validate that values are one of `opus`, `sonnet`, `haiku`.
9. Add unit tests for `get_model()` fallback logic, config parsing/serialization, and model propagation to `run_phase()`.

**Acceptance criteria:**
- `config.get_model(Phase.IMPLEMENT)` returns the phase-specific model if configured, otherwise the default
- `run_phase()` uses the correct model per phase (verified via test mocks)
- `colonyos init` offers cost-optimized vs quality-first model presets
- `PhaseResult` records which model was used
- `colonyos stats` shows model breakdown in output
- All existing tests pass; new tests cover the fallback logic and config round-trip
