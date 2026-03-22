# Review by Andrej Karpathy (Round 1)

I now have a thorough understanding of the entire implementation. Let me write my review.

---

## Review: Intent Router Agent — Andrej Karpathy

I've reviewed the full diff (15 files, +2579/-4 lines), the PRD, the task file, and confirmed all 225 tests pass.

### Completeness Assessment

**Implemented (core):**
- ✅ FR-1: Intent classification with 4 categories
- ✅ FR-2: Reuses Slack triage infrastructure via shared `route_query()`
- ✅ FR-3: Two-stage design (router → Q&A agent)
- ✅ FR-4: Entry point integration (`run` command + REPL + Slack)
- ✅ FR-5: Fail-open behavior at confidence threshold
- ✅ FR-6: `--no-triage` CLI flag
- ✅ FR-7: `RouterConfig` in config.yaml with all specified fields
- ✅ FR-8: Audit logging to `.colonyos/runs/triage_<timestamp>.json`

**Incomplete:**
- ❌ Task 6.1: Integration tests for `colonyos run` with routing
- ❌ Task 7.1: Tests for REPL routing behavior
- ❌ Tasks 10.1-10.3: README documentation and end-to-end integration tests

### Quality Assessment

The **prompt engineering is solid**. The router prompt treats categories as a clear taxonomy with examples — this is exactly right for a classification task. The fail-open instruction ("lean toward code_change when uncertain") is embedded directly in the system prompt rather than being post-hoc logic, which means the model participates in the safety behavior rather than having it bolted on. Good.

The **two-stage architecture is well-designed**. Phase 1 (haiku, zero tools, $0.05) is a proper "classifier" — minimum capability, minimum blast radius. Phase 2 (configurable model, Read/Glob/Grep only, $0.50) gives the Q&A agent just enough tools to be useful without being dangerous. This is the correct level of privilege escalation.

The **fallback chain is robust**: JSON parse failure → CODE_CHANGE, unknown category → CODE_CHANGE, LLM error → CODE_CHANGE, low confidence → full pipeline. Every failure mode defaults to "do the expensive thing" rather than "silently drop the user's request." This is exactly right.

**One architectural concern**: The router asks for raw JSON text output rather than using Claude's tool_use/structured output mechanism. For haiku, raw JSON works ~98% of the time, and the markdown-fence stripping + fallback handling covers the remaining cases. But if you ever want guaranteed structured output, switching to tool_use would eliminate the parse-failure path entirely. Not blocking, but worth noting for v2.

**Minor inconsistency**: `answer_question()` defaults `model="haiku"` in its function signature, but `RouterConfig` defaults `qa_model="sonnet"`. The CLI correctly passes `config.router.qa_model`, so this doesn't cause bugs — but a developer calling `answer_question()` directly without config would get haiku instead of the intended sonnet. The function default should match the config default.

The **Q&A prompt template** (`qa.md`) is well-structured with clear role definition, tool restrictions, response format, and scope boundaries. Treating the prompt as a first-class artifact in the repo is the right call.

The **Slack refactoring** is clean — `triage_message()` delegates to the shared router when no `triage_scope` is set, falls back to legacy path when it is. Backward compatibility is preserved through the `RouterResult → TriageResult` mapping. The `_extract_base_branch_from_text()` extraction handles the Slack-specific concern that the router doesn't need to know about.

### Safety

- ✅ Input sanitization via `sanitize_untrusted_content()` at all entry points
- ✅ Read-only tools for Q&A agent (no Bash, Write, Edit)
- ✅ Zero tools for router classifier
- ✅ No secrets in committed code
- ✅ Audit trail for all routing decisions
- ✅ Error handling with graceful fallbacks

### Test Coverage

225 tests pass. The `test_router.py` file (878 lines) is thorough for unit tests — covering enum values, dataclass construction, prompt building, JSON parsing edge cases, LLM error handling, and audit logging. However, the **missing integration tests** (tasks 6.1, 7.1, 10.3) are a gap. The CLI and REPL routing paths are only tested implicitly through the unit tests of their component functions, not as integrated flows.

---

VERDICT: request-changes

FINDINGS:
- [cOS_tasks/...tasks...md]: Tasks 6.1, 7.1, 10.1-10.3 are incomplete — missing integration tests for CLI `run` routing, REPL routing, and end-to-end flows. The core routing logic is well-tested in isolation, but the integration points where `route_query()` → `answer_question()` → click output are not covered by tests.
- [src/colonyos/router.py:317]: `answer_question()` defaults `model="haiku"` but `RouterConfig.qa_model` defaults to `"sonnet"`. The function default should match the config default to avoid confusion when calling `answer_question()` directly without config. Change to `model: str = "sonnet"`.
- [src/colonyos/router.py:234-242]: Router uses raw text JSON output. Consider a comment noting that structured output (tool_use) could replace this in future for guaranteed parsing. Not blocking, but the fallback-to-CODE_CHANGE on parse failure means ~2% of legitimate questions will get routed to the full pipeline unnecessarily.

SYNTHESIS:
This is a clean, well-architected implementation that gets the key design decisions right: two-stage privilege escalation, fail-open at every level, prompts treated as first-class code, and minimal blast radius for the classifier. The router module is properly isolated, the config integration follows existing patterns, and the Slack refactoring maintains backward compatibility while eliminating duplication. The two blocking issues are (1) the missing integration tests — the CLI and REPL routing paths need test coverage to catch regressions when these entry points evolve, and (2) the `answer_question()` default model mismatch, which is a latent bug for any caller that doesn't pass config explicitly. Fix those two and this is ready to ship.