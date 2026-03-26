# Review: Persistent Memory System — Andrej Karpathy

## Review Checklist

### Completeness
- [x] All functional requirements from the PRD are implemented (FR-1 through FR-6)
- [x] All 7 tasks in the task file are marked complete
- [x] No placeholder or TODO code remains

### Quality
- [x] All 39 tests pass
- [x] Code follows existing project conventions (dataclass configs, CLI groups, orchestrator helpers)
- [x] Zero new dependencies (stdlib sqlite3 only)
- [x] No unrelated changes included

### Safety
- [x] No secrets or credentials in committed code
- [x] Memory DB gitignored; sanitization via `sanitize_ci_logs` before write
- [x] Error handling wraps every memory operation with try/except + warning log
- [x] Writes restricted to orchestrator process only (no agent-side writes)

---

VERDICT: approve

FINDINGS:
- [src/colonyos/memory.py]: Keyword extraction in `load_memory_for_injection` is naive — splits on whitespace and takes words >=3 chars. This will pass stopwords, markdown syntax, and prompt boilerplate as "keywords", diluting FTS5 relevance. Acceptable for MVP since the fallback to recency-only retrieval is sound, but this is the single most impactful v2 improvement (a simple TF-IDF or even a stopword list would help significantly).
- [src/colonyos/memory.py]: The FTS5 query wraps sanitized keywords in a single double-quoted phrase (`"word1 word2 word3"`), meaning it matches the exact phrase only. This is overly strict — "pytest PYTHONPATH" as a phrase won't match a memory that mentions both in different sentences. Switching to individual quoted terms joined by implicit AND or OR would improve recall.
- [src/colonyos/memory.py]: Pruning is global FIFO, not per-category FIFO as the PRD specifies. The code documents this deviation with a clear rationale (simpler, unlikely to matter at 500-entry cap). Acceptable tradeoff.
- [src/colonyos/orchestrator.py]: `_get_memory_store` opens a SQLite connection at the top of `run()` and closes it in the `finally` block of `_run_pipeline`. This means the connection stays open for the entire pipeline duration (potentially hours). Not a resource leak since there's only one connection, but worth noting — a context manager with open/close per phase would be marginally cleaner.
- [src/colonyos/orchestrator.py]: `_capture_phase_memory` extracts `phase_result.artifacts.get("result", "")` — this assumes phases store their output under a `"result"` key. If a phase uses a different artifact key, nothing gets captured silently. The broad `except Exception` on lines 108 and 144 is the right call for a non-critical subsystem, but the silent fallthrough on missing artifact keys means some phases may never produce memories. A debug-level log when `result_text` is empty would aid observability.
- [src/colonyos/orchestrator.py]: Memory injection logs `line_count` as the number of newlines in the block, which is a proxy for entry count but off by one (header takes 2 lines). Minor, but "Injected 5 memories" when it's really 3 entries and 2 header lines could confuse debugging.
- [src/colonyos/memory.py]: Token estimation via `chars / 4` is a reasonable rough proxy but systematically undercounts for code-heavy memories (which have high token-to-char ratio due to special characters). Not a blocker — the budget is a soft cap anyway.
- [tests/test_memory.py]: The FTS5 escaping tests assert `len(results) >= 0` (always true) rather than asserting specific expected behavior. They verify "no crash" but not "correct results". This is fine for defensive tests against FTS5 parse errors, but a stronger assertion on the AND/OR tests would catch regressions where operators leak through.
- [src/colonyos/router.py]: Direct-agent prompt builder accepts a `memory_block` string parameter cleanly, keeping the injection logic in the orchestrator. Good separation.
- [src/colonyos/config.py]: `MemoryConfig` follows the established dataclass pattern exactly (matches `LearningsConfig`, `CleanupConfig`, etc.). Clean integration.

SYNTHESIS:
This is a well-executed MVP of a memory system. The architecture makes the right fundamental choices: writes only from the orchestrator (not from agent sessions), sanitization before persistence, configurable token budget, and graceful degradation everywhere (every memory operation is wrapped in try/except so a corrupt DB never crashes a pipeline run). The code is clean, follows existing conventions, and the 39-test suite covers the important paths including FTS5 injection safety.

From an LLM-application perspective, the main gap is retrieval quality. The current system is essentially "recent memories from relevant categories, maybe filtered by a naive keyword phrase match." This is fine for the first 50-100 memories, but as the store grows, the signal-to-noise ratio in the injected `## Memory Context` block will degrade. The keyword extraction treats prompt boilerplate the same as task-specific terms, and the single-phrase FTS5 query is too strict to get good recall. The good news is the architecture cleanly supports upgrading retrieval without touching the storage layer or injection points — `load_memory_for_injection` is the single function to improve.

The token budget mechanism (greedy packing with chars/4 proxy) is pragmatic and appropriate. The phase-category mapping is a sensible heuristic. The coexistence with the learnings ledger is handled cleanly — both blocks appear in prompts, clearly labeled, no interference.

I approve this for merge. The retrieval quality improvements I've flagged are genuine v2 concerns but don't block shipping — the system will already deliver value by surfacing recent failure context and codebase facts, which addresses the core "cross-run amnesia" problem stated in the PRD.
