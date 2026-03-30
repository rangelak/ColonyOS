# ColonyOS Daemon — VM Deployment Guide

## Prerequisites

- Python 3.11+
- Git with `gh` CLI authenticated
- Slack Bot Token (`SLACK_BOT_TOKEN`) and App Token (`SLACK_APP_TOKEN`)
- Anthropic API Key (`ANTHROPIC_API_KEY`)
- systemd (Linux)

## Quick Start

1. **Clone and install**:
   ```bash
   cd /opt/colonyos
   git clone <your-repo-url> repo
   cd repo
   python -m venv ../venv
   ../venv/bin/pip install -e .
   ```

2. **Configure environment** — create `/opt/colonyos/env` owned by the
   `colonyos` user:
   ```bash
   ANTHROPIC_API_KEY=sk-ant-...
   COLONYOS_SLACK_BOT_TOKEN=xoxb-...
   COLONYOS_SLACK_APP_TOKEN=xapp-...
   GITHUB_TOKEN=ghp_...
   ```
   ```bash
   sudo chown colonyos:colonyos /opt/colonyos/env
   sudo chmod 600 /opt/colonyos/env
   ```
   > **Tip:** For production deployments, consider using `systemd-creds`
   > or a secrets manager (e.g., HashiCorp Vault, AWS Secrets Manager)
   > instead of a plaintext env file.

3. **Initialize ColonyOS**:
   ```bash
   cd /opt/colonyos/repo
   ../venv/bin/colonyos init
   ```

4. **Configure daemon** — edit `.colonyos/config.yaml`:
   ```yaml
   daemon:
     daily_budget_usd: 500.0
     allow_all_control_users: true
     github_poll_interval_seconds: 120
     ceo_cooldown_minutes: 60
   slack:
     enabled: true
     channels:
       - C12345678
   ```
   `slack.allowed_user_ids` is optional. If you leave it unset, any human user in
   the configured Slack channels can submit work into the queue. If you want to
   restrict queue submission to specific people, add their Slack user IDs under
   `slack.allowed_user_ids`.

   `daemon.allowed_control_user_ids` is a separate control-path allowlist for
   Slack pause/resume commands. Set `daemon.allow_all_control_users: true` if you
   want every Slack user in the configured channels to be able to send daemon
   control commands too.

5. **Install and start the service**:
   ```bash
   sudo cp deploy/colonyos-daemon.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable colonyos
   sudo systemctl start colonyos
   ```

6. **Verify**:
   ```bash
   sudo systemctl status colonyos
   sudo journalctl -u colonyos -f
   ```

## Monitoring

- **Logs**: `journalctl -u colonyos --since "1 hour ago"`
- **Health**: `curl http://localhost:8741/healthz`
- **Slack**: The daemon posts heartbeat messages every 4 hours
- **Daily digest**: Summary posted at the configured UTC hour

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Daemon won't start | `journalctl -u colonyos -e` for errors |
| No Slack messages | Verify `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in env file |
| Budget paused | Check `.colonyos/daemon_state.json` for `daily_spend_usd` |
| Circuit breaker active | Check `daemon_state.json` for `circuit_breaker_until` |
| Multiple instances | Check for stale `.colonyos/daemon.pid` file |

## Updating

```bash
cd /opt/colonyos/repo
git pull
../venv/bin/pip install -e .
sudo systemctl restart colonyos
```
