---

## Review Complete — Andrej Karpathy, Round 4

VERDICT: approve

FINDINGS:
- [src/colonyos/repo_map.py:rank_by_relevance]: Scoring function uses flat keyword overlap with tiered weights (path=10, symbol=5, exact_path=1000, basename=500) — deterministic and interpretable, correct choice over embeddings. One subtle gap: prompt keywords are split on whitespace only, so `config.py` in a prompt yields `"config.py"` as one token that won't match path parts split on `.` — but FR-9's exact basename match (`basename in prompt_lower`) covers this case, so it's fine in practice.
- [src/colonyos/repo_map.py:truncate_to_budget]: Greedy packing calls `format_tree([fs])` per file inside the loop — O(n) string allocations. For 2000 files this is negligible (<10ms), but if max_files is ever raised significantly, a single `format_tree` pass with incremental char counting would be more efficient. Not a blocker for V1.
- [src/colonyos/repo_map.py:_format_args]: Correctly strips `self`/`cls` from method signatures — good UX decision, saves ~5 tokens per method and the agent doesn't need them.
- [src/colonyos/repo_map.py:SENSITIVE_PATTERNS]: `.env`, `.env.*`, `.env*` — the `.env` and `.env*` patterns are redundant (`.env*` subsumes `.env`), and `.env.*` is also subsumed by `.env*`. Harmless but three patterns where one suffices. Not blocking.
- [src/colonyos/orchestrator.py:_inject_repo_map]: Injection ordering is correct — repo map goes before memory block in every phase, establishing spatial context before semantic context. This matches the prompt layering order in the PRD (Section: Interaction with Other Context Injections).
- [src/colonyos/orchestrator.py:_run_pipeline]: `generate_repo_map` is called once with the user's prompt for relevance ranking, then the same text is reused across all 8 phases. This is the right call — generating per-phase would add latency and the structural overview doesn't need to change between plan/implement/review.
- [src/colonyos/orchestrator.py:run_ceo]: CEO phase generates its own repo map (no prompt text for ranking) since it runs outside `_run_pipeline`. Correct — CEO is a standalone entry point.
- [src/colonyos/cli.py:map]: `dataclass_replace` for max_tokens override — clean, idiomatic. The `--prompt` flag for relevance demo is a nice debugging affordance.
- [tests/test_repo_map.py]: 95 tests using real `git init` repos, not mocks of `git ls-files`. This is the right testing strategy — mocking subprocess for a 30ms command buys nothing and hides real integration bugs.
- [src/colonyos/config.py:save_config]: Only serializes `repo_map` when values differ from defaults — follows the existing sparse-config pattern. Correct.

SYNTHESIS:
This implementation nails the core insight: every agent phase burning 3-8 tool calls on `Glob`/`Grep` exploration is a compounding tax on latency and context window. A deterministic ~4000 token structural injection is the optimal fix — it's the cheapest possible way to give the model spatial awareness. The design choices are consistently correct: `ast.parse()` for Python (exact, no dependencies), regex for JS/TS (good enough for exports, avoids tree-sitter), `chars/4` token estimation (matches existing convention), keyword overlap for ranking (deterministic, no stochastic behavior from embeddings), greedy truncation with relevance ordering (ensures highest-value files always fit). The `_MAX_PARSE_SIZE` guard prevents OOM on generated megafiles. The fail-closed `try/except` in the orchestrator means a repo map bug can never crash a pipeline run. All 660 tests pass including 95 repo map tests against real git repos. The two prior rounds of cosmetic fixes (duplicate comment, `dataclasses.replace()`) are resolved. This is ready to ship.

Review saved to `cOS_reviews/reviews/andrej_karpathy/20260331_round4_build_a_repomap_module.md`.
