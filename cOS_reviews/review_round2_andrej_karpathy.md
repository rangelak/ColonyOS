# Review by Andrej Karpathy (Round 2)

All 432 tests pass. Now let me produce my review.

---

## Review: Per-Phase Model Override Configuration

**Reviewer:** Andrej Karpathy  
**Branch:** `colonyos/add_per_phase_model_override_configuration_to_colonyos_currently_config_yaml_has`  
**PRD:** `cOS_prds/20260318_003243_prd_add_per_phase_model_override_configuration_to_colonyos_currently_config_yaml_has.md`

---

### Completeness Assessment

All 20 functional requirements (FR-1 through FR-20) from the PRD are implemented:

| Requirement | Status | Notes |
|---|---|---|
| FR-1–FR-7 (Config layer) | ✅ | `phase_models`, `VALID_MODELS`, `get_model()`, parsing, validation, serialization all present |
| FR-8 (PhaseResult.model) | ✅ | Field added with `None` default |
| FR-9 (Agent populates model) | ✅ | All 3 return paths in `run_phase()` set `model=model` |
| FR-10 (Orchestrator call sites) | ✅ | All `model=config.model` replaced with `config.get_model(Phase.XXX)` |
| FR-11 (phase_header calls) | ✅ | All updated |
| FR-13–FR-15 (Init presets) | ✅ | Quality-first and Cost-optimized presets, quick mode defaults to cost-optimized |
| FR-16–FR-19 (Stats model usage) | ✅ | `ModelUsageRow`, `compute_model_usage()`, `render_model_usage()`, integrated into dashboard |
| FR-20 (Run log serialization) | ✅ | Model field serialized, backward-compat with `None` default on load |

All tasks in the task file are marked `[x]`. 432 tests pass. No TODO/placeholder code remains.

### Quality Assessment from My Perspective

**What's done well — treating prompts as programs:**

1. **`get_model()` is a single point of truth** — the resolution logic `phase_models.get(phase.value, self.model)` is clean, testable, and has exactly one code path. No chance of divergent behavior across call sites. This is how you'd design a model routing layer.

2. **Fail-fast validation is correct** — validating at `load_config()` time rather than at phase execution time is the right call. Discovering a typo 30 minutes into a $5 pipeline run is the kind of failure mode that erodes trust in autonomous systems. The error messages are excellent — they mention short names vs full model IDs, which is exactly the guidance a confused user needs.

3. **Safety-critical phase warnings** — the `_SAFETY_CRITICAL_PHASES` constant and the warning when haiku is assigned to review/decision/fix is a pragmatic middle ground. It doesn't block the user (preserving autonomy), but it makes the trade-off visible. This is the right level of human oversight for a V1.

4. **`VALID_MODELS` as a frozenset** — immutable, one-line extensible when new models ship. Clean.

5. **Test coverage is thorough** — 28 new tests for the config layer alone, covering positive paths, negative paths, round-trips, backward compat, and the safety warning behavior. The backward compat test for old run logs without `model` fields is particularly important for a system that persists state across runs.

**Concerns:**

1. **Significant scope creep** — The diff is 3,770 insertions across 32 files, but the PRD describes a focused config+routing change. The branch also includes:
   - A full `github.py` module (291 lines) for issue fetching with prompt injection mitigations
   - `--issue` CLI flag
   - `source_issue` / `source_issue_url` fields on `RunLog`
   - CEO prompt integration with open GitHub issues
   - A full `stats.py` analytics dashboard (576 lines) far beyond the FR-16–19 model usage requirements
   - UI changes for Agent/Dispatch/Task tool display

   These are separate features that should be on separate branches. Bundling them makes this PR harder to review and increases regression risk. The stats and github modules are well-written, but they don't belong here.

2. **The Cost-optimized preset sets `"plan": "sonnet"` explicitly** — This is redundant since the global model is already `"sonnet"`. It's not wrong, but it means the YAML will contain a `phase_models` entry that has no effect. A user reading their config might think they're getting a different model for plan than the default, when they're not. Consider omitting entries that match the global default.

3. **No test for orchestrator model propagation** — Task 4.1 says "Write tests verifying that `run_phase_sync` is called with the correct per-phase model," but I don't see a test class in `test_orchestrator.py` that actually mocks `config.get_model()` and asserts the correct model reaches the agent. The existing tests verify prompt construction and issue integration, but not the model routing path through the orchestrator's `run()` function. This is a gap — the core feature (routing different models to different phases) lacks an end-to-end test through the orchestrator.

4. **`compute_model_usage` maps `None` to `"unknown"`** — This is fine for old logs, but the string `"unknown"` in the stats output could be confusing. Consider labeling it as `"<legacy>"` or similar to make it clear this isn't a model name.

### Safety

- No secrets or credentials in committed code ✅
- The `github.py` module has thoughtful prompt injection mitigations (XML tag stripping, content delimiting) ✅
- Error handling present throughout — timeouts, auth failures, malformed JSON all handled ✅

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/github.py]: Entire module (291 lines) is out of PRD scope — should be a separate branch/PR
- [src/colonyos/stats.py]: 576-line analytics dashboard far exceeds FR-16–19 scope (model usage only) — bulk of this belongs in a separate PR
- [src/colonyos/cli.py]: `--issue` flag, `source_issue` propagation, and `stats` command are unrelated features bundled into this PR
- [src/colonyos/models.py]: `source_issue` and `source_issue_url` fields on RunLog are out of scope
- [src/colonyos/orchestrator.py]: CEO open-issues integration, deliver issue-closing, plan issue-linking are out of scope
- [tests/test_orchestrator.py]: Missing test that verifies `run_phase_sync` is called with `config.get_model(Phase.XXX)` rather than `config.model` in the orchestrator's `run()` function — this is the core routing path
- [src/colonyos/init.py]: Cost-optimized preset includes `"plan": "sonnet"` which is redundant with the global `model: "sonnet"` default — adds noise to config YAML without changing behavior

SYNTHESIS:
The per-phase model override feature itself is cleanly implemented — `get_model()` is elegant, validation is fail-fast with excellent error messages, the safety warning for lightweight models on critical phases strikes the right balance of autonomy vs. oversight, and test coverage for the config/models layer is thorough. This is exactly how you'd design a model routing layer for an autonomous pipeline. However, this branch carries ~60% unrelated code (GitHub issue integration, full analytics dashboard, UI tweaks) that should be separate PRs. The bundling makes it harder to evaluate the core feature's impact and increases merge risk. I'd approve the per-phase model parts immediately if they were isolated. Split the branch: land the model override feature first, then the GitHub and stats features as follow-ups. Also add the missing orchestrator-level integration test that actually verifies the correct model string reaches `run_phase_sync` for each phase.