# Review by Andrej Karpathy (Round 2)

Now let me write the review output. I've reviewed the full implementation thoroughly.

---

## Review: Intent Router Agent — Andrej Karpathy

### Completeness Assessment

All 9 functional requirements from the PRD are implemented:

- **FR-1 (Intent Classification)**: ✅ `RouterCategory` enum with all 4 categories, `route_query()` with haiku classification
- **FR-2 (Reuse Slack Triage)**: ✅ `triage_message()` now delegates to `route_query()`, legacy path preserved for `triage_scope`
- **FR-3 (Two-Stage Design)**: ✅ Classification (haiku, no tools, $0.05) → Q&A agent (configurable model, read-only tools, $0.50)
- **FR-4 (Entry Point Integration)**: ✅ `run()`, REPL, and Slack all integrated; correctly excluded from `auto`, `queue`, explicit-verb commands
- **FR-5 (Fallback Behavior)**: ✅ Confidence threshold check, fail-open to pipeline, user messaging
- **FR-6 (CLI Bypass)**: ✅ `--no-triage` flag
- **FR-7 (Configuration)**: ✅ `RouterConfig` with all specified fields plus `qa_model`
- **FR-8 (Audit Logging)**: ✅ `log_router_decision()` writes to `.colonyos/runs/triage_<timestamp>.json`

Tasks 10.1 and 10.2 (documentation) are incomplete but are non-blocking for functionality.

### Quality Deep-Dive

**Prompt Engineering (my main focus area)**:

The classification prompt in `_build_router_prompt()` is well-structured. I particularly like:
1. The explicit JSON-only instruction ("no markdown fencing, no extra text")
2. Concrete examples for each category — this is exactly how you get reliable classification from a small model
3. The fail-open rule embedded directly in the prompt: "When uncertain between code_change and question, lean toward code_change"
4. Input sanitization via `sanitize_untrusted_content()` before prompt injection

The Q&A agent prompt in `qa.md` is clean — clear role definition, explicit tool constraints, and good formatting instructions.

**Architecture (LLM as classifier)**:

The two-stage design is textbook correct. Stage 1 (haiku, no tools, $0.05) for classification is the right call — you don't need a powerful model to distinguish "what does X do?" from "add X". Stage 2 dispatches to the appropriate capability level. This is exactly the pattern I'd advocate for.

**Parsing robustness**:

`_parse_router_response()` handles markdown fences, invalid JSON, unknown categories, and confidence clamping. Every failure mode falls back to `CODE_CHANGE` with `confidence=0.0`. This is the correct fail-open behavior. The confidence-based fallback in `_handle_routed_query()` then catches these and routes to the full pipeline. Belt and suspenders — good.

**Test coverage**: 1138 lines of test code for 433 lines of router code (~2.6x ratio). Tests cover all parsing edge cases, all routing paths, audit logging, and configuration. Solid.

### Issues Found

1. **`answer_question()` docstring says "haiku" but default is "sonnet"** (line 335 says `default: haiku` but the signature on line 320 says `model: str = "sonnet"`). The config default is also `sonnet`. The docstring is stale from an earlier iteration.

2. **`result.artifacts` extraction is fragile** — Lines 247-249 and 366-368 use `next(iter(result.artifacts.values()))` to extract text from `run_phase_sync()`. The comment acknowledges this ("If the SDK ever returns multiple artifacts, revisit"). This is fine for now since the contract is well-understood, but it's a coupling point to watch.

3. **REPL routing doesn't check `config.router.confidence_threshold`** — Actually wait, it does, because `_handle_routed_query()` checks it. Good — the shared helper handles this correctly for both `run()` and REPL.

4. **Slack Q&A doesn't use `config.router.qa_model`** — In `slack.py` line 846, `answer_question()` is called without passing `model=` or `qa_budget=`, so it falls back to the function's hardcoded defaults (`sonnet`, `$0.50`) rather than reading from config. The CLI path correctly passes `config.router.qa_model` and `config.router.qa_budget`. This is an inconsistency.

5. **`RouterCategory` is defined in `router.py` not `models.py`** — The PRD and task file mention adding it to `models.py`, but it's actually in `router.py`. This is arguably better (keeps routing logic self-contained), but it's a deviation from the spec. Not a blocker.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/router.py:335]: Docstring says "default: haiku" but actual default parameter is "sonnet" — stale docstring from earlier iteration
- [src/colonyos/slack.py:846]: `answer_question()` called without `model=config.router.qa_model` or `qa_budget=config.router.qa_budget`, falling back to hardcoded defaults instead of user config. CLI path correctly passes these.
- [src/colonyos/router.py:247-249]: Artifact extraction via `next(iter(result.artifacts.values()))` is fragile but acknowledged in comments — acceptable technical debt
- [cOS_tasks]: Tasks 10.1 and 10.2 (documentation updates) are still incomplete

SYNTHESIS:
This is a well-executed implementation of a classic LLM-as-classifier pattern. The two-stage architecture (cheap classifier → appropriate executor) is exactly right — you're using the model effectively rather than fighting against it. The prompt engineering is solid: concrete examples, explicit JSON schema, fail-open instructions baked into the system prompt. The parsing layer is robust with multiple fallback paths that all converge on the safe default (full pipeline). Input sanitization before prompt construction is a good security practice. The 2.6x test-to-code ratio gives me confidence in the edge cases. The main nit is the Slack path not respecting `qa_model`/`qa_budget` from config, which means Slack users can't configure Q&A behavior — easy fix, not blocking. Overall, this is clean, minimal, and ships the smallest thing that works. Approve.
