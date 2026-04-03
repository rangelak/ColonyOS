# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 2)

All 191 tests pass. I've now reviewed the full diff, the PRD, and the task file. Here is my assessment:

---

## Review: Principal Systems Engineer Perspective

### Completeness
- [x] **FR-1 (Mode Selection)**: `--manual` flag added, default routes to `run_ai_init()`, `--quick`/`--personas` unchanged
- [x] **FR-2 (Repo Auto-Detection)**: `scan_repo_context()` deterministically scans all specified manifests, truncates to 2000 chars, includes CI workflow
- [x] **FR-3 (LLM Config Generation)**: Single call via `run_phase_sync()` with Haiku, $0.50 budget cap, max 3 turns, restricted tools `["Read", "Glob", "Grep"]`, constrained output schema
- [x] **FR-4 (Config Preview)**: Rich panel renders project info, persona roles, model preset, budget, and vision
- [x] **FR-5 (Graceful Error Handling)**: Auth, timeout, parse, and general failures all fall back to manual wizard with pre-filled defaults
- [x] **FR-6 (Cost Transparency)**: Pre-call message and post-call cost display both present
- [x] All 65 task items marked complete
- [x] No TODOs or placeholder code

### Quality
- [x] All 191 tests pass (0.72s)
- [x] Code follows existing project conventions (dataclasses, `click`, `rich`)
- [x] No new dependencies added
- [x] Clean separation: scan → prompt → parse → preview → confirm → save
- [x] `_finalize_init()` correctly extracted to eliminate duplication between AI and manual paths

### Safety
- [x] `permission_mode="default"` — not `bypassPermissions` — verified in code and tested explicitly
- [x] No secrets in committed code
- [x] No partial state on failure (`.colonyos/` only created after confirmation) — tested
- [x] LLM selects from predefined pack keys and preset names; Python constructs the `ColonyConfig`

### Findings

VERDICT: approve

FINDINGS:
- [src/colonyos/init.py]: **SIGALRM + asyncio interaction risk.** The timeout uses `signal.SIGALRM` which fires in the main thread, but `run_phase_sync` wraps `asyncio.run()`. Raising `_AiInitTimeout` inside a signal handler during an active event loop could leave the loop in a partially torn-down state or trigger `RuntimeError` in edge cases. Consider using `asyncio.wait_for()` inside `run_phase_sync` instead, or wrapping the signal-based approach in a `try/finally` that ensures the event loop is fully cleaned up. Low probability at init-time (single user, single call), but worth hardening in a follow-up.
- [src/colonyos/init.py]: **No timeout on Windows.** The `_has_alarm` guard correctly avoids calling `signal.alarm` on Windows, but this means Windows users get no timeout protection at all — the LLM call could hang indefinitely. Consider a thread-based timeout fallback for cross-platform parity.
- [src/colonyos/init.py]: **`run_ai_init` returns `ColonyConfig` from fallback `run_init()` but the CLI caller (`cli.py`) discards the return value.** This is fine for the current flow (side-effect-based save), but the type signature suggests the return value matters. Consistent with the existing `run_init` pattern, so no action needed, but worth noting for future refactors.
- [src/colonyos/persona_packs.py]: **`packs_summary()` docstring says "prompt injection"** — technically accurate (injecting data into the prompt), but could confuse security reviewers scanning for the vulnerability sense. A minor docstring tweak to "prompt serialization" or "prompt context" would reduce ambiguity.
- [tests/test_init.py]: **Tests mock at `colonyos.agent.run_phase_sync` rather than `colonyos.init.run_phase_sync`.** The import in `init.py` is `from colonyos.agent import run_phase_sync`, so the mock path should technically be `colonyos.init.run_phase_sync` for correctness. However, since the import is deferred (inside `run_ai_init`), the mock at the source module works — but this is fragile and could silently stop working if the import is hoisted to module level.

SYNTHESIS:
This is a well-structured, security-conscious implementation that delivers on all PRD requirements. The architecture follows the right pattern: deterministic scan first, constrained single-shot LLM call second, Python-side validation third. The fallback chain is comprehensive — every failure mode (auth, timeout, parse, user rejection) routes cleanly to the manual wizard with pre-filled defaults, which is exactly the right UX. The `permission_mode="default"` enforcement (vs. `bypassPermissions`) is the single most important security decision and it's correctly implemented and tested. The two operational concerns — SIGALRM/asyncio interaction and Windows timeout gap — are low-severity for an init-time command that runs once per project, but should be tracked for hardening. Test coverage is thorough at 39 new tests covering happy paths, error paths, and edge cases. Ship it.
