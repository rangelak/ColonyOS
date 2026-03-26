# Review: Add Persistent Memory to ColonyOS — Andrej Karpathy

## Checklist

### Completeness
- [x] All functional requirements from the PRD are implemented
- [x] All tasks in the task file are marked complete
- [x] No placeholder or TODO code remains

### Quality
- [x] All tests pass (71 passed in 2.28s)
- [ ] No linter errors introduced — not verified but code follows existing patterns
- [x] Code follows existing project conventions
- [x] No unnecessary dependencies added (sqlite3 stdlib only)
- [x] No unrelated changes included — **minor exception**: TUI styles.py refactor

### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive database operations without safeguards (clear requires --yes)
- [x] Error handling is present for failure cases

## Detailed Findings

### What's done well

**The retrieval design is correct for the scale.** Keyword + recency via FTS5 is the right call at hundreds of entries. Vector search would be premature complexity for zero recall benefit at this corpus size. The `PHASE_CATEGORY_MAP` acts as a lightweight "routing" mechanism to control what the model sees — this is essentially a hand-coded attention mask over memory categories, which is the right level of structure for v1.

**Token budget enforcement is solid.** Greedy packing with chars÷4 proxy is honest about its approximation and good enough. The `max_tokens=1500` default is sensible — roughly 10-15 memory bullets, enough signal without drowning the prompt.

**Security model is sound.** Writes only happen in the orchestrator process, never from agent sessions. Content passes through `sanitize_ci_logs()` (which is a superset of `sanitize_untrusted_content()` — it does XML stripping AND secret redaction), preventing prompt injection persistence. The PRD asked for `sanitize_untrusted_content()` but the implementation correctly uses the stricter function.

**Context-manager protocol on MemoryStore** is clean and prevents connection leaks.

### Issues

1. **[src/colonyos/orchestrator.py]: Memory store `close()` is scattered and fragile.** There are 5+ manual `if memory_store is not None: memory_store.close()` calls at every early-return point in `_run_pipeline()`. This is a classic resource-leak pattern — any new early-return path added in the future will silently skip cleanup. The store should be managed via `try/finally` or the existing context manager protocol, not manual close calls at every exit. This is the most serious structural issue.

2. **[src/colonyos/memory.py]: `load_memory_for_injection()` ignores `prompt_text` entirely.** The function accepts `prompt_text` as a parameter (ostensibly for keyword-based relevance scoring from the current task), but it's never used — memories are retrieved purely by category + recency. The PRD specifies "keyword overlap with the current prompt/task" as a retrieval signal. While I understand this is punted to v2, the dead parameter creates a false promise in the API. It should either be used for keyword extraction (even a simple `prompt_text.split()` → FTS query) or the parameter should be documented as reserved-for-future.

3. **[src/colonyos/orchestrator.py]: No memory capture for review phases.** The `_capture_phase_memory()` call is wired into plan, implement, and fix phases, but the review loop in the orchestrator doesn't capture review-phase results to memory. The `phase_category_map` inside `_capture_phase_memory` includes `"review"` → `REVIEW_PATTERN`, but I don't see the capture hook actually called after review phases complete. This means the `review_pattern` category will remain perpetually empty unless populated manually.

4. **[src/colonyos/memory.py]: Pruning is FIFO globally, not per-category as PRD specifies.** The PRD says "pruning oldest entries on overflow (FIFO by category)" but the implementation prunes globally by `created_at`. This means a burst of codebase memories could evict all failure memories. Per-category FIFO would be more robust for preserving diverse memory types.

5. **[src/colonyos/orchestrator.py]: No memory capture for learn phase (FR-2).** The PRD's FR-2 explicitly requires "Post-learn capture: Enhance the existing learn phase to write memories alongside the learnings ledger." This isn't implemented — there's no capture hook in the learn phase flow.

6. **[src/colonyos/tui/styles.py]: Unrelated TUI style refactor included.** The styles.py changes (hex colors → named Textual tokens, layout adjustments) are unrelated to memory. These should be in a separate commit/PR to keep the diff reviewable and bisectable.

7. **[src/colonyos/cli.py]: Memory injection in `_run_direct_agent` uses bare `except Exception: pass`.** Silent exception swallowing makes debugging impossible. At minimum, log the exception. The orchestrator helpers correctly log warnings on failure — this call site should do the same.

## Assessment

VERDICT: request-changes

FINDINGS:
- [src/colonyos/orchestrator.py]: Memory store close() is manually scattered across 5+ exit points instead of using try/finally — fragile, will leak on future code changes
- [src/colonyos/memory.py]: load_memory_for_injection() accepts prompt_text but never uses it for keyword relevance — dead parameter violates PRD's "keyword overlap" retrieval signal
- [src/colonyos/orchestrator.py]: No _capture_phase_memory() call after review phases — review_pattern category will stay empty
- [src/colonyos/memory.py]: Pruning is global FIFO, not per-category FIFO as PRD specifies
- [src/colonyos/orchestrator.py]: No memory capture for learn phase (PRD FR-2 "Post-learn capture")
- [src/colonyos/tui/styles.py]: Unrelated TUI style refactor included in memory feature branch
- [src/colonyos/cli.py]: Silent `except Exception: pass` in direct-agent memory injection — should log warning

SYNTHESIS:
The core memory architecture is well-designed — SQLite+FTS5, zero deps, sane token budgets, proper sanitization, and the orchestrator-only write model prevents the most dangerous failure mode (prompt injection poisoning the memory store). The test coverage is strong with 71 tests covering CRUD, FTS, cap enforcement, config, and CLI. However, there are two PRD compliance gaps (no learn-phase capture, no review-phase capture) that will leave significant categories of memory unpopulated, and the resource management pattern for the store connection is fragile enough to cause real issues as the codebase evolves. The unrelated TUI changes should be split out. Fix the try/finally resource management, wire up the missing capture hooks for review and learn phases, and this is ready to ship.
