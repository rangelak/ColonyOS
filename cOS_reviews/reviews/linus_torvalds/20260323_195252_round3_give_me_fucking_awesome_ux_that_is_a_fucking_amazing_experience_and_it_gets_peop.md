# Review by Linus Torvalds (Round 3)

Now I have a complete picture. Let me write the review.

---

## Review: Linus Torvalds — Interactive Terminal UI (Textual TUI)

I've read the PRD, reviewed every new file and every diff, and run the full test suite. Here's my assessment.

**The good:** This is surprisingly well-structured for what it is. The code is clean, the data flow is simple and understandable, the widget count is minimal (4 widgets, as promised), and the adapter pattern is straightforward — frozen dataclasses through a janus queue. The test suite is extensive (139 new tests) and all 1689 existing tests pass unchanged. The sanitizer fix to preserve `\t`, `\n`, `\r` is correct and the old behavior (stripping newlines from display text) was obviously wrong. No unnecessary abstractions. No premature generalization. The file structure matches the PRD exactly.

**The concerns:**

1. **`_launch_tui` closure pattern is fragile.** You create the `AssistantApp` with `run_callback=None`, then monkey-patch `_run_callback` after construction. This works but it's ugly. If someone later adds validation in `__init__` or `on_mount` that checks for `_run_callback is not None`, it breaks silently. Just pass the callback to the constructor — you already accept it as a parameter.

2. **`_run_callback` creates a new `TextualUI` adapter on every submission.** Each user submission in `_launch_tui` creates a fresh `TextualUI`, which means `_turn_count` resets to 0 and any state from the previous run is lost. This is probably intentional for independent runs, but it means the status bar's `total_cost` accumulates across runs while the adapter's turn count doesn't. Inconsistent. Document this or unify the approach.

3. **`on_composer_submitted` captures `self._run_callback` in a lambda closure.** Line 172 in `app.py`: `lambda: self._run_callback(text)` — but `text` here captures the event variable from the enclosing scope. This is actually fine because `text` is reassigned before the lambda, but it's the kind of pattern that breeds bugs when people modify the code later. Explicit is better.

4. **`TranscriptView` extends `RichLog` directly AND has `DEFAULT_CSS` that duplicates `APP_CSS`.** The CSS for `TranscriptView` appears in both `styles.py` (lines 45-48) and `transcript.py` (lines 34-39). One of these is dead weight. Pick one place for the truth.

5. **`Composer` has the same CSS duplication issue.** DEFAULT_CSS in `composer.py` (lines 57-74) duplicates constraints from `APP_CSS` in `styles.py` (lines 55-71). Two sources of truth for the same layout constraints.

6. **The `_check_dependencies()` call at module level in `__init__.py` is executed on import.** Line 33: `_check_dependencies()`. Then in `_launch_tui`, line 4232: `from colonyos.tui import _check_dependencies`. The import itself already triggers the check — importing `_check_dependencies` as a name is misleading because it suggests you're calling a function, when actually the side effect already happened. The `# noqa: F401` comment even acknowledges this is weird. Just do `import colonyos.tui` and let the module-level call do its job.

7. **No `exclusive=True` guard against concurrent orchestrator runs from repeated Enter presses.** Wait — actually `run_worker` with `exclusive=True` is used on line 101 and 173, which should cancel the previous worker. Good. But there's no user-facing feedback that the previous run was cancelled. The status bar doesn't reset. Minor, but could confuse users.

8. **`on_scroll_y` may not be the right Textual event for scroll tracking.** This is a nitpick — verify this actually fires correctly on Textual ≥0.40. The method name follows an event pattern, but I don't see it documented as a standard Textual event handler. It may need `on_scroll` or `watch_scroll_y` instead.

**What's missing from the PRD:**

- **FR-6 Ctrl+C to cancel current phase** — I see `Ctrl+C cancel` in the HintBar text, but I don't see any actual implementation of Ctrl+C cancellation. There's no binding for it in `AssistantApp.BINDINGS`, no `action_cancel` method, nothing. The hint bar lies to the user. This is a real gap.
- **FR-2 auto-scroll behavior** — implemented via `on_scroll_y` and `_scroll_to_end`. Looks correct in concept.
- **FR-3 composer auto-grow** — implemented correctly (3-8 lines).
- **FR-4 status bar** — implemented with spinner, phase tracking, cost, turns, elapsed.
- **FR-1 entry points** — both `colonyos tui` and `--tui` flag implemented.
- **FR-7 optional dependency** — clean import guard, `tui` extra in `pyproject.toml`.
- **FR-8 sanitization** — all adapter output goes through `sanitize_display_text()`.

**Test quality:** Tests are thorough. The adapter tests cover all 8 callbacks. The widget tests use Textual's test harness properly. The CLI integration tests mock correctly. No mocking-as-testing antipatterns. Clean.

---

VERDICT: request-changes

FINDINGS:
- [src/colonyos/tui/widgets/hint_bar.py]: HintBar advertises "Ctrl+C cancel" but Ctrl+C cancellation is not implemented anywhere — no binding, no action handler. FR-6 from the PRD is unmet. Either implement it or remove the hint.
- [src/colonyos/cli.py:4236-4254]: `_launch_tui` creates AssistantApp with `run_callback=None` then monkey-patches `_run_callback`. Pass the callback to the constructor properly — the parameter already exists.
- [src/colonyos/tui/widgets/transcript.py:34-39]: DEFAULT_CSS in TranscriptView duplicates layout from APP_CSS in styles.py. Pick one source of truth.
- [src/colonyos/tui/widgets/composer.py:57-74]: DEFAULT_CSS in Composer duplicates layout from APP_CSS in styles.py. Same issue — two places defining the same constraints.
- [src/colonyos/tui/__init__.py:33]: Module-level `_check_dependencies()` call is correct, but the re-import in `_launch_tui` is misleading. Clean up the import to `import colonyos.tui` instead.
- [src/colonyos/cli.py:4238-4252]: Each submission creates a new TextualUI adapter, resetting turn count while status bar accumulates cost across runs. Document the intentional inconsistency or unify.

SYNTHESIS:
This is a clean, minimal implementation that mostly delivers what the PRD promised. The data flow is simple and correct: frozen dataclasses through a janus queue, no over-engineering, no premature abstractions. The widget count is exactly what was specified. The test coverage is thorough — 139 new tests with zero regressions on the existing 1689. The sanitizer fix is correct. However, the missing Ctrl+C cancellation is a real gap — the PRD explicitly calls it out as FR-6 and it's advertised in the hint bar but not implemented. That's a lie to the user, and I don't ship UIs that lie. The CSS duplication across DEFAULT_CSS and APP_CSS is sloppy — pick one place for layout truth. The monkey-patching of `_run_callback` after construction is unnecessary given the constructor already accepts the parameter. Fix the Ctrl+C gap and the CSS duplication, and this is ready to ship.
