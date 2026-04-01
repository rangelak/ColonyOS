# PRD: Fix TUI Scrolling, Double Scrollbar, and Text Selection

## Introduction/Overview

The ColonyOS TUI (built on Textual/Python) has three usability bugs that severely impair the agent-monitoring experience:

1. **Double scrollbars** in the daemon monitor TUI — caused by a dead CSS selector and the Screen itself scrolling
2. **Forced auto-scroll** — users cannot scroll up to read agent output because every new line snaps the view back to the bottom
3. **No text selection/copy** — Textual captures mouse events, preventing terminal-native text selection

These bugs make the TUI effectively write-only: users cannot review what the agent did, copy error messages, or inspect LLM reasoning. This is especially critical for an autonomous coding agent where observability is the entire value proposition of the TUI.

**Prior attempt**: Branch `colonyos/fix_the_daemon_monitor_having_two_scrollbars_in_a143d5655f` failed. This PRD addresses the root causes identified through code analysis.

## Goals

1. Eliminate the double scrollbar in both regular and daemon monitor TUI modes
2. Implement smart auto-scroll: follow new output by default, but stop following when the user scrolls up; re-engage when user scrolls back near the bottom
3. Add a visual "new content below" indicator when the user is scrolled up and new output arrives
4. Surface text selection guidance (Shift+drag) and improve the existing Ctrl+S export discoverability
5. All fixes apply to both regular TUI and daemon monitor TUI (shared `TranscriptView` widget)

## User Stories

1. **As a developer monitoring an agent run**, I want to scroll up to read the agent's reasoning without being yanked back to the bottom every time new output appears, so I can understand what the agent did.

2. **As a developer using the daemon monitor**, I want a single scrollbar so the interface looks professional and behaves predictably.

3. **As a developer reviewing agent output**, I want to know when new content has arrived below my scroll position, so I can decide when to resume following the output.

4. **As a developer debugging an issue**, I want to select and copy text from the TUI output (or export the transcript), so I can paste error messages into bug reports.

## Functional Requirements

### FR-1: Fix Double Scrollbar
- **FR-1.1**: Fix the dead CSS selector `TranscriptView RichLog` → `TranscriptView` in `styles.py` so that `padding` and `scrollbar-size` are actually applied to the widget
- **FR-1.2**: Add `overflow: hidden;` to the `Screen` CSS rule to prevent the Screen from independently scrolling (TranscriptView's own scroll handles all scrolling)

### FR-2: Fix Auto-Scroll Behavior
- **FR-2.1**: Pass `auto_scroll=False` to `RichLog.__init__()` so the base class's built-in auto-scroll is disabled, allowing the custom `_auto_scroll` tracking to be the sole scroll controller
- **FR-2.2**: Add a small tolerance threshold (3 lines) to the `on_scroll_y` handler so auto-scroll re-engages when the user scrolls near (not just exactly at) the bottom: `self.scroll_y >= max_scroll - 3`
- **FR-2.3**: Fix the `_programmatic_scroll` flag timing — the flag is cleared synchronously after `scroll_end()` but the scroll event fires asynchronously on the next event loop tick. Use `call_after_refresh` or clear the flag inside `on_scroll_y` to ensure programmatic scrolls are correctly identified

### FR-3: "New Content Below" Indicator
- **FR-3.1**: Track an `_unread_lines` counter that increments when content is written while `_auto_scroll` is `False`
- **FR-3.2**: Display a subtle indicator (e.g., "↓ N new lines — press End to resume") when unread lines exist. Implement as a reactive label or notification in the transcript area
- **FR-3.3**: Clear the counter and hide the indicator when the user scrolls back to the bottom or presses End

### FR-4: Text Selection and Copy Discoverability
- **FR-4.1**: Add "Shift+drag select" hint to the `HintBar` keybinding display so users know how to bypass Textual's mouse capture for terminal-native text selection
- **FR-4.2**: Update the welcome banner and daemon monitor banner to mention Shift+drag for selection and Ctrl+S for export
- **FR-4.3**: Ensure the existing `Ctrl+S` transcript export works reliably and is prominently displayed

## Non-Goals

- **Custom text selection implementation** within Textual — fighting the framework's mouse capture system is not worth the complexity. Terminal-native Shift+drag is sufficient.
- **Copy-mode toggle** — adds a modal state that complicates the interaction model for marginal benefit
- **Collapsible log groups** — desirable but a separate feature, not part of this bugfix
- **Different scroll behavior per mode** — the same `TranscriptView` is used in both modes; consistency is more valuable than mode-specific tuning
- **Clipboard integration** (pyperclip/OSC 52) — adds a dependency and complexity for something terminal-native selection already provides

## Technical Considerations

### Root Cause Analysis

**Double scrollbar**:
- `TranscriptView` extends `RichLog` (inheritance), but the CSS selector `TranscriptView RichLog` targets a `RichLog` *descendant* of `TranscriptView` (containment). Since `TranscriptView` IS the `RichLog`, the selector never matches. The `padding: 0 2` and `scrollbar-size: 1 1` are never applied.
- Without `overflow: hidden` on `Screen`, the Screen can independently scroll when content overflows, creating a second scrollbar.

**Auto-scroll override**:
- `RichLog.__init__` defaults `auto_scroll=True`. The `TranscriptView.__init__` never overrides this. The base class scrolls to the bottom on every `.write()` call regardless of the custom `_auto_scroll` flag.
- The `_programmatic_scroll` flag is set/cleared synchronously around `scroll_end(animate=False)`, but `scroll_end` posts an async message — by the time `on_scroll_y` fires, the flag is already `False`, making the guard ineffective.

**Text selection**:
- Textual captures mouse events for its widget system. Terminal-native text selection works with Shift+drag in most terminal emulators (iTerm2, Terminal.app, Windows Terminal, gnome-terminal).

### Files to Modify

| File | Change |
|------|--------|
| `src/colonyos/tui/styles.py` | Fix CSS selector, add Screen overflow |
| `src/colonyos/tui/widgets/transcript.py` | Fix auto_scroll init, scroll threshold, _programmatic_scroll timing, add unread counter and indicator |
| `src/colonyos/tui/widgets/hint_bar.py` | Add Shift+drag hint |
| `src/colonyos/tui/app.py` | Minor: wire indicator clear on End key action |
| `tests/tui/test_transcript.py` | New tests for scroll behavior, unread counter |
| `tests/tui/test_app.py` | New tests for Screen overflow, indicator |

### Dependencies
- No new dependencies required. All fixes use existing Textual APIs.

### Compatibility
- Fixes apply to Textual's `RichLog` widget. The code must work with the Textual version pinned in the project.

## Persona Consensus

| Decision | Agreement | Notes |
|----------|-----------|-------|
| Fix all three bugs, not just one | **7/7** | "These are broken fundamentals, not features" |
| Apply fixes to both TUI modes | **7/7** | Shared `TranscriptView` — one fix covers both |
| Pass `auto_scroll=False` to RichLog super | **7/7** | "Two scroll controllers fighting = guaranteed jank" |
| Fix CSS selector from descendant to direct | **7/7** | "CSS 101 — containment ≠ inheritance" |
| Document Shift+drag, don't build custom selection | **7/7** | "Don't fight the framework" |
| Add scroll re-engagement threshold (~3 lines) | **6/7** | Steve Jobs suggests exact-bottom + End key only; others prefer threshold |
| Add "new content below" indicator | **5/7** | YC Partner says over-engineering for v1; Jony Ive & Karpathy say table stakes |
| Drop `_programmatic_scroll` flag entirely | **3/7** | Linus says unnecessary complexity once base auto_scroll disabled; others prefer keeping it as safety |

### Tensions
- **Indicator complexity vs. simplicity**: YC Partner (Seibel) argues the End key binding is sufficient; Jony Ive and Karpathy argue users need a visual signal that new content exists. **Resolution**: Ship the indicator — it's a few lines of code and critical for agent observability.
- **`_programmatic_scroll` flag**: Linus argues it's unnecessary once base auto_scroll is disabled; Systems Engineer argues for keeping it as a safety net. **Resolution**: Keep the flag but fix its timing using `call_after_refresh`.

## Success Metrics

1. **Zero double scrollbars** in either TUI mode (manual QA verification)
2. **Scroll position preserved** when user scrolls up — no auto-snap to bottom on new content
3. **Auto-scroll re-engages** when user scrolls within 3 lines of the bottom
4. **Unread indicator visible** when scrolled up and new content arrives
5. **All existing tests pass** with no regressions
6. **New tests cover**: auto_scroll=False init, scroll threshold logic, unread counter, CSS selector fix

## Open Questions

1. **Indicator placement**: Should the "new content below" indicator be a floating label within `TranscriptView`, or a state shown in the `StatusBar`? (Jony Ive recommends transcript edge; Karpathy recommends sticky bar at bottom of TranscriptView.) **Leaning**: Reactive label at bottom of `TranscriptView` — keeps StatusBar focused on phase/cost info.
2. **Threshold tuning**: Is 3 lines the right threshold for scroll re-engagement, or should it be configurable? **Leaning**: Hardcode at 3 lines for v1; no configuration needed.
3. **`_programmatic_scroll` race**: Should we use `call_after_refresh` to clear the flag, or clear it inside `on_scroll_y`? **Leaning**: Clear inside `on_scroll_y` (simpler, no timing dependency).
