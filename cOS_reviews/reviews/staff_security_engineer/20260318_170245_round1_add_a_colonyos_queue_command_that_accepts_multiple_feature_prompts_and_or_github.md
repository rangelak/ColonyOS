# Review by Staff Security Engineer (Round 1)

No actual secrets found. Now I have all the information I need. Let me write the review output directly in the required format. Here's my review as Staff Security Engineer:

---

## Review: `colonyos queue` — Staff Security Engineer

### Checklist Assessment

**Completeness:**
- [x] All functional requirements from the PRD are implemented (FR-1 through FR-18)
- [x] All tasks in the task file are marked complete
- [~] Task 4.6 (SIGINT/crash handling) is marked done but has a gap — see findings

**Quality:**
- [x] All 41 queue tests pass
- [x] Code follows existing project conventions (Click groups, Rich output, atomic writes)
- [x] No unnecessary dependencies added
- [~] Diff includes significant unrelated changes (CI fix command, show command, ~3500+ lines not related to queue)

**Safety:**
- [x] No secrets or credentials in committed code
- [x] Queue file is gitignored (`.colonyos/queue.json`)
- [x] Atomic writes via tempfile + `os.replace` for crash-safe persistence
- [~] Error handling gap for "running" items on resume (see finding below)

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/cli.py:1333-1335]: **Stuck "running" items on crash/SIGINT.** The execution loop marks items as `RUNNING` (line 1359) before calling `run_orchestrator`, but there is no SIGINT handler and no recovery logic on resume. The resume path (line 1315) only processes `PENDING` items: `pending_items = [i for i in state.items if i.status == QueueItemStatus.PENDING]`. If the process is killed while an item is `RUNNING`, that item will be permanently stuck — never retried, never completed. Task 4.6 ("Handle SIGINT/crash gracefully") is marked complete but the implementation is missing. Fix: either (a) add a `try/except KeyboardInterrupt` wrapper that resets the current item to `PENDING` before exit, or (b) at `queue start` startup, reset any `RUNNING` items back to `PENDING` (since a `RUNNING` item in persisted state always means a prior crash).
- [src/colonyos/cli.py:1409-1413]: **Unfiltered exception messages stored in queue state.** When `run_orchestrator` throws, `str(exc)` is stored verbatim in `item.error` and persisted to `queue.json`. If the orchestrator propagates an exception containing API keys, auth tokens, or internal paths (e.g., from an HTTP library traceback), those get written to disk. Consider truncating and sanitizing error messages before persisting — e.g., `item.error = str(exc)[:500]` at minimum, or strip known secret patterns via `sanitize_ci_logs()`.
- [src/colonyos/cli.py:1244-1288]: **No config validation before queue add.** The `add` command calls `_find_repo_root()` but does not call `load_config()` or check `config.project`. This means items can be added to a queue in an unconfigured repo, only to fail at `start` time. Minor UX issue but inconsistent with `start`'s validation.
- [git diff]: **Unrelated changes in scope.** The branch includes ~3500+ lines of changes unrelated to the queue feature (CI fix command, show command, sanitize module, learnings, etc.). This makes the diff harder to audit for security. Ideally each feature ships on its own branch. Not blocking but noted.
- [src/colonyos/cli.py:1256,1273]: **Repeated inline import of `uuid`.** `import uuid as _uuid` is called inside a loop body on every iteration. This is a minor style issue (not a security concern) — should be moved to module-level imports.

SYNTHESIS:
From a security standpoint, the queue implementation is largely sound: queue state is gitignored, atomic writes prevent data corruption, issue content is sanitized through the existing `format_issue_as_prompt()` pipeline, and free-text CLI prompts follow the established first-party trust model. The budget and time cap enforcement provides good guardrails against runaway spend. However, the **stuck "running" item bug** is a real operational hazard — in a tool that runs unattended overnight, a single Ctrl+C or laptop sleep event will permanently orphan a queue item with no user-visible indication or recovery path. This is the single blocking finding. The error message persistence without sanitization is a secondary concern worth addressing — this tool runs with elevated permissions (`bypassPermissions`), and exception tracebacks from HTTP clients are a known vector for credential leakage to disk. I recommend fixing the RUNNING-item recovery before merging.
