# PRD: Add Persistent Memory to ColonyOS

## 1. Introduction / Overview

ColonyOS currently suffers from cross-run amnesia. Each pipeline run and TUI session starts nearly from scratch — the only persistent context is a flat markdown learnings ledger (`learnings.md`) that captures generic post-review patterns and a strategic directions document for the CEO phase. Agents repeatedly burn budget re-discovering codebase structure, forgotten gotchas, and user preferences that were established in prior runs.

This feature adds a **native persistent memory system** to ColonyOS, inspired by [claude-mem](https://github.com/thedotmack/claude-mem)'s design principles (lifecycle hooks, structured observations, relevance-based retrieval) but implemented entirely in Python using SQLite — zero new external dependencies. Memory entries are captured automatically at phase boundaries, stored in `.colonyos/memory.db`, and injected into phase prompts based on relevance and recency, so run #50 feels fundamentally smarter than run #2.

## 2. Goals

1. **Reduce wasted agent turns** — agents should not re-discover the same codebase patterns, test conventions, or architectural constraints every run.
2. **Capture failure knowledge** — when a run fails, the next run should know what went wrong and how to avoid it.
3. **Preserve user preferences** — coding style, review standards, and tooling choices expressed through repeated corrections should persist.
4. **Zero new dependencies** — memory must work with `pip install colonyos` and nothing else (Python's built-in `sqlite3`).
5. **Token-efficient injection** — memory context must fit within a configurable token budget (default 1500 tokens) and be ranked by relevance.

## 3. User Stories

- **As a developer using ColonyOS daily**, I want the system to remember that my project uses pytest (not unittest), requires `PYTHONPATH=src`, and has a fragile circular import in the auth module — so agents stop making the same mistakes.
- **As a developer resuming work**, I want the system to know what the last run changed, so follow-up runs have context without me re-explaining.
- **As a team using ColonyOS on Slack**, I want the agent to accumulate knowledge about our codebase conventions over time, reducing review iterations.
- **As a developer**, I want to view, search, and manage memories via `colonyos memory` CLI commands.
- **As a security-conscious user**, I want memory capture to be sanitized and I want the ability to disable it or delete entries.

## 4. Functional Requirements

### FR-1: Memory Storage Layer (`src/colonyos/memory.py`)
- Store memories in a SQLite database at `.colonyos/memory.db`
- Schema: `id`, `created_at`, `category` (enum: `codebase`, `failure`, `preference`, `review-pattern`), `phase` (which phase created it), `run_id`, `text` (the memory content), `tags` (comma-separated)
- Auto-create database and tables on first access
- Support CRUD operations: `add_memory()`, `query_memories()`, `delete_memory()`, `count_memories()`
- Enforce a configurable max entries cap (default 500), pruning oldest entries on overflow (FIFO by category)

### FR-2: Memory Capture Hooks
- **Post-phase capture**: After each phase completes, extract structured observations from `PhaseResult.artifacts` and write to memory DB
- **Post-learn capture**: Enhance the existing learn phase to write memories alongside the learnings ledger (coexistence, not replacement)
- **Failure capture**: When a phase fails, capture the error context as a `failure` category memory so the next run can avoid the same issue
- **Capture runs through `sanitize_untrusted_content()`** before writing to prevent prompt injection persistence

### FR-3: Memory Injection into Phase Prompts
- At prompt-build time for implement, fix, plan, review, and direct-agent phases, query relevant memories and inject as a `## Memory Context` block in the system prompt
- Retrieve memories using: category matching (map phase → relevant categories), recency weighting, and keyword overlap with the current prompt/task
- Hard-cap injected memory at `memory.max_inject_tokens` (default 1500 tokens, configurable)
- Inject alongside but separate from the existing learnings block

### FR-4: Memory Configuration
- Add `MemoryConfig` dataclass to `config.py`:
  ```yaml
  memory:
    enabled: true
    max_entries: 500
    max_inject_tokens: 1500
    capture_failures: true
  ```
- Add `memory` field to `ColonyConfig` with parsing/validation/serialization following existing patterns
- Respect `memory.enabled` toggle — when false, skip both capture and injection

### FR-5: CLI Commands (`colonyos memory`)
- `colonyos memory list` — show recent memories, filterable by `--category` and `--phase`
- `colonyos memory search <query>` — keyword search across memories
- `colonyos memory delete <id>` — delete a specific memory
- `colonyos memory clear` — delete all memories (with confirmation)
- `colonyos memory stats` — show memory counts by category and total

### FR-6: Learnings Ledger Coexistence
- The existing `learnings.py` system continues to work unchanged
- The learn phase writes to both the learnings ledger AND the memory DB
- `load_learnings_for_injection()` remains the learnings API; memory injection is a separate path
- Both blocks appear in the system prompt, clearly labeled

## 5. Non-Goals

- **Semantic/vector search** — MVP uses keyword + recency retrieval via SQLite FTS5. Embeddings are a v2 concern.
- **Web viewer UI** — claude-mem's localhost:37777 web viewer is out of scope. The CLI commands provide sufficient visibility.
- **Cross-project memory** — memories are per-repository (stored in `.colonyos/`). Global user memory is out of scope.
- **Claude-mem integration** — we are building native, not wrapping claude-mem as a dependency.
- **Memory during agent execution** — the agent cannot write to memory mid-session. Only the orchestrator writes at phase boundaries. This prevents prompt injection from poisoning the memory store.
- **Replacing the learnings ledger** — learnings.md remains as a human-readable, git-friendly audit trail. Memory coexists alongside it.

## 6. Technical Considerations

### Existing Code Integration Points
- **`src/colonyos/orchestrator.py`** — Learnings injection already happens at prompt-build time (implement, fix, standalone review). Memory injection follows the same pattern at the same sites.
- **`src/colonyos/config.py`** — New `MemoryConfig` dataclass follows the established pattern of `LearningsConfig`, `CleanupConfig`, etc.
- **`src/colonyos/learnings.py`** — Remains untouched. The learn phase instruction template (`instructions/learn.md`) may get a small addition to also emit memory-worthy observations.
- **`src/colonyos/cli.py`** — New `colonyos memory` command group, following patterns from `colonyos stats`, `colonyos show`, etc.
- **`src/colonyos/router.py`** — The direct-agent prompt builder (`build_direct_agent_prompt`) gains memory injection.
- **`src/colonyos/sanitize.py`** — All memory content passes through `sanitize_untrusted_content()` before storage.

### Storage
- Single SQLite file at `.colonyos/memory.db`, gitignored (alongside `runs/`)
- Python's built-in `sqlite3` module — zero new dependencies
- Schema migrations handled by checking a `schema_version` table on open
- FTS5 virtual table for keyword search (available in standard Python sqlite3)

### Token Budget
- Memory injection capped at configurable token count (default 1500)
- Approximate token counting via character count (÷4 as proxy)
- Retrieval ranks by: (1) category relevance to current phase, (2) recency, (3) keyword overlap
- Greedy packing: add entries until budget is exhausted

### Security
- All memory content sanitized via `sanitize_untrusted_content()` before write
- Memory writes only happen in the orchestrator process, never inside agent sessions
- Memory DB should be added to `.gitignore` template during `colonyos init`

## 7. Persona Synthesis

### Strong Agreement (All 7 Personas)
- **Build native, don't integrate claude-mem** — unanimous. The Bun/Chroma/uv dependency chain is unacceptable for a `pip install` tool.
- **Start with keyword + recency retrieval** — unanimous. Semantic search is premature for hundreds of entries.
- **Automatic capture, configurable injection** — unanimous. Opt-in capture means nobody uses it.
- **Hard token cap on injection** — unanimous. Range: 500-2000 tokens suggested. We chose 1500 as default.

### Moderate Agreement
- **SQLite vs flat files** — 4/7 favored SQLite (Steve Jobs, Jony Ive, Karpathy, Security). 3/7 preferred flat files (Michael Seibel, Linus, Systems Engineer). We chose SQLite because the learnings.md already shows flat-file parsing fragility (broken dedup), and SQLite is stdlib with zero new deps.
- **Coexist vs replace learnings** — 5/7 favored coexistence. Jony Ive suggested eventual subsumption. We chose coexistence for safety.

### Key Tensions
- **Linus/Systems Engineer** want to keep everything debuggable with `cat` — addressed by keeping learnings.md as the human-readable audit trail while memory.db handles structured retrieval.
- **Security Engineer** flags that agent-written memories are a prompt injection vector — addressed by restricting writes to the orchestrator only, never inside agent sessions.
- **Karpathy** suggests progressive disclosure (inject summaries, let agent request details) — noted as v2 enhancement.

## 8. Success Metrics

- **Reduced agent turns per run** — measure average turns in implement/fix phases before vs. after memory, targeting 15% reduction.
- **Reduced duplicate learnings** — memory's structured storage should eliminate the dedup failures visible in current `learnings.md`.
- **Budget savings** — less time spent on codebase orientation means lower per-run cost.
- **User adoption** — `memory.enabled` stays true (default) for >90% of users.

## 9. Open Questions

1. **Memory extraction prompt**: Should we create a new instruction template (`instructions/memory_extract.md`) or extend the existing `learn.md` template?
2. **Phase-category mapping**: Exact mapping of which memory categories are relevant to which phases needs tuning based on real usage.
3. **TUI visibility**: Should the TUI show "X memories injected" in the status bar? Linus and Security both want observability.
4. **Migration path**: Should existing learnings.md entries be imported into memory.db on first run of the new system?
