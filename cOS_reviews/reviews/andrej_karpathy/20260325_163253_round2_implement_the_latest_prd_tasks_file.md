# Review by Andrej Karpathy (Round 2)

---

Here's my review as Andrej Karpathy:

## Summary

**VERDICT: request-changes**

This branch implements three PRDs (TUI, TUI-default/smart-routing, sweep) with ~9,000 lines of changes across 72 files. The architecture is solid — the janus queue adapter pattern, the mode-selection heuristic cascade, and the sweep instruction template are all well-designed. All 1,922 tests pass. The sanitizer hardening against OSC/DCS/bare-CR terminal injection is excellent security work.

**Blocking issue:** The router classifier model was changed from `haiku` to `opus` in `config.py`. All three PRDs and all 7 personas unanimously agreed haiku is correct for a simple JSON classification. This is a 30-60x cost increase per non-heuristic routing call that users won't notice until their bill arrives. The `qa_model` → opus change is fine per user direction, but `router.model` must stay haiku.

**Non-blocking concerns:**
1. The Ctrl+C kill chain in `tui/app.py` — need to verify `cancel_callback` actually sends SIGTERM to the SDK subprocess tree, not just cancels the Textual worker
2. `_drain_injected_context()` is defined in `orchestrator.py` but its wiring into the phase execution loop needs verification
3. Two parallel routing codepaths (`_handle_routed_query` legacy + `_route_prompt` TUI) that could drift — worth a tracking issue to unify

The full review artifact is at `cOS_reviews/reviews/andrej_karpathy/20260325_review_implement_latest_prd.md`.