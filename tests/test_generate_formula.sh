#!/usr/bin/env bash
# Tests for scripts/generate-homebrew-formula.sh
#
# Usage: bash tests/test_generate_formula.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GEN_SCRIPT="$REPO_ROOT/scripts/generate-homebrew-formula.sh"
PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1" >&2; }

echo "=== generate-homebrew-formula.sh tests ==="

# Test 1: Script exists and is executable
if [ -x "$GEN_SCRIPT" ]; then
  pass "script exists and is executable"
else
  fail "script not found or not executable"
fi

# Test 2: Shellcheck lint (if available)
if command -v shellcheck >/dev/null 2>&1; then
  if shellcheck "$GEN_SCRIPT"; then
    pass "shellcheck passes"
  else
    fail "shellcheck found issues"
  fi
else
  echo "  SKIP: shellcheck not installed"
fi

# Test 3: Dry-run mode exits successfully
if bash "$GEN_SCRIPT" --dry-run >/dev/null 2>&1; then
  pass "dry-run mode exits successfully"
else
  fail "dry-run mode failed"
fi

# Test 4: Dry-run output contains expected markers
DRY_OUTPUT=$(bash "$GEN_SCRIPT" --dry-run 2>&1)
if echo "$DRY_OUTPUT" | grep -q "dry-run"; then
  pass "dry-run output contains 'dry-run' marker"
else
  fail "dry-run output missing 'dry-run' marker"
fi

if echo "$DRY_OUTPUT" | grep -q "homebrew-pypi-poet"; then
  pass "dry-run output mentions homebrew-pypi-poet"
else
  fail "dry-run output missing homebrew-pypi-poet reference"
fi

# Test 5: Missing version argument fails
if bash "$GEN_SCRIPT" 2>/dev/null; then
  fail "should fail without version argument"
else
  pass "fails without version argument"
fi

# Test 6: Missing sha256 argument fails
if bash "$GEN_SCRIPT" "0.1.0" 2>/dev/null; then
  fail "should fail without sha256 argument"
else
  pass "fails without sha256 argument"
fi

# Test 7: Invalid version with 'v' prefix fails
if bash "$GEN_SCRIPT" "v0.1.0" "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890" 2>/dev/null; then
  fail "should reject version with 'v' prefix"
else
  pass "rejects version with 'v' prefix"
fi

# Test 8: Invalid sha256 (wrong length) fails
if bash "$GEN_SCRIPT" "0.1.0" "tooshort" 2>/dev/null; then
  fail "should reject invalid sha256"
else
  pass "rejects invalid sha256"
fi

# Test 9: Invalid sha256 (uppercase) fails
if bash "$GEN_SCRIPT" "0.1.0" "ABCDEF1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF1234567890" 2>/dev/null; then
  fail "should reject uppercase sha256"
else
  pass "rejects uppercase sha256"
fi

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
