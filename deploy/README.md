# ColonyOS Daemon — VM Deployment Guide

## Automated Provisioning (Recommended)

The fastest way to set up ColonyOS on a fresh Ubuntu 22.04+ VM:

```bash
# Clone the repo
git clone https://github.com/rangelak/ColonyOS.git /tmp/colonyos-setup
cd /tmp/colonyos-setup

# Run the provisioning script
sudo bash deploy/provision.sh

# With Slack support:
sudo bash deploy/provision.sh --slack

# Non-interactive (reads ANTHROPIC_API_KEY and GITHUB_TOKEN from env):
sudo ANTHROPIC_API_KEY=sk-ant-... GITHUB_TOKEN=ghp_... bash deploy/provision.sh --yes

# Preview what would be done:
sudo bash deploy/provision.sh --dry-run
```

The script handles everything: Python 3.11+, Node.js, GitHub CLI, pipx,
ColonyOS, systemd service, and environment file creation.

## Manual Setup

If you prefer manual control, follow these steps:

### Prerequisites

- Ubuntu 22.04+ (or similar Linux with systemd)
- Python 3.11-3.13 recommended
- Git with `gh` CLI authenticated
- Slack Bot Token (`COLONYOS_SLACK_BOT_TOKEN`) and App Token (`COLONYOS_SLACK_APP_TOKEN`)
- Anthropic API Key (`ANTHROPIC_API_KEY`)

### Steps

1. **Clone and install**:
   ```bash
   cd /opt/colonyos
   git clone <your-repo-url> repo
   cd repo
   python -m venv ../venv
   ../venv/bin/pip install -e ".[slack]"
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
     auto_recover_dirty_worktree: true
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

   `daemon.auto_recover_dirty_worktree: true` is recommended only for a dedicated
   daemon checkout. It lets the daemon preserve dirty state to recovery/stash,
   reset the repo, and retry once when queue execution is blocked by a dirty
   worktree preflight failure.

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

## Web Dashboard

The ColonyOS daemon automatically starts a web dashboard on port `8741`
(configurable via `daemon.dashboard_port` in `.colonyos/config.yaml`).

By default, the dashboard binds to `127.0.0.1` (localhost only). To expose it
externally, use a reverse proxy. **Do not bind to `0.0.0.0` in production —
always terminate TLS at the reverse proxy.**

### Reverse Proxy Setup

#### Caddy (recommended — automatic HTTPS)

```
colonyos.myapp.com {
    reverse_proxy localhost:8741
}
```

That's it — Caddy handles TLS certificates automatically via Let's Encrypt.

#### nginx

```nginx
server {
    listen 443 ssl http2;
    server_name colonyos.myapp.com;

    ssl_certificate     /etc/letsencrypt/live/colonyos.myapp.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/colonyos.myapp.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8741;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### CORS Configuration

When serving the dashboard from a subdomain, set the allowed origins so the
browser can reach the API:

```bash
# In /opt/colonyos/env
COLONYOS_ALLOWED_ORIGINS=https://colonyos.myapp.com
```

Multiple origins can be comma-separated:

```bash
COLONYOS_ALLOWED_ORIGINS=https://colonyos.myapp.com,http://localhost:5173
```

### Dashboard Configuration

In `.colonyos/config.yaml`:

```yaml
daemon:
  dashboard_enabled: true   # set to false to disable the web dashboard
  dashboard_port: 8741      # port the dashboard listens on
```

## Monitoring

- **Logs**: `journalctl -u colonyos --since "1 hour ago"`
- **Health**: `curl http://localhost:8741/healthz`
- **Dashboard**: Open `http://localhost:8741` in a browser (or your subdomain)
- **Slack**: The daemon posts heartbeat messages every 4 hours
- **Daily digest**: Summary posted at the configured UTC hour

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Daemon won't start | `journalctl -u colonyos -e` for errors |
| No Slack messages | Verify `COLONYOS_SLACK_BOT_TOKEN` and `COLONYOS_SLACK_APP_TOKEN` in env file; if imports fail, reinstall with `../venv/bin/pip install -e ".[slack]"` and use Python 3.11-3.13 |
| Budget paused | Check `.colonyos/daemon_state.json` for `daily_spend_usd` |
| Circuit breaker active | Check `daemon_state.json` for `circuit_breaker_until` |
| Multiple instances | Check `.colonyos/runtime.lock` and `.colonyos/runtime_processes.json` for an active repo runtime before starting another daemon or standalone watcher |

## Updating

```bash
cd /opt/colonyos/repo
git pull
../venv/bin/pip install -e ".[slack]"
sudo systemctl restart colonyos
```
