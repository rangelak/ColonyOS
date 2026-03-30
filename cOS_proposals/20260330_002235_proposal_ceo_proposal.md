## Proposal: Repo Map Generation & Context Injection

### Rationale
Context exhaustion is the #1 scaling bottleneck for autonomous agents working on real codebases — strategic directions explicitly flag it as a key risk and cite Aider's repo-map approach as the solution. Today, every ColonyOS phase either gets zero structural context or consumes massive token budgets reading raw files. A lightweight repo map (module tree, function/class signatures, dependency graph) injected into phase prompts would make every pipeline run smarter — better plans, more targeted implementations, and more relevant reviews — without blowing context windows.

### Builds Upon
- "Persistent Memory System" (memory injection into phase prompts — same injection pattern)
- "Cross-Run Learnings System" (cached knowledge injected at phase boundaries)
- "Intent Router Agent" (complexity classification benefits from knowing codebase structure)

### Inspired By
Aider's repo-map approach (cited in STRATEGIC_DIRECTIONS.md as "repo maps vs brute-force — solve context exhaustion with smart retrieval"). Also draws from Superpowers' subagent-per-task architecture where each agent gets fresh, focused context rather than the full codebase.

### Feature Request
Build a **repo map generator** that creates a compact, token-efficient structural summary of the target repository and injects it into agent phase prompts.

**Core components:**

1. **`src/colonyos/repomap.py`** — A `RepoMap` class that:
   - Walks the repository file tree (respecting `.gitignore` and a configurable exclude list)
   - For Python files: extracts module-level docstrings, class names with bases, function/method signatures (name + params, no bodies), and top-level constants
   - For JS/TS files: extracts exported function signatures, class declarations, and type/interface names
   - For other files: includes filename + first-line comment/docstring if present
   - Produces a compact text representation (tree-style with indented signatures) that fits within a configurable token budget (default: 4000 tokens)
   - Uses a relevance-ranked truncation strategy: files recently modified (git log) and files matching the current prompt keywords rank higher and survive truncation
   - Caches the generated map to `.colonyos/repomap.cache` with a file-content hash so it only regenerates when the repo actually changes

2. **Prompt injection** — Wire repo map into phase prompts in `orchestrator.py`:
   - **Plan phase**: Full repo map so the planner understands existing architecture before proposing tasks
   - **Implement phase**: Filtered repo map (only modules relevant to the current task, based on keyword/path matching from the task description)
   - **Review phase**: Full repo map so reviewers can assess architectural fit
   - **CEO phase**: Full repo map so proposals are grounded in actual codebase structure

3. **`RepoMapConfig` dataclass** in `config.py`:
   - `enabled: bool = True`
   - `max_tokens: int = 4000` (total budget for the map in any single prompt)
   - `exclude_patterns: List[str] = ["node_modules", "dist", ".git", "__pycache__", "*.min.js"]`
   - `cache_ttl_seconds: int = 300` (regenerate if cache older than 5 minutes)
   - `language_parsers: List[str] = ["python", "javascript", "typescript"]` (extensible)

4. **CLI integration**:
   - `colonyos repomap` command that generates and prints the repo map to stdout (useful for debugging/inspection)
   - `--format` flag: `tree` (default compact view) or `json` (machine-readable)

5. **Language parsing strategy**: Use Python's `ast` module for Python files (zero dependencies). For JS/TS, use regex-based extraction of `export function`, `export class`, `export interface`, `export type` declarations (no Node.js dependency required). This keeps the feature dependency-free.

**Acceptance criteria:**
- `colonyos repomap` prints a readable structural summary of the current repo
- Repo map is automatically injected into plan, implement, review, and CEO phase prompts when `repomap.enabled` is true
- Map respects the configured `max_tokens` budget — truncates intelligently based on relevance
- Cache works: second run with no file changes skips regeneration
- Cache invalidates: modifying a file causes regeneration on next run
- Tests cover: map generation, caching/invalidation, token truncation, prompt injection, Python AST parsing, JS/TS regex parsing, exclude patterns, CLI command