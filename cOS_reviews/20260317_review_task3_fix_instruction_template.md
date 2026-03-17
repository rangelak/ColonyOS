# Review: Task 3.0 — Create Fix Instruction Template

**Branch**: `colonyos/add_a_review_driven_fix_loop_to_the_orchestrator_pipeline_when_the_decision_gate`
**PRD**: `cOS_prds/20260317_144239_prd_add_a_review_driven_fix_loop_to_the_orchestrator_pipeline_when_the_decision_gate.md`
**Requirement**: FR-3 — Fix Instruction Template (`src/colonyos/instructions/fix.md`)
**Date**: 2026-03-17

---

## Consolidated Verdict: APPROVE (6 approve, 1 request-changes)

Six of seven reviewers approve. The Security Engineer requests changes for a format-string injection concern in the calling code (not the template itself) and recommends additional guardrails.

---

## Persona Reviews

### YC Partner (Michael Seibel) — ✅ Approve

- **Findings**:
  - `src/colonyos/instructions/fix.md`: All six FR-3 requirements are covered — read review artifacts, read decision artifact, understand findings, make targeted fixes on same branch, run tests, update task file.
  - `src/colonyos/instructions/fix.md`: Follows the same structural pattern as `implement.md` and `review.md` (title, Context, Process, Rules). Consistent style.
  - `src/colonyos/instructions/fix.md`: No placeholder or TODO items. No secrets, no unnecessary dependencies.

- **Synthesis**: This template does exactly what FR-3 asks for and nothing more, which is the right call. It is structurally consistent with the existing templates, uses the same placeholder variable pattern, and covers every bullet point in the PRD requirement. The rules section is appropriately narrow. The inclusion of `{fix_iteration}` and `{max_fix_iterations}` at the top gives the agent useful context. Ship it.

---

### Steve Jobs — ✅ Approve

- **Findings**:
  - `src/colonyos/instructions/fix.md`: All six FR-3 requirements covered. Nothing missing.
  - `src/colonyos/instructions/fix.md`: Structural consistency with `implement.md` and `review.md` is well executed — same pattern (role statement, Context, Process, Rules).
  - `src/colonyos/instructions/fix.md`: The `{decision_text}` placeholder embedded inline (line 17) aligns with the PRD's hybrid architecture decision — embed for immediate action, reference `{reviews_dir}` for deeper context.
  - `src/colonyos/instructions/fix.md`: Rules section appropriately scoped — prevents fix agent from wandering into unrelated refactoring.

- **Synthesis**: This template does one thing and does it well. It tells the fix agent exactly what went wrong, where to look for detail, and what constraints to operate under. No fat, no redundant preamble. The inline embedding of `{decision_text}` is the most important design choice and it is correct. Ship it.

---

### Jony Ive — ✅ Approve

- **Findings**:
  - `src/colonyos/instructions/fix.md`: Satisfies every FR-3 bullet point. All seven placeholders are well-named and self-evident.
  - `src/colonyos/instructions/fix.md` (line 1): Opening sentence parallels `implement.md` and `review.md` — good structural consistency.
  - `src/colonyos/instructions/fix.md` (line 50, Rules): "Only fix issues identified in the review findings" is a strong, clear constraint appropriate to the fix phase's narrower scope.

- **Synthesis**: This template is quiet and precise. It follows the established pattern with near-exact structural fidelity. The `{decision_text}` inline embedding reflects the hybrid architecture decision. Every section justifies its presence, variable names are self-documenting, and the language is imperative without being verbose. Nothing to remove and nothing missing.

---

### Principal Systems Engineer (Google/Stripe caliber) — ✅ Approve

- **Findings**:
  - `src/colonyos/instructions/fix.md`: All seven placeholders match exactly what `_build_fix_prompt()` passes at orchestrator.py line 255-262. No dangling or unused placeholders.
  - `src/colonyos/instructions/fix.md` (minor, non-blocking): Template lacks an explicit "Output Format" section that `review.md` has. Acceptable because the fix phase produces code changes/commits rather than structured text.
  - `src/colonyos/instructions/fix.md` (minor, non-blocking): No explicit handling for empty/malformed `decision_text`. Upstream orchestrator loop wouldn't reach fix phase without valid decision output, so non-blocking.
  - `src/colonyos/instructions/fix.md` (minor, non-blocking): No persona support (`{persona_block}`), consistent with PRD's single-agent fix phase design.

- **Synthesis**: Well-structured, minimal artifact that fulfills every sub-requirement of FR-3. All placeholders correctly wired. Follows established conventions. Scoping rules appropriately tight. Clean, ship-ready template.

---

### Linus Torvalds — ✅ Approve

- **Findings**:
  - `src/colonyos/instructions/fix.md`: All six FR-3 bullet points addressed. Seven placeholders match exactly what `_build_fix_prompt()` passes. No stray or missing placeholders.
  - `src/colonyos/instructions/fix.md`: Follows same structural conventions as sibling templates.
  - `src/colonyos/instructions/fix.md` (minor, non-blocking): Lacks equivalent ambiguity-handling guidance that `implement.md` has ("If a task is unclear, make a reasonable decision"). Worth considering for contradictory findings from multiple persona reviewers.

- **Synthesis**: Clean, well-structured instruction file that satisfies every bullet point of FR-3. Placeholders are perfectly aligned with the call site. Follows established conventions closely enough to feel native but is appropriately differentiated for the fix use case. Ready to ship.

---

### Staff Security Engineer — ⚠️ Request Changes

- **Findings**:
  - `src/colonyos/instructions/fix.md` (line 17, `{decision_text}`): **Format-string injection via decision_text.** The `decision_text` variable is raw agent output passed through Python `str.format()`. If decision gate output contains literal curly braces (code snippets, JSON, etc.), the `.format()` call will crash or potentially leak Python object attributes. Fix: escape curly braces in `decision_text` before `.format()`, or do a simple string replacement after the `.format()` call.
  - `src/colonyos/instructions/fix.md`: **No scope-limiting guardrails.** The template grants the fix agent full-access posture driven entirely by prior agent output, creating a transitive-trust chain. Consider adding explicit negative constraints (e.g., "Do not modify CI configuration files").
  - `src/colonyos/instructions/fix.md` (lines 40-43): **No structured audit trail.** Unlike the review template's Verdict/Findings/Synthesis format, the fix template doesn't require a machine-parseable fix report.
  - `src/colonyos/instructions/fix.md`: **Missing ambiguity guidance** for contradictory findings from multiple persona reviewers.

- **Synthesis**: The template meets FR-3 at a surface level, but has a critical format-string injection vulnerability where untrusted `decision_text` is passed through `str.format()` and could crash the pipeline or leak internals. Beyond that, the transitive trust chain and lack of structured audit output represent defense-in-depth gaps. Requesting changes primarily for the format-string injection issue.

---

### Andrej Karpathy — ✅ Approve

- **Findings**:
  - `src/colonyos/instructions/fix.md`: All six FR-3 bullet points addressed. Placeholder variables align exactly with `_build_fix_prompt()` arguments.
  - `src/colonyos/instructions/fix.md`: Follows structural conventions of sibling templates.
  - `src/colonyos/instructions/fix.md` (minor, non-blocking): No `{persona_block}` placeholder — correct per PRD, noted for future extensibility.
  - `src/colonyos/instructions/fix.md` (minor, non-blocking): "Every fix must have corresponding test coverage" could cause unnecessary test churn for non-code fixes (e.g., docstring findings). Softer phrasing like "where applicable" would reduce this risk.

- **Synthesis**: Clean, well-structured template that satisfies every bullet point of FR-3. The hybrid approach of embedding `{decision_text}` inline while referencing `{reviews_dir}` is the right design. Follows established conventions closely. Ready to ship.

---

## Review Checklist

### Completeness
- [x] All functional requirements from the PRD (FR-3) are implemented
- [x] No placeholder or TODO code remains

### Quality
- [x] Code follows existing project conventions (Context/Process/Rules structure)
- [x] No unnecessary dependencies added
- [x] No unrelated changes included

### Safety
- [x] No secrets or credentials in committed code
- [ ] ⚠️ Format-string injection risk: `{decision_text}` passed through `str.format()` — curly braces in agent output could crash or leak (raised by Security Engineer; note: this is in the *calling code* `_build_fix_prompt()`, not the template itself)
- [x] Error handling: upstream orchestrator validates decision output before reaching fix phase

---

## Actionable Items

| Priority | Finding | Owner | Status |
|----------|---------|-------|--------|
| **High** | Format-string injection: escape curly braces in `decision_text` before `.format()` in `_build_fix_prompt()` | Task 4.0 (build_fix_prompt) | To address in calling code |
| Low | Add ambiguity-handling guidance for contradictory findings | Nice-to-have | Non-blocking |
| Low | Soften "every fix must have test coverage" to "where applicable" | Nice-to-have | Non-blocking |
| Low | Consider structured fix report output format | Future iteration | Non-blocking |

---

## Final Assessment

The `fix.md` template **meets all FR-3 requirements** and is structurally consistent with existing instruction templates. Six of seven reviewers approve unconditionally. The Security Engineer's format-string injection concern is valid but pertains to the *calling code* (`_build_fix_prompt()` in `orchestrator.py`), not the template file itself — it should be addressed as part of Task 4.0. The template itself is well-scoped, clearly written, and ready to ship.

**Consolidated Verdict: ✅ APPROVE** (with high-priority note to address format-string injection in the calling code)
