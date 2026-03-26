# Review by Staff Security Engineer (Round 4)

## Security Review — Staff Security Engineer

### Checklist Assessment

**Completeness:**
- [x] All functional requirements from the PRD are implemented (FR-1 through FR-8)
- [x] File structure matches the PRD specification exactly
- [x] No placeholder or TODO code remains
- [x] All tasks complete

**Quality:**
- [x] All 1695 existing tests pass — zero regressions
- [x] 147 new TUI + sanitize tests pass
- [x] Code follows existing project conventions (duck-type PhaseUI interface, TOOL_STYLE reuse)
- [x] Only two new dependencies (`textual>=0.40`, `janus>=1.0`), both justified and optional
- [x] No unrelated changes

**Safety:**
- [x] No secrets or credentials in committed code
- [x] No destructive operations
- [x] Error handling present for dependency imports, queue lifecycle, and malformed JSON

### Round 3 Findings — Resolution Status

1. **ANSI escape regex gaps (FIXED):** The `_ANSI_ESCAPE_RE` regex now covers CSI, OSC (`\x1b]...\x07`), DCS (`\x1bP...\x07`), and single-char escape sequences (`\x1b[\x20-\x7e]`). This closes the window retitling (`\x1b]0;pwned\x07`) and clipboard write (`\x1b]52;c;BASE64\x07`) attack vectors. Tests confirm OSC and DCS sequences are stripped.

2. **Bare `\r` carriage return (FIXED):** The sanitizer now normalizes `\r\n` → `\n` and strips bare `\r`. The control char regex explicitly excludes `\r` from preservation. The docstring documents the security rationale. Tests cover both the CRLF normalization and the overwrite attack case (`"safe text\rmalicious"`).

3. **`append_user_message` sanitization (FIXED):** User messages now pass through `sanitize_display_text()` before rendering. Verified at transcript.py:139.

### Remaining Low-Severity Observations (Informational)

- **No input length limit on composer:** Arbitrarily large text can be submitted. Since the user is local and the orchestrator has its own budget controls, this is acceptable for v1.
- **Unbounded `_tool_json` buffer:** The adapter accumulates partial tool JSON without a size cap. Would require a compromised SDK stream to exploit. Acceptable for v1.
- **`initial_prompt` auto-execution:** Consistent with existing `colonyos run "prompt"` behavior. Not a new attack surface.
- **Rich Markdown link rendering:** Rich renders URLs visually but doesn't make them clickable. Informational only.

VERDICT: approve

FINDINGS:
- [src/colonyos/sanitize.py]: ANSI escape regex now covers CSI, OSC, DCS, and single-char escapes — all round 3 gaps closed
- [src/colonyos/sanitize.py]: Carriage return handling is now secure — CRLF normalized, bare CR stripped, with test coverage
- [src/colonyos/tui/widgets/transcript.py]: User message sanitization now applied via sanitize_display_text()
- [src/colonyos/tui/adapter.py]: All agent output paths (phase names, errors, tool args, text blocks) sanitized before queuing — verified
- [src/colonyos/tui/adapter.py]: Queue messages use frozen dataclasses — thread-safe by construction
- [src/colonyos/tui/__init__.py]: Clean dependency guard with actionable error messages
- [pyproject.toml]: textual and janus correctly scoped as optional `[tui]` extra — zero impact on base install

SYNTHESIS:
All security findings from round 3 have been addressed. The two critical issues — incomplete ANSI escape stripping (OSC/DCS gaps) and bare carriage return preservation — are both fixed with corresponding test coverage. The sanitization layer is now comprehensive: every path from agent output to terminal display passes through `sanitize_display_text()`, which strips CSI, OSC, DCS, and single-char escape sequences, normalizes CRLF, strips bare CR, and removes control characters while preserving tabs and newlines. User input is also sanitized before rendering. The frozen-dataclass queue message pattern provides thread safety by construction. The optional dependency guard is clean. The remaining observations (unbounded buffers, no input length limit) are low-severity and appropriate to defer to v2. This is ready to ship.
