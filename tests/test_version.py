"""Tests for single-source versioning via setuptools-scm."""

import re
from pathlib import Path

import colonyos


class TestVersionConsistency:
    """Verify __version__ is valid and accessible."""

    def test_version_attribute_exists(self):
        """colonyos.__version__ must be defined."""
        assert hasattr(colonyos, "__version__")

    def test_version_is_string(self):
        """__version__ must be a string."""
        assert isinstance(colonyos.__version__, str)

    def test_version_not_empty(self):
        """__version__ must not be empty."""
        assert colonyos.__version__ != ""

    def test_version_is_valid_semver_prefix(self):
        """__version__ must start with a valid version pattern (semver or PEP 440 dev)."""
        pattern = r"^\d+\.\d+(\.\d+|\.dev\d+)"
        assert re.match(pattern, colonyos.__version__), (
            f"Version '{colonyos.__version__}' does not match semver or PEP 440 dev pattern"
        )

    def test_version_matches_importlib_metadata(self):
        """__version__ must match importlib.metadata if package is installed."""
        from importlib.metadata import PackageNotFoundError, version

        try:
            meta_version = version("colonyos")
            assert colonyos.__version__ == meta_version, (
                f"__version__={colonyos.__version__!r} != "
                f"metadata={meta_version!r}"
            )
        except PackageNotFoundError:
            # In editable installs without metadata, skip this check
            pass


class TestDoctorVersionCheck:
    """Verify the doctor version check flags degraded state."""

    @staticmethod
    def _run_doctor_checks_patched(version: str):
        """Run doctor checks without real claude/git/gh subprocess calls."""
        from unittest.mock import MagicMock, patch

        from colonyos.doctor import run_doctor_checks

        mock_ok = MagicMock(returncode=0, stdout="", stderr="")
        with patch("colonyos.__version__", version):
            with patch("colonyos.doctor.subprocess.run", return_value=mock_ok):
                return run_doctor_checks(Path("."))

    def test_doctor_version_check_detects_dev_fallback(self):
        """Doctor must flag 0.0.0.dev0 as degraded, not passed."""
        results = self._run_doctor_checks_patched("0.0.0.dev0")
        # First result is the version check
        name, passed, hint = results[0]
        assert "0.0.0.dev0" in name
        assert passed is False, (
            "Dev fallback version should be flagged as failed"
        )
        assert hint != "", "Dev fallback version should have a fix hint"

    def test_doctor_version_check_passes_for_release(self):
        """Doctor must pass for a real release version."""
        results = self._run_doctor_checks_patched("1.2.3")
        name, passed, _ = results[0]
        assert "1.2.3" in name
        assert passed is True
