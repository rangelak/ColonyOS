# Review: Add Persistent Memory System
**Reviewer**: Linus Torvalds
**Branch**: `colonyos/add_memory_to_the_system_https_github_com_thedotmack_claude_mem_git`
**Date**: 2026-03-26

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/orchestrator.py]: Memory store `close()` is manually scattered across 5+ early-return paths instead of using a try/finally or context manager. One missed return = resource leak. The class already implements `__enter__`/`__exit__` — use it. Wrap the entire `_run_pipeline` body in `with memory_store:` or add a single `finally` block in `run()`. This is the kind of manual resource management that guarantees a bug when someone adds a new return path six months from now.
- [src/colonyos/memory.py]: Uses `sanitize_ci_logs()` for sanitization but the PRD explicitly requires `sanitize_untrusted_content()`. These are different functions — `sanitize_ci_logs` redacts secrets/credentials but `sanitize_untrusted_content` strips XML tags used for prompt injection. Memory text that arrives from agent output can contain prompt injection payloads, and those need the XML-tag stripping from `sanitize_untrusted_content`, not just secret redaction. Should apply both, or at minimum use `sanitize_untrusted_content`.
- [src/colonyos/orchestrator.py]: The learn phase (`_run_learn_phase`, line 2499) is never wired to write memories. FR-2 says "Post-learn capture: Enhance the existing learn phase to write memories alongside the learnings ledger (coexistence, not replacement)." The learn phase successfully extracts learning entries but doesn't call `store.add_memory()`. This is a missing functional requirement.
- [src/colonyos/orchestrator.py]: `_capture_phase_memory` only extracts `phase_result.artifacts.get("result", "")` and blindly truncates to 2000 chars. No structured extraction, no attempt to pull meaningful observations. For review phases this will dump the entire review verdict as a single blob. At minimum, split on paragraph boundaries or extract the FINDINGS section for review phases.
- [src/colonyos/orchestrator.py]: Memory injection is missing from review phase prompts. The diff shows injection for plan, implement, and fix phases, but the review/fix loop's review iterations don't get memory injection. FR-3 says "implement, fix, plan, review, and direct-agent phases" should all get injection.
- [src/colonyos/tui/styles.py]: This diff changes TUI color constants from hex values to named Textual colors. This is completely unrelated to the memory feature. Keep unrelated changes out of feature branches — it makes bisecting regressions a nightmare.
- [tests/tui/conftest.py, tests/tui/test_setup.py]: Same problem — unrelated TUI test changes mixed into a memory feature branch.
- [src/colonyos/memory.py]: The pruning strategy is global FIFO (`ORDER BY created_at ASC`), but the PRD says "pruning oldest entries on overflow (FIFO by category)". Per-category FIFO ensures you don't lose all your failure memories just because you have 400 codebase memories. The current implementation could starve important minority categories.
- [src/colonyos/cli.py]: The `_run_direct_agent` memory injection silently swallows all exceptions with a bare `except Exception: pass`. At least log a warning. Silent failures are debugging cancer.

SYNTHESIS:
The data structures are right — `MemoryStore` with SQLite + FTS5 is the correct choice, and the schema is clean. The `MemoryEntry` dataclass, the category enum, the phase-category mapping — all sensible. The test suite is solid at 71 tests covering CRUD, FTS, pruning, and injection formatting. The config integration follows existing patterns correctly. But the *plumbing* has real problems. The manual `close()` calls scattered across the orchestrator are a resource-leak timebomb — you built a context manager and then didn't use it where it matters most. The wrong sanitization function is a security gap for a feature whose entire threat model is "don't let agent output poison future prompts." Missing learn-phase integration means one of the six PRD functional requirements (FR-2) is only partially implemented. And mixing unrelated TUI color changes into this branch is sloppy branch hygiene. Fix the resource management, the sanitization, wire up the learn phase, and remove the unrelated changes — then this is ready.
