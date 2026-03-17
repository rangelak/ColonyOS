# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 3)

All 537 tests pass. Now let me compile my review.

---

## Review: Per-Phase Model Override Configuration

### Assessment

I've thoroughly reviewed the implementation on branch `colonyos/add_per_phase_model_override_configuration_to_colonyos_currently_config_yaml_has` against the PRD. Here is my structured assessment:

**PRD Functional Requirements Coverage:**

| FR | Status | Notes |
|---|---|---|
| FR-1: `phase_models` field | ✅ | Added to `ColonyConfig` |
| FR-2: `VALID_MODELS` constant | ✅ | `frozenset({"opus", "sonnet", "haiku"})` |
| FR-3: `get_model()` method | ✅ | Clean fallback logic |
| FR-4: Parse in `load_config()` | ✅ | |
| FR-5: Validate model values | ✅ | Fail-fast with clear error messages |
| FR-6: Validate phase keys | ✅ | |
| FR-7: Conditional serialization | ✅ | Only when non-empty |
| FR-8: `PhaseResult.model` field | ✅ | |
| FR-9: Populate model in agent | ✅ | All 3 return paths covered |
| FR-10: Replace `config.model` | ✅ | Zero remaining `config.model` refs in orchestrator |
| FR-11: Update `phase_header` calls | ✅ | |
| FR-12: No UI changes needed | ✅ | |
| FR-13: Init presets | ⚠️ | Preset deviates from PRD spec (see findings) |
| FR-14: Quick mode default | ✅ | Defaults to cost-optimized |
| FR-15: Persist phase_models | ✅ | |
| FR-16: `ModelUsageRow` | ✅ | |
| FR-17: `compute_model_usage()` | ✅ | |
| FR-18: `model_usage` in StatsResult | ✅ | |
| FR-19: `render_model_usage()` + dashboard | ✅ | |
| FR-20: Run log serialization | ✅ | Backward-compatible |

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/init.py]: **Cost-optimized preset deviates from PRD FR-13.** The PRD specifies "haiku for decision/learn/deliver" but the implementation only maps `learn` and `deliver` to haiku — `decision` falls through to the default `sonnet`. This is actually *arguably better* than the PRD (keeping a stronger model on the decision gate is safer, as the Security Engineer noted), but it's an undocumented deviation. Either update the preset to match the PRD (`"decision": "haiku"`) or explicitly document in the PRD that the decision was made to keep `decision` on `sonnet` for safety reasons. Given the Security Engineer's concern about downgrading safety-critical phases, I'd recommend keeping the current behavior but updating the PRD to match.
- [src/colonyos/init.py]: **`MODEL_PRESETS["Quality-first"]` has empty `phase_models` with `model: "opus"`, but the existing default model is `"sonnet"`.** This means selecting "Quality-first" during init silently upgrades the default model from sonnet to opus — which is the correct behavior per the preset name, but differs from the current default. A user who picks "Quality-first" expecting "same as before" gets a more expensive default. Minor UX concern, not blocking.
- [src/colonyos/config.py]: **Safety warning for haiku on critical phases is well-implemented** — uses `logger.warning()` which is non-blocking and discoverable. Good call including `fix` in `_SAFETY_CRITICAL_PHASES` (the PRD only hinted at review/decision). This exceeds the PRD in a positive way.
- [src/colonyos/stats.py]: **`<legacy>` sentinel for old logs without model field** is a pragmatic choice. Renders clearly in the stats table and avoids None-handling downstream. Clean.
- [src/colonyos/orchestrator.py]: **Unrelated changes bundled in.** The diff includes substantial GitHub issue integration (`source_issue`, `source_issue_url`, `fetch_open_issues` in CEO prompt, `--issue` CLI flag, `github.py` module). These are from a different feature and inflate the diff. Not blocking the per-phase model review, but makes the branch harder to review in isolation and increases merge conflict surface.
- [src/colonyos/ui.py]: **Unrelated UI changes bundled** — agent tool display refactoring (`_AGENT_TOOLS`, `_first_meaningful_line`, new tool styles for Dispatch/Task). Clean changes but not part of this PRD.

SYNTHESIS:
The core per-phase model override implementation is solid and production-ready. The config layer is well-structured with fail-fast validation, clear error messages, and a clean `get_model()` fallback. All 15+ `config.model` call sites in the orchestrator have been correctly replaced — I verified zero remaining direct references. The `PhaseResult.model` field is populated on all three agent return paths (success, error, no-result). Run log serialization is backward-compatible. The stats integration is clean with the `<legacy>` sentinel for old logs. Test coverage is comprehensive at 537 passing tests covering round-trip serialization, validation edge cases, and model propagation.

The only substantive finding is the cost-optimized preset deviation from the PRD (missing `decision: haiku`). I actually *agree* with the implementation's choice — keeping the decision gate on sonnet is safer since it runs with `bypassPermissions` — but it should be explicitly documented rather than silently diverging from the spec. Fix this documentation gap and this is ready to ship. The unrelated GitHub issue integration changes bundled in the branch are a process concern, not a code quality concern.