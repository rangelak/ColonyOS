## Proposal: Codebase Context Map for Phase Prompts

### Rationale
Every pipeline phase currently receives the user prompt, instruction templates, and memory/learnings — but no structured understanding of the target codebase itself. Agents must re-discover the repo layout, key modules, and architectural patterns from scratch on every run. A lightweight, cached codebase context map injected into phase prompts would raise the quality floor of planning, implementation, and review across every single pipeline execution while reducing wasted tokens from brute-force exploration.

### Builds Upon
- "Persistent Memory System" (cross-run knowledge injection into prompts — this extends the same injection pattern with structural codebase knowledge)
- "Intent Router Agent" (the router's complexity classification would benefit from knowing repo structure to better estimate change scope)
- "AI-Assisted Setup for ColonyOS Init" (the `scan_repo_context()` function already does basic repo detection — this generalizes it into a richer, reusable index)

### Inspired By
Aider's "repo maps" pattern (cited in STRATEGIC_DIRECTIONS.md as a key gap: "Repo maps beat context-window brute force") and Superpowers' "subagent-per-task with fresh context" pattern where each agent gets precisely the context it needs rather than everything.

### Feature Request
Build a `colonyos map` command and underlying `RepoMap` module that generates a structured codebase context map and integrates it into the pipeline:

**Indexing**: Scan the repository to produce a cached JSON/YAML map containing: (1) a file tree with one-line purpose annotations for each source file, (2) key exports per module (classes, functions, CLI commands), (3) dependency relationships between modules (imports graph), and (4) a 2-3 sentence architecture summary. Use a cheap model (haiku) to generate annotations by reading file headers/docstrings — not full file contents. Cache the map in `.colonyos/repo_map.json` with a content hash so it only regenerates when the repo changes significantly (new files added, files deleted, or manual `colonyos map --refresh`).

**Injection**: Add a `_inject_repo_map_block()` method to the orchestrator (following the same pattern as `_inject_memory_block()`) that selects the most relevant subset of the map for each phase. For PLAN phases, inject the full architecture summary + file tree. For IMPLEMENT phases, inject files related to the task's target area (match task descriptions against file annotations). For REVIEW phases, inject the map of changed files plus their neighbors in the dependency graph. Cap injection at a configurable `max_map_tokens` (default: 2000 tokens) in `RepoMapConfig`.

**CLI**: `colonyos map` generates/refreshes the map and prints a pretty-printed summary. `colonyos map --show` displays the cached map. `colonyos map --refresh` forces regeneration. The map auto-generates on first pipeline run if missing.

**Configuration**: Add `RepoMapConfig` dataclass to config.py with fields: `enabled: bool = True`, `max_map_tokens: int = 2000`, `model: str = "haiku"`, `exclude_patterns: list[str] = ["tests/*", "docs/*", "*.md"]` (patterns to skip during annotation), `auto_refresh: bool = True`.

**Acceptance criteria**: (1) `colonyos map` produces a cached repo map with file annotations and architecture summary, (2) map is automatically injected into plan/implement/review phase prompts, (3) map regenerates only when repo structure changes, (4) injection respects token budget, (5) pipeline works normally when map is disabled or missing, (6) unit tests cover indexing, caching, injection, and CLI commands.