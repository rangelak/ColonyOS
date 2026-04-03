# Review by Linus Torvalds (Round 2)

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/orchestrator.py]: Memory store `close()` is manually scattered across 5+ early-return paths instead of using a try/finally or context manager. The class already implements `__enter__`/`__exit__` — use it. This is a resource-leak timebomb.
- [src/colonyos/memory.py]: Uses `sanitize_ci_logs()` but PRD requires `sanitize_untrusted_content()`. These are different functions — `sanitize_ci_logs` redacts secrets but doesn't strip XML prompt-injection tags. Memory content from agent output needs both.
- [src/colonyos/orchestrator.py]: Learn phase (`_run_learn_phase`) never writes memories to the store. FR-2 explicitly requires "Post-learn capture: Enhance the existing learn phase to write memories alongside the learnings ledger." Missing functional requirement.
- [src/colonyos/orchestrator.py]: Memory injection missing from review phase prompts. FR-3 requires injection for "implement, fix, plan, review, and direct-agent phases" — review is absent.
- [src/colonyos/orchestrator.py]: `_capture_phase_memory` blindly truncates artifacts to 2000 chars with no structured extraction. Review phases dump entire verdicts as blobs.
- [src/colonyos/tui/styles.py, tests/tui/*]: Unrelated TUI color and test changes mixed into a memory feature branch. Sloppy branch hygiene — makes bisecting regressions impossible.
- [src/colonyos/memory.py]: Pruning is global FIFO but PRD specifies "FIFO by category" to prevent minority categories from being starved.
- [src/colonyos/cli.py]: Silent `except Exception: pass` in direct-agent memory injection. At minimum log a warning.

SYNTHESIS:
The data structures are right — `MemoryStore` with SQLite + FTS5 is the correct choice, the schema is clean, the test suite is solid at 71 tests. Config integration follows existing patterns well. But the plumbing has real problems. Manual `close()` calls scattered across the orchestrator are a resource-leak timebomb when you already built a context manager. Wrong sanitization function is a security gap for a feature whose entire threat model is "don't let agent output poison future prompts." Missing learn-phase integration means FR-2 is only partially implemented. And mixing unrelated TUI changes into this branch is sloppy. Fix the resource management, the sanitization, wire up the learn phase, and remove the unrelated changes — then this is ready.
