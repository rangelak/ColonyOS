# ColonyOS Telemetry

ColonyOS includes an **opt-in** PostHog telemetry integration that sends anonymized pipeline lifecycle events. Telemetry is **disabled by default** and never activates without explicit user consent.

## How to opt in

1. Add to your `.colonyos/config.yaml`:

   ```yaml
   posthog:
     enabled: true
   ```

2. Set the PostHog API key as an environment variable:

   ```bash
   export COLONYOS_POSTHOG_API_KEY="phc_your_key_here"
   ```

3. Optionally, point to a custom PostHog instance:

   ```bash
   export COLONYOS_POSTHOG_HOST="https://your-posthog.example.com"
   ```

4. Install the PostHog SDK:

   ```bash
   pip install 'colonyos[posthog]'
   ```

## How to opt out

Remove or set `enabled: false` in `config.yaml`:

```yaml
posthog:
  enabled: false
```

Or simply unset the environment variable:

```bash
unset COLONYOS_POSTHOG_API_KEY
```

## What data is sent

Only anonymized structural metadata. The following properties are on the allowlist:

| Event | Properties |
|---|---|
| `run_started` | `model`, `phase_config` (which phases enabled), `persona_count`, `budget_per_run`, `colonyos_version` |
| `phase_completed` | `phase_name`, `model`, `cost_usd`, `duration_ms`, `success` |
| `run_completed` | `status`, `total_cost_usd`, `total_duration_ms`, `phase_count`, `fix_iteration_count`, `colonyos_version` |
| `run_failed` | `failing_phase_name`, `colonyos_version` |
| `cli_command` | `command_name`, `colonyos_version` |

Each event includes an anonymous `distinct_id` (SHA-256 hash of machine identifier + config directory path). This ID contains no personally identifiable information.

## What is never sent

The following data is **explicitly blocked** by the property allowlist and will never leave your machine:

- Prompts, feature descriptions, or any user-written text
- Branch names, file paths, or repository names
- PRD content, task content, or artifact content
- Error messages or stack traces
- GitHub issue URLs or issue numbers
- Project names or descriptions
- Persona definitions or review content
- Any code or diff content

## Design principles

- **Opt-in only**: Telemetry is disabled by default. No data is ever sent without `posthog.enabled: true` in config and a valid API key.
- **Optional dependency**: The PostHog SDK is not required for core ColonyOS functionality. If not installed, all telemetry functions are silent no-ops.
- **Silent failures**: All PostHog calls are wrapped in try/except. Telemetry errors are logged at DEBUG level and never block or slow the pipeline.
- **No feature flags**: ColonyOS does not use PostHog feature flags. `config.yaml` is the sole source of configuration.

## Verify with `colonyos doctor`

When telemetry is enabled, `colonyos doctor` checks for the `COLONYOS_POSTHOG_API_KEY` environment variable:

```
  ✓ PostHog API key
```
