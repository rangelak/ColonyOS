#!/usr/bin/env bash
# ColonyOS Installer
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/rangelak/ColonyOS/main/install.sh | sh
#
# Verify integrity (optional):
#   sha256sum install.sh
#   Compare against the checksum published in the GitHub Release assets.
#
# Options:
#   --dry-run    Print what would be done without making changes
#
set -euo pipefail

DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
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

# --- pipx Detection / Installation ---

if command -v pipx >/dev/null 2>&1; then
  ok "pipx found"
  INSTALLER="pipx"
else
  info "pipx not found."
  if [ "$DRY_RUN" = true ]; then
    info "(dry-run) would install pipx, then use it to install colonyos"
    INSTALLER="pipx"
  else
    printf "  Install pipx for isolated package management? [Y/n] "
    read -r REPLY
    case "$REPLY" in
      [nN]*)
        info "Falling back to pip install --user"
        INSTALLER="pip"
        ;;
      *)
        info "Installing pipx..."
        "$PYTHON" -m pip install --user pipx
        "$PYTHON" -m pipx ensurepath
        INSTALLER="pipx"
        ;;
    esac
  fi
fi

# --- Install ColonyOS ---

info "Installing ColonyOS via $INSTALLER..."

if [ "$INSTALLER" = "pipx" ]; then
  run_cmd pipx install colonyos
else
  run_cmd "$PYTHON" -m pip install --user colonyos
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
