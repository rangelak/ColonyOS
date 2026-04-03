# Review by Linus Torvalds (Round 3)

Now I have enough to write the review. Let me write the structured output.

---

## Review by Linus Torvalds

I've gone through the full diff — memory.py, config.py, cli.py, orchestrator.py, router.py, init.py, and the test files. All 2058 tests pass. Let me cut through the bullshit.

### What's Good

The core data structure in `memory.py` is clean. A single SQLite file with FTS5, context manager protocol, proper schema versioning, FIFO pruning — this is the obvious, boring implementation, which is exactly what it should be. The `MemoryStore` class does one thing and does it well. The FTS5 keyword sanitization is thoughtful (`_sanitize_fts_keyword` handles boolean operators and special characters). The separation between storage and injection logic (`load_memory_for_injection`) is correct. Config follows existing patterns exactly. CLI commands are clean Click groups. Tests are comprehensive — 78 dedicated memory tests plus full integration coverage.

### What's Bad

**The orchestrator.py reindentation is the worst kind of diff.** The entire `_run_pipeline` function body was wrapped in a `try/finally` block to close the memory store, which means the diff shows ~360 lines of removed code and ~375 lines of added code — but the actual *logic* changes are about 15 lines of `_inject_memory_block()` and `_capture_phase_memory()` calls sprinkled in. This is a nightmare to review. The `memory_store` should have been opened and closed at the `run()` call site (which it *already is* — `_get_memory_store` is called in `run()`) with the try/finally wrapping just the `_run_pipeline` call in `run()`, not re-indenting the entire function body.

**The TUI styles.py changes are completely unrelated.** Changing color constants from hex values to named Textual color strings (`"#55eeff"` → `"cyan"`, `"#f0a030"` → `"green"`) has nothing to do with memory. This should have been a separate commit or excluded entirely. Same for the `tests/tui/conftest.py` and `tests/tui/test_setup.py` changes.

**Global FIFO pruning deviates from the PRD's per-category FIFO.** The code acknowledges this in a comment, but it means a burst of failure memories could evict all codebase memories. At 500 entries this is unlikely, but it's still a spec deviation.

**The `_get_memory_store` in `run()` creates the store, but `_run_pipeline` closes it in a `finally` block.** This split ownership is messy — whoever opens a resource should close it. The `run()` function should own both open and close, or `_run_pipeline` should own both.

### Minor Issues

- `sanitize_ci_logs` is used instead of the PRD-specified `sanitize_untrusted_content`. The docstring explains this is intentionally stricter, which is fine, but it's worth noting.
- The keyword extraction in `load_memory_for_injection` is extremely naive — split on whitespace, take first 8 words ≥3 chars. Words like "the", "and", "for" will pollute the FTS query. Functional but dumb. Good enough for MVP.
- The `prompt_text` parameter in `load_memory_for_injection` is labeled "reserved for future keyword-based relevance" in the docstring but is actually used for keyword extraction. Stale docstring.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/orchestrator.py]: The try/finally re-indentation of _run_pipeline creates a massive, misleading diff (~360 lines changed) for what is ~15 lines of actual logic. Resource ownership split between run() and _run_pipeline is messy.
- [src/colonyos/tui/styles.py]: Completely unrelated color constant changes bundled into this branch. Should be a separate commit.
- [tests/tui/conftest.py, tests/tui/test_setup.py]: Unrelated TUI test changes included.
- [src/colonyos/memory.py]: Global FIFO pruning deviates from PRD's per-category FIFO spec (acknowledged in comment, acceptable for MVP).
- [src/colonyos/memory.py]: load_memory_for_injection docstring says prompt_text is "reserved for future" but it's actively used for keyword extraction.
- [src/colonyos/memory.py]: sanitize_ci_logs used instead of PRD-specified sanitize_untrusted_content (intentionally stricter — acceptable).

SYNTHESIS:
The implementation is functionally complete and correct. All PRD requirements are covered — storage layer with FTS5, capture hooks at phase boundaries, injection into prompts, config integration, CLI commands, learnings coexistence, gitignore. All 2058 tests pass. The code is well-structured and follows existing project patterns. My main gripe is the orchestrator diff — wrapping 360 lines in a try/finally instead of handling resource cleanup at the call site turned a clean 15-line integration into an unreadable sea of indentation changes. The unrelated TUI style changes are sloppy housekeeping that don't belong in this branch. But the actual memory system itself? It's the simple, obvious implementation — SQLite, keyword search, greedy packing under a token budget, no over-engineering. That's what I want to see. Ship it, then fix the resource ownership in a follow-up.
