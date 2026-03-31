# Review by Andrej Karpathy (Round 5)

All 660 tests pass. Let me now write the review artifact.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/repo_map.py:SENSITIVE_PATTERNS]: `.env`, `.env.*`, `.env*` — the third pattern subsumes the first two. Harmless redundancy, zero behavioral impact.
- [src/colonyos/repo_map.py:truncate_to_budget]: Calls `format_tree([fs])` per file in the greedy loop — O(n) string allocations. Correct tradeoff for V1 at 2000-file cap; not a perf bottleneck.
- [src/colonyos/repo_map.py:rank_by_relevance]: Tiered weights (path=10, symbol=5, exact_path=1000, basename=500) are deterministic and interpretable. Right call over embeddings — prompts are programs, not vibes. The scoring function has no stochastic behavior, which means the map is reproducible across runs given the same inputs. This is essential for debugging.
- [src/colonyos/repo_map.py:_format_args]: Strips `self`/`cls` — good UX, reduces token waste on information the agent already knows.
- [src/colonyos/repo_map.py:extract_python_symbols]: `ast.parse()` for structural extraction only, never `exec()`/`eval()`. This is the right boundary — we parse the program but never execute it.
- [src/colonyos/repo_map.py:extract_js_ts_symbols]: Regex-only for JS/TS exports. Correct V1 decision — tree-sitter would add a native dependency for marginal gain on a secondary language. The regexes are anchored to line starts (`^export`), avoiding false matches on comments or strings in most real-world code.
- [src/colonyos/orchestrator.py:_run_pipeline]: Single `generate_repo_map()` call reused across all 8 phases — correct. No per-phase regeneration. The map is a static structural artifact that doesn't change during a run.
- [src/colonyos/orchestrator.py:_inject_repo_map]: Fail-closed: wrapped in `try/except Exception` in both `_run_pipeline()` and `run_ceo()`. Map failure logs a warning and continues with empty map. The pipeline never crashes due to a map error. This is the correct autonomy boundary.
- [src/colonyos/orchestrator.py]: Injection ordering: repo map → memory → phase template. Most static context first, most dynamic last. This matches how attention works — the model attends more strongly to recent tokens for task-specific info while using earlier structural context for orientation.
- [src/colonyos/cli.py:map]: `dataclass_replace` for `--max-tokens` override is clean. `--prompt` flag is excellent for debugging relevance ranking without running a full pipeline. This is the kind of developer affordance that separates good infra from great infra.
- [src/colonyos/config.py:_parse_repo_map_config]: Validates `max_tokens >= 1` and `max_files >= 1`. Follows exact same pattern as `_parse_memory_config`. Convention consistency is high.
- [tests/test_repo_map.py]: 95 tests using real `git init` repos in tmp_path, not mocks. This is the right testing strategy — you're testing the actual behavior, not your assumptions about the behavior. The mock is only used for error paths (timeout, OSError) where real git failures are hard to induce.

SYNTHESIS:
This implementation solves exactly the right problem in exactly the right way. Every agent phase burning 3-8 tool calls on `Glob`/`Grep`/`Read` just to figure out what exists is a compounding tax on both latency and context window. A deterministic ~4000 token structural injection eliminates that cold start. The key architectural decisions are all correct: `ast.parse()` for Python (exact, zero deps), regex for JS/TS (good enough for exports, avoids native deps), `chars/4` token estimation (matches existing convention — consistency beats precision), keyword overlap for ranking (deterministic, reproducible, no stochastic embedding behavior), greedy truncation (simple, debuggable, the 5-10% budget slack is the correct tradeoff vs. knapsack complexity). The code treats prompts as programs — the structured output format, the tiered scoring weights, the reproducible ranking — all evidence of prompt engineering rigor. The fail-closed error handling ensures the pipeline degrades gracefully if map generation fails, which is the right autonomy boundary for a context injection system. 660 tests passing, zero regressions. Ship it.