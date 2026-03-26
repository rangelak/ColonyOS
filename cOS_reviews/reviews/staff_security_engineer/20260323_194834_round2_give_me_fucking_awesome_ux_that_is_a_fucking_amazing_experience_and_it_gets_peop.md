# Review by Staff Security Engineer (Round 2)

Now I have enough to produce a thorough security review. Here is my assessment:

---

## Security Review — Staff Security Engineer

### Checklist Assessment

#### Completeness
- [x] All functional requirements from the PRD are implemented (FR-1 through FR-8)
- [x] File structure matches the PRD specification exactly
- [x] CLI entry points (`colonyos tui`, `colonyos run --tui`) implemented
- [x] Optional dependency pattern implemented correctly

#### Quality
- [x] Tests cover adapter, app, CLI integration, composer, status bar, transcript, and setup
- [x] Code follows existing project conventions (duck-type PhaseUI interface, style map reuse)
- [x] No unnecessary dependencies — only `textual` and `janus` as specified
- [x] No unrelated changes beyond a minimal README update

#### Safety
- [x] No secrets or credentials in committed code
- [x] No destructive database operations
- [x] Error handling present for import failures and missing dependencies

### Detailed Findings

**FINDING 1 — `sanitize_display_text()` strips newlines, breaking multi-line content (Medium Severity — Functional Bug with Security Origin)**

`sanitize_display_text()` uses `_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")` which strips `\n` (0x0a) and `\t` (0x09). In `adapter.py:189`, the full text buffer is sanitized before queuing as a `TextBlockMsg`. When `transcript.py:append_text_block()` later calls `text.splitlines()` or passes to `Markdown()`, the text is already flattened into one line. This means all agent text — including markdown with headings, lists, code blocks — will render as a single collapsed line. The security intent is correct (strip control chars), but the sanitizer needs to preserve `\n` and `\t` for display purposes. This is a **functional regression** caused by over-aggressive sanitization.

**FINDING 2 — Concurrent orchestrator runs via `exclusive=False` (Medium Severity — Safety)**

In `app.py:105` and `app.py:155`, `run_worker(..., exclusive=False)` is used. If a user submits a second prompt while the first orchestrator run is still active, two orchestrator threads will run concurrently, both modifying the same repository. This could lead to race conditions (concurrent git operations, file writes, conflicting agent actions). The worker should use `exclusive=True` or the composer should be disabled while a run is in progress, preventing concurrent submissions.

**FINDING 3 — Output sanitization is correctly placed at the adapter boundary (Positive)**

All 8 PhaseUI callbacks in `TextualUI` sanitize text through `sanitize_display_text()` before pushing onto the queue. This is the right architecture — sanitize at the trust boundary (adapter) rather than in individual widgets. The `_CONTROL_CHARS_RE` regex strips the escape character `\x1b` itself (within `\x00-\x1f`), which prevents not just CSI sequences but also OSC (`\x1b]`), DCS (`\x1bP`), and other terminal escape families. This is comprehensive terminal injection protection.

**FINDING 4 — No audit trail of agent actions in TUI mode (Low Severity — Observation)**

The TUI operates purely in-memory with no logging of agent actions, tool calls, or user submissions. This matches the existing Rich CLI behavior and is explicitly a non-goal per the PRD ("No event persistence / replay"). However, from a security posture perspective, if a bad instruction template exfiltrates data during a TUI session, there is no forensic record beyond the user's own terminal scrollback. This is not a regression but is worth noting for future hardening.

**FINDING 5 — User input from composer flows unsanitized to orchestrator (By Design — Acceptable)**

The `Composer.Submitted` text goes directly to `run_orchestrator()` without sanitization. This is correct — the user is the trust principal. Sanitizing user input would break legitimate prompts. The trust boundary is correctly placed: user input is trusted, agent/tool output is untrusted and sanitized before display.

**FINDING 6 — No new privilege escalation surface (Positive)**

The TUI is a pure rendering frontend. It reuses `run_orchestrator()` with the same `config`, `repo_root`, and permission model as the existing CLI. The `TextualUI` adapter is a display-only sink — it cannot influence agent behavior, modify permissions, or access resources beyond what the orchestrator already has. Least privilege is maintained.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/sanitize.py]: `sanitize_display_text()` strips `\n` and `\t` (within `\x00-\x1f` range), causing all multi-line agent text to collapse into a single line when rendered in the transcript. The adapter calls this on the full text buffer before queuing, destroying markdown structure. Fix: exclude `\n` and `\t` from the control character regex, or use a TUI-specific sanitizer that preserves whitespace while still stripping dangerous control chars.
- [src/colonyos/tui/app.py]: `run_worker(..., exclusive=False)` allows concurrent orchestrator runs when the user submits multiple prompts. Two agents modifying the same repo simultaneously is a safety hazard. Fix: use `exclusive=True` or disable the composer input while a run is in progress.
- [src/colonyos/tui/adapter.py]: Output sanitization correctly applied at the adapter boundary for all 8 callbacks — this is well-architected.
- [src/colonyos/tui/app.py]: No audit logging of agent actions or user submissions in TUI mode — acceptable for v1 per PRD non-goals, but should be on the security roadmap.

SYNTHESIS:
The implementation is architecturally sound from a security perspective. The critical decision to sanitize at the adapter boundary (before queuing) rather than in widgets is correct and prevents terminal escape injection from untrusted agent/tool output. The trust model is preserved — user input is trusted, agent output is not. No new privilege escalation surfaces are introduced. However, two issues need resolution before shipping: (1) the `sanitize_display_text()` function strips newlines, which will render all agent text as collapsed single-line blobs — a severe UX regression that ironically stems from security-correct instincts, and (2) the `exclusive=False` worker configuration allows concurrent orchestrator runs that could corrupt repository state. Both are straightforward fixes. The overall security posture of this feature is strong; these are implementation bugs, not architectural flaws.