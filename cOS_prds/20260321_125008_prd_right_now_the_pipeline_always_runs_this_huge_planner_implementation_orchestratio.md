# PRD: Intent Router Agent for ColonyOS

## Introduction/Overview

ColonyOS currently runs the full planning, implementation, orchestration pipeline (Plan → Implement → Verify → Review → Deliver) for every user input, regardless of whether the user wants to build a feature or simply ask a question about the codebase. This wastes significant time and money when users just want information.

This feature adds an **Intent Router Agent** — a lightweight, cheap classifier that runs before the main pipeline to determine the user's intent and route their query to the appropriate handler: full pipeline for code changes, direct answers for questions, or existing CLI commands for status queries.

## Goals

1. **Reduce unnecessary pipeline runs by 40-60%** — Users asking questions like "what does this function do?" should get answers in 5-10 seconds for $0.05-0.50, not wait 2+ minutes and spend $5-15 on a full pipeline run.

2. **Reuse existing infrastructure** — Extend the battle-tested `triage_message()` function in `/src/colonyos/slack.py` rather than building a separate implementation.

3. **Maintain fail-safe behavior** — If the router is uncertain, default to the full pipeline (fail-open) to avoid missing legitimate feature requests.

4. **Add minimal latency** — The routing decision should take <2 seconds using haiku with no tool access.

5. **Enable codebase-aware Q&A** — When a user asks a question, spawn a second cheap agent with read-only tools to answer it intelligently.

## User Stories

1. **As a developer**, when I type `colonyos run "what does the sanitize function do?"`, I want to get an answer immediately (5-10 seconds) instead of watching a full PRD generation and implementation cycle.

2. **As a developer**, when I type `colonyos run "add a health check endpoint"`, I want the full pipeline to run just as it does today.

3. **As a developer** using the REPL, when I type a question, I want an intelligent answer; when I type a feature description, I want it built.

4. **As a Slack user**, when I @ the bot with a question about the codebase, I want an answer, not a PR.

5. **As a power user**, I want to bypass routing with `--no-triage` when I know I want the full pipeline.

## Functional Requirements

### FR-1: Intent Classification
The router agent must classify user input into one of these categories:
- **`code_change`** — Feature requests, bug fixes, refactoring → runs full pipeline
- **`question`** — Codebase inquiries, how-to questions → answers directly with read-only agent
- **`status`** — Queue state, run history, stats → redirects to existing CLI commands
- **`out_of_scope`** — Unrelated requests → polite rejection with suggestion

### FR-2: Reuse Slack Triage Infrastructure
The router must extend the existing `triage_message()` function in `/src/colonyos/slack.py` (lines 770-826):
- Factor out shared logic into a new `colonyos.router` module
- Use the same `TriageResult` dataclass (extended with new fields if needed)
- Preserve the haiku model, $0.05 budget, no-tools pattern for classification

### FR-3: Two-Stage Design for Questions
When intent is `question`:
1. Router classifies intent (haiku, no tools, $0.05, <2s)
2. Q&A agent answers with context (haiku/sonnet, read-only tools, $0.25-0.50, 5-10s)

### FR-4: Entry Point Integration
Apply routing to:
- `colonyos run` command with freeform prompts
- The REPL feature prompt path
- Extend Slack watcher to use the unified router

Do NOT apply to:
- `colonyos auto` (CEO agent already decides intent)
- `colonyos queue start` (items pre-triaged at add time)
- Commands with explicit verbs: `colonyos review`, `colonyos ci-fix`, etc.

### FR-5: Fallback Behavior
- If `confidence < 0.7`, default to full pipeline (fail-open)
- Log all routing decisions to `.colonyos/runs/triage_<timestamp>.json` for debugging
- Print a brief message: "Treating this as a feature request..."

### FR-6: CLI Flag for Bypass
Add `--no-triage` flag to `colonyos run` for power users who want to skip routing.

### FR-7: Configuration (Minimal)
Add to `.colonyos/config.yaml`:
```yaml
router:
  enabled: true           # default: true
  model: haiku            # classification model
  confidence_threshold: 0.7
  qa_budget: 0.50         # budget for answering questions
```

### FR-8: Audit Logging
All router decisions must be logged with:
- Input prompt (sanitized)
- Classification result and confidence
- Selected route
- Timestamp and source (cli/repl/slack)

## Non-Goals

- **Per-category sub-routing** — Don't distinguish between "bug" vs "feature" vs "refactor"; the pipeline handles this uniformly.
- **Interactive clarification** — Don't prompt users "Did you mean X?" when uncertain; this breaks scriptability.
- **Configuration of categories** — Don't expose category taxonomy in config; this is code structure, not user configuration.
- **Routing for `colonyos auto`** — CEO agent already handles intent determination.
- **Complex Q&A memory** — The Q&A agent is stateless; don't build conversation history.

## Technical Considerations

### Existing Infrastructure to Leverage

1. **`/src/colonyos/slack.py` lines 659-826**:
   - `TriageResult` dataclass with `actionable`, `confidence`, `summary`, `base_branch`, `reasoning`
   - `_build_triage_prompt()` for constructing the system prompt
   - `_parse_triage_response()` for handling JSON output and fallbacks
   - `triage_message()` as the main entry point

2. **`/src/colonyos/models.py` line 37**:
   - `Phase.TRIAGE` enum already exists

3. **`/src/colonyos/agent.py` lines 67-201**:
   - `run_phase_sync()` with `allowed_tools` parameter for sandboxing

4. **`/src/colonyos/cli.py`**:
   - Line 527: `run()` command entry point
   - Lines 309-447: REPL implementation
   - Line 1976+: Slack watcher

### Architectural Decisions

1. **New module**: Create `/src/colonyos/router.py` to house:
   - `RouterResult` dataclass (extends TriageResult with `category` enum)
   - `route_query()` main function
   - `answer_question()` for Q&A agent

2. **Two-phase execution**:
   - Phase 1: Classification (no tools, $0.05)
   - Phase 2: Execution based on category

3. **Read-only Q&A agent**:
   - `allowed_tools=["Read", "Glob", "Grep"]`
   - No Bash, Write, or Edit access
   - Separate `Phase.QA` enum value

### Security Considerations (from Staff Security Engineer)

1. **Least privilege**: Q&A agent has read-only access; no code execution
2. **Two-stage design**: Router has zero tools; routes to appropriate privilege level
3. **Audit trail**: All decisions logged for security review
4. **Input sanitization**: Reuse `sanitize_slack_content()` for all user input

### Files to Modify

| File | Changes |
|------|---------|
| `/src/colonyos/router.py` | New module (core routing logic) |
| `/src/colonyos/models.py` | Add `Phase.QA`, `RouterCategory` enum |
| `/src/colonyos/config.py` | Add `RouterConfig` dataclass |
| `/src/colonyos/cli.py` | Integrate router into `run()` and REPL |
| `/src/colonyos/slack.py` | Factor out shared triage logic, import from router |
| `/src/colonyos/instructions/qa.md` | New instruction template for Q&A agent |

## Success Metrics

1. **Routing accuracy** >95% — Measured by manual review of logged decisions
2. **Latency for routing** <2 seconds p95
3. **Q&A response time** <10 seconds p95
4. **Cost reduction** — 40-60% fewer full pipeline runs for mixed workloads
5. **User satisfaction** — Questions get answers, not PRs

## Open Questions

1. **Q&A model selection**: Should Q&A use haiku (faster, cheaper) or sonnet (smarter)? Start with haiku, make configurable if needed.

2. **Status query handling**: Should `status` queries print the answer directly or just suggest the command? Consensus: Show the command so users learn the system.

3. **Slack integration depth**: Should we update all Slack handlers to use the unified router, or keep the existing `triage_message()` as-is? Recommendation: Unified router, with Slack-specific context injection.

## Persona Synthesis

### Areas of Agreement
- **Reuse existing triage**: All personas agree to extend `triage_message()` rather than duplicate
- **Two-stage design**: Cheap classification → appropriate execution
- **Fail-open**: Default to full pipeline when uncertain
- **Minimal configuration**: Ship with sensible defaults, don't over-expose knobs
- **Haiku for classification**: Fast, cheap, sufficient for intent detection

### Areas of Tension
- **Configuration exposure**: Jony Ive and Principal Engineer want config options; Steve Jobs and Michael Seibel say ship defaults first
- **Entry points**: Jony Ive wants routing everywhere; Linus and Steve say only `colonyos run` and REPL need it
- **Clarification prompts**: Security Engineer suggests asking users when uncertain; Steve Jobs and Linus say this breaks flow

**Resolution**: Start minimal (run + REPL only), fail-open, minimal config. Add complexity only if users request it after real-world usage.
