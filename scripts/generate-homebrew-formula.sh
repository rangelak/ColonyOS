#!/usr/bin/env bash
# Generate a Homebrew formula for ColonyOS with all Python dependency resource blocks.
#
# Usage:
#   scripts/generate-homebrew-formula.sh <version> <sha256>
#   scripts/generate-homebrew-formula.sh --dry-run
#
# Arguments:
#   version   — The release version (e.g., "0.1.0"). Omit "v" prefix.
#   sha256    — The SHA-256 checksum of the sdist tarball on PyPI.
#
# Options:
#   --dry-run   Print what would be done without generating the formula.
#   --output    Write formula to this path instead of stdout (default: stdout).
#
# Requirements:
#   - Python 3.11+
#   - pip (for installing into temp venv)
#   - homebrew-pypi-poet (installed automatically into the temp venv)
#
# Example:
#   scripts/generate-homebrew-formula.sh 0.1.0 abc123def456...
#   scripts/generate-homebrew-formula.sh 0.1.0 abc123def456... --output Formula/colonyos.rb
#
set -euo pipefail

# --- Constants ---

PACKAGE_NAME="colonyos"
PYPI_URL_TEMPLATE="https://files.pythonhosted.org/packages/source/c/colonyos/colonyos-VERSION.tar.gz"
PYTHON_DEP="python@3.11"
FORMULA_CLASS="Colonyos"
HOMEPAGE="https://github.com/rangelak/ColonyOS"
LICENSE="MIT"
DESC="Autonomous agent loop that turns prompts into shipped PRs"

# --- Argument Parsing ---

DRY_RUN=false
VERSION=""
SHA256=""
OUTPUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --output)
      OUTPUT="$2"
      shift 2
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      if [[ -z "$VERSION" ]]; then
        VERSION="$1"
      elif [[ -z "$SHA256" ]]; then
        SHA256="$1"
      else
        echo "Unexpected argument: $1" >&2
        exit 1
      fi
      shift
      ;;
  esac
done

# --- Dry-Run Mode ---

if [[ "$DRY_RUN" == "true" ]]; then
  echo "[dry-run] Would generate Homebrew formula for ${PACKAGE_NAME}"
  echo "[dry-run] Steps:"
  echo "[dry-run]   1. Create temporary Python virtual environment"
  echo "[dry-run]   2. Install ${PACKAGE_NAME} and homebrew-pypi-poet into venv"
  echo "[dry-run]   3. Run 'poet ${PACKAGE_NAME}' to generate resource blocks"
  echo "[dry-run]   4. Assemble complete Formula/${PACKAGE_NAME}.rb"
  echo "[dry-run]   5. Output formula to ${OUTPUT:-stdout}"
  echo "[dry-run] Required: version and sha256 arguments (not provided in dry-run)"
  exit 0
fi

# --- Validate Arguments ---

if [[ -z "$VERSION" ]]; then
  echo "Error: version argument is required" >&2
  echo "Usage: $0 <version> <sha256> [--output <path>]" >&2
  exit 1
fi

if [[ -z "$SHA256" ]]; then
  echo "Error: sha256 argument is required" >&2
  echo "Usage: $0 <version> <sha256> [--output <path>]" >&2
  exit 1
fi

# Validate version format (simple check: should not start with 'v')
if [[ "$VERSION" == v* ]]; then
  echo "Error: version should not include 'v' prefix (got: $VERSION)" >&2
  echo "Example: $0 0.1.0 <sha256>" >&2
  exit 1
fi

# Validate SHA-256 format (64 hex chars)
if ! [[ "$SHA256" =~ ^[a-f0-9]{64}$ ]]; then
  echo "Error: sha256 must be a 64-character lowercase hex string" >&2
  exit 1
fi

# --- Find a suitable Python ---
# Prefer python3.11 or python3.12 (homebrew-pypi-poet uses pkg_resources
# which may be removed in newer Python versions without setuptools).
PYTHON=""
for candidate in python3.11 python3.12 python3.13 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done

if [[ -z "$PYTHON" ]]; then
  echo "Error: no suitable Python interpreter found (need 3.11+)" >&2
  exit 1
fi

echo "Using Python: $PYTHON ($(${PYTHON} --version 2>&1))" >&2

# --- Setup Temp Venv ---

TMPDIR_BASE="${TMPDIR:-/tmp}"
WORK_DIR=$(mktemp -d "${TMPDIR_BASE}/colonyos-formula-XXXXXX")
cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT

echo "Creating temporary virtual environment in ${WORK_DIR}..." >&2

"$PYTHON" -m venv "${WORK_DIR}/venv"
# shellcheck source=/dev/null
source "${WORK_DIR}/venv/bin/activate"

echo "Installing ${PACKAGE_NAME} and homebrew-pypi-poet..." >&2
# homebrew-pypi-poet depends on pkg_resources which requires setuptools.
# Python 3.12+ no longer bundles setuptools, and setuptools 78+ removed
# pkg_resources entirely. Pin to a version that still includes it.
pip install --quiet 'setuptools<78' "${PACKAGE_NAME}==${VERSION}" homebrew-pypi-poet

# --- Generate Resource Blocks ---

echo "Generating resource blocks with poet..." >&2
RESOURCE_BLOCKS=$(poet "${PACKAGE_NAME}")

# Filter out the resource block for colonyos itself (poet includes the package itself)
# We only want dependency resource blocks, not the main package.
FILTERED_RESOURCES=$(echo "$RESOURCE_BLOCKS" | awk '
  /^  resource "colonyos"/ { skip=1; next }
  skip && /^  end/ { skip=0; next }
  skip { next }
  { print }
')

# --- Build URL ---

URL="${PYPI_URL_TEMPLATE//VERSION/$VERSION}"

# --- Assemble Formula ---
# Build formula using printf to avoid heredoc quoting issues with Ruby strings.

FORMULA_HEADER="# Homebrew formula for ColonyOS
#
# This formula is auto-generated by scripts/generate-homebrew-formula.sh
# during the release workflow. Do not edit manually.
#
# Install: brew install rangelak/colonyos/colonyos
class ${FORMULA_CLASS} < Formula
  include Language::Python::Virtualenv

  desc \"${DESC}\"
  homepage \"${HOMEPAGE}\"
  url \"${URL}\"
  sha256 \"${SHA256}\"
  license \"${LICENSE}\"

  depends_on \"${PYTHON_DEP}\""

# The caveats/test blocks use Ruby heredoc syntax with single quotes,
# so we keep them in a quoted heredoc to avoid shell interpretation.
read -r -d '' FORMULA_FOOTER << 'RUBY_EOF' || true

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      ColonyOS is installed! Next steps:

        1. Run 'colonyos doctor' to verify your setup
        2. Install the Claude Code CLI if you haven't already:
           npm install -g @anthropic-ai/claude-code
        3. Set your ANTHROPIC_API_KEY environment variable
        4. cd into a git repo and run 'colonyos init'
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/colonyos --version")
  end
end
RUBY_EOF

# Remove any trailing blank lines from resources, then assemble
TRIMMED_RESOURCES=$(echo "$FILTERED_RESOURCES" | sed -e :a -e '/^[[:space:]]*$/d;N;ba' 2>/dev/null || echo "$FILTERED_RESOURCES")

FORMULA="${FORMULA_HEADER}

${TRIMMED_RESOURCES}
${FORMULA_FOOTER}"

# --- Output ---

if [[ -n "$OUTPUT" ]]; then
  # Ensure parent directory exists
  mkdir -p "$(dirname "$OUTPUT")"
  echo "$FORMULA" > "$OUTPUT"
  echo "Formula written to ${OUTPUT}" >&2
else
  echo "$FORMULA"
fi

echo "Done. Formula generated for ${PACKAGE_NAME} v${VERSION}" >&2
