# PRD: PostHog Telemetry Integration for ColonyOS

## Introduction/Overview

ColonyOS currently computes run analytics locally via `colonyos stats` (backed by `stats.py`), which reads JSON run logs from `.colonyos/runs/` and renders cost breakdowns, failure hotspots, review loop efficiency, and model usage. This is powerful for individual repos but provides zero cross-installation visibility.

This feature adds an opt-in PostHog integration that emits anonymized pipeline lifecycle events (run started, phase completed, run finished) to a PostHog instance, giving ColonyOS maintainers aggregate product intelligence: which model configurations yield the best cost-to-success ratios, where the pipeline fails most across the user base, and whether features like the learnings system improve outcomes over time.

### Persona Consensus & Tensions

**Unanimous agreement across all 7 personas:**
- **Server-side only** — Python SDK in the orchestrator/agent layer. No client-side JS in the React dashboard (it's a localhost tool, not a SaaS product).
- **Opt-in with `enabled: false` default** — follow the `SlackConfig`/`CIFixConfig` pattern in `config.py`. Never phone home without explicit consent.
- **Optional dependency** — `pip install colonyos[posthog]` with lazy imports. Never add PostHog to core deps.
- **Anonymized metadata only** — never send prompts, branch names, error strings, artifact content, or anything from `RunLog.prompt`. Only structural metadata (phase names, durations, costs, success booleans, model names).
- **Silent failures** — `try/except` around every PostHog call, log at DEBUG level, never block the pipeline. Analytics is a side-effect, never on the critical path.
- **No feature flags** — ColonyOS is a local CLI tool where `config.yaml` already controls behavior. Remote feature flags would introduce latency, a failure mode, and a trust violation for a tool that runs with `bypassPermissions`.

**Key tension — Primary consumer:**
- **Michael Seibel / Systems Engineer**: Build for end-users pointing at their own PostHog instance — makes the tool stickier and avoids maintainer privacy liability.
- **Steve Jobs / Jony Ive / Linus / Security / Karpathy**: This is for ColonyOS maintainers to understand aggregate usage patterns. End-users already have `colonyos stats`.

**Resolution**: Design the integration to be configurable (user provides their own `COLONYOS_POSTHOG_API_KEY` and optional `COLONYOS_POSTHOG_HOST`), but the primary documented use case is maintainer product analytics via an opt-in consent flow. End-users who want their own PostHog instance can use the same mechanism.

**Minor tension — Event count:**
- Most personas converge on 4-5 core events. Systems Engineer adds queue/budget events. Karpathy adds `learning_extracted` and `config_shape`.

**Resolution**: Ship 5 core events (run_started, phase_completed, run_completed, run_failed, cli_command). Additional events (queue, learnings, budget) can be added incrementally.

## Goals

1. **Cross-installation visibility** — Enable ColonyOS maintainers to see aggregate success rates, failure patterns, and cost trends across all opt-in installations.
2. **Model optimization data** — Understand which `phase_models` configurations produce the best cost-to-quality ratios across the user base.
3. **Zero-impact integration** — PostHog must never slow down, block, or alter any pipeline run. The tool must work identically with or without PostHog.
4. **Trust-preserving design** — Opt-in only, anonymized metadata only, no prompts or code ever sent, clear documentation of exactly what is transmitted.
5. **Consistent codebase patterns** — Follow the established `SlackConfig` / `CIFixConfig` / optional-dependency patterns exactly.

## User Stories

1. **As a ColonyOS maintainer**, I want to see aggregate run success rates across all opt-in installations so I can identify which phases are most fragile.
2. **As a ColonyOS maintainer**, I want to know which model tier configurations (e.g., haiku for implement, opus for review) produce the best outcomes so I can recommend defaults.
3. **As a ColonyOS user**, I want to opt in to telemetry via a simple config flag so I can help improve the tool while knowing exactly what data leaves my machine.
4. **As a ColonyOS user**, I want telemetry to be completely invisible during runs — no slowdowns, no error messages, no behavioral changes.
5. **As a team running ColonyOS at scale**, I want to point telemetry at our own PostHog instance so we can track our own pipeline performance in our observability stack.

## Functional Requirements

### FR-1: PostHog Configuration
1.1. Add a `PostHogConfig` dataclass to `config.py` with fields: `enabled` (bool, default `False`).
1.2. Add `posthog` field to `ColonyConfig` dataclass using `PostHogConfig`, following the `SlackConfig` pattern.
1.3. Parse `posthog:` section from `config.yaml` via `_parse_posthog_config()` in `config.py`.
1.4. Serialize `posthog` section in `save_config()`.
1.5. Read `COLONYOS_POSTHOG_API_KEY` and optional `COLONYOS_POSTHOG_HOST` from environment variables only — never from config.yaml.
1.6. Add PostHog token validation to `doctor.py` (soft check when `posthog.enabled` is true).

### FR-2: Telemetry Module (`telemetry.py`)
2.1. Create `src/colonyos/telemetry.py` as the single module responsible for all PostHog interactions.
2.2. Lazy-import `posthog` SDK — if not installed, all functions become silent no-ops.
2.3. Initialize PostHog client on first use with API key from env var and optional custom host.
2.4. Generate and persist an anonymous installation ID (SHA256 hash of machine identifier + config directory path) as the `distinct_id` — never use a user identifier.
2.5. Provide a `capture(event_name, properties)` wrapper that catches all exceptions and logs at DEBUG level.
2.6. Provide a `shutdown()` function to flush the PostHog queue on process exit.

### FR-3: Event Definitions
3.1. `run_started` — Properties: model, phase_config (which phases enabled), persona_count, budget_per_run, colonyos_version.
3.2. `phase_completed` — Properties: phase_name, model, cost_usd, duration_ms, success (bool).
3.3. `run_completed` — Properties: status, total_cost_usd, total_duration_ms, phase_count, fix_iteration_count, colonyos_version.
3.4. `run_failed` — Properties: failing_phase_name, colonyos_version.
3.5. `cli_command` — Properties: command_name (e.g., "run", "stats", "init", "queue"), colonyos_version.

### FR-4: Data Safety
4.1. Maintain an explicit allowlist of properties that may be sent. All other `RunLog`/`PhaseResult` fields are blocked.
4.2. Never send: `prompt`, `branch_name`, `prd_rel`, `task_rel`, `source_issue`, `source_issue_url`, `error` strings, `artifacts`, `project.name`, `project.description`, persona content.
4.3. Document the exact data transmitted in the README or a dedicated `TELEMETRY.md` file.

### FR-5: Orchestrator Integration
5.1. Call `telemetry.capture("run_started", ...)` at the start of `orchestrator.run()`.
5.2. Call `telemetry.capture("phase_completed", ...)` after each phase completes in the orchestrator loop.
5.3. Call `telemetry.capture("run_completed", ...)` or `telemetry.capture("run_failed", ...)` when a run finishes.
5.4. Call `telemetry.capture("cli_command", ...)` in the Click CLI entry points.
5.5. Call `telemetry.shutdown()` in CLI cleanup/exit handlers.

### FR-6: Optional Dependency
6.1. Add `posthog = ["posthog>=3.0"]` to `[project.optional-dependencies]` in `pyproject.toml`.
6.2. Use lazy import with `ImportError` guard and helpful install message, following the Slack SDK pattern.

## Non-Goals

- **Client-side React dashboard tracking** — The web dashboard is a localhost tool. No PostHog JS SDK.
- **PostHog feature flags** — `config.yaml` is the feature flag system. No remote behavior control.
- **Full prompt or code telemetry** — Never. Only anonymized structural metadata.
- **Replacing `colonyos stats`** — Local stats remain the primary analytics tool for end-users. PostHog supplements with cross-installation data.
- **Automatic opt-in / opt-out prompts** — No interactive consent flows. Users configure `posthog.enabled: true` in config.yaml manually.
- **Real-time dashboards or alerts** — PostHog ingestion only. Dashboard/alerting configuration is done in PostHog's UI, not in ColonyOS.

## Technical Considerations

### Existing Patterns to Follow
- **Config dataclass**: `SlackConfig` in `config.py` (lines 78-86) — `PostHogConfig` follows the same `@dataclass` + parser + DEFAULTS pattern.
- **Optional dependency**: Slack SDK in `pyproject.toml` (line 30) and lazy import in `slack.py` — same pattern for `posthog`.
- **Doctor checks**: Slack token validation in `doctor.py` (lines 106-131) — same pattern for PostHog API key.
- **Save/load config**: `_parse_slack_config()` and `save_config()` slack section — same pattern for PostHog.

### Key Files to Modify
- `src/colonyos/config.py` — Add `PostHogConfig`, parsing, serialization
- `src/colonyos/orchestrator.py` — Add telemetry capture calls at run/phase lifecycle points
- `src/colonyos/cli.py` — Add `cli_command` capture and `shutdown()` call
- `src/colonyos/doctor.py` — Add PostHog token check
- `pyproject.toml` — Add `posthog` optional dependency group

### New Files
- `src/colonyos/telemetry.py` — The single telemetry module (all PostHog interactions isolated here)
- `tests/test_telemetry.py` — Tests for the telemetry module

### Dependencies
- `posthog>=3.0` (optional) — Python SDK, pulls in `requests`, `backoff`, `python-dateutil`

### Performance
- PostHog Python SDK supports async batch mode — events are queued in-memory and flushed periodically, not sent synchronously per call.
- All capture calls wrapped in `try/except` with no retries beyond what the SDK does internally.
- `shutdown()` called once at CLI exit to flush remaining events with a short timeout.

## Success Metrics

1. **Adoption**: >10% of active ColonyOS installations opt in to telemetry within 30 days of release.
2. **Data quality**: All 5 core events fire correctly for every pipeline run on opt-in installations.
3. **Zero impact**: No measurable increase in run duration or failure rate attributable to telemetry.
4. **Actionable insights**: Within 60 days, at least one product decision (model default change, phase improvement) is informed by PostHog data.

## Open Questions

1. Should `colonyos init` include a prompt asking the user whether to enable telemetry, or should it remain a manual config.yaml edit?
2. Should we add a `colonyos telemetry on/off` convenience CLI command, or is editing config.yaml sufficient?
3. What is the right anonymous installation ID strategy? SHA256 of hostname + config path, or a random UUID persisted in `.colonyos/`?
4. Should the telemetry module also capture events from `colonyos auto` (CEO loop) and `colonyos watch` (Slack watcher), or just `colonyos run`?
