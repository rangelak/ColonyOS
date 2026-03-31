"""Tests that README.md contains required installation and deployment sections."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"


@pytest.fixture(scope="module")
def readme_text():
    return README.read_text(encoding="utf-8")


class TestReadmeInstallation:
    """Verify installation instructions are present and correct."""

    def test_homebrew_install_command(self, readme_text):
        assert "brew install rangelak/colonyos/colonyos" in readme_text

    def test_homebrew_listed_before_curl(self, readme_text):
        brew_pos = readme_text.index("brew install rangelak/colonyos/colonyos")
        curl_pos = readme_text.index("curl -sSL https://raw.githubusercontent.com")
        assert brew_pos < curl_pos, "Homebrew should appear before the curl installer"

    def test_curl_installer_present(self, readme_text):
        assert "curl -sSL https://raw.githubusercontent.com/rangelak/ColonyOS/main/install.sh" in readme_text

    def test_pip_install_present(self, readme_text):
        assert "pip install colonyos" in readme_text

    def test_no_stale_tap_reference(self, readme_text):
        assert "colonyos/tap" not in readme_text, (
            "Stale 'colonyos/tap' reference found — should be 'rangelak/colonyos'"
        )


class TestReadmeVMDeployment:
    """Verify VM deployment quickstart section."""

    def test_vm_deployment_section_exists(self, readme_text):
        assert "## VM Deployment" in readme_text

    def test_provision_script_referenced(self, readme_text):
        assert "deploy/provision.sh" in readme_text

    def test_deploy_readme_linked(self, readme_text):
        assert "deploy/README.md" in readme_text

    def test_vm_section_in_nav(self, readme_text):
        assert 'href="#vm-deployment"' in readme_text
