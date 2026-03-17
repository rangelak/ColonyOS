# Tasks: CEO Past-Work Context via CHANGELOG

## Relevant Files
- `CHANGELOG.md`
- `src/colonyos/orchestrator.py`
- `src/colonyos/instructions/ceo.md`
- `src/colonyos/instructions/deliver.md`
- `src/colonyos/cli.py`
- `tests/test_ceo.py`

## Tasks

- [x] 1.0 Move `cOS_tasks/CHANGELOG.md` to `CHANGELOG.md` at project root
- [x] 2.0 Backfill CHANGELOG with 8 missing feature entries from colonyos auto runs
- [x] 3.0 Add CHANGELOG update step to `deliver.md` (Step 2) so future auto runs keep it current
- [x] 4.0 Update `_build_ceo_prompt()` to accept `repo_root`, read `CHANGELOG.md`, inject into user prompt
- [x] 5.0 Simplify Step 2 in `ceo.md` — reference injected changelog instead of directory scanning
- [x] 5.1 Add "Builds Upon" section to CEO output format
- [x] 6.0 Re-apply rich Markdown rendering for CEO proposal display in `cli.py`
- [x] 7.0 Remove unused `reviews_dir`/`proposals_dir` from `_build_ceo_prompt` format call
- [x] 8.0 Update `tests/test_ceo.py` for new `repo_root` parameter and changelog injection
- [x] 9.0 Run full test suite — 355 tests pass
