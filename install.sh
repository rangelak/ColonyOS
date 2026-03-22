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
export AUTO_YES=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --yes) export AUTO_YES=true ;;
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

# --- Virtualenv Detection ---

IN_VENV=false
if [ -n "${VIRTUAL_ENV:-}" ] || "$PYTHON" -c "import sys; sys.exit(0 if sys.prefix != sys.base_prefix else 1)" 2>/dev/null; then
  IN_VENV=true
  ok "Virtualenv detected ($("$PYTHON" -c "import sys; print(sys.prefix)"))"
fi

# --- Install ColonyOS ---

if [ "$IN_VENV" = true ]; then
  info "Installing ColonyOS into active virtualenv..."
  run_cmd "$PYTHON" -m pip install colonyos
elif command -v pipx >/dev/null 2>&1; then
  ok "pipx found"
  info "Installing ColonyOS via pipx..."
  run_cmd pipx install colonyos
else
  info "No virtualenv active and pipx not found."
  info "Installing directly with pip..."
  if [ "$DRY_RUN" = true ]; then
    info "(dry-run) would run: $PYTHON -m pip install --user colonyos"
  else
    if "$PYTHON" -m pip install --user colonyos 2>/dev/null; then
      : # success
    elif "$PYTHON" -m pip install colonyos 2>/dev/null; then
      : # success (some systems don't support --user)
    else
      info "pip install failed. Trying with --break-system-packages..."
      "$PYTHON" -m pip install --user --break-system-packages colonyos
    fi
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
