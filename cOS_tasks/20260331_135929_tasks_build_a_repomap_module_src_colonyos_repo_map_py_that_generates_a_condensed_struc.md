# Tasks: RepoMap Module

## Relevant Files

- `src/colonyos/repo_map.py` - **New file**. Core repo map module: file walking, AST/regex extraction, tree formatting, relevance ranking, truncation
- `tests/test_repo_map.py` - **New file**. Comprehensive tests for repo map generation, extraction, truncation, and relevance ranking
- `src/colonyos/config.py` - Add `RepoMapConfig` dataclass, `repo_map` field on `ColonyConfig`, parsing in `load_config()`, serialization in `save_config()`
- `src/colonyos/orchestrator.py` - Generate repo map at pipeline start, inject into system prompts via `_format_base()` or sibling helper
- `src/colonyos/cli.py` - Add `colonyos map` CLI command
- `tests/test_config.py` - Add tests for `RepoMapConfig` parsing, validation, and defaults
- `tests/test_cli.py` - Add tests for `colonyos map` CLI command
- `tests/test_orchestrator.py` - Add tests for repo map injection into phase prompts

## Tasks

- [x] 1.0 Add `RepoMapConfig` to configuration system
  depends_on: []
  - [x] 1.1 Write tests for `RepoMapConfig` parsing in `tests/test_config.py`: default values (`enabled=True`, `max_tokens=4000`, `max_files=2000`, empty `include_patterns`/`exclude_patterns`), custom values from YAML, validation (max_tokens > 0, max_files > 0)
  - [x] 1.2 Add `RepoMapConfig` dataclass to `src/colonyos/config.py` with fields: `enabled: bool = True`, `max_tokens: int = 4000`, `max_files: int = 2000`, `include_patterns: list[str]`, `exclude_patterns: list[str]`
  - [x] 1.3 Add `repo_map: RepoMapConfig` field to `ColonyConfig` dataclass
  - [x] 1.4 Add `_parse_repo_map_config()` function following the pattern of `_parse_memory_config()`
  - [x] 1.5 Wire `_parse_repo_map_config()` into `load_config()` and add `repo_map` serialization to `save_config()`

- [x] 2.0 Build core repo map generator — file walking and Python AST extraction
  depends_on: []
  - [x] 2.1 Write tests in `tests/test_repo_map.py` for: `get_tracked_files()` returning file list from `git ls-files`, sensitive file filtering (`.env`, `*credential*`, `*secret*`, `*.pem`, `*.key`), `include_patterns`/`exclude_patterns` glob filtering, file count cap behavior and warning logging
  - [x] 2.2 Write tests for Python extraction: module docstrings, class names with bases, method signatures (name + params), top-level function signatures, handling of syntax errors (graceful skip), handling of empty files
  - [x] 2.3 Implement `get_tracked_files(repo_root, config)` in `src/colonyos/repo_map.py`: call `git ls-files` with `subprocess.run(timeout=30)`, filter by sensitive denylist, apply include/exclude patterns via `fnmatch`, cap at `config.max_files` with warning log
  - [x] 2.4 Implement `extract_python_symbols(file_path)` using `ast.parse()`: return a structured list of symbols (classes with methods, functions, module docstring). Handle `SyntaxError` gracefully by returning empty result with a warning.
  - [x] 2.5 Define data structures: `FileSymbols` (path, symbols list, line_count), `Symbol` (name, kind: class/function/method, params, bases), `RepoMap` (files: list[FileSymbols], overview: str)

- [x] 3.0 Build JS/TS regex extraction and other-file handling
  depends_on: []
  - [x] 3.1 Write tests for JS/TS extraction: `export function foo()`, `export class Bar`, `export default`, `export const/let/var`, `export { named }`, TypeScript `export interface`, `export type`. Test with `.js`, `.jsx`, `.ts`, `.tsx` extensions.
  - [x] 3.2 Write tests for other-file handling: files like `.yaml`, `.md`, `.json` produce path + size only
  - [x] 3.3 Implement `extract_js_ts_symbols(file_path)` using regex patterns. Return list of `Symbol` objects for exported declarations. Handle file read errors gracefully.
  - [x] 3.4 Implement `extract_other_file_info(file_path)` returning path and file size in bytes.
  - [x] 3.5 Implement `extract_file_symbols(file_path)` dispatcher that routes to `extract_python_symbols`, `extract_js_ts_symbols`, or `extract_other_file_info` based on file extension.

- [x] 4.0 Build tree formatting, relevance ranking, and token-budget truncation
  depends_on: [2.0, 3.0]
  - [x] 4.1 Write tests for tree formatting: directory grouping, indentation, class/function display, line counts. Verify output matches expected format from FR-5.
  - [x] 4.2 Write tests for relevance ranking: files matching prompt keywords rank higher, exact path matches always included, basename matches always included. Test with various prompt texts.
  - [x] 4.3 Write tests for truncation: output never exceeds `max_tokens` (using `chars/4` estimation), structure overview always included (~500 tokens), files are dropped in reverse relevance order, edge cases (budget too small for overview, empty repo)
  - [x] 4.4 Implement `format_tree(files: list[FileSymbols])` that produces the tree-formatted text output grouped by directory
  - [x] 4.5 Implement `rank_by_relevance(files, prompt_text)` that scores files by keyword overlap (words >= 3 chars from prompt vs. file path + symbol names), returns sorted list. Files with exact path or basename matches get maximum score.
  - [x] 4.6 Implement `generate_overview(files)` that produces a compact directory tree with file counts (~500 tokens)
  - [x] 4.7 Implement `truncate_to_budget(overview, ranked_files, max_tokens)` that greedily adds files until the `chars/4` budget is exhausted. Overview is always included first.
  - [x] 4.8 Implement top-level `generate_repo_map(repo_root, config, prompt_text="")` function that orchestrates: `get_tracked_files` → `extract_file_symbols` (for each) → `rank_by_relevance` → `truncate_to_budget` → return formatted string

- [ ] 5.0 Integrate repo map into the orchestrator pipeline
  depends_on: [1.0, 4.0]
  - [ ] 5.1 Write tests in `tests/test_orchestrator.py` for: repo map injection into system prompt when `enabled=True`, no injection when `enabled=False`, repo map appears after user_directions and before phase template, prompt text passed for relevance ranking
  - [ ] 5.2 Add `_inject_repo_map()` helper function in `orchestrator.py` following the pattern of `_inject_memory_block()`: takes system prompt string + repo map string, appends with `## Repository Structure` header, returns modified system prompt
  - [ ] 5.3 Generate the repo map once in `_run_pipeline()` before the first phase. Store it as a local variable passed to prompt-building functions.
  - [ ] 5.4 Call `_inject_repo_map()` in `_format_base()` or at each prompt-building call site (whichever is cleaner), injecting after user_directions. Skip when `config.repo_map.enabled` is False.
  - [ ] 5.5 Pass the current task/feature description as `prompt_text` to `generate_repo_map()` so relevance ranking works against the actual user request

- [x] 6.0 Add `colonyos map` CLI command
  depends_on: [4.0]
  - [x] 6.1 Write tests in `tests/test_cli.py` for: `colonyos map` invocation produces output, `--max-tokens` overrides config value, `--prompt` text triggers relevance-based truncation, command fails gracefully outside a git repo
  - [x] 6.2 Implement `map` command in `cli.py` as `@app.command()` with options: `--max-tokens` (int, optional), `--prompt` (str, optional). Loads config, calls `generate_repo_map()`, prints to stdout via `click.echo()`.
  - [x] 6.3 Add help text and ensure `colonyos --help` lists the new `map` command

- [ ] 7.0 End-to-end verification and edge case hardening
  depends_on: [5.0, 6.0]
  - [ ] 7.1 Write an integration test that runs `generate_repo_map()` against the ColonyOS repo itself and verifies: output is valid text, token budget is respected, key files (config.py, orchestrator.py, cli.py) appear in the map, Python symbols are extracted correctly
  - [ ] 7.2 Test edge cases: empty repository (no tracked files), repo with only binary files, files with encoding errors (non-UTF-8), extremely small token budget (100 tokens), Python files with syntax errors
  - [ ] 7.3 Run the full test suite (`pytest tests/`) to verify zero regressions
  - [ ] 7.4 Manually run `colonyos map` on the ColonyOS repo and verify output quality
