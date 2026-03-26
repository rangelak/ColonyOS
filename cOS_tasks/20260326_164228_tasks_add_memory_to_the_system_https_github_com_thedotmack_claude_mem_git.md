# Tasks: Add Persistent Memory to ColonyOS

## Relevant Files

- `src/colonyos/memory.py` - **New file** — Memory storage layer (SQLite CRUD, FTS5 search, retrieval with ranking)
- `tests/test_memory.py` - **New file** — Tests for memory.py
- `tests/test_memory_integration.py` - **New file** — Integration tests for memory capture, injection, config, and CLI
- `src/colonyos/config.py` - Add `MemoryConfig` dataclass, parsing, serialization, defaults
- `tests/test_config.py` - Tests for new memory config parsing/validation
- `src/colonyos/orchestrator.py` - Add memory injection at prompt-build sites + post-phase capture hooks
- `tests/test_orchestrator.py` - Tests for memory injection and capture in orchestrator
- `src/colonyos/cli.py` - Add `colonyos memory` CLI command group (list, search, delete, clear, stats)
- `tests/test_cli.py` - Tests for memory CLI commands
- `src/colonyos/router.py` - Add memory injection to `build_direct_agent_prompt()`
- `tests/test_router.py` - Tests for memory injection in direct-agent prompt
- `src/colonyos/models.py` - No changes expected (PhaseResult already has artifacts dict)
- `src/colonyos/learnings.py` - No changes (coexistence, not replacement)
- `src/colonyos/sanitize.py` - Used by memory.py for content sanitization (no changes expected)
- `.gitignore` - Add `memory.db` pattern

## Tasks

- [x] 1.0 Memory Storage Layer — SQLite CRUD and retrieval (`src/colonyos/memory.py`)
  depends_on: []
  - [x] 1.1 Write tests in `tests/test_memory.py`: test DB auto-creation, add_memory(), query_memories() by category/recency, delete_memory(), count_memories(), max_entries pruning, FTS5 keyword search, sanitization of content before write
  - [x] 1.2 Create `src/colonyos/memory.py` with:
    - `MemoryCategory` enum (`codebase`, `failure`, `preference`, `review_pattern`)
    - `MemoryEntry` dataclass (`id`, `created_at`, `category`, `phase`, `run_id`, `text`, `tags`)
    - `MemoryStore` class wrapping SQLite connection at `.colonyos/memory.db`
    - `_init_db()` with schema creation + FTS5 virtual table + `schema_version` table
    - `add_memory(category, phase, run_id, text, tags)` — sanitizes text via `sanitize_ci_logs()`, inserts row, enforces max_entries cap
    - `query_memories(categories, limit, keyword, phase)` — returns ranked entries (category match + recency + keyword relevance via FTS5)
    - `delete_memory(id)`, `clear_memories()`, `count_memories()`, `count_by_category()`
  - [x] 1.3 Add `load_memory_for_injection(store, phase, prompt_text, max_tokens)` function that retrieves relevant memories, formats as markdown block, and truncates at token budget (chars ÷ 4 proxy)
  - [x] 1.4 Run tests, verify all pass

- [x] 2.0 Memory Configuration — Add `MemoryConfig` to config system
  depends_on: []
  - [x] 2.1 Write tests in `tests/test_memory_integration.py`: test `MemoryConfig` defaults, YAML parsing with valid/invalid values, serialization round-trip, `memory.enabled=false` behavior
  - [x] 2.2 Add `MemoryConfig` dataclass to `src/colonyos/config.py`
  - [x] 2.3 Add `memory: MemoryConfig` field to `ColonyConfig` dataclass
  - [x] 2.4 Add `"memory"` to `DEFAULTS` dict with default values
  - [x] 2.5 Add `_parse_memory_config(raw: dict) -> MemoryConfig` parser with validation (max_entries >= 1, max_inject_tokens >= 0)
  - [x] 2.6 Wire parsing into `load_config()` and serialization into `save_config()`
  - [x] 2.7 Run tests, verify all pass including existing config tests

- [x] 3.0 Memory Capture Hooks — Post-phase memory extraction in orchestrator
  depends_on: [1.0, 2.0]
  - [x] 3.1 Write tests in `tests/test_memory_integration.py`: test that memory capture is called after implement/review/fix phases, test failure capture on phase error, test that capture respects `memory.enabled=false`, test sanitization
  - [x] 3.2 Add `_capture_phase_memory(store, phase_result, run_id, config)` helper to `src/colonyos/orchestrator.py`
  - [x] 3.3 Add `_get_memory_store(repo_root)` factory that returns a `MemoryStore` instance (or `None` if memory disabled)
  - [x] 3.4 Wire `_capture_phase_memory()` calls into the orchestrator's post-phase hooks (after plan, implement, fix phases in `_run_pipeline`)
  - [x] 3.5 Run tests, verify all pass

- [x] 4.0 Memory Injection into Phase Prompts
  depends_on: [1.0, 2.0]
  - [x] 4.1 Write tests in `tests/test_memory_integration.py`: test that memory block appears in system prompt for implement/fix/plan phases, test memory disabled produces no injection, test empty memory produces no block
  - [x] 4.2 Add memory injection calls at existing prompt-build sites in `src/colonyos/orchestrator.py` (plan, implement, fix phases)
  - [x] 4.3 Add memory injection to `build_direct_agent_prompt()` in `src/colonyos/router.py`
  - [x] 4.4 Write tests in `tests/test_memory_integration.py` for memory injection in direct-agent prompt
  - [x] 4.5 Define phase-to-category mapping:
    - `plan` → [`codebase`, `failure`, `preference`]
    - `implement/fix` → [`codebase`, `failure`, `preference`]
    - `review/decision` → [`review_pattern`, `codebase`]
    - `direct_agent` → all categories
  - [x] 4.6 Run tests, verify all pass

- [x] 5.0 CLI Commands — `colonyos memory` command group
  depends_on: [1.0, 2.0]
  - [x] 5.1 Write tests in `tests/test_memory_integration.py`: test `memory list`, `memory search`, `memory delete`, `memory clear`, `memory stats` commands
  - [x] 5.2 Add `@app.group()` for `memory` in `src/colonyos/cli.py`
  - [x] 5.3 Implement `memory list` — show recent memories with optional `--category` and `--limit` flags, formatted as table
  - [x] 5.4 Implement `memory search <query>` — keyword search via FTS5, display results with IDs
  - [x] 5.5 Implement `memory delete <id>` — delete by ID with confirmation
  - [x] 5.6 Implement `memory clear` — delete all with `--yes` flag to skip confirmation
  - [x] 5.7 Implement `memory stats` — show counts by category and total entries
  - [x] 5.8 Run tests, verify all pass

- [x] 6.0 Gitignore and Init Integration
  depends_on: []
  - [x] 6.1 Write test verifying `colonyos init` adds `memory.db` to `.gitignore` patterns
  - [x] 6.2 Update `.gitignore` template in `src/colonyos/init.py` to include `.colonyos/memory.db`
  - [x] 6.3 Add `memory.db` to the project's own `.gitignore`

- [x] 7.0 Integration Testing and End-to-End Verification
  depends_on: [3.0, 4.0, 5.0, 6.0]
  - [x] 7.1 Write integration test: capture memory then inject into prompts (test_capture_then_inject)
  - [x] 7.2 Write integration test: phase failure → verify failure memory captured
  - [x] 7.3 Write integration test: `memory.enabled: false` → verify no DB created, no capture, no injection
  - [x] 7.4 Write integration test: memory cap enforcement → add 600 entries with max_entries=500 → verify oldest pruned
  - [x] 7.5 Write integration test: CLI commands work against a real (temp) SQLite DB
  - [x] 7.6 Run full existing test suite to verify no regressions (1924 passed, 0 failed)
  - [x] 7.7 Verify learnings ledger still works unchanged (coexistence)
