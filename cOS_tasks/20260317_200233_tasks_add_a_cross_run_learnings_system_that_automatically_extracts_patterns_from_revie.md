# Tasks: Cross-Run Learnings System

## Relevant Files

- `src/colonyos/models.py` - Add `LEARN` to `Phase` enum
- `src/colonyos/config.py` - Add `LearningsConfig` dataclass and parse/serialize learnings config
- `src/colonyos/learnings.py` - **New file**: Ledger I/O, parsing, formatting, deduplication, pruning
- `src/colonyos/orchestrator.py` - Wire learn phase into pipeline, inject learnings into implement/fix prompts
- `src/colonyos/instructions/learn.md` - **New file**: Extraction agent instruction template
- `src/colonyos/instructions/implement.md` - Add `{learnings_block}` placeholder for learnings injection
- `src/colonyos/instructions/fix.md` - Add `{learnings_block}` placeholder for learnings injection
- `src/colonyos/cli.py` - Show learnings count in `status` command
- `tests/test_learnings.py` - **New file**: Unit tests for the learnings module
- `tests/test_orchestrator.py` - Add tests for learn phase wiring, prompt injection, non-blocking failure
- `tests/test_config.py` - Add tests for LearningsConfig parsing and defaults
- `tests/test_cli.py` - Add test for learnings count in status output

## Tasks

- [x] 1.0 Add `Phase.LEARN` enum value and `LearningsConfig` to models/config
  - [x] 1.1 Write tests in `tests/test_config.py` for `LearningsConfig` parsing: default values (`enabled=True`, `max_entries=100`), explicit values from YAML, missing `learnings:` section falls back to defaults
  - [x] 1.2 Add `LEARN = "learn"` to the `Phase` enum in `src/colonyos/models.py` after `FIX` and before `DELIVER`
  - [x] 1.3 Add `LearningsConfig` dataclass to `src/colonyos/config.py` with `enabled: bool = True` and `max_entries: int = 100`
  - [x] 1.4 Add `learnings: LearningsConfig` field to `ColonyConfig` with default factory
  - [x] 1.5 Add `"learnings": {"enabled": True, "max_entries": 100}` to `DEFAULTS` dict
  - [x] 1.6 Update `load_config()` to parse `learnings:` section from YAML and populate `LearningsConfig`
  - [x] 1.7 Update `save_config()` to serialize the `learnings:` section to YAML
  - [x] 1.8 Run existing tests to verify no regressions

- [x] 2.0 Create the learnings module (`src/colonyos/learnings.py`)
  - [x] 2.1 Write tests in `tests/test_learnings.py` for:
    - `parse_learnings()`: parse well-formed markdown into `LearningEntry` objects, handle empty file, handle malformed sections
    - `format_learnings_section()`: format entries back to markdown with run header
    - `append_learnings()`: appends new section to file, creates file if missing
    - `prune_ledger()`: with cap=5, a file with 7 entries prunes the 2 oldest run sections
    - `load_learnings_for_injection()`: returns formatted string of most recent N entries, returns empty string if file missing
    - `count_learnings()`: counts total entries across all run sections
    - Deduplication: entries with identical normalized text (lowercase, whitespace-collapsed) are skipped during append
  - [x] 2.2 Create `LearningEntry` dataclass with fields: `category: str`, `text: str`
  - [x] 2.3 Implement `parse_learnings(content: str) -> list[tuple[str, str, str, list[LearningEntry]]]` that parses `## Run:` sections into `(run_id, date, feature, entries)` tuples
  - [x] 2.4 Implement `format_learnings_section(run_id, date, feature_summary, entries) -> str` to produce the markdown block for one run
  - [x] 2.5 Implement `append_learnings(repo_root, run_id, date, feature_summary, new_entries, max_entries)` with deduplication against existing entries and cap enforcement via `prune_ledger()`
  - [x] 2.6 Implement `prune_ledger(content, max_entries) -> str` that drops oldest run sections until total entries ≤ max_entries
  - [x] 2.7 Implement `load_learnings_for_injection(repo_root, max_entries=20) -> str` that reads the ledger and formats the most recent N entries as a prompt-ready block
  - [x] 2.8 Implement `count_learnings(repo_root) -> int`
  - [x] 2.9 Define `LEARNINGS_FILE = "learnings.md"` constant and `learnings_path(repo_root) -> Path` helper

- [x] 3.0 Create the learn phase instruction template
  - [x] 3.1 Create `src/colonyos/instructions/learn.md` with template variables `{reviews_dir}`, `{learnings_path}`, and instructions for the extraction agent to: read review artifacts, identify 3-5 actionable patterns, categorize under fixed categories (`code-quality`, `testing`, `architecture`, `security`, `style`), check existing ledger for duplicates, output structured markdown with `- **[category]** learning text` format, cap each entry at 150 characters

- [x] 4.0 Inject learnings into implement and fix phase prompts
  - [x] 4.1 Write tests in `tests/test_orchestrator.py` for:
    - `_build_implement_prompt()` includes learnings block when ledger exists
    - `_build_implement_prompt()` works normally when ledger is missing (no crash, no learnings block)
    - `_build_fix_prompt()` includes learnings block when ledger exists
    - `_build_fix_prompt()` works normally when ledger is missing
  - [x] 4.2 Modify `_build_implement_prompt()` in `orchestrator.py` to accept `repo_root: Path` parameter, call `load_learnings_for_injection(repo_root)`, and append the result (if non-empty) as a `\n\n## Learnings from Past Runs\n\n{learnings}` section to the system prompt
  - [x] 4.3 Modify `_build_fix_prompt()` similarly to inject learnings into the fix phase system prompt
  - [x] 4.4 Update all call sites of `_build_implement_prompt()` and `_build_fix_prompt()` in `orchestrator.run()` and `run_standalone_review()` to pass `repo_root`

- [x] 5.0 Wire the learn phase into the pipeline (`orchestrator.run()`)
  - [x] 5.1 Write tests in `tests/test_orchestrator.py` for:
    - Learn phase runs after decision gate and produces a `PhaseResult` with `Phase.LEARN`
    - Learn phase runs on NO-GO verdict (before the early return)
    - Learn phase is skipped when `config.learnings.enabled` is `False`
    - Learn phase failure (mocked exception) does not prevent deliver phase from running
    - Learn phase failure logs a warning but does not set `RunStatus.FAILED`
    - Learn phase budget is `min(0.50, config.budget.per_phase / 2)`
  - [x] 5.2 Create `_build_learn_prompt()` function in `orchestrator.py` that loads `learn.md`, formats with `reviews_dir` and `learnings_path`, and returns `(system, user)` tuple
  - [x] 5.3 Add learn phase execution block after the decision gate (after line 1265) and before the NO-GO early return (line 1267). Wrap in try/except to catch all exceptions, log warning on failure, append `PhaseResult` regardless (with `success=False` and error message on failure)
  - [x] 5.4 Also add learn phase execution before the NO-GO early return path — extract learnings even on failed runs
  - [x] 5.5 After successful learn phase, call `append_learnings()` to persist extracted entries to the ledger file
  - [x] 5.6 Guard the entire learn block with `if config.learnings.enabled:`
  - [x] 5.7 Set learn phase allowed_tools to `["Read", "Glob", "Grep"]` (read-only)
  - [x] 5.8 Set learn phase budget to `min(0.50, config.budget.per_phase / 2)`

- [x] 6.0 Integrate learnings count into `colonyos status`
  - [x] 6.1 Write test in `tests/test_cli.py` that verifies `status` output includes "Learnings ledger: N entries" when the ledger file exists, and "Learnings ledger: not found" when it does not
  - [x] 6.2 In the `status` command in `cli.py`, after the run summaries loop, import `count_learnings` from `learnings.py` and display the count

- [x] 7.0 End-to-end integration testing
  - [x] 7.1 Write an integration test in `tests/test_orchestrator.py` that mocks `run_phase_sync` and verifies the full pipeline flow: Plan → Implement → Review → Decision → **Learn** → Deliver, confirming the learn phase is called with correct parameters
  - [x] 7.2 Write an integration test verifying that when learn phase raises an exception, the pipeline still completes with `RunStatus.COMPLETED` and the deliver phase runs
  - [x] 7.3 Run the full test suite (`pytest tests/`) and verify all existing tests pass with the new code
