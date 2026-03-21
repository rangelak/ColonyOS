# Tasks: Intent Router Agent for ColonyOS

## Relevant Files

### Core Implementation
- `src/colonyos/router.py` - **NEW**: Core routing logic, `RouterResult`, `route_query()`, `answer_question()`, `log_router_decision()`
- `src/colonyos/models.py` - Add `Phase.QA`, `RouterCategory` enum
- `src/colonyos/config.py` - Add `RouterConfig` dataclass and loader (with `qa_model` field)
- `src/colonyos/instructions/qa.md` - **NEW**: System prompt for Q&A agent

### Integration Points
- `src/colonyos/cli.py` - Integrate router into `run()` command and REPL
- `src/colonyos/slack.py` - Factor out shared triage logic, import from router
- `src/colonyos/orchestrator.py` - May need updates for router integration

### Tests
- `tests/test_router.py` - **NEW**: Unit tests for router module
- `tests/test_cli.py` - Update for `--no-triage` flag and routing behavior
- `tests/test_slack.py` - Update for shared triage logic

---

## Tasks

- [x] 1.0 Create Router Module Foundation (`src/colonyos/router.py`)
  depends_on: []
  - [x] 1.1 Write unit tests for `RouterCategory` enum and `RouterResult` dataclass
  - [x] 1.2 Define `RouterCategory` enum: `CODE_CHANGE`, `QUESTION`, `STATUS`, `OUT_OF_SCOPE`
  - [x] 1.3 Create `RouterResult` dataclass extending the pattern from `TriageResult` in slack.py
  - [x] 1.4 Implement `_build_router_prompt()` following the pattern in slack.py:670-719
  - [x] 1.5 Implement `_parse_router_response()` with JSON parsing and fallback handling
  - [x] 1.6 Implement `route_query()` main function using `run_phase_sync()` with haiku, no tools, $0.05 budget

- [x] 2.0 Add Model Layer Updates (`src/colonyos/models.py`)
  depends_on: []
  - [x] 2.1 Write unit tests for new `Phase.QA` enum value
  - [x] 2.2 Add `Phase.QA = "qa"` to the Phase enum (after line 46)
  - [x] 2.3 Verify `Phase.TRIAGE` is already present and correctly handled in existing code

- [x] 3.0 Add Router Configuration (`src/colonyos/config.py`)
  depends_on: []
  - [x] 3.1 Write unit tests for `RouterConfig` loading and defaults
  - [x] 3.2 Create `RouterConfig` dataclass with fields: `enabled`, `model`, `qa_model`, `confidence_threshold`, `qa_budget`
  - [x] 3.3 Add `router: RouterConfig` field to `ColonyConfig` class
  - [x] 3.4 Update `_parse_config()` to load router section with sensible defaults
  - [x] 3.5 Update `_serialize_config()` to write router section

- [x] 4.0 Create Q&A Agent Instruction Template (`src/colonyos/instructions/qa.md`)
  depends_on: []
  - [x] 4.1 Create `qa.md` instruction template for read-only codebase Q&A
  - [x] 4.2 Include: role definition, available tools (Read, Glob, Grep only), response format
  - [x] 4.3 Add safety instructions: no code changes, no Bash execution, read-only analysis

- [x] 5.0 Implement Q&A Answer Function
  depends_on: [1.0, 2.0, 4.0]
  - [x] 5.1 Write unit tests for `answer_question()` function
  - [x] 5.2 Implement `answer_question()` in router.py using `Phase.QA`, haiku model, read-only tools
  - [x] 5.3 Implement `_build_qa_prompt()` to load and format the qa.md template
  - [x] 5.4 Add budget cap from config (`qa_budget`, default $0.50)

- [x] 6.0 Integrate Router into CLI `run` Command
  depends_on: [1.0, 3.0, 5.0]
  - [x] 6.1 Write integration tests for `colonyos run` with routing enabled
  - [x] 6.2 Add `--no-triage` flag to `run()` command in cli.py
  - [x] 6.3 Add routing logic before `run_orchestrator()` call: check config.router.enabled, call `route_query()`
  - [x] 6.4 Handle `CODE_CHANGE` category: proceed to `run_orchestrator()` as before
  - [x] 6.5 Handle `QUESTION` category: call `answer_question()`, print result, return
  - [x] 6.6 Handle `STATUS` category: print suggested CLI command (e.g., `colonyos status`)
  - [x] 6.7 Handle `OUT_OF_SCOPE` category: print polite rejection message
  - [x] 6.8 Implement confidence threshold fallback: if `confidence < threshold`, run full pipeline

- [x] 7.0 Integrate Router into REPL
  depends_on: [6.0]
  - [x] 7.1 Write tests for REPL routing behavior
  - [x] 7.2 Update `_run_repl()` in cli.py to call `route_query()` before `run_orchestrator()`
  - [x] 7.3 Ensure existing command routing (lines 398-411) takes precedence over intent routing
  - [x] 7.4 Display routing decision to user: "Treating this as a [question/feature request]..."

- [x] 8.0 Refactor Slack Triage to Use Shared Router
  depends_on: [1.0]
  - [x] 8.1 Write tests to ensure Slack triage behavior is preserved after refactor
  - [x] 8.2 Factor out common prompt-building logic from slack.py into router.py
  - [x] 8.3 Update `triage_message()` to call shared `route_query()` with Slack-specific parameters
  - [x] 8.4 Maintain backward compatibility: `TriageResult.actionable` maps to `CODE_CHANGE` category
  - [x] 8.5 Update Slack-specific formatting functions to handle new result structure

- [x] 9.0 Add Audit Logging for Router Decisions
  depends_on: [1.0, 3.0]
  - [x] 9.1 Write tests for audit log generation
  - [x] 9.2 Create `log_router_decision()` function in router.py
  - [x] 9.3 Log to `.colonyos/runs/triage_<timestamp>.json` with: prompt, category, confidence, reasoning, source
  - [x] 9.4 Integrate logging into CLI and REPL call sites

- [ ] 10.0 Documentation and Final Integration Tests
  depends_on: [6.0, 7.0, 8.0, 9.0]
  - [ ] 10.1 Add router configuration section to README.md CLI Reference
  - [ ] 10.2 Add `--no-triage` flag to README.md run command documentation
  - [x] 10.3 Write end-to-end integration tests covering all routing paths
  - [x] 10.4 Run full test suite and fix any regressions
