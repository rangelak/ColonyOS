# PRD: AI-Assisted Setup for ColonyOS Init

## 1. Introduction / Overview

The current `colonyos init` command is a sequential wizard with 8-10 `click.prompt()` calls that require users to already understand persona packs, model presets, and budget thresholds. This creates a significant onboarding barrier — new users who just ran `pip install colonyos` must become experts in ColonyOS configuration before they can run their first pipeline.

This feature adds a second init mode: **AI-assisted setup**, where Claude (via the existing `claude_agent_sdk`) reads the repository, auto-detects project info, selects the best persona pack and model preset, and proposes a complete config for the user to confirm. The manual wizard remains available via a `--manual` flag. The result is a dramatically faster time-to-first-run without sacrificing config quality.

## 2. Goals

1. **Reduce time-to-first-run by 50%+** — AI-assisted init should complete in under 60 seconds, compared to 2-3 minutes for the manual wizard.
2. **Smart defaults over blind defaults** — Unlike `--quick` which always picks the first persona pack, the AI mode reads the actual repo and makes an informed choice.
3. **Zero jargon exposure** — New users should never need to understand "persona packs" or "model presets" to get a working config.
4. **Graceful degradation** — If the LLM call fails (no API key, network error, rate limit), fall back seamlessly to the manual wizard.
5. **Minimal cost** — The init conversation should cost under $0.05 using Haiku.

## 3. User Stories

**US-1: New user, first time**
> As a developer who just installed ColonyOS, I run `colonyos init` and a friendly assistant reads my repo, proposes a config ("I see this is a Python/FastAPI project — here's what I recommend"), and I confirm with a single "y". I'm running `colonyos run` within 30 seconds.

**US-2: Experienced user, manual mode**
> As a power user who wants full control, I run `colonyos init --manual` and get the exact same wizard I've always used. Nothing is broken.

**US-3: User with no API credits**
> As a user whose API key is missing or expired, I run `colonyos init` and the tool detects this, shows a friendly message, and falls back to the manual wizard automatically.

**US-4: User with an unusual project**
> As a user with a monorepo that doesn't fit neatly into the four persona packs, I see the AI's proposal, say "no", and drop into the manual wizard to customize.

## 4. Functional Requirements

### FR-1: Mode Selection
- `colonyos init` (no flags) → AI-assisted mode (default)
- `colonyos init --manual` → existing manual wizard
- `colonyos init --quick` → existing quick mode (unchanged)
- `colonyos init --personas` → existing personas-only mode (unchanged)

### FR-2: Repo Auto-Detection (Deterministic, Pre-LLM)
Before the LLM call, Python code must scan for and read (truncated to ~2000 chars each):
- `README.md` / `README.rst`
- `package.json`
- `pyproject.toml`
- `Cargo.toml`
- `go.mod`
- `requirements.txt`
- `Gemfile`
- `pom.xml` / `build.gradle`
- `.github/workflows/*.yml` (first file only)

This produces a structured `RepoContext` with detected project name, description, and tech stack signals. This step uses zero LLM tokens.

### FR-3: LLM-Powered Config Generation
- Use a **single LLM call** (not multi-turn conversation) to propose a complete config.
- Model: **Haiku** (cost-effective, sufficient for classification/config tasks).
- Budget cap: **$0.50** via `max_budget_usd`.
- Max turns: **3** via `max_turns`.
- Allowed tools: **Read, Glob, Grep only** (no Write, Edit, or Bash — least privilege).
- The system prompt must contain:
  - The detected `RepoContext` from FR-2
  - The full list of persona packs from `PACKS` in `persona_packs.py`
  - The `MODEL_PRESETS` dict from `init.py`
  - The `DEFAULTS` dict from `config.py`
  - The `ColonyConfig` schema (field names and types)
- The LLM must output structured JSON matching the `ColonyConfig` shape, constrained to:
  - Selecting a `pack_key` from `["startup", "backend", "fullstack", "opensource"]`
  - Selecting a `preset_name` from `["Quality-first", "Cost-optimized"]`
  - Filling in `project.name`, `project.description`, `project.stack`
  - Optionally suggesting a `vision` string

### FR-4: Config Preview and Confirmation
- Render the proposed config as a formatted Rich panel showing:
  - Project name, description, tech stack
  - Selected persona pack name + list of persona roles
  - Model preset name + per-phase model assignments
  - Budget settings
- Single `click.confirm("Save this configuration?", default=True)` gate
- On "yes": save via existing `save_config()`, create directories, update `.gitignore`
- On "no": fall back to manual wizard with AI-proposed values pre-filled as defaults

### FR-5: Graceful Error Handling
- If Claude SDK auth fails → print friendly message, fall back to manual wizard
- If LLM call times out (>30 seconds) → fall back to manual wizard
- If LLM output fails JSON parsing or validation → fall back to manual wizard
- All fallbacks must be seamless — no stack traces, no partial state

### FR-6: Cost Transparency
- Before the LLM call, display: "Using Claude Haiku to analyze your repo (typically <$0.05)..."
- After completion, display the actual cost from `ResultMessage.total_cost_usd`

## 5. Non-Goals

- **Multi-turn conversational setup** — v1 is single-shot detect-propose-confirm. A chatbot-style back-and-forth is explicitly deferred to v2.
- **Custom persona generation** — The LLM selects from the 4 existing packs. Generating novel personas introduces prompt injection risks (persona `perspective` strings flow into downstream system prompts running under `bypassPermissions`) and quality control problems.
- **Vision/strategy inference** — The `vision` field defaults to empty unless the README contains obvious mission-statement text.
- **Interactive config editing in AI mode** — If the user wants to tweak individual fields, they use `--manual` or edit `config.yaml` directly.
- **Changing the `--quick` mode** — It remains a separate, non-interactive path.

## 6. Technical Considerations

### Architecture
The AI-assisted init is a new function `run_ai_init()` in `src/colonyos/init.py` that:
1. Calls a new `scan_repo_context(repo_root)` function to deterministically gather repo signals
2. Builds a system prompt with the schema, packs, presets, and defaults
3. Invokes `run_phase_sync()` from `agent.py` with `Phase.PLAN` (or a new lightweight `Phase` if needed), Haiku model, $0.50 budget, and restricted `allowed_tools=["Read", "Glob", "Grep"]`
4. Parses the structured JSON response
5. Validates against `VALID_MODELS`, `pack_keys()`, and budget sanity checks
6. Constructs a `ColonyConfig` using the existing dataclasses
7. Renders preview and prompts for confirmation
8. On confirmation, delegates to the existing directory-creation and `.gitignore` logic already in `run_init()`

### Security (per Staff Security Engineer consensus)
- **Least privilege**: Init agent gets only `Read`, `Glob`, `Grep` — no `Write`, `Edit`, `Bash`
- **No `bypassPermissions`**: Use `"default"` permission mode for the init call since no writes are needed
- **Constrained output**: LLM picks from predefined pack keys and preset names; Python code constructs the config, not the LLM
- **No custom persona text**: Avoids prompt injection vectors where LLM-authored `perspective` strings propagate into future `bypassPermissions` agents
- **Sanitization**: If custom personas are added in v2, all LLM-generated text must pass through `sanitize_untrusted_content()` from `sanitize.py`

### Key Files to Modify
| File | Change |
|------|--------|
| `src/colonyos/init.py` | Add `scan_repo_context()`, `run_ai_init()`, `_build_init_system_prompt()`, `_parse_ai_config_response()` |
| `src/colonyos/cli.py` | Add `--manual` flag to `init` command, route to `run_ai_init()` by default |
| `src/colonyos/config.py` | Add `init_mode` field to `ColonyConfig` for telemetry (optional) |
| `src/colonyos/models.py` | Add `RepoContext` dataclass |
| `tests/test_init.py` | Add tests for all new functions |

### Dependencies
- No new dependencies. Uses existing `claude_agent_sdk`, `rich`, `click`, `yaml`.
- Haiku model availability is the only external dependency.

## 7. Success Metrics

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Time from `init` to first `run` | < 60 seconds | Compare config file mtime to first RunLog timestamp in `.colonyos/runs/` |
| Config acceptance rate | > 70% of users accept AI proposal on first try | Track whether user confirms "yes" vs falls back to manual |
| Init completion rate | > 90% of init starts lead to a saved config | Log init events |
| Init cost | < $0.05 median | Log `ResultMessage.total_cost_usd` |
| Re-init rate | < 20% re-run init within 3 runs | Compare config file modification times |

## 8. Open Questions

1. **Should AI-assisted be the true default, or should it be behind `--ai`?** — Strong consensus from personas (5/7) says make it the default, but Linus and the Security Engineer argue for `--ai` flag to avoid surprising users with API calls. **Recommendation**: Default to AI-assisted, with clear upfront messaging about the API call.

2. **Should we add a `Phase.INIT` enum value or reuse `Phase.PLAN`?** — Using PLAN works but may confuse analytics. A dedicated INIT phase is cleaner but touches more files.

3. **Should the preview show raw YAML or a formatted summary?** — Jony Ive argues for the actual YAML (what you see is what you get), while others prefer a Rich panel summary. **Recommendation**: Show a Rich summary panel by default, with the full YAML visible if `--verbose` is passed.

## Persona Synthesis

### Areas of Agreement (All 7 personas)
- **Auto-detection is the core value**: Reading the repo to infer project info is the single most important capability and the primary justification for using an LLM.
- **Single-shot, not chatbot**: V1 should be detect → propose → confirm. Multi-turn conversation adds latency and cost without proportional value.
- **Use Haiku**: This is a classification/selection task, not complex reasoning. Haiku at <$0.01 per init is the right choice.
- **Constrain LLM output**: The LLM selects from predefined options (pack keys, preset names); Python code constructs the config. Do not let the LLM write YAML directly.
- **Fallback is mandatory**: Any LLM failure must gracefully fall back to the manual wizard.
- **No custom personas in v1**: Quality control and prompt injection risks make this a v2 feature.

### Areas of Tension
- **Default mode**: Michael Seibel, Steve Jobs, Jony Ive, and Karpathy want AI-assisted as the default (best first impression). Linus and the Security Engineer prefer an explicit `--ai` flag (no surprise API calls). The Systems Engineer is neutral.
- **Preview format**: Jony Ive wants the actual YAML artifact shown. Karpathy wants a clean Rich summary. Others are neutral.
- **Deterministic vs LLM file scanning**: Karpathy strongly argues for deterministic Python-based file scanning before the LLM call (inject facts, don't let the model explore). The Systems Engineer agrees. Others assume the LLM does the reading.
