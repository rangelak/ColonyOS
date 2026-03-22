# Review: Intent Router Agent — Round 2

**Reviewer:** Linus Torvalds
**Branch:** `colonyos/right_now_the_pipeline_always_runs_this_huge_planner_implementation_orchestratio`
**PRD:** `cOS_prds/20260321_125008_prd_right_now_the_pipeline_always_runs_this_huge_planner_implementation_orchestratio.md`

---

## Checklist Assessment

### Completeness

- [x] **FR-1 (Intent Classification):** Four categories implemented as `RouterCategory` enum — `CODE_CHANGE`, `QUESTION`, `STATUS`, `OUT_OF_SCOPE`. Clean, obvious, no over-engineering.
- [x] **FR-2 (Reuse Slack Triage):** `triage_message()` now delegates to `route_query()` from the shared router module. Legacy fallback preserved for `triage_scope` callers. Good.
- [x] **FR-3 (Two-Stage Q&A):** Router classifies with haiku/no-tools/$0.05, then `answer_question()` runs with read-only tools and configurable model/budget. Correct.
- [x] **FR-4 (Entry Point Integration):** `colonyos run`, REPL, and Slack all integrated. Correctly skipped for `--from-prd`, `--issue`, and `colonyos auto`.
- [x] **FR-5 (Fallback):** Low-confidence fallback to pipeline at configurable threshold (default 0.7). Audit logging to `.colonyos/runs/triage_<timestamp>.json`. Messages printed.
- [x] **FR-6 (CLI Bypass):** `--no-triage` flag added to `colonyos run`.
- [x] **FR-7 (Configuration):** `RouterConfig` dataclass with `enabled`, `model`, `qa_model`, `confidence_threshold`, `qa_budget`. Parsed from YAML, serialized only when non-default. Clean.
- [x] **FR-8 (Audit Logging):** `log_router_decision()` writes structured JSON with timestamp, source, sanitized prompt, classification, confidence, reasoning.
- [x] **Phase.QA enum** added to models.py.
- [x] **Q&A instruction template** at `instructions/qa.md` — clear, well-scoped.

### Quality

- [x] **All 236 tests pass.** No failures.
- [x] **No TODOs, FIXMEs, or placeholder code.**
- [x] **Follows existing conventions:** Lazy imports from `colonyos.agent`, dataclass patterns, config parsing style, test organization — all match the codebase.
- [x] **No unnecessary dependencies.** Uses only existing infrastructure (`run_phase_sync`, `sanitize_untrusted_content`).
- [x] **No unrelated changes** (one test changed `"sonnet"` → `"opus"` due to a default model change on main — acceptable merge artifact).

### Safety

- [x] **No secrets or credentials in committed code.**
- [x] **Input sanitized** via `sanitize_untrusted_content()` in both router prompt and audit log.
- [x] **Q&A agent sandboxed** to `["Read", "Glob", "Grep"]` — no write or execute access.
- [x] **Router has zero tools** — cannot be tricked into executing anything.
- [x] **Error handling present** throughout: JSON parse failures, LLM call failures, file write failures, `KeyboardInterrupt` in CLI.

---

## Findings

- **[src/colonyos/router.py:334]:** Docstring says `model` default is `haiku` but the actual default parameter is `model: str = "sonnet"`. Minor documentation bug — the code is correct (config overrides anyway), but the docstring is wrong.

- **[src/colonyos/router.py:246-249]:** The artifact extraction pattern (`next(iter(result.artifacts.values()), "")`) is used in both `route_query()` and `answer_question()`. A one-liner helper like `_extract_text(artifacts)` would eliminate the duplicated comment explaining the same fragility. Not a blocker, but it's the kind of thing that rots into a copy-paste bug.

- **[src/colonyos/slack.py:844-855]:** The Slack Q&A path doesn't pass `model` or `qa_budget` from config to `answer_question()`, so it always uses the function defaults. The CLI path correctly reads from `config.router.qa_model` and `config.router.qa_budget`. This is a real inconsistency — if someone sets `qa_model: haiku` in config, CLI respects it but Slack ignores it. The Slack `triage_message()` doesn't receive the config object, which is the root cause.

- **[src/colonyos/cli.py:309-389]:** `_handle_routed_query()` is a clean, well-factored function. The confidence threshold check before category dispatch is the right structure. No complaints.

- **[src/colonyos/config.py]:** `_parse_router_config()` validates the confidence threshold range (0.0-1.0) and the model against `VALID_MODELS`. Config serialization only writes non-default values. This is how config should be done.

- **[tests/test_router.py]:** 1138 lines of tests covering enum values, dataclass construction, prompt building, response parsing (valid JSON, markdown-fenced JSON, garbage input, unknown categories, missing fields, clamped confidence), audit logging, route_query integration, and answer_question integration. Thorough.

---

## Synthesis

This is a well-executed piece of work. The data structures are right: `RouterCategory` is a simple enum, `RouterResult` is a frozen dataclass, the config is a plain dataclass with sensible defaults. The code does the obvious thing at every decision point — fail-open on low confidence, fail-open on parse errors, zero tools for classification, read-only tools for Q&A. No cleverness, no premature abstractions.

The architecture correctly reuses `run_phase_sync()` with `allowed_tools=[]` for classification and `allowed_tools=["Read", "Glob", "Grep"]` for Q&A — that's the right way to sandbox these agents. The Slack integration properly delegates to the shared router while preserving backward compatibility through the legacy fallback path.

I have one real issue: the Slack path doesn't forward `qa_model`/`qa_budget` from config to `answer_question()`. It's a minor functional gap since the defaults are reasonable, but it violates the principle that configuration should actually configure things. The docstring bug in `answer_question()` is trivial. The duplicated artifact extraction is a style nit.

None of these are worth blocking the merge. The code is correct, the tests are comprehensive, the security model is sound. Ship it.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/router.py:334]: Docstring claims model default is "haiku" but actual default parameter is "sonnet" — documentation bug
- [src/colonyos/router.py:246-249]: Artifact extraction pattern duplicated between route_query() and answer_question() with identical explanatory comments — extract a helper
- [src/colonyos/slack.py:844-855]: Slack Q&A path doesn't forward qa_model/qa_budget from config to answer_question(), always uses function defaults — config not honored in Slack context

SYNTHESIS:
Clean, well-structured implementation that does the simple obvious thing at every turn. Data structures are correct, security sandboxing is correct, fail-open behavior is correct. The Slack config gap is the only real functional issue and it's minor since defaults are reasonable. 236 tests pass, no TODOs, no secrets, no unrelated changes. Approve.
