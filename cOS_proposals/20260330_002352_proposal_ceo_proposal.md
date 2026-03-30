Based on my thorough analysis of the project, its 30+ shipped features, strategic directions, and the gaps that remain, here is my proposal:

---

## Proposal: Repo Map Context Injection

### Rationale
Context window exhaustion is the #1 risk called out in STRATEGIC_DIRECTIONS.md, and currently every agent phase operates blind — it sees only what it stumbles upon via tool calls. A lightweight repo map that gives agents a structural overview of the codebase (module tree, key classes/functions, dependency graph) before they start working would dramatically improve plan quality, implementation accuracy, and review depth across *every* pipeline phase, without requiring larger context windows or more expensive models.

### Builds Upon
- "Persistent Memory System" (the memory injection pattern into phase prompts is directly reusable for repo map injection)
- "Per-Phase Model Override Configuration" (repo map token budget should respect per-phase model limits)
- "Intent Router Agent" (the router's complexity classification can inform how much repo map detail to inject)

### Inspired By
Aider's repo-map abstraction — explicitly called out in STRATEGIC_DIRECTIONS.md: "Repo maps solve context-window exhaustion better than just throwing larger models at the problem. ColonyOS should eventually build or adopt a comparable repo-map abstraction."

### Feature Request
Build a repo map generator and context injection system that provides agents with a structural overview of the target codebase at the start of each phase. Specifically:

**Repo Map Generator (`src/colonyos/repomap.py`)**:
- Walk the project tree respecting `.gitignore` and configurable exclude patterns
- For Python files: extract module-level docstrings, class names with method signatures, top-level function signatures, and import relationships using `ast` (stdlib only — no new dependencies)
- For other languages (JS/TS, Go, Rust, etc.): fall back to a file-tree-only view with file sizes and last-modified dates
- Output a compact text representation that fits within a configurable token budget (default: 4000 tokens, max: 8000)
- Cache the repo map to `.colonyos/repomap.cache` with an mtime-based invalidation strategy — regenerate only when source files change
- Include a relevance ranking: when a user prompt or PRD is available, score files/modules by keyword overlap and surface the most relevant sections first (simple TF-IDF or keyword matching, no ML dependencies)

**Context Injection**:
- Inject the repo map into the system prompt for Plan, Implement, Review, and Fix phases (configurable per-phase via `config.yaml`)
- The injection should appear as a clearly delimited `## Repository Structure` section in the prompt, after memory injection but before the phase-specific instructions
- Respect the phase's model context limit — if the repo map would push the prompt over budget, truncate least-relevant sections first

**Configuration** (in `.colonyos/config.yaml`):
```yaml
repo_map:
  enabled: true
  max_tokens: 4000
  exclude_patterns: ["*.pyc", "__pycache__", "node_modules", ".git"]
  languages: ["python"]  # deep parsing; others get tree-only
  inject_phases: [plan, implement, review, fix]
  cache_ttl_seconds: 300
```

**CLI Integration**:
- `colonyos repomap` command that prints the generated repo map to stdout (useful for debugging and inspection)
- `colonyos repomap --refresh` to force cache regeneration

**Acceptance Criteria**:
1. Running `colonyos repomap` on the ColonyOS repo itself produces a readable structural overview under 4000 tokens
2. The repo map is automatically injected into Plan/Implement/Review/Fix phase prompts when enabled
3. Cache invalidation works: changing a source file and re-running produces an updated map
4. Relevance ranking works: when a prompt mentions "Slack", Slack-related modules appear first in the map
5. The feature adds zero new dependencies (uses only `ast`, `os`, `pathlib` from stdlib)
6. All existing tests continue to pass
7. New tests cover: map generation, caching, invalidation, relevance ranking, prompt injection, configuration parsing, and the CLI command