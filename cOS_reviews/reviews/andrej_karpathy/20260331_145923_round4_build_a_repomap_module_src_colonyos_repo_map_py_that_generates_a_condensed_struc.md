# Review by Andrej Karpathy (Round 4)

---

## Review Complete — Andrej Karpathy, Round 4

**VERDICT: approve**

**FINDINGS:**
- **[src/colonyos/repo_map.py:rank_by_relevance]**: Scoring uses flat keyword overlap with tiered weights (path=10, symbol=5, exact_path=1000, basename=500) — deterministic and interpretable, correct choice over embeddings. Subtle gap: prompt keywords split on whitespace only, so `config.py` yields one token — but FR-9's exact basename match covers this.
- **[src/colonyos/repo_map.py:truncate_to_budget]**: Greedy packing calls `format_tree([fs])` per file inside the loop — O(n) string allocations. Negligible for 2000 files. Not a blocker.
- **[src/colonyos/repo_map.py:SENSITIVE_PATTERNS]**: `.env`, `.env.*`, `.env*` are redundant — `.env*` subsumes both others. Harmless, not blocking.
- **[src/colonyos/orchestrator.py:_inject_repo_map]**: Injection ordering is correct — repo map before memory block in every phase, matching PRD's prompt layering spec.
- **[src/colonyos/orchestrator.py:_run_pipeline]**: Single `generate_repo_map` call reused across all 8 phases — correct, no per-phase regeneration needed.
- **[src/colonyos/orchestrator.py:run_ceo]**: CEO generates its own map independently since it's outside `_run_pipeline`. Correct.
- **[src/colonyos/cli.py:map]**: `dataclass_replace` is clean and idiomatic. `--prompt` flag is a nice debugging affordance.
- **[tests/test_repo_map.py]**: 95 tests using real `git init` repos, not mocks. Right testing strategy.

**SYNTHESIS:**
This implementation nails the core insight: every agent phase burning 3-8 tool calls on exploration is a compounding tax on latency and context window. A deterministic ~4000 token structural injection is the optimal fix. The design choices are consistently correct: `ast.parse()` for Python (exact, no deps), regex for JS/TS (good enough for exports), `chars/4` token estimation (matches existing convention), keyword overlap for ranking (deterministic, no stochastic behavior from embeddings), greedy truncation with relevance ordering. The `_MAX_PARSE_SIZE` guard prevents OOM. The fail-closed `try/except` in the orchestrator means a repo map bug can never crash a pipeline. All 660 tests pass. Prior cosmetic fixes are resolved. Ship it.
