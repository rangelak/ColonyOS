#!/usr/bin/env bash
# ColonyOS VM Provisioning Script
#
# Automates full-stack setup on a fresh Ubuntu 22.04+ VM.
# After running this script, `colonyos daemon` is ready to serve requests.
#
# Usage:
#   sudo bash deploy/provision.sh
#   sudo bash deploy/provision.sh --dry-run
#   sudo bash deploy/provision.sh --yes
#
# Options:
#   --dry-run    Print what would be done without making changes
#   --yes        Auto-approve all prompts (non-interactive mode)
#
set -euo pipefail

DRY_RUN=false
AUTO_YES=false
COLONYOS_EXTRA=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --yes) AUTO_YES=true ;;
    --slack) COLONYOS_EXTRA="[slack]" ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

# --- Helpers ---

info() { echo "  [info] $*"; }
ok()   { echo "  [ok]   $*"; }
warn() { echo "  [warn] $*" >&2; }
fail() { echo "  [fail] $*" >&2; }

run_cmd() {
  if [ "$DRY_RUN" = true ]; then
    info "(dry-run) would run: $*"
  else
    "$@"
  fi
}

confirm() {
  if [ "$AUTO_YES" = true ] || [ "$DRY_RUN" = true ]; then
    return 0
  fi
  read -r -p "  $1 [y/N] " answer
  case "$answer" in
    [yY]|[yY][eE][sS]) return 0 ;;
    *) return 1 ;;
  esac
}

# --- Pre-flight Checks ---

if [ "$(id -u)" -ne 0 ] && [ "$DRY_RUN" = false ]; then
  fail "This script must be run as root (use sudo)."
  exit 1
fi

# Detect Ubuntu version
if [ -f /etc/os-release ]; then
  # shellcheck source=/dev/null
  . /etc/os-release
  if [ "${ID:-}" != "ubuntu" ]; then
    fail "This script requires Ubuntu. Detected: ${ID:-unknown}"
    exit 1
  fi
  UBUNTU_VERSION="${VERSION_ID:-0}"
  UBUNTU_MAJOR="${UBUNTU_VERSION%%.*}"
  if [ "$UBUNTU_MAJOR" -lt 22 ]; then
    fail "Ubuntu 22.04+ required. Detected: $UBUNTU_VERSION"
    exit 1
  fi
  ok "Ubuntu $UBUNTU_VERSION detected"
else
  fail "Cannot detect OS — /etc/os-release not found."
  exit 1
fi

info "ColonyOS VM Provisioning"
info "========================"
if [ "$DRY_RUN" = true ]; then
  info "Running in dry-run mode — no changes will be made."
fi
echo ""

# --- Step 1: System Packages ---

info "Step 1/7: Installing system packages..."
run_cmd apt-get update -qq

# Python 3.11+ — use deadsnakes PPA if system Python is too old
SYSTEM_PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "0")
if [ "$SYSTEM_PY_MINOR" -lt 11 ]; then
  info "System Python 3.$SYSTEM_PY_MINOR is below 3.11, adding deadsnakes PPA..."
  run_cmd apt-get install -y -qq software-properties-common
  run_cmd add-apt-repository -y ppa:deadsnakes/ppa
  run_cmd apt-get update -qq
  run_cmd apt-get install -y -qq python3.11 python3.11-venv python3.11-dev
  PYTHON=python3.11
else
  run_cmd apt-get install -y -qq python3 python3-venv python3-dev
  PYTHON=python3
fi

# Git
run_cmd apt-get install -y -qq git curl

ok "System packages installed"

# --- Step 2: Node.js LTS (for Claude Code CLI) ---

info "Step 2/7: Installing Node.js LTS..."
if command -v node >/dev/null 2>&1; then
  NODE_VERSION=$(node --version)
  ok "Node.js $NODE_VERSION already installed"
else
  if [ "$DRY_RUN" = true ]; then
    info "(dry-run) would install Node.js LTS via nodesource signed apt repo"
  else
    # Install via signed apt repo instead of curl|bash (supply chain safety)
    apt-get install -y -qq ca-certificates gnupg
    mkdir -p /usr/share/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /usr/share/keyrings/nodesource.gpg
    NODE_MAJOR=20
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
      | tee /etc/apt/sources.list.d/nodesource.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq nodejs
  fi
  ok "Node.js LTS installed"
fi

# --- Step 3: GitHub CLI ---

info "Step 3/7: Installing GitHub CLI..."
if command -v gh >/dev/null 2>&1; then
  GH_VERSION=$(gh --version | head -1)
  ok "GitHub CLI already installed: $GH_VERSION"
else
  if [ "$DRY_RUN" = true ]; then
    info "(dry-run) would install GitHub CLI"
  else
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
    chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      | tee /etc/apt/sources.list.d/github-cli.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq gh
  fi
  ok "GitHub CLI installed"
fi

# --- Step 4: pipx + ColonyOS ---

info "Step 4/7: Installing pipx and ColonyOS..."
if ! command -v pipx >/dev/null 2>&1; then
  run_cmd apt-get install -y -qq pipx
  run_cmd pipx ensurepath
fi
ok "pipx available"

if [ -n "$COLONYOS_EXTRA" ]; then
  info "Installing colonyos with extra: $COLONYOS_EXTRA"
  run_cmd pipx install --force "colonyos${COLONYOS_EXTRA}" --python "$PYTHON"
else
  run_cmd pipx install --force colonyos --python "$PYTHON"
fi
ok "ColonyOS installed via pipx"

# --- Step 5: System User & Directory ---

info "Step 5/7: Creating colonyos system user and directories..."
if id colonyos >/dev/null 2>&1; then
  ok "User 'colonyos' already exists"
else
  run_cmd useradd --system --create-home --home-dir /opt/colonyos --shell /usr/sbin/nologin colonyos
  ok "User 'colonyos' created"
fi

run_cmd mkdir -p /opt/colonyos/repo
run_cmd chown -R colonyos:colonyos /opt/colonyos

# --- Step 6: Environment & Secrets ---

info "Step 6/7: Configuring environment..."
ENV_FILE="/opt/colonyos/env"

if [ -f "$ENV_FILE" ]; then
  ok "Environment file already exists at $ENV_FILE"
else
  if [ "$DRY_RUN" = true ]; then
    info "(dry-run) would create $ENV_FILE and prompt for API keys"
  else
    ANTHROPIC_KEY="${ANTHROPIC_API_KEY:-}"
    GITHUB_KEY="${GITHUB_TOKEN:-}"

    if [ -z "$ANTHROPIC_KEY" ] && [ "$AUTO_YES" = false ]; then
      read -rs -p "  Enter ANTHROPIC_API_KEY (or leave blank to configure later): " ANTHROPIC_KEY
      echo  # newline after silent input
    fi
    if [ -z "$GITHUB_KEY" ] && [ "$AUTO_YES" = false ]; then
      read -rs -p "  Enter GITHUB_TOKEN (or leave blank to configure later): " GITHUB_KEY
      echo  # newline after silent input
    fi

    cat > "$ENV_FILE" <<ENVEOF
ANTHROPIC_API_KEY=${ANTHROPIC_KEY}
GITHUB_TOKEN=${GITHUB_KEY}
ENVEOF
    chown colonyos:colonyos "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    ok "Environment file created at $ENV_FILE (mode 600)"
    warn "For production, consider using systemd-creds or a secrets manager instead of a plaintext env file."
  fi
fi

# --- Step 7: systemd Service ---

info "Step 7/7: Setting up systemd service..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_SRC="${SCRIPT_DIR}/colonyos-daemon.service"

if [ ! -f "$SERVICE_SRC" ]; then
  # Fallback: look relative to cwd
  SERVICE_SRC="deploy/colonyos-daemon.service"
fi

if [ -f "$SERVICE_SRC" ]; then
  run_cmd cp "$SERVICE_SRC" /etc/systemd/system/colonyos-daemon.service
  run_cmd systemctl daemon-reload
  run_cmd systemctl enable colonyos-daemon.service
  if confirm "Start the colonyos daemon now?"; then
    run_cmd systemctl start colonyos-daemon.service
    ok "colonyos-daemon service started"
  else
    info "Service enabled but not started. Run: sudo systemctl start colonyos-daemon"
  fi
else
  warn "Service file not found at $SERVICE_SRC — skipping systemd setup."
  warn "Copy deploy/colonyos-daemon.service to /etc/systemd/system/ manually."
fi

# --- Verification ---

echo ""
info "Verification..."
if command -v colonyos >/dev/null 2>&1; then
  COLONYOS_VERSION=$(colonyos --version 2>/dev/null || echo "unknown")
  ok "colonyos $COLONYOS_VERSION is available on PATH"
else
  if [ "$DRY_RUN" = true ]; then
    info "(dry-run) would verify colonyos is on PATH"
  else
    warn "colonyos not found on PATH. You may need to log out and back in, or run: pipx ensurepath"
  fi
fi

echo ""
ok "ColonyOS VM provisioning complete!"
echo ""
info "Next steps:"
info "  1. Clone your repo into /opt/colonyos/repo"
info "  2. Run 'sudo -u colonyos colonyos init' in /opt/colonyos/repo"
info "  3. Edit /opt/colonyos/env with your API keys (if not set above)"
info "  4. Run 'sudo systemctl start colonyos-daemon' (if not started)"
info "  5. Run 'colonyos doctor' to verify all prerequisites"
echo ""
