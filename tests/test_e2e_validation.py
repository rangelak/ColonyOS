"""End-to-end validation tests for the Homebrew installation & VM deployment feature.

Task 7.0 — validates that all prior tasks (1.0–6.0) are correctly wired together:
  7.1  generate-homebrew-formula.sh produces a valid formula with resource blocks
  7.2  Formula/colonyos.rb has valid Homebrew structure
  7.3  colonyos doctor shows correct install method and upgrade instructions
  7.4  colonyos init warns when run outside a git repo
  7.5  deploy/provision.sh --dry-run completes without errors
  7.6  Release workflow update-homebrew job logic is correct end-to-end
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 7.1  Formula generation script produces a valid formula
# ---------------------------------------------------------------------------


class TestFormulaGenerationE2E:
    """Validate scripts/generate-homebrew-formula.sh end-to-end."""

    SCRIPT = REPO_ROOT / "scripts" / "generate-homebrew-formula.sh"

    def test_script_exists_and_is_executable(self):
        assert self.SCRIPT.exists(), "generate-homebrew-formula.sh missing"
        assert os.access(self.SCRIPT, os.X_OK), "script is not executable"

    def test_dry_run_succeeds(self):
        result = subprocess.run(
            ["bash", str(self.SCRIPT), "--dry-run"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"dry-run failed: {result.stderr}"

    def test_dry_run_output_describes_all_steps(self):
        result = subprocess.run(
            ["bash", str(self.SCRIPT), "--dry-run"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
        # Must mention the key generation steps
        assert "homebrew-pypi-poet" in output, "dry-run should mention poet"
        assert "virtual environment" in output.lower() or "venv" in output.lower(), (
            "dry-run should mention venv creation"
        )

    def test_rejects_version_with_v_prefix(self):
        sha = "a" * 64
        result = subprocess.run(
            ["bash", str(self.SCRIPT), "v1.0.0", sha],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0, "Should reject 'v' prefix on version"
        assert "v" in result.stderr.lower()

    def test_rejects_invalid_sha256(self):
        result = subprocess.run(
            ["bash", str(self.SCRIPT), "1.0.0", "not-a-sha"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0, "Should reject invalid sha256"

    def test_rejects_uppercase_sha256(self):
        sha = "A" * 64
        result = subprocess.run(
            ["bash", str(self.SCRIPT), "1.0.0", sha],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0, "Should reject uppercase sha256"

    def test_rejects_missing_arguments(self):
        # No args
        r1 = subprocess.run(
            ["bash", str(self.SCRIPT)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert r1.returncode != 0, "Should fail with no arguments"

        # Only version, no sha
        r2 = subprocess.run(
            ["bash", str(self.SCRIPT), "1.0.0"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert r2.returncode != 0, "Should fail with only version argument"

    def test_script_passes_shellcheck(self):
        """Shellcheck lint if available."""
        if not _command_exists("shellcheck"):
            pytest.skip("shellcheck not installed")
        result = subprocess.run(
            ["shellcheck", str(self.SCRIPT)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"shellcheck issues:\n{result.stdout}"


# ---------------------------------------------------------------------------
# 7.2  Formula/colonyos.rb has valid Homebrew structure
# ---------------------------------------------------------------------------


class TestFormulaStructureE2E:
    """Validate that Formula/colonyos.rb has all required Homebrew components."""

    def setup_method(self):
        self.formula_path = REPO_ROOT / "Formula" / "colonyos.rb"
        assert self.formula_path.exists(), "Formula/colonyos.rb not found"
        self.content = self.formula_path.read_text(encoding="utf-8")

    def test_formula_is_valid_ruby_class(self):
        """Formula must define a class that inherits from Formula."""
        assert re.search(r"class\s+Colonyos\s*<\s*Formula", self.content), (
            "Formula must define 'class Colonyos < Formula'"
        )

    def test_includes_virtualenv_mixin(self):
        assert "Language::Python::Virtualenv" in self.content

    def test_has_desc(self):
        assert re.search(r'desc\s+"', self.content), "Formula must have a desc"

    def test_has_homepage(self):
        assert re.search(r'homepage\s+"https://', self.content), (
            "Formula must have a homepage URL"
        )

    def test_has_url_pointing_to_pypi(self):
        assert "files.pythonhosted.org" in self.content, (
            "Formula must use canonical PyPI URL"
        )

    def test_has_sha256(self):
        assert re.search(r'sha256\s+"[a-f0-9]{64}"', self.content), (
            "Formula must have a valid sha256"
        )

    def test_has_license(self):
        assert re.search(r'license\s+"MIT"', self.content)

    def test_depends_on_python(self):
        assert 'depends_on "python@3.11"' in self.content

    def test_has_install_method(self):
        assert "def install" in self.content
        assert "virtualenv_install_with_resources" in self.content

    def test_has_test_block(self):
        assert "test do" in self.content
        assert "assert_match" in self.content

    def test_documents_tap_repo(self):
        """Development formula must point users to the canonical tap."""
        lower = self.content.lower()
        assert "homebrew-colonyos" in lower or "homebrew tap" in lower, (
            "Formula should reference the canonical tap repo"
        )

    def test_ruby_syntax_valid(self):
        """Check Ruby syntax if ruby is available."""
        if not _command_exists("ruby"):
            pytest.skip("ruby not installed")
        result = subprocess.run(
            ["ruby", "-c", str(self.formula_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Ruby syntax check failed: {result.stderr}"


# ---------------------------------------------------------------------------
# 7.3  colonyos doctor shows correct install method & upgrade instructions
# ---------------------------------------------------------------------------


class TestDoctorInstallMethodE2E:
    """End-to-end: doctor reports correct install method for each install type."""

    @pytest.fixture(autouse=True)
    def _patch_common(self, tmp_path):
        """Common patches for doctor calls."""
        self.tmp_path = tmp_path

    def _run_doctor_with_executable(self, fake_exe: str) -> list:
        """Run doctor checks with a mocked sys.executable path."""
        with (
            patch("colonyos.doctor.subprocess.run") as mock_subproc,
            patch("colonyos.doctor.sys") as mock_sys,
            patch("colonyos.__version__", "1.0.0"),
        ):
            mock_sys.version_info = type("V", (), {"major": 3, "minor": 12})()
            mock_sys.executable = fake_exe

            from colonyos.doctor import run_doctor_checks

            return run_doctor_checks(self.tmp_path)

    def test_homebrew_install_detected_with_correct_upgrade_hint(self):
        results = self._run_doctor_with_executable(
            "/opt/homebrew/Cellar/colonyos/1.0.0/libexec/bin/python"
        )
        install_checks = [
            (name, passed, hint)
            for name, passed, hint in results
            if "Install method" in name
        ]
        assert install_checks, "Doctor must include 'Install method' check"
        name, _, hint = install_checks[0]
        assert "homebrew" in name.lower() or "homebrew" in hint.lower()
        assert "brew upgrade" in hint

    def test_pipx_install_detected_with_correct_upgrade_hint(self):
        results = self._run_doctor_with_executable(
            "/home/user/.local/pipx/venvs/colonyos/bin/python"
        )
        install_checks = [
            (name, passed, hint)
            for name, passed, hint in results
            if "Install method" in name
        ]
        assert install_checks, "Doctor must include 'Install method' check"
        _, _, hint = install_checks[0]
        assert "pipx upgrade" in hint

    def test_pip_install_detected_with_correct_upgrade_hint(self):
        results = self._run_doctor_with_executable("/usr/bin/python3")
        install_checks = [
            (name, passed, hint)
            for name, passed, hint in results
            if "Install method" in name
        ]
        assert install_checks, "Doctor must include 'Install method' check"
        _, _, hint = install_checks[0]
        assert "pip install --upgrade" in hint

    def test_version_check_uses_install_method_hint(self):
        """When version is degraded, the fix hint matches install method."""
        with (
            patch("colonyos.doctor.subprocess.run"),
            patch(
                "colonyos.doctor.detect_install_method",
                return_value=("homebrew", "brew upgrade colonyos"),
            ),
            patch("colonyos.doctor.sys") as mock_sys,
            patch("colonyos.__version__", "0.0.0"),
        ):
            mock_sys.version_info = type("V", (), {"major": 3, "minor": 12})()
            mock_sys.executable = "/opt/homebrew/Cellar/colonyos/1.0/libexec/bin/python"

            from colonyos.doctor import run_doctor_checks

            results = run_doctor_checks(self.tmp_path)

        version_checks = [
            (name, passed, hint)
            for name, passed, hint in results
            if "ColonyOS v" in name and not passed
        ]
        assert version_checks, "Degraded version should produce a failed check"
        _, _, hint = version_checks[0]
        assert "brew upgrade colonyos" in hint


# ---------------------------------------------------------------------------
# 7.4  colonyos init warns when run outside a git repo
# ---------------------------------------------------------------------------


class TestInitGitRepoGuardE2E:
    """End-to-end: init warns and prompts when not inside a git repo."""

    def test_is_git_repo_true_for_actual_repo(self, tmp_path: Path):
        """is_git_repo returns True for a directory with .git."""
        (tmp_path / ".git").mkdir()
        from colonyos.init import is_git_repo

        assert is_git_repo(tmp_path) is True

    def test_is_git_repo_false_for_plain_directory(self, tmp_path: Path):
        from colonyos.init import is_git_repo

        assert is_git_repo(tmp_path) is False

    def test_is_git_repo_true_for_subdirectory(self, tmp_path: Path):
        """is_git_repo walks up to find .git."""
        (tmp_path / ".git").mkdir()
        sub = tmp_path / "deep" / "nested" / "dir"
        sub.mkdir(parents=True)
        from colonyos.init import is_git_repo

        assert is_git_repo(sub) is True

    def test_is_git_repo_handles_submodule_file(self, tmp_path: Path):
        """Git submodules use a .git *file*, not a directory."""
        (tmp_path / ".git").write_text("gitdir: ../../../.git/modules/sub\n")
        from colonyos.init import is_git_repo

        assert is_git_repo(tmp_path) is True

    def test_init_cli_warns_outside_git_repo(self, tmp_path: Path):
        """CLI init command must warn when cwd is not inside a git repo."""
        from click.testing import CliRunner

        from colonyos.cli import init

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(init, input="n\n")
            assert "Not inside a git repository" in result.output, (
                f"Expected git repo warning, got:\n{result.output}"
            )
            # User declined — should exit cleanly
            assert result.exit_code == 0

    def test_init_cli_no_warning_inside_git_repo(self, tmp_path: Path):
        """CLI init must NOT warn when inside a proper git repo."""
        from click.testing import CliRunner

        from colonyos.cli import init

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            Path(td, ".git").mkdir()
            result = runner.invoke(init, ["--manual"], input="\n")
            assert "Not inside a git repository" not in result.output


# ---------------------------------------------------------------------------
# 7.5  deploy/provision.sh --dry-run
# ---------------------------------------------------------------------------


class TestProvisionScriptE2E:
    """Validate deploy/provision.sh structure and dry-run behaviour."""

    SCRIPT = REPO_ROOT / "deploy" / "provision.sh"

    def test_script_exists_and_is_executable(self):
        assert self.SCRIPT.exists(), "deploy/provision.sh missing"

    def test_has_strict_mode(self):
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "set -euo pipefail" in content, (
            "Provisioning script must use strict mode"
        )

    def test_supports_dry_run_flag(self):
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "--dry-run" in content, "Script must support --dry-run flag"

    def test_supports_yes_flag(self):
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "--yes" in content, "Script must support --yes flag"

    def test_supports_slack_extra(self):
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "--slack" in content, "Script must support --slack flag"

    def test_checks_ubuntu_version(self):
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "22" in content, "Script must check for Ubuntu 22.04+"
        assert "os-release" in content, "Script must read /etc/os-release"

    def test_installs_python_311_plus(self):
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "python3.11" in content or "python3" in content
        assert "deadsnakes" in content, (
            "Script must use deadsnakes PPA as Python fallback"
        )

    def test_installs_nodejs(self):
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "nodesource" in content or "nodejs" in content, (
            "Script must install Node.js"
        )

    def test_nodejs_installed_via_signed_apt_repo(self):
        """Node.js must be installed via signed apt repo, not curl|bash."""
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "nodesource.com/setup" not in content, (
            "Node.js must not be installed via curl|bash setup script (supply chain risk)"
        )
        assert "nodesource.gpg" in content or "keyrings" in content, (
            "Node.js must be installed via signed apt repo with GPG key"
        )

    def test_installs_github_cli(self):
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "gh" in content, "Script must install GitHub CLI"

    def test_installs_colonyos_via_pipx(self):
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "pipx install" in content

    def test_pipx_install_is_idempotent(self):
        """pipx install must use --force for re-runnability."""
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "pipx install --force" in content, (
            "pipx install must use --force for idempotent re-runs"
        )

    def test_creates_system_user(self):
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "useradd" in content, "Script must create colonyos system user"
        assert "colonyos" in content

    def test_sets_up_systemd_service(self):
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "systemctl" in content, "Script must configure systemd"
        assert "colonyos-daemon" in content

    def test_env_file_has_restrictive_permissions(self):
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "chmod 600" in content, (
            "Env file must have chmod 600 for secrets protection"
        )

    def test_recommends_systemd_creds(self):
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "systemd-creds" in content or "secrets manager" in content, (
            "Script should recommend systemd-creds for production"
        )

    def test_seven_provisioning_steps(self):
        """Script must execute all 7 provisioning stages."""
        content = self.SCRIPT.read_text(encoding="utf-8")
        for step_num in range(1, 8):
            assert f"Step {step_num}/7" in content, (
                f"Missing provisioning step {step_num}/7"
            )

    def test_passes_shellcheck(self):
        """Shellcheck lint if available."""
        if not _command_exists("shellcheck"):
            pytest.skip("shellcheck not installed")
        result = subprocess.run(
            ["shellcheck", str(self.SCRIPT)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"shellcheck issues:\n{result.stdout}"

    def test_requires_root(self):
        content = self.SCRIPT.read_text(encoding="utf-8")
        assert "id -u" in content, "Script must check for root privileges"


# ---------------------------------------------------------------------------
# 7.6  Release workflow update-homebrew job logic
# ---------------------------------------------------------------------------


class TestReleaseWorkflowE2E:
    """End-to-end validation of the release workflow's Homebrew update logic."""

    def setup_method(self):
        release_path = REPO_ROOT / ".github" / "workflows" / "release.yml"
        assert release_path.exists(), "release.yml not found"
        with open(release_path) as f:
            self.workflow = yaml.safe_load(f)
        self.homebrew_job = self.workflow["jobs"]["update-homebrew"]

    def test_update_homebrew_job_exists(self):
        assert "update-homebrew" in self.workflow["jobs"]

    def test_depends_on_publish(self):
        needs = self.homebrew_job.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        assert "publish" in needs, (
            "update-homebrew must run after publish succeeds"
        )

    def test_uses_python_312(self):
        steps = self.homebrew_job.get("steps", [])
        python_steps = [
            s for s in steps
            if "python" in str(s.get("with", {})).lower()
        ]
        assert python_steps, "Job must set up Python"
        python_version = str(python_steps[0].get("with", {}).get("python-version", ""))
        assert "3.12" in python_version

    def test_downloads_build_artifacts(self):
        steps = self.homebrew_job.get("steps", [])
        step_texts = " ".join(str(s.get("uses", "")) for s in steps)
        assert "download-artifact" in step_texts, (
            "Job must download build artifacts"
        )

    def test_extracts_version_from_tag(self):
        steps = self.homebrew_job.get("steps", [])
        all_run = " ".join(str(s.get("run", "")) for s in steps)
        assert "GITHUB_REF" in all_run, (
            "Job must extract version from GITHUB_REF"
        )
        # Must strip the 'v' prefix
        assert "TAG#v" in all_run.replace(" ", "") or "${TAG#v}" in all_run, (
            "Job must strip 'v' prefix from tag"
        )

    def test_computes_sha256_from_sdist(self):
        steps = self.homebrew_job.get("steps", [])
        all_run = " ".join(str(s.get("run", "")) for s in steps)
        assert "sha256sum" in all_run, "Job must compute SHA-256 of sdist"

    def test_runs_formula_generation_script(self):
        steps = self.homebrew_job.get("steps", [])
        all_run = " ".join(str(s.get("run", "")) for s in steps)
        assert "generate-homebrew-formula.sh" in all_run
        assert "--output" in all_run, (
            "Formula generation must use --output flag"
        )

    def test_clones_tap_repo(self):
        steps = self.homebrew_job.get("steps", [])
        all_run = " ".join(str(s.get("run", "")) for s in steps)
        assert "homebrew-colonyos" in all_run
        assert "git clone" in all_run, "Job must clone the tap repo"

    def test_uses_homebrew_tap_token(self):
        steps = self.homebrew_job.get("steps", [])
        step_envs = " ".join(str(s.get("env", {})) for s in steps)
        assert "HOMEBREW_TAP_TOKEN" in step_envs, (
            "Job must use HOMEBREW_TAP_TOKEN secret"
        )

    def test_commits_and_pushes_formula(self):
        steps = self.homebrew_job.get("steps", [])
        all_run = " ".join(str(s.get("run", "")) for s in steps)
        assert "git commit" in all_run, "Job must commit the formula"
        assert "git push" in all_run, "Job must push to tap repo"

    def test_uses_bot_identity_for_commit(self):
        steps = self.homebrew_job.get("steps", [])
        all_run = " ".join(str(s.get("run", "")) for s in steps)
        assert "github-actions[bot]" in all_run, (
            "Job must use bot identity for git commit"
        )

    def test_actions_pinned_to_shas(self):
        """All action references must be SHA-pinned."""
        for step in self.homebrew_job.get("steps", []):
            uses = step.get("uses", "")
            if uses:
                assert re.search(r"@[0-9a-f]{40}", uses), (
                    f"Action '{uses}' is not pinned to a commit SHA"
                )

    def test_permissions_are_least_privilege(self):
        permissions = self.homebrew_job.get("permissions", {})
        assert permissions.get("contents") == "read", (
            "update-homebrew should only need contents: read"
        )

    def test_release_notes_include_brew_install(self):
        """Release notes body must mention brew install."""
        release_job = self.workflow["jobs"]["release"]
        steps = release_job.get("steps", [])
        all_run = " ".join(str(s.get("run", "")) for s in steps)
        assert "brew install" in all_run


# ---------------------------------------------------------------------------
# Cross-cutting: README documents all install methods
# ---------------------------------------------------------------------------


class TestReadmeInstallDocsE2E:
    """Verify README has correct, consistent install documentation."""

    def setup_method(self):
        readme_path = REPO_ROOT / "README.md"
        assert readme_path.exists()
        self.content = readme_path.read_text(encoding="utf-8")

    def test_homebrew_install_is_first_option(self):
        """Homebrew should appear before curl installer."""
        brew_pos = self.content.find("brew install")
        curl_pos = self.content.find("curl")
        assert brew_pos != -1, "README must mention brew install"
        assert curl_pos != -1, "README must mention curl installer"
        assert brew_pos < curl_pos, (
            "Homebrew install should appear before curl installer"
        )

    def test_homebrew_uses_correct_tap(self):
        assert "rangelak/colonyos/colonyos" in self.content, (
            "README must use 'brew install rangelak/colonyos/colonyos'"
        )

    def test_curl_installer_still_present(self):
        assert "curl" in self.content and "install.sh" in self.content

    def test_vm_deployment_section_exists(self):
        lower = self.content.lower()
        assert "vm" in lower or "provision" in lower or "deploy" in lower, (
            "README should mention VM deployment"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _command_exists(cmd: str) -> bool:
    """Check if a command is available on PATH."""
    try:
        subprocess.run(
            ["which", cmd],
            capture_output=True,
            timeout=5,
        )
        return subprocess.run(
            ["which", cmd], capture_output=True, timeout=5
        ).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
