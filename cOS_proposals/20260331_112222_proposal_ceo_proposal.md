## Proposal: Repository Map for Context-Aware Agent Prompts

### Rationale
Context window exhaustion is explicitly flagged as the #1 "Watch Out For" in the strategic directions, and every pipeline phase currently relies on agents discovering codebase structure through brute-force tool calls. A repo map — a condensed structural summary of the codebase (files, classes, function signatures, imports) — injected into phase prompts would immediately improve agent accuracy across plan, implement, review, and fix phases while reducing token waste from redundant exploration, making every single pipeline run faster and cheaper.

### Builds Upon
- "Persistent Memory System" — the repo map complements episodic memory by providing structural/semantic context rather than historical context
- "Intent Router Agent" — complexity classification can leverage the repo map to better gauge change scope
- "Per-Phase Model Override Configuration" — cheaper models become viable for more phases when they receive a focused repo map instead of raw file dumps

### Inspired By
**Aider's repo-map abstraction** — explicitly cited in strategic directions: "Repo maps solve context-window exhaustion better than just throwing larger models at the problem. ColonyOS should eventually build or adopt a comparable repo-map abstraction."

### Feature Request
Build a `RepoMap` module (`src/colonyos/repo_map.py`) that generates a condensed structural summary of the target repository and injects it into agent phase prompts. Specifically:

**Core repo map generator:**
- Walk the repository tree respecting `.gitignore` patterns
- For Python files: use `ast` module to extract module docstrings, class names with base classes, method signatures (name + params), and top-level function signatures
- For JS/TS files: use regex-based extraction of `export` declarations, class names, and function signatures (no new dependencies — regex is sufficient for structural overview)
- For other files: include file path and size as structural markers
- Generate a tree-formatted text output showing the codebase skeleton (file paths → class/function signatures) similar to Aider's tag-based format
- Respect a configurable token budget (`max_repo_map_tokens`, default ~4000 tokens) — prioritize files by relevance when the map must be truncated

**Relevance-aware truncation:**
- When the full map exceeds the token budget, rank files by relevance to the current prompt/task using keyword overlap (file names, class names vs. prompt terms)
- Always include files that are directly referenced in the user's prompt or task description
- Include a "structure overview" section (directory tree with file counts) that fits in ~500 tokens regardless of repo size

**Integration into the pipeline:**
- Add a `repo_map` section to `config.yaml` with `enabled: bool` (default true), `max_tokens: int`, and `include_patterns`/`exclude_patterns` glob lists
- Generate the repo map once at pipeline start (in the orchestrator, before the first phase) and cache it for the duration of the run
- Inject the repo map into the system prompt for Plan, Implement, Review, Fix, and CEO phases via a `{repo_map}` template variable in the instruction markdown files
- Add a `colonyos map` CLI command that prints the repo map to stdout for debugging/inspection

**Acceptance criteria:**
- `colonyos map` prints a readable structural summary of the current repo
- Python files show class and function signatures extracted via AST
- The map respects the configured token budget and truncates intelligently
- Phase prompts include the repo map when `repo_map.enabled` is true
- Config supports `include_patterns` and `exclude_patterns` for customization
- Unit tests cover map generation, truncation, relevance ranking, and prompt injection
- No new dependencies — uses Python's `ast` module and stdlib only