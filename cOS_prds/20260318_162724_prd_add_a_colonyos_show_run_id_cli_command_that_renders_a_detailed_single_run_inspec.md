# PRD: `colonyos show <run-id>` — Single-Run Inspector

## 1. Introduction / Overview

ColonyOS currently offers two observability windows: a brief `_print_run_summary` table shown at the end of a live run (in `cli.py` lines 43–93), and `colonyos stats` which computes aggregates across all historical runs. There is no way to go back and inspect a single past run in detail — users must `cat` raw JSON files to understand what happened.

`colonyos show <run-id>` closes that gap. Given a run ID (or prefix), it loads the corresponding `run-*.json` from `.colonyos/runs/` and renders a rich, readable breakdown: header metadata, phase-by-phase timeline with cost/duration/status, and artifact links. It is the `git show` equivalent for ColonyOS runs.

## 2. Goals

1. **Post-hoc triage in < 10 seconds**: A developer who ran `colonyos auto` should be able to understand where cost accumulated and why a run succeeded/failed without reading raw JSON.
2. **Prefix-based lookup**: Users can type a partial run ID (timestamp fragment or hash suffix) and resolve to a unique run, with clear disambiguation when ambiguous.
3. **Machine-readable output**: `--json` flag outputs structured JSON to stdout for piping into `jq`, dashboards, or CI scripts.
4. **Architectural consistency**: Follow the proven data-layer / render-layer separation from `stats.py`.
5. **Testability**: All data logic covered by unit tests; rendering tested for no-crash and key content assertions.

## 3. User Stories

- **US-1**: As a developer, after `colonyos auto` completes (or fails), I run `colonyos show <run-id>` to see a phase-by-phase cost/duration breakdown so I can understand what happened.
- **US-2**: As a developer debugging a $17 run, I use `colonyos show c28fc6` (hash prefix) to quickly pull up the run without typing the full 37-character ID.
- **US-3**: As a developer building a monitoring dashboard, I use `colonyos show <id> --json | jq '.phases'` to extract phase data programmatically.
- **US-4**: As a developer, when I mistype a run ID, I get a clear "no matching run" error, or a list of ambiguous matches if multiple runs share the prefix.
- **US-5**: As a developer, I run `colonyos show <id> --phase review` to see extended detail for all review phases in a specific run.

## 4. Functional Requirements

### FR-1: Run Resolution by ID Prefix
- Accept a full or partial run ID as a positional argument.
- Match against filenames in `.colonyos/runs/run-*.json` using prefix matching (on run ID) and also substring matching on the hash suffix.
- If exactly one match: load and display it.
- If zero matches: print a clear error message and exit with non-zero code.
- If multiple matches: list all matching run IDs with their status and timestamp, then exit with non-zero code.
- Validate the input to prevent path traversal (reject `/`, `\`, `..` characters).

### FR-2: Run Header Panel
- Display: run ID, status (with color: green for completed, red for failed, yellow for running), branch name, total cost, wall-clock duration (start → end), and the original prompt (truncated to ~120 chars by default).
- If `source_issue_url` is present, display it.
- If `last_successful_phase` is set (indicating a resume), note it.

### FR-3: Phase Timeline Table
- One row per phase execution showing: phase name, model, duration (formatted via `_format_duration`), cost, status (✓/✗).
- **Collapse consecutive review phases** into a summary row like "review ×4 (round 1)" to prevent wall-of-text for runs with many review iterations. Show the aggregate cost and duration for the collapsed group.
- Fix phases and subsequent review blocks should start a new "round" visually.
- Phases from skipped resume sections should be visually distinct (dimmed).

### FR-4: Review Details Section (conditional)
- Show only if review phases exist in the run.
- Display: number of review rounds, number of fix iterations, per-round review count.
- This section uses data already computable from the phase list (no new schema fields needed).

### FR-5: Decision Gate Section (conditional)
- Show only if a `decision` phase exists.
- Display: success/failure status of the decision phase.

### FR-6: CI Section (conditional)
- Show only if `ci_fix` phases exist.
- Display: number of CI fix attempts, final CI fix status.

### FR-7: Artifact Links
- Display file paths for: PRD (`prd_rel`), task file (`task_rel`), branch name.
- Display GitHub PR URL if available (from `source_issue_url` or discoverable from branch).

### FR-8: `--json` Flag
- When passed, output the run data as formatted JSON to stdout and exit (no Rich rendering).
- Use `json.dumps` with `indent=2` (not raw file cat) so the schema is controlled.
- Output goes to stdout (not stderr like the Rich console).

### FR-9: `--phase <name>` Flag
- Filter the display to show extended detail for all executions of the named phase within the run.
- Show: sequence index, cost, duration, model, session_id, success/failure, error message if any.

## 5. Non-Goals

- **Session transcript display**: We will not fetch or display Claude conversation logs from session IDs. Users can use `session_id` to manually inspect if needed.
- **Token count tracking**: Not adding `input_tokens`/`output_tokens` to `PhaseResult` in this feature.
- **Artifact content rendering**: Not reading/displaying PRD or task file contents — only file paths.
- **Interactive TUI**: This is a static output command, not an interactive browser.
- **Cross-run comparison**: That's `stats` territory.
- **`--latest` shortcut**: Deferring to a follow-up (can be added trivially to the resolution logic).

## 6. Technical Considerations

### Architecture
- **New file**: `src/colonyos/show.py` — following the `stats.py` pattern with data-layer (pure functions returning dataclasses) and render-layer (Rich output functions).
- **CLI wiring**: New `show` command in `src/colonyos/cli.py` using Click, registered alongside `stats`.
- **Tests**: `tests/test_show.py` following the pattern in `tests/test_stats.py`.

### Key Dependencies
- `stats.load_run_logs()` — reuse for loading run files from the runs directory.
- `ui._format_duration()` — reuse for human-readable duration formatting.
- `config.runs_dir_path()` — reuse for locating the runs directory.
- `rich` library — Panel, Table, Console for rendering.

### Data Model
New dataclasses in `show.py`:
- `RunHeader` — metadata for FR-2
- `PhaseTimelineEntry` — per-row data for FR-3 (supports collapsed review groups)
- `ReviewSummary` — FR-4 computed data
- `ShowResult` — top-level container aggregating all sections

### Path Traversal Safety
The run ID input must be sanitized before use in file globbing. Reject any input containing `/`, `\`, or `..`. Construct glob patterns only within the hardcoded runs directory path.

### Review Phase Collapsing
The key UX challenge: runs can have 10+ review phases (the ci-fix run has 11). The phase timeline must collapse contiguous review blocks into summary rows. The collapsing logic is a pure function in the data layer, making it testable.

## 7. Persona Synthesis

### Areas of Agreement (all 7 personas)
- **Must-have feature**: Universal agreement that the gap between aggregate `stats` and raw JSON is a real usability problem.
- **Follow `stats.py` pattern**: Strong consensus on data/render separation in a new `show.py` file.
- **Prefix matching is essential**: Run IDs are too long to type fully; prefix/substring matching with disambiguation is the right UX.
- **`--json` is cheap and valuable**: Trivial to implement with the data/render split; ship in v1.
- **Collapse review phases**: The 19-phase ci-fix run makes this a critical UX decision.

### Areas of Tension
- **`--phase` flag**: Michael Seibel, Steve Jobs, Linus Torvalds, and Jony Ive say defer to v2. The Systems Engineer and Karpathy say include it (it's small and useful for triage). **Decision**: Include in v1 — it's ~30 lines of additional code and completes the drill-down story.
- **Data/render complexity**: Linus argues a simpler single-function approach is fine. Others prefer the full pattern. **Decision**: Follow the `stats.py` pattern — it's already proven, makes `--json` trivial, and keeps tests clean.
- **Prompt truncation**: Security Engineer recommends truncating prompts by default. Others want full visibility. **Decision**: Truncate in rich view (120 chars), full in `--json`.

## 8. Success Metrics

1. `colonyos show <full-id>` renders a complete run breakdown within 200ms for any run file under 1MB.
2. `colonyos show <prefix>` resolves unambiguously for 4+ character prefixes in a directory of 100+ runs.
3. `colonyos show <id> --json` outputs valid, parseable JSON.
4. Zero regressions in existing test suite.
5. 100% of new data-layer functions have unit tests.

## 9. Open Questions

1. Should `colonyos show` with no argument default to the most recent run? (Deferred — easy to add later.)
2. Should the phase timeline show `session_id` by default or only in `--phase` detail? (Current decision: only in `--phase` detail.)
3. Should the `stats` recent-trend view link to `show` with a hint like "Run `colonyos show <id>` for details"? (Nice follow-up.)
