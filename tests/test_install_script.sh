#!/usr/bin/env bash
# Tests for install.sh — runs shellcheck and verifies dry-run mode.
#
# Usage: bash tests/test_install_script.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_SCRIPT="$REPO_ROOT/install.sh"
PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1" >&2; }

echo "=== install.sh tests ==="

# Test 1: Script exists and is executable
if [ -f "$INSTALL_SCRIPT" ]; then
  pass "install.sh exists"
else
  fail "install.sh not found"
fi

# Test 2: Shellcheck lint (if available)
if command -v shellcheck >/dev/null 2>&1; then
  if shellcheck "$INSTALL_SCRIPT"; then
    pass "shellcheck passes"
  else
    fail "shellcheck found issues"
  fi
else
  echo "  SKIP: shellcheck not installed"
fi

# Test 3: Dry-run mode exits successfully
if bash "$INSTALL_SCRIPT" --dry-run 2>&1; then
  pass "dry-run mode succeeds"
else
  fail "dry-run mode failed"
fi

# Test 4: Dry-run output contains expected markers
DRY_OUTPUT=$(bash "$INSTALL_SCRIPT" --dry-run 2>&1)
if echo "$DRY_OUTPUT" | grep -q "dry-run"; then
  pass "dry-run output contains 'dry-run' marker"
else
  fail "dry-run output missing 'dry-run' marker"
fi

if echo "$DRY_OUTPUT" | grep -q "Detected OS"; then
  pass "dry-run output contains OS detection"
else
  fail "dry-run output missing OS detection"
fi

# Test 5: Unknown option causes failure
if bash "$INSTALL_SCRIPT" --bogus-flag 2>/dev/null; then
  fail "unknown option should cause non-zero exit"
else
  pass "unknown option rejected"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
