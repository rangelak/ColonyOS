# PRD: RepoMap Module

## Introduction/Overview

Build a `RepoMap` module (`src/colonyos/repo_map.py`) that generates a condensed structural summary of the target repository and injects it into agent phase prompts. The repo map gives every pipeline phase (Plan, Implement, Review, Fix, Deliver, CEO) a "table of contents" of the codebase — file paths, class names, function signatures — so the agent can orient itself without spending tool calls on initial exploration.

This directly addresses a core limitation: today, each agent phase starts with zero structural awareness of the repository. The agent must use `Read`, `Glob`, and `Grep` tool calls to discover what exists before doing useful work. A pre-injected repo map eliminates this cold-start overhead and improves agent accuracy by ensuring every phase knows about relevant modules from the first token.

## Goals

1. **Reduce agent cold-start cost**: Eliminate 3-8 exploratory tool calls per phase by pre-injecting structural context
2. **Improve code quality**: Help agents reference correct file paths, class names, and function signatures from the start
3. **Stay within token budget**: Generate a useful map in ~4000 tokens (configurable) that does not crowd out other context injections (memory, learnings)
4. **Zero new dependencies**: Use only Python stdlib (`ast`, `re`, `pathlib`, `subprocess`)
5. **Provide debugging visibility**: `colonyos map` CLI command lets users inspect exactly what the agent sees

## User Stories

1. **As a developer running `colonyos run`**, I want the agent to already know my project's file structure and key APIs so it makes fewer incorrect file references and fewer wasted tool calls.
2. **As a developer debugging agent behavior**, I want to run `colonyos map` to see exactly what structural context the agent receives, so I can tune `include_patterns`/`exclude_patterns` if needed.
3. **As a daemon operator**, I want the repo map to be generated once per pipeline run and cached in-memory for the duration, so it does not add latency to each phase.
4. **As a user with a large monorepo**, I want the map to intelligently truncate to my configured token budget, prioritizing files relevant to the current task over distant utility code.

## Functional Requirements

### Core Map Generation

- **FR-1**: Walk the repository using `git ls-files` (subprocess call with timeout) to get the list of tracked files, respecting `.gitignore` automatically.
- **FR-2**: For Python files (`.py`), use the `ast` module to extract:
  - Module-level docstrings (first line only)
  - Class names with base classes (e.g., `class Daemon(threading.Thread)`)
  - Method signatures within classes (name + parameters)
  - Top-level function signatures (name + parameters)
- **FR-3**: For JavaScript/TypeScript files (`.js`, `.jsx`, `.ts`, `.tsx`), use regex-based extraction of:
  - `export` declarations (named exports, default exports)
  - Class names
  - Top-level function signatures
- **FR-4**: For all other files, include file path and size (bytes) as structural markers.
- **FR-5**: Generate tree-formatted text output showing the codebase skeleton. Format:
  ```
  src/colonyos/
    config.py (284 lines)
      class ColonyConfig
        get_model(phase: Phase) -> str
      load_config(repo_root: Path) -> ColonyConfig
      save_config(repo_root: Path, config: ColonyConfig) -> Path
    orchestrator.py (4500 lines)
      class Orchestrator
        run() -> RunResult
        ...
  ```
- **FR-6**: Exclude files matching sensitive patterns by default: `.env*`, `*credential*`, `*secret*`, `*.pem`, `*.key`. Use a hardcoded denylist plus respect `exclude_patterns` from config.

### Relevance-Aware Truncation

- **FR-7**: Estimate token count using `chars / 4`, consistent with the existing convention in `load_memory_for_injection()` (`memory.py` line 444).
- **FR-8**: When the full map exceeds `max_tokens`, rank files by relevance to the current prompt/task using keyword overlap (file names, class names, function names vs. prompt terms extracted as words >= 3 chars).
- **FR-9**: Always include files directly referenced in the user's prompt (exact path match or basename match).
- **FR-10**: Always include a "structure overview" header (~500 tokens) showing the directory tree with file counts, regardless of total budget.
- **FR-11**: Apply a file count cap (default 2000 files) before parsing to bound CPU cost on large repos. Log a warning when the cap is hit.

### Configuration

- **FR-12**: Add a `RepoMapConfig` dataclass to `config.py` with:
  - `enabled: bool` (default `True`)
  - `max_tokens: int` (default `4000`)
  - `max_files: int` (default `2000`)
  - `include_patterns: list[str]` (default `[]` — empty means include all)
  - `exclude_patterns: list[str]` (default `[]`)
- **FR-13**: Add `repo_map: RepoMapConfig` field to `ColonyConfig` dataclass.
- **FR-14**: Parse the `repo_map` section in `load_config()` and serialize it in `save_config()`.

### Pipeline Integration

- **FR-15**: Generate the repo map once in the orchestrator's `_run_pipeline()` method, before the first phase, and pass it through to all prompt-building functions.
- **FR-16**: Inject the repo map programmatically in `_format_base()` (or a sibling helper), appending it after user_directions and before phase-specific templates. Follow the same pattern as `_inject_memory_block()`.
- **FR-17**: Skip injection when `config.repo_map.enabled` is `False`.
- **FR-18**: The repo map block should be formatted as:
  ```
  ## Repository Structure

  <repo map content here>
  ```

### CLI Command

- **FR-19**: Add a `colonyos map` CLI command that:
  - Loads config from `.colonyos/config.yaml`
  - Generates the repo map for the current repository
  - Prints it to stdout as plain text
  - Accepts optional `--max-tokens` override
  - Accepts optional `--prompt` text to demonstrate relevance-based truncation

## Non-Goals

- **No new dependencies**: No `tiktoken`, no tree-sitter, no external parsers
- **No persistent caching across runs**: Per-run in-memory caching only. Persistent caching adds invalidation complexity (branch switches, rebases, worktrees) for marginal gain. Can be added in a follow-up if profiling shows need.
- **No deep JS/TS parsing**: Regex extraction of top-level exports is sufficient. Nested class methods in JS/TS are not extracted (agents can `Read` files for detail).
- **No `--format` options on CLI**: Plain text only. JSON/YAML output can be added later if requested.
- **No per-phase customization**: The same repo map is injected into all phases. Per-phase filtering can be a follow-up.
- **No file content extraction**: The map contains structure (signatures, names) only, never file contents.

## Technical Considerations

### Existing Patterns to Follow

| Pattern | Location | How We Follow It |
|---|---|---|
| Context injection | `_inject_memory_block()` in `orchestrator.py:190` | Same append-to-system-prompt pattern |
| Token estimation | `memory.py:444` (`max_chars = max_tokens * 4`) | Identical heuristic |
| Config dataclass | `MemoryConfig`, `DaemonConfig` in `config.py` | Same dataclass pattern |
| Config parsing | `_parse_memory_config()` in `config.py` | Same `_parse_repo_map_config()` pattern |
| CLI commands | `doctor`, `stats` in `cli.py` | Same Click command pattern |
| Subprocess calls | `_get_current_branch()` in `orchestrator.py:210` | Same `subprocess.run` with timeout |
| Keyword extraction | `load_memory_for_injection()` in `memory.py:428` | Same `words >= 3 chars` approach |

### Key Files to Modify

- `src/colonyos/config.py` — Add `RepoMapConfig` dataclass and parsing
- `src/colonyos/orchestrator.py` — Generate map, inject into prompts
- `src/colonyos/cli.py` — Add `map` command

### Key Files to Create

- `src/colonyos/repo_map.py` — Core module (map generation, parsing, truncation)
- `tests/test_repo_map.py` — Comprehensive tests

### Performance Considerations

- `git ls-files` is fast (< 100ms for most repos)
- Python `ast.parse()` is fast for individual files but should be bounded by the file count cap
- The file count cap (FR-11) ensures we never parse more than 2000 files regardless of repo size
- For ColonyOS itself (~40 Python files), generation should complete in < 1 second

### Interaction with Other Context Injections

The system prompt is composed in layers. With repo map, the order becomes:
1. `_format_base(config)` — base instructions + user_directions
2. **Repo map** — structural context (new, ~4000 tokens)
3. Phase-specific template — plan.md, implement.md, etc.
4. Learnings — historical lessons (~500-1000 tokens)
5. Memory — relevant memories (~1500 tokens)

Total additional context budget: ~4000 tokens. This is acceptable given Claude's 200k context window and the structural value provided.

## Persona Synthesis

### Areas of Unanimous Agreement (7/7)

| Decision | Rationale |
|---|---|
| Use `git ls-files` not custom gitignore parser | Already used in codebase; handles all edge cases correctly |
| Use `chars / 4` for token estimation | Existing convention in `memory.py`; consistency > precision |
| Inject programmatically, not via template placeholders | Avoids touching 20+ `.md` files; prevents `KeyError` on `{` in signatures; matches `_inject_memory_block()` pattern |
| Standalone keyword intersection, not FTS5 | Repo map is a static artifact, not a growing collection of entries; avoids coupling to MemoryStore |
| Plain text CLI output only | No existing `--format` flags in CLI; YAGNI |
| Exclude sensitive file patterns by default | Even file names can leak infrastructure info |
| Repo map injected first, before memory/learnings | Most static context comes first; establishes spatial orientation |

### Areas of Tension

| Topic | Camp A | Camp B | Resolution |
|---|---|---|---|
| **Caching** | Persist in `.colonyos/` (Jobs, Ive, Karpathy, Linus) | Per-run only (YC, Systems Eng, Security) | **Per-run only** — invalidation complexity (worktrees, branch switches) and security risk (cache poisoning) outweigh the marginal performance gain |
| **JS/TS method depth** | Top-level exports only (YC, Jobs, Security, Karpathy) | Include class methods one level deep (Ive, Linus, Systems Eng) | **Top-level exports only for V1** — token budget is precious; agents can `Read` files for detail |
| **File count cap default** | 500 (Jobs) / 2000 (YC, Linus, Systems Eng) / 5000 (Security) | Token budget alone sufficient | **2000 files** — balances coverage and performance; configurable for monorepos |

## Success Metrics

1. **Reduction in exploratory tool calls**: Measure average tool calls in the first 30 seconds of Plan and Implement phases before vs. after repo map injection
2. **File reference accuracy**: Track how often agents reference files that actually exist (expect improvement from ~85% to ~95%)
3. **Generation latency**: Repo map generation completes in < 2 seconds for repos under 2000 files
4. **Token budget compliance**: Generated maps never exceed `max_tokens` config value
5. **User adoption**: `repo_map.enabled` remains `True` (default) for > 90% of users after 30 days

## Open Questions

1. **Should the repo map include line counts per file?** Line counts give the agent a sense of file complexity but add ~2 tokens per file. Recommend: yes, include them.
2. **Should we add a `--watch` mode to `colonyos map` for live updates during development?** Defer to V2.
3. **Should the relevance ranking consider git blame recency (recently modified files rank higher)?** Interesting but adds complexity. Defer to V2.
4. **Should the parallel implement path generate per-task maps focused on that task's file scope?** Worth exploring but out of scope for V1.
