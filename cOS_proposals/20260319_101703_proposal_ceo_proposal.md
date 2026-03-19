## Proposal: Run Completion Notifications

### Rationale
ColonyOS excels at autonomous, long-running workflows (`auto --loop`, `queue start`, Slack-triggered runs), but once a user kicks off a pipeline, they have no way to learn about completion or failure without watching the terminal or manually checking `colonyos status`. A lightweight notification system that fires on run success/failure would close this critical feedback gap and make the autonomous experience truly hands-off.

### Builds Upon
- "Slack Integration (`colonyos watch`)" — reuses Slack client to post run-complete DMs/channel messages
- "GitHub Issue Integration" — posts a comment on the source issue when a run completes or fails
- "`colonyos queue` Durable Multi-Item Execution Queue" — queue completion summaries benefit most from notifications

### Feature Request
Add a **run completion notification system** with a `notifications` section in `.colonyos/config.yaml` and a `notify.py` module that dispatches messages when any pipeline run finishes (success, failure, or budget-exceeded).

**Notification channels to support:**

1. **Slack message** — Post a summary (run ID, feature title, status, cost, PR link if delivered) to a configured Slack channel or DM. Reuse the existing `slack-bolt` dependency and Slack config. Only fires if Slack is configured and enabled.

2. **GitHub issue comment** — If the run was triggered via `--issue`, post a comment on that issue with the outcome (e.g., "✅ PR #42 created" or "❌ Run failed in REVIEW phase"). Uses the existing `github.py` module and `gh` CLI.

3. **System desktop notification** — Use `osascript` on macOS or `notify-send` on Linux to fire a native desktop notification. Zero-dependency, best-effort (silently skip if unavailable).

4. **Webhook** — HTTP POST a JSON payload (run ID, status, cost, duration, PR URL) to a user-configured URL. Useful for custom integrations (Discord, PagerDuty, email relays). Use `urllib.request` from stdlib to avoid adding dependencies.

**Configuration format:**
```yaml
notifications:
  enabled: true
  on_success: true
  on_failure: true
  slack_channel: "#colony-notifications"   # optional, falls back to watch channel
  desktop: true
  webhook_url: "https://hooks.example.com/colonyos"  # optional
  github_comment: true  # comment on source issue
```

**Implementation details:**
- Add `src/colonyos/notify.py` with a `NotificationConfig` dataclass, `notify_run_complete(run_log, config)` dispatcher, and per-channel send functions.
- Wire `notify_run_complete()` into `orchestrator.py` at the end of `run()`, after the final phase completes (success path) and in the exception handler (failure path). Also wire into queue execution loop for per-item and queue-complete notifications.
- Add `notifications` parsing to `config.py` with sensible defaults (desktop=true, everything else off).
- During `colonyos init`, ask "Enable desktop notifications for completed runs? [Y/n]" — one question, no complex setup.
- Add `tests/test_notify.py` with unit tests for message formatting, channel dispatch (mocked), and config parsing.

**Acceptance criteria:**
- A run triggered via `colonyos run "..."` fires a desktop notification on completion.
- A run triggered via `--issue 42` that succeeds posts a comment on issue #42 with the PR link.
- A Slack-configured project posts a summary to the configured notification channel.
- A webhook-configured project POSTs a JSON payload to the URL.
- All channels are independently toggleable; disabled channels are silently skipped.
- `colonyos init` offers to enable desktop notifications.
- Notifications include: run ID, feature title, status (success/failure), total cost, duration, and PR URL (if applicable).