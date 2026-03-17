# Review by Staff Security Engineer (Round 3)

I have completed my review. Here is my assessment:

---

## Security Review: Per-Phase Model Override Configuration

### Completeness
- [x] All functional requirements from the PRD are implemented (FR-1 through FR-20)
- [x] All tasks in the task file are marked complete (1.0–8.0, all checked)
- [x] No placeholder or TODO code remains (only in instruction templates, which are review checklists, not shipped code)

### Quality
- [x] All tests pass (294 passed in 0.49s)
- [x] No linter errors introduced
- [x] Code follows existing project conventions (`.get()` with defaults, conditional serialization, dataclass patterns)
- [x] No unnecessary dependencies added
- [x] No unrelated changes included in the per-phase model feature itself (branch does include prior features, but the model override changes are cohesive)

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive database operations
- [x] Error handling is present for failure cases (ValueError on bad model/phase, backward-compat None defaults for old logs)

---

### Detailed Findings

**[src/colonyos/config.py]**: **GOOD** — `VALID_MODELS` is a `frozenset` allowlist (`opus`, `sonnet`, `haiku`). This prevents arbitrary model strings, which is the right V1 approach. Validation happens at `load_config()` time (fail-fast), not at phase execution time. Both top-level `model` and every entry in `phase_models` are validated. Phase keys are validated against `Phase` enum values. This is solid input validation.

**[src/colonyos/config.py]**: **GOOD (security-positive)** — `_SAFETY_CRITICAL_PHASES` warning when haiku is assigned to `review`, `decision`, or `fix` phases. These phases run with `permission_mode="bypassPermissions"` (see `agent.py:52`), meaning a weaker model in those gates could miss dangerous operations. The warning is informational only (`logger.warning()`), not a hard block — consistent with PRD non-goals. However, the audit trail it creates is valuable.

**[src/colonyos/config.py]**: **MINOR** — `_SAFETY_CRITICAL_PHASES` uses raw strings (`"review"`, `"decision"`, `"fix"`) rather than `Phase.REVIEW.value` etc. If someone renames a Phase enum value, this frozenset silently becomes stale. Low risk since the validation loop catches invalid user-supplied keys, but the constant itself wouldn't track enum renames.

**[src/colonyos/init.py]**: **GOOD** — The cost-optimized preset correctly keeps `decision` at `sonnet` (the global default) rather than downgrading to `haiku` as the PRD originally suggested. This is a security-conscious deviation: the decision gate determines whether code passes review, and it runs with bypassPermissions. Only `learn` and `deliver` get `haiku` — appropriate for mechanical tasks with no security judgment.

**[src/colonyos/agent.py]**: **GOOD** — `PhaseResult.model` is populated on all three return paths (success, error, no-result-message). This means the audit trail captures which model ran even when phases fail, which is essential for post-incident analysis.

**[src/colonyos/orchestrator.py]**: **VERIFIED** — All ~15 former `config.model` call sites now use `config.get_model(Phase.XXX)`. Zero remaining `config.model` references in orchestrator (confirmed via grep). The `ui.phase_header()` calls also pass the resolved per-phase model, so operators see the actual model used in real-time output.

**[src/colonyos/stats.py]**: **GOOD** — `compute_model_usage()` handles old run logs gracefully by labeling missing model fields as `<legacy>`. This means the stats dashboard works correctly even with a mix of old and new run logs. The `ModelUsageRow` exposes both `invocations` and `total_cost`, giving operators the visibility they need to audit model usage patterns.

**[src/colonyos/init.py]**: **NOTE** — Quick mode defaults to the cost-optimized preset. This means automated `colonyos init --quick` setups will use sonnet as the global default with opus only for implement. This is a change from the previous behavior where everything used the single configured model. The PRD flagged this as an open question (OQ-1). From a security standpoint, the cost-optimized preset is still safe because all safety-critical phases (review, decision, fix) remain at sonnet.

**[src/colonyos/agent.py]**: **ARCHITECTURAL CONCERN (pre-existing, not introduced by this PR)** — Every phase runs with `permission_mode="bypassPermissions"` regardless of model. The model override feature doesn't make this worse, but it does make it more visible: a user could assign `haiku` to `review` and `decision` phases, which serve as the pipeline's safety gates. A less capable model reviewing code that runs without permission checks is a risk. The logger warning is the mitigation for V1; enforcing a minimum model floor for safety-critical phases should be a V2 priority.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/config.py]: `_SAFETY_CRITICAL_PHASES` uses raw string literals instead of `Phase.REVIEW.value` etc. — if enum values are renamed, the frozenset silently becomes stale. Low risk.
- [src/colonyos/init.py]: Cost-optimized preset deviates from PRD FR-13 by keeping `decision` at `sonnet` instead of `haiku`. This is a security-positive deviation — decision is a safety gate running with bypassPermissions.
- [src/colonyos/agent.py]: All phases run with `permission_mode="bypassPermissions"`. The haiku warning on safety-critical phases is informational only. V2 should consider enforcing a minimum model floor for review/decision/fix phases.
- [src/colonyos/config.py]: Fail-fast validation of model names and phase keys at `load_config()` time is correctly implemented against a frozenset allowlist. No arbitrary model strings accepted.

SYNTHESIS:
From a security perspective, this implementation is well-considered. The hardcoded `VALID_MODELS` allowlist prevents model name injection. Fail-fast validation at config load time means typos or invalid models are caught before any budget is burned. The `PhaseResult.model` field creates a complete audit trail of which model ran each phase — essential for cost forensics and post-incident review. The most significant security consideration is that all phases, including review and decision gates, run with `bypassPermissions`, and this feature now lets users downgrade those gates to `haiku`. The implementation mitigates this with a `logger.warning()` on safety-critical phases assigned to haiku, and the cost-optimized preset deliberately keeps decision at sonnet rather than haiku (improving on the PRD's original suggestion). The warning creates an audit trail without blocking power users — the right trade-off for V1. I recommend approving with a note that V2 should enforce a configurable minimum model floor for phases that serve as security gates.