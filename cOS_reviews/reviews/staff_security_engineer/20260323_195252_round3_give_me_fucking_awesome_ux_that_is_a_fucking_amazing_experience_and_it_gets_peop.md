# Review by Staff Security Engineer (Round 3)

I have now reviewed all the relevant code. Here is my security review:

---

## Security Review — Staff Security Engineer

### Checklist Assessment

**Completeness:**
- [x] All functional requirements from the PRD are implemented (FR-1 through FR-8)
- [x] File structure matches the PRD specification
- [x] No placeholder or TODO code remains

**Quality:**
- [x] Tests are comprehensive — 7 test modules with ~350+ lines covering adapter, app, widgets, CLI, and setup
- [x] Code follows existing project conventions (duck-type PhaseUI interface, TOOL_STYLE reuse)
- [x] No unnecessary dependencies — `textual` and `janus` are justified and well-scoped
- [x] No unrelated changes beyond the sanitize.py fix (which is a related security improvement)

**Safety:**
- [x] No secrets or credentials in committed code
- [x] No destructive operations
- [x] Error handling present for dependency import failures and queue lifecycle

### Security-Specific Findings

VERDICT: request-changes

FINDINGS:
- [src/colonyos/sanitize.py]: The ANSI escape regex `\x1b\[[0-9;]*[A-Za-z]` only covers CSI sequences. It does **not** strip OSC sequences (`\x1b]...ST`), DCS sequences (`\x1bP...ST`), or raw `\x1b` followed by single characters (e.g., `\x1b7`, `\x1b8` for cursor save/restore). A crafted tool output containing `\x1b]0;pwned\x07` could retitle the terminal window, and `\x1b]52;c;BASE64\x07` could write to the clipboard on some terminals. The control char regex strips `\x07` (BEL) which truncates OSC payloads, but leaves the `\x1b]...` prefix intact as visible garbage — partial mitigation at best. Recommend broadening to `\x1b[\x20-\x7e]*` or using a well-tested library like `strip-ansi-escapes`.
- [src/colonyos/sanitize.py]: Preserving `\r` (carriage return) is a security regression. Carriage return allows "overwrite" attacks: `"safe command\rmalicious"` renders as `malicious` in some terminals, hiding the true content. The previous behavior (stripping `\r`) was safer. If CRLF support is needed, normalize `\r\n` → `\n` instead of preserving bare `\r`.
- [src/colonyos/tui/app.py]: The `_run_callback` lambda in `on_composer_submitted` captures `self._run_callback` via closure and runs it in a worker thread with `exclusive=True`. However, there is no input length limit on composer submissions. A user (or a prompt injection via initial_prompt) could submit arbitrarily large text that gets passed directly to the orchestrator. This is low-severity since the user is local, but worth noting.
- [src/colonyos/tui/app.py]: The `run_worker(lambda: callback(prompt), thread=True)` pattern for initial_prompt runs the orchestrator callback immediately on mount without any user confirmation. If `--tui "malicious prompt"` is invoked (e.g., from a shell alias or script), it auto-executes. This matches the existing `colonyos run "prompt"` behavior, so it's consistent, but worth documenting.
- [src/colonyos/tui/adapter.py]: The `_try_extract_arg` method calls `json.loads()` on potentially partial/malformed JSON. This is handled correctly with try/except, but the accumulated `_tool_json` buffer has no size limit. A pathological tool input stream could accumulate unbounded memory before `on_tool_done()` clears it. Low severity — would require a compromised SDK stream.
- [src/colonyos/tui/widgets/transcript.py]: The `append_text_block` method renders agent text as `Markdown()` when `_looks_like_markdown()` returns True. Rich's Markdown renderer processes links, which could display misleading URLs in the transcript. This is informational — Rich doesn't make links clickable in terminal, but they are visually rendered.
- [src/colonyos/tui/widgets/transcript.py]: `append_user_message` does not sanitize user text through `sanitize_display_text()`. While user text is locally-sourced, if the TUI is ever used in a shared context (e.g., tmux pair session), unsanitized display text could contain escape sequences.

SYNTHESIS:
The implementation is well-structured and follows security best practices in most areas — all agent output flows through `sanitize_display_text()` before rendering, queue messages use frozen dataclasses for thread safety, and the dependency guard provides clean failure modes. The adapter correctly sanitizes phase names, errors, tool arguments, and text blocks. However, there are two findings that warrant changes before merge: (1) the ANSI escape sanitization regex has known gaps for OSC/DCS sequences that could allow terminal manipulation (window retitling, clipboard writes) from crafted tool output, and (2) the decision to preserve `\r` (carriage return) is a security regression that enables content-overwrite attacks in terminal display. The `\r` issue is particularly concerning because it was explicitly stripped before and the change was made to support "CRLF line endings" — but normalizing `\r\n` → `\n` would achieve the same goal without the security risk. I recommend fixing these two issues (broaden escape regex, normalize `\r`) and then this is ready to ship.
