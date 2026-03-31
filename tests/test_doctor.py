"""Tests for colonyos.doctor module — install-method detection."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from colonyos.doctor import detect_install_method


class TestDetectInstallMethod:
    """Tests for detect_install_method()."""

    def test_homebrew_cellar_path(self):
        """Detect Homebrew when executable is under Cellar."""
        fake_exe = "/opt/homebrew/Cellar/colonyos/1.0.0/libexec/bin/python"
        with patch("colonyos.doctor.sys") as mock_sys:
            mock_sys.executable = fake_exe
            method, upgrade_hint = detect_install_method()
        assert method == "homebrew"
        assert "brew upgrade colonyos" in upgrade_hint

    def test_homebrew_cellar_intel_mac(self):
        """Detect Homebrew on Intel Mac (/usr/local/Cellar)."""
        fake_exe = "/usr/local/Cellar/colonyos/1.0.0/libexec/bin/python"
        with patch("colonyos.doctor.sys") as mock_sys:
            mock_sys.executable = fake_exe
            method, upgrade_hint = detect_install_method()
        assert method == "homebrew"
        assert "brew upgrade colonyos" in upgrade_hint

    def test_pipx_venv_path(self):
        """Detect pipx when executable is under pipx venvs directory."""
        fake_exe = "/home/user/.local/pipx/venvs/colonyos/bin/python"
        with patch("colonyos.doctor.sys") as mock_sys:
            mock_sys.executable = fake_exe
            method, upgrade_hint = detect_install_method()
        assert method == "pipx"
        assert "pipx upgrade colonyos" in upgrade_hint

    def test_pipx_venv_macos_path(self):
        """Detect pipx on macOS (Library path)."""
        fake_exe = "/Users/dev/Library/Application Support/pipx/venvs/colonyos/bin/python"
        with patch("colonyos.doctor.sys") as mock_sys:
            mock_sys.executable = fake_exe
            method, upgrade_hint = detect_install_method()
        assert method == "pipx"
        assert "pipx upgrade colonyos" in upgrade_hint

    def test_pip_fallback(self):
        """Falls back to pip when path matches neither Homebrew nor pipx."""
        fake_exe = "/usr/bin/python3"
        with patch("colonyos.doctor.sys") as mock_sys:
            mock_sys.executable = fake_exe
            method, upgrade_hint = detect_install_method()
        assert method == "pip"
        assert "pip install --upgrade colonyos" in upgrade_hint

    def test_venv_path_falls_back_to_pip(self):
        """A plain venv (not pipx) falls back to pip."""
        fake_exe = "/home/user/myproject/.venv/bin/python"
        with patch("colonyos.doctor.sys") as mock_sys:
            mock_sys.executable = fake_exe
            method, upgrade_hint = detect_install_method()
        assert method == "pip"
        assert "pip install --upgrade colonyos" in upgrade_hint

    def test_returns_tuple(self):
        """Return type is a (method, hint) tuple."""
        with patch("colonyos.doctor.sys") as mock_sys:
            mock_sys.executable = "/usr/bin/python3"
            result = detect_install_method()
        assert isinstance(result, tuple)
        assert len(result) == 2


class TestDoctorIncludesInstallMethod:
    """Verify run_doctor_checks includes install-method info."""

    def test_install_method_in_results(self, tmp_path):
        """run_doctor_checks should include an 'Install method' check."""
        with (
            patch("colonyos.doctor.subprocess.run"),
            patch("colonyos.doctor.detect_install_method", return_value=("pip", "pip install --upgrade colonyos")),
            patch("colonyos.doctor.sys") as mock_sys,
            patch("colonyos.__version__", "1.0.0"),
        ):
            mock_sys.version_info = type("V", (), {"major": 3, "minor": 12})()
            mock_sys.executable = "/usr/bin/python3"

            from colonyos.doctor import run_doctor_checks
            results = run_doctor_checks(tmp_path)

        check_names = [name for name, _, _ in results]
        assert any("Install method" in name for name in check_names), \
            f"Expected 'Install method' in check names, got: {check_names}"

    def test_homebrew_upgrade_hint_in_version_check(self, tmp_path):
        """When installed via Homebrew, version fix hint should suggest brew upgrade."""
        with (
            patch("colonyos.doctor.subprocess.run"),
            patch("colonyos.doctor.detect_install_method", return_value=("homebrew", "brew upgrade colonyos")),
            patch("colonyos.doctor.sys") as mock_sys,
            patch("colonyos.__version__", "0.0.0"),
        ):
            mock_sys.version_info = type("V", (), {"major": 3, "minor": 12})()
            mock_sys.executable = "/opt/homebrew/Cellar/colonyos/1.0/libexec/bin/python"

            from colonyos.doctor import run_doctor_checks
            results = run_doctor_checks(tmp_path)

        # Find the version check
        for name, passed, hint in results:
            if "ColonyOS v" in name and not passed:
                assert "brew upgrade colonyos" in hint
                break
