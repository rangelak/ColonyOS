# PRD: Reorganize cOS_reviews Directory Structure

## Introduction/Overview

The `cOS_reviews/` directory currently stores all review artifacts — persona reviews, decision gate outputs, task reviews, standalone reviews, and summaries — in a single flat directory. With 45+ files and four inconsistent naming conventions, the directory has become difficult to navigate, lacks chronological ordering on key artifacts (decisions have no timestamps), and provides no structural separation between fundamentally different artifact types.

This feature reorganizes `cOS_reviews/` into a structured hierarchy grouped by **artifact type** (`decisions/`, `reviews/`), with consistent timestamp-prefixed naming for all files, and centralizes all filename generation in `naming.py`.

## Goals

1. **Structured hierarchy**: Introduce subdirectories that separate decisions from reviews, making the directory instantly scannable.
2. **Consistent timestamps**: Every artifact file gets a `YYYYMMDD_HHMMSS` prefix — no exceptions. This prevents silent overwrites between runs and enables chronological forensics.
3. **Centralized naming**: All artifact filename generation flows through `naming.py`, eliminating the 4+ ad-hoc naming conventions scattered across `orchestrator.py`.
4. **Persona grouping within reviews**: Persona reviews are organized into `reviews/<persona_slug>/` subfolders with timestamped filenames, making it easy to see a persona's review history.
5. **Backward-compatible agent discovery**: Instruction templates are updated so agents can recursively discover artifacts in the new nested structure.

## User Stories

1. **As a developer reviewing pipeline output**, I want to open `cOS_reviews/decisions/` and immediately see all decision gate verdicts in chronological order, without scanning through dozens of unrelated review files.
2. **As a developer debugging a failed review**, I want to navigate to `cOS_reviews/reviews/staff_security_engineer/` and see that persona's full review history sorted by timestamp.
3. **As the pipeline orchestrator**, I want a single naming module that generates correct, consistent filenames and paths for every artifact type, so I never construct ad-hoc f-strings.
4. **As an AI agent in the fix phase**, I want instruction templates that tell me exactly where to find review artifacts in the nested structure, so I don't miss context hidden in subdirectories.

## Functional Requirements

### Directory Structure

1. **FR-1**: The reviews directory must support the following subdirectory layout:
   ```
   cOS_reviews/
   ├── decisions/
   │   ├── 20260317_163656_decision_add_auth.md
   │   └── 20260318_091200_decision_slack_integration.md
   ├── reviews/
   │   ├── staff_security_engineer/
   │   │   ├── 20260318_110500_round1_install_script.md
   │   │   └── 20260318_111200_round2_install_script.md
   │   ├── linus_torvalds/
   │   │   └── 20260318_110500_round1_install_script.md
   │   └── principal_systems_engineer_google_stripe_caliber/
   │       └── 20260318_110500_round1_install_script.md
   └── .gitkeep
   ```

2. **FR-2**: All artifact files must be prefixed with a `YYYYMMDD_HHMMSS` timestamp using the existing `generate_timestamp()` from `naming.py`.

3. **FR-3**: Decision filenames follow the pattern: `{timestamp}_decision_{feature_slug}.md`

4. **FR-4**: Persona review filenames follow the pattern: `{timestamp}_round{N}_{feature_slug}.md`, stored under `reviews/{persona_slug}/`

5. **FR-5**: Task review filenames follow the pattern: `{timestamp}_review_task_{N}_{feature_slug}.md`, stored under `reviews/tasks/` (for legacy pipeline task-level reviews)

### Naming Module (`naming.py`)

6. **FR-6**: Add a `ReviewArtifactPath` frozen dataclass to `naming.py` that encodes both the subdirectory and filename for any review artifact.

7. **FR-7**: Add `decision_artifact_path()` function to `naming.py` that returns a `ReviewArtifactPath` for decision files.

8. **FR-8**: Add `persona_review_artifact_path()` function to `naming.py` that returns a `ReviewArtifactPath` for persona review files, including the persona slug subdirectory.

9. **FR-9**: Add `task_review_artifact_path()` function to `naming.py` that returns a `ReviewArtifactPath` for task-level review files.

### Orchestrator (`orchestrator.py`)

10. **FR-10**: Update `_save_review_artifact()` to accept an optional `subdirectory: str | None = None` parameter. When provided, files are written to `reviews_dir/subdirectory/filename`. The function must validate the resolved path stays under `repo_root / reviews_dir`.

11. **FR-11**: Replace all ad-hoc filename construction in `orchestrator.py` (at approximately lines 975, 1078, 1100, 1392, 1475) with calls to the new `naming.py` functions.

### Instruction Templates

12. **FR-12**: Update all instruction templates (`base.md`, `decision.md`, `decision_standalone.md`, `fix.md`, `fix_standalone.md`, `learn.md`) to reference the nested structure, using `{reviews_dir}/**/*.md` or specific subdirectory paths as appropriate.

### Forward-only Migration

13. **FR-13**: New artifacts use the new structure going forward. Existing files are left in place (no migration utility). A `.gitkeep` is added to each new subdirectory.

## Non-Goals

- **No migration utility**: The ~45 existing files are historical artifacts from early development. Writing, testing, and debugging a migration tool is not worth the effort for this corpus size. Old files remain in place and age out naturally.
- **No per-run grouping**: While organizing by run ID was considered, the standalone `review-branch` command doesn't have a run context, and the primary consumers (fix agents, decision agents) always operate per-feature, not per-run.
- **No changes to `config.yaml` schema**: The `reviews_dir` config key continues to point to the root directory (e.g., `cOS_reviews`). Subdirectories are convention, not configuration.
- **No changes to the learnings system**: The `learn.md` instruction template will be updated to point at the new structure, but the learnings extraction logic itself is unchanged.

## Technical Considerations

### Existing Code Touch Points

- **`src/colonyos/naming.py`**: Core change — add `ReviewArtifactPath` dataclass and 3 new factory functions. The existing `ReviewNames` dataclass is used only by `test_naming.py` and is not called from the orchestrator (the orchestrator constructs filenames ad-hoc). The new functions will be the canonical path for all review artifact naming.
- **`src/colonyos/orchestrator.py`**: 5-6 call sites construct filenames inline. Each must be updated to use `naming.py`. The `_save_review_artifact()` function gains a `subdirectory` parameter.
- **`src/colonyos/instructions/*.md`**: 6 templates reference `{reviews_dir}/`. Each needs updating.
- **`src/colonyos/init.py`**: The init function creates the `cOS_reviews/` directory. It should also create `decisions/` and `reviews/` subdirectories with `.gitkeep` files.
- **`tests/test_naming.py`**: Must be extended with tests for all new naming functions.
- **`tests/test_orchestrator.py`**: Must verify the new subdirectory writing behavior.

### Persona Consensus & Tensions

**Universal agreement (7/7 personas)**:
- All files must be timestamped consistently
- Naming must be centralized in `naming.py`
- `_save_review_artifact()` should gain subdirectory awareness

**Majority agreement (5/7)**:
- Organize by artifact type (decisions vs reviews), not by persona as primary axis
- No migration utility needed (Ive and Karpathy dissented, favoring migration)

**Key tension — Primary grouping axis**:
- **By artifact type** (Jobs, Ive, Torvalds, Seibel): `decisions/`, `reviews/`, `summaries/`
- **By run/feature** (Karpathy, Systems Engineer): `<feature_slug>/reviews/`, `<feature_slug>/decision.md`
- **Resolution**: The user's request explicitly asks for "reviews by specific personas in subfolder of that persona" and "decisions by timestamp." This maps to a hybrid: `decisions/` at the top level (by type) and `reviews/<persona_slug>/` for persona grouping with timestamps. This honors the user's intent while keeping the structure navigable.

**Key tension — Migration**:
- **No migration** (Seibel, Torvalds, Systems Engineer): Old files age out, not worth the effort
- **Migration** (Ive, Karpathy, Security Engineer): Prevents schema inconsistency confusing agents
- **Resolution**: No migration. The old files don't block the new structure, and agents will be instructed to read from specific subdirectories going forward.

## Success Metrics

1. **Zero ad-hoc filename construction**: All review artifact filenames in `orchestrator.py` are generated by `naming.py` functions.
2. **100% timestamp coverage**: Every new artifact file has a `YYYYMMDD_HHMMSS` prefix.
3. **All tests pass**: Existing tests remain green; new tests cover all naming functions and subdirectory writing.
4. **Agent discovery works**: AI agents in fix/decision phases can find all relevant artifacts via the updated instruction templates.

## Open Questions

1. **Should `reviews/tasks/` be a separate subdirectory?** The legacy pipeline generates `review_task_{N}` files during the orchestrated run. These could go under `reviews/tasks/` or remain at the `reviews/` root. Current recommendation: put them under `reviews/tasks/` for consistency.
2. **Should the `ReviewNames` dataclass be deprecated?** It's currently only used in `test_naming.py` and never called from the orchestrator. The new `ReviewArtifactPath` functions supersede it, but removing it is a separate cleanup.
3. **Path traversal validation**: The Security Engineer flagged that `_save_review_artifact()` has no path traversal check. Should we add `path.resolve().is_relative_to(target_dir.resolve())` as a safety measure? Recommendation: yes, it's a one-line addition.
