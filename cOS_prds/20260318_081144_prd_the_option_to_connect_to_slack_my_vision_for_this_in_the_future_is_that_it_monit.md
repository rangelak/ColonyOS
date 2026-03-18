# PRD: Slack Integration for ColonyOS

## Introduction/Overview

ColonyOS currently accepts work through three input channels: CLI prompts (`colonyos run`), GitHub issues (`--issue`), and autonomous CEO proposals (`colonyos auto`). This feature adds Slack as a fourth input source, allowing team members to trigger the ColonyOS pipeline directly from Slack conversations — eliminating the context-switch between where bugs/features are discussed and where work gets executed.

The core value proposition: **ColonyOS should be wherever your team already talks, not the other way around.** A bug mentioned in a Slack channel at 2am can trigger a fix PR before anyone files a formal issue.

### Persona Consensus & Tensions

**Strong agreement across all personas:**
- Use **Slack Bolt SDK with Socket Mode** (no public URL needed, fits CLI-first architecture)
- Add as a **long-running CLI command** (`colonyos watch` or `colonyos slack`) following the existing `colonyos auto` pattern
- Store tokens as **environment variables**, never in `config.yaml`
- **Post back to Slack** via threaded replies with phase progress and PR links
- **Deduplicate** via a processed-message ledger keyed on Slack `ts` timestamps

**Key tension — Trigger mechanism:**
- **Michael Seibel / Steve Jobs / Jony Ive / Karpathy**: Phase 1 must include pipeline triggering (connectivity without action is a demo, not a product), but use explicit triggers (slash command, emoji reaction, `@mention`)
- **Linus Torvalds / Security Engineer**: Phase 1 should be connectivity + notification only; auto-triggering from untrusted Slack input into `bypassPermissions` agents is too risky without a proven classifier
- **Systems Engineer**: Include triggering but with a mandatory human-approval gate via Slack reaction

**Resolution**: Phase 1 includes end-to-end triggering but requires **explicit intent signals** (slash command, `@ColonyOS` mention, or emoji reaction) — not ambient message classification. This satisfies the "ship something useful" camp while addressing the security concerns. Ambient NLP classification is deferred to Phase 2.

**Key tension — LLM classification:**
- **Karpathy / Systems Engineer**: Use a haiku-tier LLM triage classifier with structured JSON output and confidence thresholds
- **Everyone else**: Don't try to be clever; require explicit human intent signals

**Resolution**: Phase 1 uses explicit triggers only. Phase 2 can add LLM-based ambient classification once there's training data from intentional invocations.

## Goals

1. **Add Slack as an input source** — team members can trigger ColonyOS pipeline runs from Slack without leaving the conversation
2. **Maintain CLI-first architecture** — Slack watcher runs as a long-lived CLI command, no cloud deployment required
3. **Provide in-Slack feedback** — threaded replies show pipeline progress and final PR links
4. **Reuse existing infrastructure** — leverage `LoopState`, heartbeat, budget caps, and content sanitization patterns already in the codebase
5. **Preserve security posture** — Slack content is untrusted input; apply the same sanitization as GitHub issues, scope tokens minimally

## User Stories

1. **As a developer**, I want to mention `@ColonyOS fix the login timeout bug` in a Slack channel so that a fix PR is created without me leaving the conversation.
2. **As a team lead**, I want to react with a `:colonyos:` emoji on a teammate's bug report so that ColonyOS picks it up and starts working on it.
3. **As a developer**, I want to see pipeline progress (planning → implementing → reviewing → delivered) as threaded replies in Slack so I know what's happening without checking the terminal.
4. **As a team lead**, I want to configure which Slack channels ColonyOS monitors so it only acts on messages in designated channels like `#eng-bugs` or `#feature-requests`.
5. **As a developer**, I want ColonyOS to post the PR link in the Slack thread when done so I can review it immediately.
6. **As an admin**, I want budget and time caps on Slack-triggered runs so a burst of messages doesn't blow through API spend.

## Functional Requirements

### FR-1: Slack Configuration
1.1. Add a `slack` section to `ColonyConfig` in `config.py` with fields: `enabled` (bool), `channels` (list of channel name/ID strings), `trigger_mode` (enum: `mention`, `reaction`, `slash_command`), `auto_approve` (bool, default false), `max_runs_per_hour` (int, default 3).
1.2. Store `COLONYOS_SLACK_BOT_TOKEN` and `COLONYOS_SLACK_APP_TOKEN` as environment variables only — never in config.yaml.
1.3. Add Slack token validation to `colonyos doctor` in `doctor.py`.

### FR-2: Slack Listener (`colonyos watch` CLI command)
2.1. Add a `watch` command to `cli.py` that starts a Slack Bolt Socket Mode listener as a long-running foreground process.
2.2. Support `--max-hours`, `--max-budget`, `--verbose`, `--quiet` flags mirroring the `auto` command.
2.3. Reuse `LoopState` persistence and `_touch_heartbeat` for liveness monitoring via `colonyos status`.
2.4. Handle graceful shutdown on SIGINT/SIGTERM.

### FR-3: Message Ingestion & Trigger Detection
3.1. Listen for app mentions (`@ColonyOS <prompt>`) in configured channels.
3.2. Listen for specific emoji reactions on messages in configured channels.
3.3. Ignore bot messages, edited messages, and messages from channels not in the allowlist.
3.4. Extract the prompt text from the triggering message.

### FR-4: Content Sanitization
4.1. Apply `_sanitize_untrusted_content` (XML tag stripping) from `github.py` to all Slack message content before it enters any prompt.
4.2. Wrap Slack content in `<slack_message>` delimiters with a preamble anchoring the model's role, mirroring the `<github_issue>` pattern in `format_issue_as_prompt`.
4.3. Never echo raw Slack message content back into bot posts (prevent reflected prompt injection).

### FR-5: Pipeline Triggering
5.1. When triggered, call `run_orchestrator()` with the extracted and sanitized prompt, exactly as the CLI `run` command does.
5.2. If `auto_approve` is false (default), post a confirmation message in-thread and wait for an approval reaction before proceeding.
5.3. Enforce `max_runs_per_hour` rate limiting per channel.
5.4. Enforce existing `BudgetConfig` caps (`per_run`, `max_total_usd`).

### FR-6: Slack Feedback (Threaded Replies)
6.1. React to the triggering message with an emoji (e.g., 👀) to acknowledge detection.
6.2. Post a threaded reply with the extracted prompt and estimated cost.
6.3. Post phase completion updates in the thread (plan ✓, implement ✓, review ✓, deliver ✓).
6.4. Post a final summary with PR link, total cost, and status — mirroring `_print_run_summary()`.
6.5. React to the original message with ✅ on success or ❌ on failure.

### FR-7: Deduplication
7.1. Maintain a `slack_processed.json` ledger in `.colonyos/runs/` keyed on `{channel_id, message_ts}`.
7.2. Before triggering, check the ledger; if already processed, reply with a link to the existing run.
7.3. Use atomic file writes (temp + rename) matching `_save_loop_state` pattern.

## Non-Goals

- **Ambient NLP classification** — Phase 1 requires explicit triggers only; no passive monitoring of all messages to guess intent
- **Cloud/server deployment** — The watcher runs as a local CLI process; hosting is a separate future feature
- **Slack slash commands** — Requires a public URL for Slack's request verification; deferred until cloud deployment
- **DM support** — Bot only responds in configured channels, not in direct messages
- **Private channel access** — Bot must be explicitly invited to channels; no admin-level access
- **Thread monitoring** — Only top-level channel messages trigger the bot, not replies within threads

## Technical Considerations

### Architecture Fit
The Slack watcher follows the exact same pattern as `colonyos auto` in `cli.py`:
- Long-running foreground process with `LoopState` persistence
- Heartbeat file for liveness (`_touch_heartbeat` in `orchestrator.py`)
- Budget caps (`BudgetConfig` in `config.py`)
- Calls `run_orchestrator()` as the single entry point (defined in `orchestrator.py`)

### New Dependency
- `slack-bolt>=1.18` — added to `pyproject.toml` alongside existing deps (`click`, `pyyaml`, `claude-agent-sdk`, `rich`)
- Socket Mode requires `slack-bolt[socket-mode]` which pulls in `websocket-client`

### Key Files to Modify
- `src/colonyos/config.py` — Add `SlackConfig` dataclass and parsing
- `src/colonyos/cli.py` — Add `watch` command
- `src/colonyos/doctor.py` — Add Slack token validation check
- `src/colonyos/models.py` — Add `SlackWatchState` dataclass
- `src/colonyos/github.py` — Extract `_sanitize_untrusted_content` for reuse (or move to a shared `sanitize.py`)

### New Files
- `src/colonyos/slack.py` — Slack client, message formatting, listener setup
- `tests/test_slack.py` — Unit tests for Slack integration

### Security Considerations (per Staff Security Engineer)
- Slack messages are untrusted input flowing into `bypassPermissions` agents — same risk profile as GitHub issues
- Channel allowlist is a hard security boundary, not a convenience feature
- Sender allowlist (optional `slack.allowed_user_ids` config) provides defense-in-depth
- Content sanitization via `_sanitize_untrusted_content` is necessary but not sufficient
- Bot OAuth scopes must be minimal: `channels:history`, `channels:read`, `chat:write`, `reactions:read`, `reactions:write`, `app_mentions:read`, `connections:write`

## Success Metrics

1. **End-to-end latency**: Time from Slack trigger to pipeline start < 10 seconds
2. **Reliability**: Watcher uptime > 99% during active sessions (no silent disconnects without reconnection)
3. **Adoption signal**: Users trigger at least 1 pipeline run per day via Slack within first week of deployment
4. **Zero false executions**: No pipeline runs triggered without explicit user intent in Phase 1
5. **Cost containment**: Slack-triggered runs stay within configured `per_run` budget caps

## Open Questions

1. **Emoji choice**: Should we use a custom `:colonyos:` emoji or a standard emoji (e.g., 🐜) for reaction-based triggers? Custom requires workspace admin setup.
2. **Concurrent runs**: If two Slack messages trigger simultaneously, should they queue or run in parallel? Current `run_orchestrator` assumes sequential git operations on one branch.
3. **Multi-repo support**: If ColonyOS is initialized in multiple repos, should one Slack bot instance serve all of them, or one watcher per repo?
4. **Message context**: Should the bot include surrounding conversation context (previous N messages in channel) to give the LLM more context about the bug/feature, or just the single triggering message?
5. **Slack workspace permissions**: Who installs the Slack app — individual developers or workspace admins? This affects the onboarding flow for `colonyos init`.
