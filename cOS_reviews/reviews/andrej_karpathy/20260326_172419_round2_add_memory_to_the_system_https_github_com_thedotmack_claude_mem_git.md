# Review by Andrej Karpathy (Round 2)

Here's my review as Andrej Karpathy:

---

## VERDICT: request-changes

### Key Findings

1. **Memory store `close()` is fragile** — There are 5+ manual `if memory_store is not None: memory_store.close()` calls scattered across every early-return path in `_run_pipeline()`. This should use `try/finally` or the context manager protocol. Any future early-return will silently leak the connection.

2. **`prompt_text` parameter is dead** — `load_memory_for_injection()` accepts `prompt_text` but never uses it for keyword relevance. The PRD specifies "keyword overlap with the current prompt/task" as a retrieval signal. Either use it (even a simple `split()` → FTS query) or document it as reserved-for-future.

3. **No review-phase memory capture** — `_capture_phase_memory()` is wired into plan/implement/fix but never called after review phases. The `review_pattern` category will remain perpetually empty.

4. **No learn-phase memory capture (PRD FR-2)** — The PRD explicitly requires "Post-learn capture: Enhance the existing learn phase to write memories alongside the learnings ledger." This is missing.

5. **Pruning is global FIFO, not per-category** — The PRD specifies per-category FIFO. A burst of codebase memories could evict all failure memories.

6. **Unrelated TUI style refactor** — `tui/styles.py` changes should be a separate commit/branch.

7. **Silent `except Exception: pass`** in CLI direct-agent memory injection — should at least log a warning.

### What's done well

- SQLite+FTS5 with zero dependencies is the correct retrieval approach at this scale
- `sanitize_ci_logs()` is actually stricter than what the PRD asked for — good call
- Orchestrator-only write model prevents the most dangerous failure mode (prompt injection poisoning memory)
- Token budget enforcement with greedy packing is pragmatic and honest
- Strong test coverage (71 tests)

### SYNTHESIS

The core memory architecture is sound — the retrieval design, security model, and token budgets are all correct. But there are two PRD compliance gaps (missing learn-phase and review-phase capture hooks) that will leave major memory categories unpopulated, and the resource management pattern is fragile enough to cause real leaks as the codebase evolves. Fix the `try/finally` resource management, wire up the missing capture hooks, and this is ready to ship.