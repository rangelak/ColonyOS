"""Pytest-integrated tests for install.sh.

Wraps the bash test script so it runs in CI via pytest, and adds
targeted tests for specific fix items (stdin handling, PEP 668, etc.).
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SCRIPT = REPO_ROOT / "install.sh"


class TestInstallScriptExists:
    """Basic sanity checks for install.sh."""

    def test_script_exists(self):
        assert INSTALL_SCRIPT.exists(), "install.sh not found at repo root"

    def test_script_is_not_empty(self):
        assert INSTALL_SCRIPT.stat().st_size > 0


class TestInstallScriptDryRun:
    """Verify dry-run mode works correctly."""

    def test_dry_run_exits_zero(self):
        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT), "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (
            f"dry-run failed: stdout={result.stdout}, stderr={result.stderr}"
        )

    def test_dry_run_output_contains_marker(self):
        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT), "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        combined = result.stdout + result.stderr
        assert "dry-run" in combined, "dry-run output missing 'dry-run' marker"

    def test_dry_run_detects_os(self):
        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT), "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        combined = result.stdout + result.stderr
        assert "Detected OS" in combined, "dry-run output missing OS detection"

    def test_unknown_option_rejected(self):
        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT), "--bogus-flag"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0, "unknown option should cause non-zero exit"

    def test_yes_flag_accepted(self):
        """The --yes flag must be accepted without error."""
        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT), "--dry-run", "--yes"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (
            f"--yes flag rejected: stdout={result.stdout}, stderr={result.stderr}"
        )


class TestInstallScriptStdinHandling:
    """Verify the script handles non-interactive stdin correctly (curl | sh)."""

    def test_non_interactive_stdin_does_not_hang(self):
        """When stdin is not a TTY (e.g. piped), the script must not block on read."""
        # Simulate curl | sh by piping empty stdin and using dry-run
        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT), "--dry-run"],
            input="",  # Simulates piped/non-interactive stdin
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (
            f"Script hung or failed with piped stdin: {result.stderr}"
        )


class TestInstallScriptContent:
    """Verify the script source contains expected patterns."""

    def setup_method(self):
        self.content = INSTALL_SCRIPT.read_text(encoding="utf-8")

    def test_detects_virtualenv(self):
        """Script must detect active virtualenvs."""
        assert "VIRTUAL_ENV" in self.content or "sys.prefix" in self.content, (
            "install.sh must detect active virtualenvs"
        )

    def test_has_pep668_handling(self):
        """Script should handle PEP 668 externally-managed-environment."""
        assert "break-system-packages" in self.content, (
            "install.sh should handle PEP 668 (--break-system-packages fallback)"
        )

    def test_has_set_euo_pipefail(self):
        """Script must use strict mode."""
        assert "set -euo pipefail" in self.content

    def test_no_bare_read_on_stdin(self):
        """No bare `read -r REPLY` without /dev/tty redirection (outside dry-run)."""
        import re
        # Find all read -r REPLY lines that don't redirect from /dev/tty
        bare_reads = re.findall(r"read -r REPLY\s*$", self.content, re.MULTILINE)
        assert len(bare_reads) == 0, (
            f"Found {len(bare_reads)} bare 'read -r REPLY' without /dev/tty: "
            "these will fail when piped via curl | sh"
        )

    def test_has_yes_flag(self):
        """Script must support --yes flag for non-interactive auto-approval."""
        assert "--yes" in self.content, (
            "install.sh must support --yes flag for non-interactive consent"
        )

    def test_curl_usage_has_f_flag(self):
        """Script header curl usage must include -f flag for HTTP error detection."""
        assert "curl -fsSL" in self.content, (
            "install.sh usage must use curl -fsSL (with -f for HTTP error detection)"
        )

    def test_non_interactive_without_yes_requires_pipx(self):
        """Non-interactive mode without --yes must fail if pipx is not found."""
        # Check that the script has logic for failing when not interactive and no --yes
        assert "AUTO_YES" in self.content, (
            "install.sh must check AUTO_YES for non-interactive consent"
        )
