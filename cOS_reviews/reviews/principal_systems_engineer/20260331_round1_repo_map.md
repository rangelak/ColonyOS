# Review: RepoMap Module — Principal Systems Engineer

**Branch**: `colonyos/build_a_repomap_module_src_colonyos_repo_map_py_that_generates_a_condensed_struc`
**PRD**: `cOS_prds/20260331_135929_prd_build_a_repomap_module_src_colonyos_repo_map_py_that_generates_a_condensed_struc.md`
**Round**: 1

## Test Results

- `tests/test_repo_map.py`: **92 passed** ✅
- `tests/test_config.py`: **141 passed** ✅
- `tests/test_cli.py`: **196 passed** ✅
- `tests/test_orchestrator.py`: **222 passed** ✅

## Functional Requirements Checklist

| FR | Status | Notes |
|----|--------|-------|
| FR-1: git ls-files with timeout | ✅ | `subprocess.run(timeout=30)`, graceful error handling for timeout/OSError/nonzero exit |
| FR-2: Python AST extraction | ✅ | Module docstrings, classes with bases, methods, top-level functions |
| FR-3: JS/TS regex extraction | ✅ | 6 regex patterns covering export function/class/const/named/{}/interface/type |
| FR-4: Other files path + size | ✅ | `extract_other_file_info()` |
| FR-5: Tree-formatted output | ✅ | Directory grouping, indentation, line counts |
| FR-6: Sensitive file exclusion | ✅ | Hardcoded denylist + config exclude_patterns |
| FR-7: chars/4 token estimation | ✅ | `max_chars = max_tokens * 4` in `truncate_to_budget()` |
| FR-8: Relevance ranking by keyword overlap | ✅ | Words >= 3 chars, path + symbol name matching |
| FR-9: Exact path/basename match priority | ✅ | 1000/500 score bonuses |
| FR-10: Structure overview always included | ✅ | Overview added first in `truncate_to_budget()` |
| FR-11: File count cap (default 2000) | ✅ | `max_files` check with warning log |
| FR-12: RepoMapConfig dataclass | ✅ | All 5 fields with correct defaults |
| FR-13: repo_map field on ColonyConfig | ✅ | |
| FR-14: load_config/save_config support | ✅ | `_parse_repo_map_config()`, save-when-different pattern |
| FR-15: Generate once in _run_pipeline | ✅ | Generated before first phase, stored as local |
| FR-16: Programmatic injection | ✅ | `_inject_repo_map()` follows `_inject_memory_block()` pattern |
| FR-17: Skip when disabled | ✅ | `if config.repo_map.enabled` guard in `_run_pipeline()` |
| FR-18: `## Repository Structure` header | ✅ | |
| FR-19: `colonyos map` CLI command | ✅ | `--max-tokens` and `--prompt` options |

**All 19 functional requirements implemented.** All 7 task groups (1.0–7.0) marked complete.

## Findings

### request-changes (1)

1. **[src/colonyos/orchestrator.py: L4718-4735]**: Deliver and CEO phases do NOT receive repo map injection. The PRD states FR-15: "pass it through to **all** prompt-building functions" and FR-16 says inject it into all phases. The repo map is injected into Plan (L4345), Implement (L4468), Review (L4547), and Fix (L4631), but the Deliver phase (`_execute_deliver_phase()` at L4718) and the CEO phase (`run_ceo()`) have no `_inject_repo_map()` call. The deliver phase creates its system prompt at L4719-4723 but never injects the repo map. This means the agent doing the actual PR creation has no structural context — arguably the phase where file references matter most (commit messages, PR descriptions).

### Non-blocking (4)

2. **[src/colonyos/orchestrator.py: L776]**: `_run_sequential_implement()` accepts `repo_map_text: str = ""` as a new parameter but I cannot find any call site that actually passes it. The parameter was added to the signature but appears unused — the sequential implement path gets the repo map injected at the call site in `_run_pipeline()` (L4468) instead, which is correct, so this unused parameter is dead code.

3. **[src/colonyos/repo_map.py: L124]**: The `max_files is not None` guard is correct and avoids the falsy-zero bug pattern identified in prior reviews. However, `config.max_files` defaults to `2000` (an int, never None) and `_parse_repo_map_config()` validates `max_files >= 1`. So the `is not None` check is defensive-correct but unreachable in practice. This is fine — better safe than sorry.

4. **[src/colonyos/repo_map.py: L469-471]**: In `generate_overview()`, `Counter` import is inside the function body. Same for `OrderedDict` in `format_tree()` (L399). These are stdlib so the overhead is negligible, but it's inconsistent with the top-of-file imports pattern used elsewhere in the module. Non-blocking style nit.

5. **[src/colonyos/repo_map.py: L585-592]**: `truncate_to_budget()` breaks on the first file that doesn't fit, even if a smaller file further down the ranked list would fit. This is a greedy-first-fit approach, which is correct for ranked order (most relevant files first), but means the budget may be underutilized by a few hundred tokens. Acceptable for V1 — a knapsack optimization would add complexity for marginal gain.
