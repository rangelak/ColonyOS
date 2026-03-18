# Tasks: Reorganize cOS_reviews Directory Structure

## Relevant Files

- `src/colonyos/naming.py` - Core naming module; add `ReviewArtifactPath` dataclass and factory functions for decisions, persona reviews, and task reviews
- `tests/test_naming.py` - Tests for naming module; extend with tests for all new artifact path functions
- `src/colonyos/orchestrator.py` - Pipeline orchestrator; update `_save_review_artifact()` and replace 5-6 ad-hoc filename constructions with `naming.py` calls
- `tests/test_orchestrator.py` - Tests for orchestrator; verify subdirectory writing and new naming integration
- `src/colonyos/instructions/base.md` - Base instruction template; update `{reviews_dir}` reference for nested structure
- `src/colonyos/instructions/decision.md` - Decision gate template; update to reference `{reviews_dir}/decisions/`
- `src/colonyos/instructions/decision_standalone.md` - Standalone decision template; update for nested structure
- `src/colonyos/instructions/fix.md` - Fix phase template; update to reference persona review subdirectories
- `src/colonyos/instructions/fix_standalone.md` - Standalone fix template; update for nested structure
- `src/colonyos/instructions/learn.md` - Learnings extraction template; update to recursively read nested reviews
- `src/colonyos/init.py` - Repo initialization; create `decisions/` and `reviews/` subdirectories with `.gitkeep`
- `tests/test_init.py` - Tests for init module; verify subdirectory creation

## Tasks

- [x] 1.0 Add `ReviewArtifactPath` dataclass and factory functions to `naming.py`
  - [x] 1.1 Write tests in `tests/test_naming.py` for `ReviewArtifactPath`, `decision_artifact_path()`, `persona_review_artifact_path()`, and `task_review_artifact_path()` — cover timestamp prefixing, slug generation, subdirectory computation, persona slug sanitization, and frozen immutability
  - [x] 1.2 Add `ReviewArtifactPath` frozen dataclass to `naming.py` with fields: `subdirectory` (str), `filename` (str), and a `relative_path` property that joins them
  - [x] 1.3 Add `decision_artifact_path(feature_name, *, timestamp=None)` function that returns `ReviewArtifactPath(subdirectory="decisions", filename="{ts}_decision_{slug}.md")`
  - [x] 1.4 Add `persona_review_artifact_path(feature_name, persona_slug, round_num, *, timestamp=None)` function that returns `ReviewArtifactPath(subdirectory="reviews/{persona_slug}", filename="{ts}_round{N}_{slug}.md")`
  - [x] 1.5 Add `task_review_artifact_path(feature_name, task_num, *, timestamp=None)` function that returns `ReviewArtifactPath(subdirectory="reviews/tasks", filename="{ts}_review_task_{N}_{slug}.md")`
  - [x] 1.6 Add `standalone_decision_artifact_path(branch_slug, *, timestamp=None)` function for standalone review-branch decisions
  - [x] 1.7 Add `summary_artifact_path(feature_name, *, timestamp=None)` for review round summaries
  - [x] 1.8 Run `tests/test_naming.py` and verify all new tests pass

- [x] 2.0 Update `_save_review_artifact()` in `orchestrator.py` to support subdirectories
  - [x] 2.1 Write tests in `tests/test_orchestrator.py` for `_save_review_artifact()` with subdirectory parameter — verify file is created in correct nested path, `mkdir -p` behavior, and path traversal rejection
  - [x] 2.2 Add `subdirectory: str | None = None` parameter to `_save_review_artifact()` — when provided, compute `target_dir = repo_root / reviews_dir / subdirectory`
  - [x] 2.3 Add path traversal validation: assert `path.resolve().is_relative_to((repo_root / reviews_dir).resolve())` before writing
  - [x] 2.4 Run existing orchestrator tests to verify no regressions

- [x] 3.0 Replace ad-hoc filename construction in `orchestrator.py` with `naming.py` calls
  - [x] 3.1 Write tests verifying that each orchestrator code path produces correctly named and placed artifacts (mock `_save_review_artifact` and assert arguments)
  - [x] 3.2 Update pipeline persona review save (around line 1392) — replace `f"review_round{iteration + 1}_{p_slug}.md"` with `persona_review_artifact_path()` and pass subdirectory to `_save_review_artifact()`
  - [x] 3.3 Update standalone persona review save (around line 975) — replace `f"review_standalone_{branch_s}_round{round_num}_{p_slug}.md"` with `persona_review_artifact_path()`
  - [x] 3.4 Update pipeline decision save (around line 1475) — replace `f"decision_{slugify(prompt)}.md"` with `decision_artifact_path()`
  - [x] 3.5 Update standalone decision save (around line 1078) — replace `f"decision_standalone_{branch_s}.md"` with `standalone_decision_artifact_path()`
  - [x] 3.6 Update review summary save (around line 1100) — replace ad-hoc summary filename with `summary_artifact_path()`
  - [x] 3.7 Run full test suite to verify no regressions

- [x] 4.0 Update instruction templates for nested directory structure
  - [x] 4.1 Update `src/colonyos/instructions/base.md` — change `{reviews_dir}/` reference to note the nested structure (`{reviews_dir}/decisions/` and `{reviews_dir}/reviews/`)
  - [x] 4.2 Update `src/colonyos/instructions/decision.md` — direct the decision agent to read from `{reviews_dir}/reviews/` for persona feedback
  - [x] 4.3 Update `src/colonyos/instructions/decision_standalone.md` — same as decision.md for the standalone path
  - [x] 4.4 Update `src/colonyos/instructions/fix.md` — direct the fix agent to read persona reviews from `{reviews_dir}/reviews/`
  - [x] 4.5 Update `src/colonyos/instructions/fix_standalone.md` — same for standalone fix path
  - [x] 4.6 Update `src/colonyos/instructions/learn.md` — direct learnings agent to recursively read all artifacts under `{reviews_dir}/`

- [x] 5.0 Update `init.py` to create subdirectories on project initialization
  - [x] 5.1 Write/update tests in `tests/test_init.py` to verify that `decisions/` and `reviews/` subdirectories are created with `.gitkeep` files during `colonyos init`
  - [x] 5.2 Update the init function in `src/colonyos/init.py` to create `reviews_dir/decisions/` and `reviews_dir/reviews/` subdirectories with `.gitkeep` files
  - [x] 5.3 Update the init output message to reflect the new subdirectory structure

- [x] 6.0 Final integration testing and cleanup
  - [x] 6.1 Run the full test suite (`pytest`) and fix any failures
  - [x] 6.2 Manually verify the directory structure by examining a sample `cOS_reviews/` output (or write an integration test that runs a mock pipeline and checks file placement)
  - [x] 6.3 Verify that the existing flat files in `cOS_reviews/` do not cause errors (backward compatibility — old files are simply ignored by the new structure)
