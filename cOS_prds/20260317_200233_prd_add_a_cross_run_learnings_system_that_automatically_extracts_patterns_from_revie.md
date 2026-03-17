# PRD: Cross-Run Learnings System

## Introduction/Overview

ColonyOS currently executes each pipeline run (Plan → Implement → Review/Fix → Decision → Deliver) in isolation — review findings from one run do not inform future runs. This feature adds a **cross-run learnings system** that automatically extracts actionable patterns from review artifacts after each completed run, persists them to a `.colonyos/learnings.md` ledger file, and injects them as context into future implement and fix phases. This creates a genuine feedback loop where each run makes subsequent runs better — particularly valuable in autonomous `auto --loop` mode where no human is performing manual retrospectives between iterations.

## Goals

1. **Reduce review fix iterations**: By injecting past review patterns into implement prompts, the agent should produce code that addresses known reviewer concerns on the first attempt.
2. **Accumulate institutional knowledge**: Build a persistent, human-readable ledger of patterns the project's reviewers consistently flag.
3. **Zero-configuration improvement**: The system should work out of the box (`learnings.enabled: true` by default) with no user intervention required.
4. **Non-disruptive**: The learn phase must never block delivery or cause pipeline failures — it is advisory, not critical.

## User Stories

1. **As a developer using `colonyos run`**, I want the pipeline to learn from past review findings so that each subsequent run produces higher-quality code with fewer review iterations.
2. **As a developer using `colonyos auto --loop`**, I want the autonomous loop to self-improve across iterations, reducing cost and increasing success rates without manual intervention.
3. **As a team lead**, I want to review the accumulated learnings ledger (`.colonyos/learnings.md`) to understand what patterns the pipeline has learned and optionally curate it.
4. **As a developer running `colonyos status`**, I want to see how many learnings have been accumulated to gauge the system's maturity.

## Functional Requirements

1. **FR-1**: Add `LEARN = "learn"` to the `Phase` enum in `src/colonyos/models.py` (line 12-19), following the existing `str, Enum` pattern.
2. **FR-2**: Create a `src/colonyos/learnings.py` module containing:
   - `parse_learnings(content: str) -> list[LearningEntry]` — Parse the markdown ledger into structured entries.
   - `append_learnings(repo_root: Path, run_id: str, date: str, feature_summary: str, entries: list[LearningEntry]) -> None` — Append new entries with deduplication and cap enforcement.
   - `load_learnings_for_injection(repo_root: Path, max_entries: int = 20) -> str` — Read the most recent N entries and format them as a prompt-ready string.
   - `prune_ledger(repo_root: Path, max_entries: int) -> None` — Remove oldest entries beyond the cap.
   - `count_learnings(repo_root: Path) -> int` — Count total entries for the status command.
3. **FR-3**: Create instruction template `src/colonyos/instructions/learn.md` that instructs the extraction agent to:
   - Read review artifacts from `{reviews_dir}/`
   - Identify recurring patterns across reviewer findings
   - Extract 3-5 concise, actionable takeaways (one sentence each, max 150 chars)
   - Categorize each under fixed categories: `code-quality`, `testing`, `architecture`, `security`, `style`
   - Check existing learnings in `.colonyos/learnings.md` for duplicates and only output genuinely new insights
   - Output in a structured markdown format
4. **FR-4**: The learnings ledger (`.colonyos/learnings.md`) must use the format:
   ```markdown
   # ColonyOS Learnings Ledger

   ## Run: <run-id>
   _Date: YYYY-MM-DD | Feature: <summary>_

   - **[code-quality]** Always add docstrings to public functions
   - **[testing]** Run `pytest` before committing changes
   ```
5. **FR-5**: Cap the ledger at `max_entries` (default: 100). When appending would exceed the cap, prune the oldest run sections first (FIFO eviction by run section).
6. **FR-6**: Deduplication uses normalized text comparison (lowercase, whitespace-collapsed) within the extraction agent's prompt instructions. The agent receives the existing ledger and is told to skip entries that are duplicates or near-duplicates. No additional LLM call is needed — deduplication happens during extraction.
7. **FR-7**: Modify `_build_implement_prompt()` in `orchestrator.py` (line 133-152) to call `load_learnings_for_injection()` and append a `## Learnings from Past Runs` section to the system prompt, truncated to the most recent 20 entries.
8. **FR-8**: Modify `_build_fix_prompt()` in `orchestrator.py` (line 238-264) to similarly inject learnings into the fix phase system prompt.
9. **FR-9**: Add a `LearningsConfig` dataclass to `config.py` with fields `enabled: bool = True` and `max_entries: int = 100`. Add a `learnings: LearningsConfig` field to `ColonyConfig` (line 49-63). Parse the `learnings:` YAML section in `load_config()` and serialize in `save_config()`.
10. **FR-10**: Wire the learn phase into `orchestrator.run()` after the decision gate (line 1266-1276) and before the deliver phase (line 1277). The learn phase executes regardless of GO/NO-GO verdict. On NO-GO, the learn phase runs before the early return.
11. **FR-11**: The learn phase runs with read-only tools only (`["Read", "Glob", "Grep"]`) and a conservative budget of `min(0.50, config.budget.per_phase / 2)`.
12. **FR-12**: If the learn phase fails (agent error, budget exceeded, exception), log a warning via `_log()` and continue to the next step (deliver or early return). Never raise or propagate the exception.
13. **FR-13**: When `config.learnings.enabled` is `False`, skip the learn phase entirely — do not invoke the agent or read/write the ledger file.
14. **FR-14**: In the `status` command in `cli.py` (line 691), after displaying run summaries, show: `Learnings ledger: N entries` (or `Learnings ledger: not found` if the file does not exist).
15. **FR-15**: Add `learnings:` section to `DEFAULTS` dict in `config.py` (line 14-29) with `{"enabled": True, "max_entries": 100}`.

## Non-Goals

- **Semantic deduplication via embeddings** — Simple LLM-in-prompt deduplication is sufficient for v1. Embedding-based dedup is over-engineering for a ledger of ≤100 entries.
- **Category-aware injection filtering** — All learnings are injected into all phases. At ≤20 entries (~2000 chars), category routing adds complexity without meaningful benefit.
- **CLI management commands** (`colonyos learnings list/remove/edit`) — The ledger is a human-readable markdown file; users can edit it directly. CLI management is a follow-up feature.
- **Extensible categories** — The five categories are fixed. Adding custom categories requires schema validation and migration logic not justified for v1.
- **Automated quality scoring** — Bad learnings self-correct via FIFO eviction and human curation. Confidence thresholds are a v2 concern.
- **Learnings in review or plan phases** — Only implement and fix phases receive learnings injection in v1.

## Technical Considerations

### Architecture Fit
- The new `Phase.LEARN` enum value follows the exact `str, Enum` pattern used by existing phases (models.py line 12-19). Run log serialization writes `phase.value` as a string, so adding a new enum value is backward-compatible.
- The `LearningsConfig` dataclass follows the same pattern as `BudgetConfig` and `PhasesConfig` in config.py.
- The learn phase uses `run_phase_sync()` from `agent.py` with the same interface as all other phases.

### File Layout
- Learnings ledger: `.colonyos/learnings.md` — Sits alongside `config.yaml` in the `.colonyos/` directory. Not in `runs/` (which is gitignored) because the ledger should be committable and version-controlled.
- New module: `src/colonyos/learnings.py` — Encapsulates all ledger I/O, parsing, and formatting.
- New instruction: `src/colonyos/instructions/learn.md` — Extraction prompt template.

### Prompt Injection Mitigation
All personas agreed the threat model is bounded (the attacker already needs write access to the repo). Mitigations:
- Extraction agent runs with **read-only tools** (`Read`, `Glob`, `Grep` — no `Write`, `Edit`, `Bash`).
- Learnings are injected in a clearly delimited `## Learnings from Past Runs` block in the user-facing portion of the prompt.
- Each learning entry is capped at 150 characters.
- The extraction prompt explicitly instructs the agent to output only factual code-quality observations, not directives or meta-instructions.

### Backward Compatibility
- Existing `config.yaml` files without a `learnings:` section default to `enabled: True, max_entries: 100`.
- Existing run logs without a `"learn"` phase entry are unaffected — the `status` command iterates over `log.phases` dynamically.
- The learn phase is the only new phase; no existing phases are modified in behavior.

### Persona Consensus & Tensions
- **Strong consensus**: All 7 personas agreed that (a) NO-GO runs should extract learnings, (b) deduplication should start simple (not embeddings), (c) the ledger should be human-readable and editable, (d) 2000 chars of learnings will not degrade agent performance.
- **Tension on categories**: Jony Ive and the systems engineer favored category-aware filtering; all others favored injecting all learnings. Decision: inject all (simpler, 2KB is negligible).
- **Tension on Phase enum**: Linus Torvalds and Karpathy suggested LEARN should not be a Phase enum (treat as post-processing). Decision: add it as a Phase for cost tracking consistency — every agent call should appear in the run log with cost/duration.
- **Security concern**: The security engineer raised stored prompt injection via review artifacts. Mitigated by read-only tools, character caps, and structured extraction instructions.

## Success Metrics

1. **Learn phase executes**: After every completed run (GO or NO-GO), a `LEARN` phase result appears in the run log with cost and duration.
2. **Ledger grows**: After 5 runs, `.colonyos/learnings.md` contains 15-25 learning entries (3-5 per run).
3. **Injection works**: Implement and fix phase prompts include a `## Learnings from Past Runs` section when the ledger exists.
4. **Fix iteration reduction**: Over 10 runs, measure whether average fix iterations decrease (target: ≥20% reduction).
5. **Non-blocking**: Zero pipeline failures caused by learn phase errors in 50+ runs.
6. **Status visibility**: `colonyos status` displays the learnings entry count.

## Open Questions

1. **Ledger file in `.gitignore`?** — The current `.gitignore` likely ignores `.colonyos/runs/` but not `.colonyos/` itself. The learnings file should be committable. Verify and update `.gitignore` if needed.
2. **Learnings in standalone review?** — Should `run_standalone_review()` also extract learnings? Deferred to v2.
3. **Cross-project learnings?** — Should learnings be shareable across repos (e.g., via a global `~/.colonyos/learnings.md`)? Deferred to v2.
4. **Recurrence weighting?** — Jony Ive suggested requiring a pattern to appear in 2+ reviews before promoting to the ledger. Worth considering for v2 but adds complexity to v1.
