# Review by Staff Security Engineer (Round 1)

Now I have a thorough understanding of the implementation. Let me write my review.

---

## Security Review: Interactive Terminal UI (Textual TUI)

**Reviewer**: Staff Security Engineer
**Branch**: `colonyos/give_me_fucking_awesome_ux_that_is_a_fucking_amazing_experience_and_it_gets_peop`

### Checklist Assessment

**Completeness**:
- [x] FR-1 (TUI Entry Point): `colonyos tui` command and `--tui` flag both implemented with graceful ImportError fallback
- [x] FR-2 (Transcript Pane): TranscriptView wrapping RichLog with auto-scroll, phase headers, tool lines, text blocks
- [x] FR-3 (Composer Pane): Multi-line TextArea with auto-grow (3→8 lines), Enter submits, Shift+Enter newline
- [x] FR-4 (Status Bar): Phase name, cumulative cost, turn count, elapsed time, spinning indicator
- [x] FR-5 (TextualUI Adapter): 8-method duck-type interface pushing frozen dataclasses onto janus queue
- [x] FR-6 (Keybindings): Enter, Shift+Enter, Ctrl+C, Ctrl+L, Escape all wired
- [x] FR-7 (Optional Dependency): `tui = ["textual>=0.40", "janus>=1.0"]` in pyproject.toml
- [x] FR-8 (Output Sanitization): `sanitize_display_text()` applied in adapter before queuing
- [x] No placeholder or TODO code
- [x] All tasks completed (84 tests pass, 1687 existing tests pass)

**Quality**:
- [x] 84 new tests pass
- [x] 1687 existing tests pass (zero regressions)
- [x] Code follows established conventions (duck-type UI interface, optional dependency pattern)
- [x] Two dependencies added (`textual>=0.40`, `janus>=1.0`) — both justified by architecture
- [x] No unrelated changes included

**Safety**:
- [x] No secrets or credentials in committed code
- [x] No destructive database operations
- [x] Error handling present (ImportError fallback, queue lifecycle cleanup, CancelledError handling)

### Security-Specific Findings

**1. Output Sanitization — Well Done** ✓
The adapter (`adapter.py`) consistently pipes all text through `sanitize_display_text()` before queuing: phase names, model names, extra text, error messages, tool arguments, and agent text blocks. The sanitizer strips ANSI escape sequences and control characters. Tests verify this (`test_sanitizes_phase_name`, `test_sanitizes_error`, `test_text_sanitized`, `test_tool_arg_sanitized`). This directly addresses the PRD's FR-8 and the security concern flagged during persona synthesis.

**2. User Message Not Sanitized in Transcript** ⚠️ (Low Risk)
`TranscriptView.append_user_message()` renders user-typed text directly without sanitization. Since this is the user's own input displayed back to them (not untrusted external content), this is low risk. However, if the composer ever receives programmatic input, this could become a terminal injection vector. Worth noting but not blocking.

**3. Thread Safety — Correct Architecture** ✓
Frozen dataclasses for queue messages prevent cross-thread mutation. The janus queue provides proper sync→async bridging. Queue lifecycle cleanup in `on_unmount` cancels the consumer task and closes the queue.

**4. `_current_instance` Class Variable** ⚠️ (Low Risk)
`AssistantApp._current_instance` is a mutable class-level reference used as a back-channel from the `_run_callback` closure to access the app instance. This is a minor code smell — it means a global mutable reference to the app exists. Not exploitable in practice since this is a single-process TUI, but it's an implicit coupling that could cause confusion if the app were ever instantiated multiple times. Not blocking.

**5. Worker Thread Runs Orchestrator with Full Permissions** ℹ️ (Existing Risk)
The `_run_callback` in `cli.py` passes user input directly to `run_orchestrator()` in a worker thread. This is the same code path as the existing CLI — no new privilege escalation. The TUI does not introduce any new permission surface; it's purely a presentation layer adapter. The orchestrator's existing `bypassPermissions` mode and instruction template injection risks remain unchanged — they are pre-existing concerns outside this PR's scope.

**6. No Input Length Limits on Composer** ⚠️ (Low Risk)
The `_ComposerTextArea` doesn't enforce any maximum input length before passing text to the orchestrator. Extremely large inputs could cause memory pressure. This mirrors the existing CLI behavior, so it's not a regression, but worth noting for future hardening.

**7. Dependency Surface** ✓
`textual>=0.40` is a well-maintained, widely-used terminal UI framework by Textualize. `janus>=1.0` is a small, focused library for sync/async queue bridging. Both are appropriate choices. The optional dependency pattern with import guards means they don't affect the base install.

---

VERDICT: approve

FINDINGS:
- [src/colonyos/tui/widgets/transcript.py]: `append_user_message()` does not sanitize user input before rendering — low risk since it's the user's own input, but could be a vector if composer ever receives programmatic input
- [src/colonyos/tui/app.py]: `_current_instance` class variable is mutable global state used as back-channel; not exploitable but is an implicit coupling
- [src/colonyos/cli.py]: `_run_callback` passes user text to orchestrator without length limits, mirroring existing CLI behavior — no new risk introduced
- [src/colonyos/tui/adapter.py]: Output sanitization consistently applied via `sanitize_display_text()` across all adapter methods — well implemented with test coverage

SYNTHESIS:
From a security perspective, this is a clean implementation. The most important security requirement — output sanitization to prevent terminal escape injection — is thoroughly implemented and tested. The adapter consistently sanitizes all output before queuing it for display, using the existing `sanitize_display_text()` function that strips ANSI escapes and control characters. The thread-safety model is correct: frozen dataclasses prevent cross-thread mutation, and the janus queue provides proper synchronization. Critically, the TUI introduces zero new permission surface — it is purely a presentation layer that adapts the existing 8-method PhaseUI interface. The orchestrator runs with exactly the same permissions as the existing CLI path. The pre-existing risks around instruction template injection and `bypassPermissions` mode remain unchanged and are outside this PR's scope. The two minor findings (unsanitized user echo, global instance reference) are low-risk and non-blocking. I recommend approving this implementation.