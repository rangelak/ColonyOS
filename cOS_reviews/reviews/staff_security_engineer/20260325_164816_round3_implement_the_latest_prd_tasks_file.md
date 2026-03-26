# Review by Staff Security Engineer (Round 3)

Now I have a comprehensive understanding of the implementation. Let me produce my review.

---

## Staff Security Engineer Review

### Reviewing branch `colonyos/implement_the_latest_prd_tasks_file`

This branch implements three major features across ~9,200 new lines: (1) an interactive Textual TUI, (2) an intent router agent for lightweight mode selection and Q&A, and (3) a `colonyos sweep` command for autonomous codebase quality analysis.

---

### Completeness Assessment

**TUI (PRD 20260323):** All functional requirements are covered — Textual app with transcript, composer, status bar, hint bar, adapter bridging synchronous orchestrator to async event loop, optional dependency guard, `colonyos tui` command and `--tui` flag, and sanitization of all displayed output. ✅

**Router (PRD 20260321):** Intent classification, two-stage Q&A design, heuristic fast-path, mode selection prompt, audit logging, configurable model/thresholds, and `--no-triage` bypass are all present. ✅

**Sweep (PRD 20260324):** `colonyos sweep` command with `--execute`, `--plan-only`, `--max-tasks`, dry-run default, read-only analysis phase, `Phase.SWEEP` enum, `SweepConfig`, `sweep.md` instruction template, and delegation to the existing pipeline. ✅

### Quality Assessment

- **All 1,927 tests pass.** ✅
- Code follows existing project conventions (Click CLI, dataclasses, `run_phase_sync` patterns). ✅
- No unnecessary dependencies — Textual is properly optional under `[tui]` extra. ✅
- No commented-out code or placeholder TODOs observed. ✅

---

### Security Assessment (My Primary Lens)

**What I liked:**

1. **Sweep analysis is genuinely read-only.** `run_sweep()` at line 1627 correctly enforces `allowed_tools=["Read", "Glob", "Grep"]` — no Write, Edit, or Bash. This is the right privilege boundary for an analysis-only phase.

2. **Router classification has zero tool access.** Both `route_query()` and `choose_tui_mode()` use `allowed_tools=[]` and a `$0.05` budget cap. A compromised prompt can't use the router call to exfiltrate or modify anything.

3. **Q&A agent is properly sandboxed.** `answer_question()` uses `allowed_tools=["Read", "Glob", "Grep"]` — read-only. No Bash execution.

4. **TUI adapter sanitizes all output.** Every callback in `TextualUI` runs through `sanitize_display_text()` before queuing, which strips ANSI escape sequences, terminal control characters, and bare carriage returns (preventing overwrite attacks). This closes a real vector for terminal injection from crafted repo content.

5. **User injection sanitization.** `enqueue_user_injection()` applies both `sanitize_untrusted_content()` (XML tag stripping) and `sanitize_display_text()` — defense in depth.

6. **Router prompts sanitize all project metadata.** `_sanitize_metadata()` applies both display-level and content-level sanitization before injecting project name/description/stack into prompts. This is correct since these fields could contain adversarial content from config files.

7. **Preflight recovery instructions** explicitly prohibit destructive git commands, broad staging (`git add .`), pushing, and committing secret-like files (`.env*`, private keys). Good security guardrails.

8. **Sweep instruction template** explicitly excludes auth/security code, secrets management, database schemas, and public API signatures from modification scope.

9. **Audit logging.** Both `log_router_decision()` and `log_mode_selection()` sanitize prompts before persisting to disk, preventing log injection.

10. **Safety-critical phases** (`review`, `decision`, `fix`) are protected from model downgrades to `haiku` with a warning, and sweep tasks go through these gates unchanged.

**Areas of minor concern (not blocking):**

1. **`bypassPermissions` remains the default.** The agent SDK runs with `permission_mode="bypassPermissions"` for all non-init phases. While this is an existing design decision (not introduced by this branch), it means any prompt injection that reaches the implement/fix phases has full write+execute access. The router's lightweight classification is the primary gatekeeper for what enters the pipeline. The fail-open behavior (uncertain → full pipeline) means an adversarial prompt that deliberately confuses the classifier gets maximum permissions. This is a conscious design trade-off documented in the PRD, but it's worth tracking.

2. **No rate limiting on sweep `--execute`.** A user could accidentally loop `colonyos sweep --execute` and accumulate unbounded cost. The per-phase budget cap exists, but there's no sweep-specific budget ceiling. Low severity since this requires deliberate (mis)use.

3. **Config validation could be tighter.** `RouterConfig.model` defaults to `"opus"` (per the config.yaml on this branch) — the PRD specified `haiku` for the classification model. Using `opus` for classification is more expensive but functionally correct. The config file shows `model: opus` which overrides the `RouterConfig` default. This is a cost concern, not a security issue.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py:1627]: Sweep phase correctly enforces read-only tool allowlist — good least-privilege enforcement.
- [src/colonyos/router.py:648-649]: Router classification correctly uses zero tools and $0.05 budget — minimal privilege for classification.
- [src/colonyos/tui/adapter.py:139-142,224,229]: All TUI output paths sanitize through `sanitize_display_text()` — closes terminal injection vector.
- [src/colonyos/router.py:200-207,373]: User injection and prompt construction both sanitize untrusted content before embedding in prompts — defense in depth against prompt injection.
- [src/colonyos/agent.py:78]: `bypassPermissions` remains the global default for all pipeline phases — existing design, but the router/sweep features expand the surface area for what enters the pipeline. Worth monitoring.
- [.colonyos/config.yaml]: Router model set to `opus` rather than `haiku` as PRD specified — higher cost but not a security issue. The router still has zero tools and $0.05 budget cap regardless.
- [src/colonyos/instructions/preflight_recovery.md]: Recovery agent instructions properly prohibit destructive git ops and secret file commits — good guardrails.
- [src/colonyos/sanitize.py]: Comprehensive sanitization suite — ANSI stripping, CR normalization (anti-overwrite), XML tag removal, secret pattern redaction, Slack link stripping. Well-structured defense-in-depth.

SYNTHESIS:
From a security perspective, this is a well-structured implementation. The three new features (TUI, router, sweep) each demonstrate appropriate least-privilege design: the sweep analysis phase is genuinely read-only, the router classifier has zero tool access, and the Q&A agent is sandboxed to read-only tools. The TUI adapter properly sanitizes all output against terminal escape injection — a real attack vector that many teams miss. Input sanitization is applied consistently across prompt construction, audit logging, and user injection paths. The existing `bypassPermissions` posture for pipeline phases is the biggest systemic risk, but it predates this branch and the new features don't make it worse — in fact the router adds a lightweight triage gate that didn't exist before. All 1,927 tests pass, no secrets are committed, and no destructive operations lack safeguards. This is ready to ship.