# Review by Linus Torvalds (Round 2)

Now I have a complete picture. Here is my review:

---

VERDICT: request-changes

FINDINGS:
- [branch scope]: This branch conflates two separate features — the verification gate (PRD `20260317_183545`) AND the standalone `colonyos review <branch>` command (PRD `20260317_180029`). The standalone review command adds ~400 lines to `orchestrator.py`, ~140 lines to `cli.py`, and 3 new instruction templates (`review_standalone.md`, `fix_standalone.md`, `decision_standalone.md`). These are separate features and belong on separate branches. Reviewing two features on one branch is how you end up unable to revert one without the other.
- [src/colonyos/orchestrator.py]: The massive `run_review_loop()` extraction refactor (~170 lines) was done to share code between the pipeline `run()` and the standalone `review` command. The refactor itself is clean, but it's driven by the out-of-scope feature. The verification gate could have been wired in with ~10 lines of changes to `run()`.
- [tests/test_orchestrator.py:320]: Test method renamed from `test_review_skipped_when_no_reviewer_personas` to `test_review_skipped_when_noreviewer_personas` — dropped an underscore. Same at line 384: `test_multiplereviewer_personas`. These look like accidental renames from a broken find-and-replace. Fix your test names.
- [src/colonyos/orchestrator.py]: Several private functions were made public (`_save_run_log` → `save_run_log`, `_touch_heartbeat` → `touch_heartbeat`, `_reviewer_personas` → `reviewer_personas`, `_extract_review_verdict` → `extract_review_verdict`) solely to support the standalone review command that shouldn't be on this branch.
- [src/colonyos/ui.py]: `REVIEWER_COLORS`, `_reviewer_color()`, `make_reviewer_prefix()`, `print_reviewer_legend()` — none of these are verification gate features. They're UI for the standalone review command. Out of scope.
- [src/colonyos/orchestrator.py]: `_validate_branch_name()`, `detect_base_branch()`, `validate_review_preconditions()`, `build_review_run_id()` — all standalone review command plumbing. Out of scope.

SYNTHESIS:

The verification gate implementation itself is actually solid. `_run_verify_command()` is a clean 15-line function that does exactly what it says. `run_verify_loop()` handles the retry logic correctly — budget guards, exhaustion fallthrough, proper phase logging with `cost_usd=0.0`. The `verify_fix.md` template is focused and actionable. The config parsing follows existing patterns precisely. The `_SKIP_MAP` comment explaining why verify doesn't skip itself shows someone who actually thought about the semantics. All 308 tests pass.

But here's the problem: this branch ships two features in one. The verification gate (which is what the PRD asks for) is ~300 lines of real changes. The standalone `colonyos review <branch>` command (which has its own separate PRD) adds another ~700+ lines of code, instruction templates, and a major refactoring of the review loop. I refuse to review two features as one. The review command drove a large refactor of `run()` that makes it impossible to assess the verification gate's integration in isolation. If the review command has a bug, you can't revert it without also reverting the verification gate.

Split these. Put the standalone review command on its own branch (it already has its own PRD). The verification gate can land cleanly without any of the review loop extraction, public API renames, UI color additions, or branch validation code. The test names with dropped underscores need fixing too — that's just sloppy.