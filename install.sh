#!/usr/bin/env bash
# ColonyOS Installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/rangelak/ColonyOS/main/install.sh | sh
#
# Non-interactive usage (auto-approve all prompts):
#   curl -fsSL https://raw.githubusercontent.com/rangelak/ColonyOS/main/install.sh | sh -s -- --yes
#
# Verify integrity (optional):
#   sha256sum install.sh
#   Compare against the checksum published in the GitHub Release assets.
#
# Options:
#   --dry-run    Print what would be done without making changes
#   --yes        Auto-approve all prompts (e.g. pipx installation)
#
set -euo pipefail

DRY_RUN=false
AUTO_YES=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --yes) AUTO_YES=true ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

# --- Helpers ---

info() { echo "  [info] $*"; }
ok()   { echo "  [ok]   $*"; }
fail() { echo "  [fail] $*" >&2; }
run_cmd() {
  if [ "$DRY_RUN" = true ]; then
    info "(dry-run) would run: $*"
  else
    "$@"
  fi
}

# --- OS Detection ---

detect_os() {
  case "$(uname -s)" in
    Linux*)  echo "linux" ;;
    Darwin*) echo "macos" ;;
    MINGW*|CYGWIN*|MSYS*) echo "windows" ;;
    *) echo "unknown" ;;
  esac
}

OS=$(detect_os)
info "Detected OS: $OS"

if [ "$OS" = "windows" ]; then
  fail "Windows is not supported by this installer."
  fail "Please use: pip install colonyos"
  exit 1
fi

if [ "$OS" = "unknown" ]; then
  fail "Unrecognized operating system: $(uname -s)"
  fail "Please use: pip install colonyos"
  exit 1
fi

# --- Python Check ---

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  fail "Python not found. Please install Python 3.11 or later."
  fail "  macOS:  brew install python@3.11"
  fail "  Linux:  sudo apt install python3.11  (or equivalent)"
  exit 1
fi

# Check version >= 3.11
PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
  fail "Python $PY_VERSION found, but ColonyOS requires Python 3.11+."
  fail "  macOS:  brew install python@3.11"
  fail "  Linux:  sudo apt install python3.11  (or equivalent)"
  exit 1
fi

ok "Python $PY_VERSION"

# --- Helpers: pip with PEP 668 fallback ---

pip_install_user() {
  # Try pip install --user first
  if "$PYTHON" -m pip install --user "$@" 2>/dev/null; then
    return 0
  fi
  # PEP 668 (externally-managed-environment on Debian 12+, Ubuntu 23.04+)
  # warns against breaking system packages. We proceed with --break-system-packages
  # only because we're installing into --user scope, not system-wide.
  info "WARNING: pip --user install failed, likely due to PEP 668 (externally-managed-environment)."
  info "Retrying with --break-system-packages to install into user site-packages."
  info "This does NOT modify system Python packages. To avoid this, install pipx via your"
  info "system package manager instead: apt install pipx / brew install pipx"
  "$PYTHON" -m pip install --user --break-system-packages "$@"
}

install_pipx() {
  pip_install_user pipx
  "$PYTHON" -m pipx ensurepath
}

# --- pipx Detection / Installation ---

if command -v pipx >/dev/null 2>&1; then
  ok "pipx found"
  INSTALLER="pipx"
else
  info "pipx not found."
  if [ "$DRY_RUN" = true ]; then
    info "(dry-run) would install pipx, then use it to install colonyos"
    INSTALLER="pipx"
  elif [ -t 0 ]; then
    # Interactive terminal — ask the user
    printf "  Install pipx for isolated package management? [Y/n] "
    read -r REPLY < /dev/tty
    case "$REPLY" in
      [nN]*)
        info "Falling back to pip install --user"
        INSTALLER="pip"
        ;;
      *)
        info "Installing pipx..."
        install_pipx
        INSTALLER="pipx"
        ;;
    esac
  elif [ "$AUTO_YES" = true ]; then
    # Non-interactive with explicit --yes flag
    info "Non-interactive mode with --yes: installing pipx automatically..."
    install_pipx
    INSTALLER="pipx"
  else
    # Non-interactive without --yes — fail safe and tell the user how to proceed
    fail "pipx is required but not installed, and no interactive terminal is available."
    fail "Re-run with --yes to auto-install pipx, or install it manually first:"
    fail "  apt install pipx  OR  brew install pipx  OR  pip install --user pipx"
    fail ""
    fail "Example: curl -fsSL https://raw.githubusercontent.com/rangelak/ColonyOS/main/install.sh | sh -s -- --yes"
    exit 1
  fi
fi

# --- Install ColonyOS ---

info "Installing ColonyOS via $INSTALLER..."

if [ "$INSTALLER" = "pipx" ]; then
  run_cmd pipx install colonyos
else
  if [ "$DRY_RUN" = true ]; then
    info "(dry-run) would run: pip_install_user colonyos"
  else
    pip_install_user colonyos
  fi
fi

# --- Post-Install ---

echo ""
ok "ColonyOS installed successfully!"
echo ""
info "Next steps:"
info "  1. Run 'colonyos doctor' to verify prerequisites"
info "  2. Run 'colonyos init' in your project directory"
info "  3. Run 'colonyos run \"your feature\"' to start building"
echo ""
