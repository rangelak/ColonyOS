# PRD: Prebuilt Persona Templates for `colonyos init`

## Introduction/Overview

Today, when users run `colonyos init`, they must manually define 3-5 personas from scratch — entering a role, expertise, and perspective for each one. This is a significant friction point in the onboarding flow, especially for users who are new to the concept and don't know what makes a good persona.

This feature introduces **prebuilt persona packs** — curated sets of personas that users can select during `colonyos init` instead of (or in addition to) defining custom ones. Think of them like starter templates: "Startup Team", "Enterprise Backend", "Frontend/Design", etc. Each pack ships with 3-5 well-crafted personas tailored to common project archetypes.

## Clarifying Questions & Persona Answers

### Q1: What problem does this actually solve? Are users struggling with persona creation today?

**YC Partner (Michael Seibel):** The init flow is the first thing users see. If they bounce here, nothing else matters. Typing out 3-5 personas from scratch is a cold-start problem — users don't know what "good" looks like. Prebuilt packs give them a working setup in seconds. This directly improves activation rate.

**Visionary CEO (Elon Musk):** The fundamental constraint is that users have to think about meta-configuration before they've even used the tool. Delete the thinking step — give them a default that works. The ideal init is zero questions: detect the stack, pick personas, done.

**Principal Systems Engineer:** The persona definitions directly affect PRD quality via `_format_personas_block()` in `orchestrator.py`. Bad personas = bad PRDs = wasted budget. Providing curated defaults reduces the chance of garbage-in-garbage-out.

**Open Source DX Lead (Sindre Sorhus):** Time-to-first-run is the metric that matters. Right now, the init wizard asks ~15 prompts before you can run anything. Prebuilt packs could cut the persona section from ~12 prompts (4 personas × 3 fields) to 1 selection prompt.

**Staff Security Engineer:** No security concerns with this specific feature — personas are just descriptive text, not executable. But the pack definitions should be bundled with the package (not fetched from a remote URL) to avoid supply chain risk.

### Q2: Where should prebuilt persona packs be defined — in code, in a data file, or fetched remotely?

**YC Partner:** Ship it in the package. Don't over-engineer. A Python dict or YAML file in the repo is fine for v1.

**Visionary CEO:** Bundled data. No network dependency for something this simple.

**Principal Systems Engineer:** A Python module (e.g., `src/colonyos/persona_packs.py`) with frozen dataclass instances is the simplest option. It's type-safe, testable, and doesn't add a file-loading dependency. Alternatively, a YAML file in `src/colonyos/` loaded at import time works too, but adds I/O to what should be a pure-data operation.

**Open Source DX Lead:** A Python module. It's discoverable, self-documenting, and IDE-friendly. Users who want to understand what packs are available can just read the file.

**Staff Security Engineer:** Bundled in the package. Never fetch persona definitions from a remote source — that's an injection vector for prompt manipulation.

### Q3: What persona packs should we ship initially?

**YC Partner:** Start with 3-4 packs covering the most common project types: a general "Startup" pack, a "Backend/API" pack, a "Full-Stack" pack, and maybe an "Open Source Library" pack. Don't overthink the categories — just cover 80% of users.

**Visionary CEO:** One universal "default" pack that works for any project, plus 2-3 specialized ones. Most users will pick the default and never think about it again.

**Principal Systems Engineer:** Each pack should have 3-5 personas with non-overlapping expertise. A "Backend" pack might include: API designer, database specialist, security auditor, SRE/ops, and product-minded engineer.

**Open Source DX Lead:** Include a pack description (one line) so users can pick without reading every persona. Like: `Startup Team — product-market fit, velocity, technical debt management`.

**Staff Security Engineer:** Every pack should include at least one security-focused persona. It's too easy to skip security review otherwise.

### Q4: How should the selection UX work during `colonyos init`?

**YC Partner:** Show a numbered list of packs. User picks one. Done. Offer "Custom" as the last option for power users.

**Visionary CEO:** Auto-detect the stack from the project info they just entered and suggest the best pack. One confirmation prompt instead of a selection menu.

**Principal Systems Engineer:** Use `click.Choice` or a numbered menu. After selecting a pack, show the personas it contains and ask for confirmation. Allow adding custom personas on top of a pack.

**Open Source DX Lead:** Numbered list with descriptions. After selection, print what you got. Offer to customize. This is the pattern every good CLI uses (like `npm init` or `cargo init`).

**Staff Security Engineer:** Fine with any UX. Just make sure the selected personas are written to `config.yaml` the same way custom ones are — no special "pack reference" that could be tampered with.

### Q5: Should users be able to mix prebuilt packs with custom personas?

**YC Partner:** Yes, but make it optional. Most users will just pick a pack and move on. Power users can add more.

**Visionary CEO:** Yes. Select a pack, then optionally add custom ones. The pack is the starting point, not a cage.

**Principal Systems Engineer:** The existing `collect_personas()` already supports starting with an existing list and adding more. We just need to seed it with the pack's personas instead of an empty list.

**Open Source DX Lead:** Absolutely. After applying a pack, ask "Add custom personas?" with a default of "no". Keep the happy path short.

**Staff Security Engineer:** No concerns. The end result in `config.yaml` is the same regardless of source.

### Q6: Should the `--personas` flag also support prebuilt packs?

**YC Partner:** Yes. It's the same flow — if you're re-doing personas, you should have the same options.

**Principal Systems Engineer:** The `--personas` flag calls `collect_personas(existing)` in `init.py`. We just need to insert the pack selection step before that call, in both the full init and personas-only paths.

**Open Source DX Lead:** Definitely. Consistency matters. Same flow, same options, regardless of entry point.

### Q7: How should this interact with the existing `collect_personas()` function?

**Principal Systems Engineer:** The cleanest approach: add a new function `select_persona_pack()` that returns `list[Persona] | None`. Call it before `collect_personas()`. If a pack is selected, pass its personas as the `existing` parameter. If "Custom" is selected, pass `None` (or the existing config personas). The existing function handles the rest.

**Open Source DX Lead:** Don't refactor `collect_personas()` — it already works well. Add the pack selection as a layer on top.

## Goals

1. **Reduce time-to-first-run** — Cut the persona section of `colonyos init` from ~12 prompts to 1-2 prompts for users who select a prebuilt pack.
2. **Improve persona quality** — Ship curated personas that produce better PRDs than ad-hoc user definitions.
3. **Maintain flexibility** — Users can still define fully custom personas or extend a prebuilt pack with custom additions.
4. **Zero new dependencies** — Persona packs are bundled Python data, no new packages or network calls.

## User Stories

1. **New user, quick setup:** "As a developer initializing ColonyOS for the first time, I want to pick a prebuilt persona pack so I can start running features in under 2 minutes without thinking about what personas to define."

2. **Experienced user, re-customizing:** "As a user running `colonyos init --personas`, I want to see the available packs and optionally switch from my current custom personas to a curated pack."

3. **Power user, hybrid setup:** "As a user who selected the 'Backend API' pack, I want to add one more custom persona (e.g., a compliance officer) on top of the pack's defaults."

4. **Curious user, browsing packs:** "As a user looking at the pack selection menu, I want to see a one-line description of each pack so I can pick the right one without reading every persona."

## Functional Requirements

1. **FR-1:** The system must include a `persona_packs` module at `src/colonyos/persona_packs.py` containing 4-5 prebuilt persona packs, each consisting of 3-5 `Persona` instances.
2. **FR-2:** Each persona pack must have a unique `key` (slug), a human-readable `name`, a one-line `description`, and an ordered list of `Persona` objects.
3. **FR-3:** During `colonyos init`, after collecting project info, the system must present a numbered menu of available packs plus a "Custom (define your own)" option.
4. **FR-4:** When a user selects a prebuilt pack, the system must display the pack's personas and ask for confirmation.
5. **FR-5:** After selecting a pack, the system must ask "Add custom personas on top?" (default: no). If yes, the existing `collect_personas()` flow runs with the pack's personas as the starting set.
6. **FR-6:** If the user selects "Custom", the existing `collect_personas()` flow runs unchanged.
7. **FR-7:** The `--personas` flag on `colonyos init` must also present the pack selection menu.
8. **FR-8:** Selected personas (whether from a pack, custom, or mixed) must be saved to `.colonyos/config.yaml` in the existing format — no pack references, just the flattened persona list.
9. **FR-9:** The minimum shipped packs must include: (a) Startup Team, (b) Backend/API, (c) Full-Stack Web, (d) Open Source Library.

## Non-Goals

- **Remote pack fetching** — No downloading packs from a registry or URL. All packs ship with the package.
- **User-defined pack files** — No mechanism for users to create `.yaml` pack files in their repo. They can define custom personas via the existing flow.
- **Pack versioning** — Packs are static per release. No migration or update mechanism.
- **Auto-detection of best pack** — No automatic stack-to-pack matching based on project info. (Good v2 idea, but out of scope.)
- **Pack editing** — No ability to modify a pack's built-in personas. Users can only add on top.

## Technical Considerations

### Files to Create
- **`src/colonyos/persona_packs.py`** — Pack definitions as frozen dataclasses. Contains a `PACKS` list and a `get_pack(key)` lookup function.

### Files to Modify
- **`src/colonyos/init.py`** — Add pack selection step in both the full init path and the `personas_only` path. Insert between project info collection and `collect_personas()`.
- **`src/colonyos/models.py`** — Add a `PersonaPack` dataclass (key, name, description, personas).

### Files to Create (Tests)
- **`tests/test_persona_packs.py`** — Unit tests for pack definitions, validation, and lookup.
- **`tests/test_init.py`** — Tests for the init flow with pack selection (mocking `click.prompt`).

### Architecture Notes
- The `Persona` dataclass in `models.py` is frozen and well-defined. Packs are just named collections of `Persona` instances.
- `collect_personas()` already accepts an `existing` parameter — pack personas can be passed through this, requiring zero changes to that function.
- The `save_config()` / `load_config()` roundtrip doesn't need changes — packs are flattened to persona lists before saving.
- The `_format_personas_block()` in `orchestrator.py` works on `list[Persona]` and needs no changes.

### Pack Data Structure
```python
@dataclass(frozen=True)
class PersonaPack:
    key: str            # e.g., "startup"
    name: str           # e.g., "Startup Team"
    description: str    # e.g., "Product-market fit, velocity, and pragmatic engineering"
    personas: tuple[Persona, ...]  # Immutable ordered list
```

## Success Metrics

1. **Activation improvement:** ≥70% of new users select a prebuilt pack instead of defining custom personas.
2. **Init completion time:** Median time through the persona section drops from ~90s to ~15s for pack users.
3. **No regression:** All existing tests continue to pass. Custom persona flow remains unchanged.
4. **Pack coverage:** ≥80% of users find a suitable pack without needing custom additions.

## Open Questions

1. **Exact pack contents:** What specific personas should each pack contain? This PRD defines the 4 pack categories but the exact role/expertise/perspective strings need design review.
2. **Pack ordering:** Should packs be listed alphabetically, or in a recommended order (e.g., most popular first)?
3. **Default selection:** Should one pack be pre-selected as the default (e.g., "Startup Team") or should the menu have no default?
4. **Future: auto-suggest:** In a future version, should the system suggest a pack based on the tech stack entered in project info? (e.g., "You mentioned FastAPI — the Backend/API pack might be a good fit.")
