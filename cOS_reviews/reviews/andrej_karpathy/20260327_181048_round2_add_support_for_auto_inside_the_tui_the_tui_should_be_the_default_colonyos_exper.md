# Review by Andrej Karpathy (Round 2)

## Review Complete: Andrej Karpathy — Round 2

**VERDICT: request-changes**

### What's Good
The implementation has gone from zero to substantial — 1,269 lines across 21 files, 52 tests all passing. The hard architectural decisions are correct:

- **Auto-scroll fix (FR-5)**: Clean binary model with `_programmatic_scroll` guard. Highest-value fix, done right.
- **CEO profiles (FR-2)**: 8 genuinely differentiated personas with meaningful `perspective` fields that will actually shape model behavior (not just cosmetic name swaps).
- **Transcript export (FR-4)**: Ctrl+S → plain text file → notice. Simple, works.
- **Auto-in-TUI core loop (FR-1)**: Janus queue, frozen dataclass messages, per-iteration adapter, stop event — all architecturally sound.

### Three Gaps That Block Approval

| # | Issue | Severity | Fix Effort |
|---|-------|----------|------------|
| 1 | **`--max-hours`, `--max-budget`, `--persona` not parsed in TUI auto path** (cli.py:5266-5273). Budget caps are silently ignored, giving the model an uncapped autonomous loop. | 🔴 Safety | ~15 min |
| 2 | **`TranscriptLogWriter` never instantiated** in any TUI session. The class is fully built and tested but is dead code — FR-3 is non-functional. | 🔴 Completeness | ~10 min |
| 3 | **Custom CEO profiles from config ignored** in TUI auto path — `get_ceo_profile()` called without `custom_profiles=config.ceo_profiles`. | 🟡 Completeness | ~5 min |

All three are straightforward wiring fixes, not architectural issues. Fix them and this is a clean approve.
