# Tasks: PostHog Telemetry Integration

## Relevant Files

- `src/colonyos/config.py` - Add `PostHogConfig` dataclass, `_parse_posthog_config()`, update `ColonyConfig`, `load_config()`, `save_config()`
- `src/colonyos/telemetry.py` - **New file** — Core telemetry module with lazy PostHog import, anonymous ID, capture wrapper, shutdown
- `src/colonyos/orchestrator.py` - Add telemetry capture calls at run/phase lifecycle boundaries
- `src/colonyos/cli.py` - Add `cli_command` capture at CLI entry points and `shutdown()` at exit
- `src/colonyos/doctor.py` - Add PostHog API key soft check when `posthog.enabled` is true
- `pyproject.toml` - Add `posthog = ["posthog>=3.0"]` to optional dependencies
- `tests/test_telemetry.py` - **New file** — Tests for telemetry module (capture, no-op when disabled, silent failures, data safety)
- `tests/test_config.py` - Add tests for PostHogConfig parsing, serialization, defaults
- `tests/test_orchestrator.py` - Add tests verifying telemetry calls during run lifecycle

## Tasks

- [x] 1.0 Add PostHog configuration to config system
  - [x] 1.1 Write tests for `PostHogConfig` parsing — defaults when no section, parsed from YAML, serialization round-trip, invalid values (add to `tests/test_config.py`)
  - [x] 1.2 Add `PostHogConfig` dataclass to `config.py` with `enabled: bool = False`
  - [x] 1.3 Add `posthog` field to `ColonyConfig` dataclass with `PostHogConfig` default
  - [x] 1.4 Implement `_parse_posthog_config()` parser function following `_parse_slack_config()` pattern
  - [x] 1.5 Update `load_config()` to parse the `posthog:` YAML section
  - [x] 1.6 Update `save_config()` to serialize the `posthog` section (only when enabled)
  - [x] 1.7 Add `"posthog"` defaults to the `DEFAULTS` dict

- [x] 2.0 Create the telemetry module (`src/colonyos/telemetry.py`)
  - [x] 2.1 Write tests for the telemetry module — capture when enabled, no-op when disabled, no-op when SDK missing, silent exception handling, anonymous ID generation, property allowlist enforcement (create `tests/test_telemetry.py`)
  - [x] 2.2 Implement lazy `posthog` SDK import with `ImportError` guard (following `slack.py` pattern)
  - [x] 2.3 Implement anonymous installation ID generation — SHA256 hash persisted in `.colonyos/telemetry_id`
  - [x] 2.4 Implement `init_telemetry(config)` function that reads `PostHogConfig` and `COLONYOS_POSTHOG_API_KEY` env var
  - [x] 2.5 Implement `capture(event_name, properties)` wrapper with try/except and DEBUG logging
  - [x] 2.6 Implement property allowlist — only permitted fields pass through, all others are stripped
  - [x] 2.7 Implement `shutdown()` function to flush the PostHog queue with a short timeout
  - [x] 2.8 Implement convenience functions: `capture_run_started()`, `capture_phase_completed()`, `capture_run_completed()`, `capture_run_failed()`, `capture_cli_command()` with typed signatures

- [x] 3.0 Add optional dependency to `pyproject.toml`
  - [x] 3.1 Add `posthog = ["posthog>=3.0"]` to `[project.optional-dependencies]` in `pyproject.toml`

- [x] 4.0 Integrate telemetry into the orchestrator pipeline
  - [x] 4.1 Write tests verifying telemetry functions are called at correct lifecycle points in orchestrator (mock `telemetry.capture_*` functions, add to `tests/test_orchestrator.py`)
  - [x] 4.2 Import and call `init_telemetry()` at the start of `orchestrator.run()`
  - [x] 4.3 Call `capture_run_started()` after run initialization with model, phase config, persona count
  - [x] 4.4 Call `capture_phase_completed()` after each phase completes with phase name, model, cost, duration, success
  - [x] 4.5 Call `capture_run_completed()` or `capture_run_failed()` when the run finishes
  - [x] 4.6 Call `shutdown()` at the end of `orchestrator.run()`

- [x] 5.0 Integrate telemetry into the CLI layer
  - [x] 5.1 Write tests for CLI telemetry integration — `cli_command` event fires, shutdown called (add to `tests/test_cli.py`)
  - [x] 5.2 Add `capture_cli_command()` call in the main CLI group callback or individual commands (run, stats, init, queue, auto, show)
  - [x] 5.3 Register `shutdown()` as an atexit handler or in the CLI cleanup path

- [x] 6.0 Add PostHog check to `colonyos doctor`
  - [x] 6.1 Write tests for the doctor PostHog check — passes with env var set, fails when missing, skipped when disabled (add to existing doctor tests or `tests/test_config.py`)
  - [x] 6.2 Add soft check in `doctor.py` for `COLONYOS_POSTHOG_API_KEY` env var when `posthog.enabled` is true, following the Slack token check pattern (lines 106-131)

- [x] 7.0 Documentation and data transparency
  - [x] 7.1 Add a `telemetry` section to the project README documenting: what data is sent, what is never sent, how to opt in/out, env var names
  - [x] 7.2 Add inline code comments in `telemetry.py` documenting the property allowlist and the rationale for each blocked field
