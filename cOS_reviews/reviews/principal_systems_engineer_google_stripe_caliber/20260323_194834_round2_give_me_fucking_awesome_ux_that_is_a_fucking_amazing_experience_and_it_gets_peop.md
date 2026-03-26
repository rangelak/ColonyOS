# Review by Principal Systems Engineer (Google/Stripe caliber) (Round 2)

## Review Complete

Here's my assessment as Principal Systems Engineer:

**VERDICT: approve**

### Key Findings

1. **🟡 Concurrent Submit Race (Medium)** — `_run_callback` uses `exclusive=False` on the Textual worker, meaning a user hitting Enter twice spawns two parallel orchestrator runs interleaving events on the same janus queue. This is a one-line fix: change to `exclusive=True`. Budget risk at 3am.

2. **🟢 Ctrl+C Mismatch (Low)** — The hint bar says "Ctrl+C cancel" but it actually exits the app (Textual default). Should say "quit" or implement actual phase cancellation. Acceptable for v1.

3. **🟢 Late-bound Callback (Low)** — `_run_callback` is assigned to `app_instance` after construction. Works but fragile. Minor.

### What's Good

- **Thread safety is correct** — The adapter's mutable streaming state (`_text_buf`, `_tool_*`) lives exclusively in the worker thread. The janus queue is the only cross-thread boundary. Clean.
- **Zero regressions** — All 1,687 existing tests pass. 86 new TUI tests added with good coverage (adapter, widgets, CLI integration, dependency guard).
- **Clean architecture** — Plugs into the existing `ui_factory` injection point (established by Slack integration). No changes to orchestrator, agent, or config.
- **Sanitization on all output** — Every text path through the adapter calls `sanitize_display_text()` before queuing. Terminal injection prevented.
- **Optional dependency done right** — `tui = ["textual>=0.40", "janus>=1.0"]` in pyproject.toml, lazy import with clear error message.

The full review artifact is saved to `cOS_reviews/reviews/principal_systems_engineer_google_stripe_caliber/20260323_tui_review.md`.