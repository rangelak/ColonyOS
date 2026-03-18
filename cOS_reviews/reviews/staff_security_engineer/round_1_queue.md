# Staff Security Engineer — Review Round 1: `colonyos queue`

**Branch:** `colonyos/add_a_colonyos_queue_command_that_accepts_multiple_feature_prompts_and_or_github`
**Date:** 2026-03-18

---

## Checklist

### Completeness
- [x] All functional requirements from the PRD are implemented (FR-1 through FR-18)
- [x] All tasks in the task file are marked complete (Tasks 1.0–8.0)
- [x] No placeholder or TODO code remains

### Quality
- [x] All 49 queue tests pass
- [x] Code follows existing project conventions (Click groups, Rich output, atomic writes)
- [x] No unnecessary dependencies added
- [ ] Unused `signal` import added to `cli.py` — minor but signals sloppy diff hygiene

### Safety
- [x] No secrets or credentials in committed code
- [x] Queue state file (`.colonyos/queue.json`) is gitignored
- [x] Error handling present for failure cases (KeyboardInterrupt, exception truncation, crash recovery)
- [x] Issue content sanitized at execution time via existing `format_issue_as_prompt()` pipeline

---

## Security-Specific Findings

### Positive

1. **Trust model is consistent.** Free-text prompts from the CLI are treated as first-party input (no sanitization), matching the existing `colonyos run "prompt"` behavior. Issue-sourced content flows through `format_issue_as_prompt()` which applies `sanitize_untrusted_content()` (XML tag stripping). This is the correct boundary.

2. **Error message truncation.** Exception messages stored in `queue.json` are truncated to 500 characters (`item.error = str(exc)[:500]`), limiting the risk of sensitive traceback content being persisted to disk. Good defensive practice.

3. **Atomic writes.** Queue persistence uses the same `tempfile.mkstemp` + `os.replace` pattern as the existing loop state, preventing truncated/corrupt state files on crash.

4. **Crash recovery is sound.** Items stuck in `RUNNING` state from a prior crash are reset to `PENDING` on the next `queue start`. The `KeyboardInterrupt` handler reverts the current item to `PENDING` and persists state. Both paths are tested.

5. **Issue re-fetch at execution time.** FR-7 is correctly implemented — issues are re-fetched at execution time to get the latest content, which also ensures the sanitization pipeline runs on fresh data.

### Concerns (Minor)

6. **`signal` import is unused.** The diff adds `import signal` to `cli.py` but never uses it. The `KeyboardInterrupt` is caught via `try/except`, not signal handlers. This is a dead import — harmless but sloppy.

7. **No queue size limit.** The PRD's Open Question #3 recommends a soft warning at 20 items. No limit or warning is implemented. An adversarial or accidental `queue add` with hundreds of items could create runaway cost. The `--max-cost` flag mitigates this somewhat, but a warning would be a nice guardrail. **Not blocking for V1.**

8. **Queue file permissions.** The queue file inherits default umask permissions. On shared systems, this could expose queue content (prompts, issue titles, PR URLs) to other users. The PRD explicitly scopes this as "single-developer, local" which makes this acceptable for V1, but worth noting.

9. **No audit trail for queue operations.** Unlike pipeline runs (which produce run logs in `.colonyos/runs/`), queue add/clear/start operations don't produce an immutable audit log. The queue state is mutable — a `clear` permanently deletes pending items. For an agent system that runs arbitrary code with `bypassPermissions`, an append-only audit log would strengthen accountability. **Not blocking for V1, but recommend for V2.**

---

VERDICT: approve

FINDINGS:
- [src/colonyos/cli.py]: Unused `import signal` added — dead code, should be removed
- [src/colonyos/cli.py]: No queue size warning/limit per PRD Open Question #3; runaway adds are possible but mitigated by --max-cost
- [src/colonyos/cli.py]: Queue operations (add/clear) lack append-only audit logging; mutable state means no forensic trail for what was enqueued or removed
- [src/colonyos/cli.py]: Queue file inherits default umask; acceptable for single-developer scope but worth hardening if scope expands

SYNTHESIS:
From a security perspective, this implementation is well-constructed for its stated scope. The trust boundaries are correctly drawn: CLI user input is trusted (consistent with `colonyos run`), while GitHub issue content flows through the existing `sanitize_untrusted_content()` pipeline. Crash recovery, error truncation, and atomic writes are all handled correctly with proper test coverage. The main gaps — no audit trail for queue mutations, no queue size guardrails, and default file permissions — are all acceptable tradeoffs for a V1 single-developer CLI tool and are documented as non-goals in the PRD. The unused `signal` import is trivial cleanup. I approve this implementation with the recommendation to add append-only audit logging in V2, especially given that this tool orchestrates agents running with `bypassPermissions`.
