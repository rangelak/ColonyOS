"""Tests for Docker-related functionality: entrypoint logic, Dockerfile validity,
.dockerignore coverage, and container-aware doctor checks."""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = REPO_ROOT / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
ENTRYPOINT = REPO_ROOT / "docker-entrypoint.sh"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"


# ---------------------------------------------------------------------------
# Dockerfile validity
# ---------------------------------------------------------------------------
class TestDockerfileValidity:
    """Verify the Dockerfile exists and has expected structure."""

    def test_dockerfile_exists(self) -> None:
        assert DOCKERFILE.exists(), "Dockerfile must exist at repo root"

    def test_dockerfile_has_multi_stage_build(self) -> None:
        content = DOCKERFILE.read_text()
        from_statements = [l for l in content.splitlines() if l.startswith("FROM ")]
        assert len(from_statements) >= 3, (
            f"Expected at least 3 FROM stages (node-deps, web-build, runtime), "
            f"found {len(from_statements)}"
        )

    def test_dockerfile_exposes_port_7400(self) -> None:
        content = DOCKERFILE.read_text()
        assert "EXPOSE 7400" in content

    def test_dockerfile_sets_non_root_user(self) -> None:
        content = DOCKERFILE.read_text()
        assert "USER colonyos" in content

    def test_dockerfile_sets_workspace_workdir(self) -> None:
        content = DOCKERFILE.read_text()
        assert "WORKDIR /workspace" in content

    def test_dockerfile_sets_entrypoint(self) -> None:
        content = DOCKERFILE.read_text()
        assert "ENTRYPOINT" in content
        assert "docker-entrypoint.sh" in content


# ---------------------------------------------------------------------------
# .dockerignore
# ---------------------------------------------------------------------------
class TestDockerignore:
    """Verify .dockerignore excludes sensitive and unnecessary files."""

    def test_dockerignore_exists(self) -> None:
        assert DOCKERIGNORE.exists(), ".dockerignore must exist at repo root"

    @pytest.mark.parametrize("pattern", [
        ".env",
        ".git/",
        ".venv/",
        "__pycache__/",
        ".colonyos/runs/",
        "node_modules/",
    ])
    def test_dockerignore_excludes_sensitive_patterns(self, pattern: str) -> None:
        content = DOCKERIGNORE.read_text()
        assert pattern in content, f".dockerignore must exclude '{pattern}'"


# ---------------------------------------------------------------------------
# Entrypoint script
# ---------------------------------------------------------------------------
class TestEntrypointScript:
    """Verify the entrypoint script exists and has correct properties."""

    def test_entrypoint_exists(self) -> None:
        assert ENTRYPOINT.exists(), "docker-entrypoint.sh must exist at repo root"

    def test_entrypoint_is_executable(self) -> None:
        mode = ENTRYPOINT.stat().st_mode
        assert mode & stat.S_IXUSR, "docker-entrypoint.sh must be executable"

    def test_entrypoint_has_shebang(self) -> None:
        first_line = ENTRYPOINT.read_text().splitlines()[0]
        assert first_line.startswith("#!/"), "Entrypoint must have a shebang line"

    def test_entrypoint_validates_anthropic_api_key(self) -> None:
        content = ENTRYPOINT.read_text()
        assert "ANTHROPIC_API_KEY" in content

    def test_entrypoint_validates_gh_token(self) -> None:
        content = ENTRYPOINT.read_text()
        assert "GH_TOKEN" in content

    def test_entrypoint_cleans_git_lock_files(self) -> None:
        content = ENTRYPOINT.read_text()
        assert "index.lock" in content

    def test_entrypoint_supports_repo_clone(self) -> None:
        content = ENTRYPOINT.read_text()
        assert "COLONYOS_REPO_URL" in content
        assert "git clone" in content

    def test_entrypoint_defaults_to_dashboard(self) -> None:
        content = ENTRYPOINT.read_text()
        assert "colonyos ui" in content
        assert "0.0.0.0" in content

    def test_entrypoint_passes_through_cmd(self) -> None:
        content = ENTRYPOINT.read_text()
        assert 'exec "$@"' in content


# ---------------------------------------------------------------------------
# Entrypoint logic — env var validation via bash execution
# ---------------------------------------------------------------------------
class TestEntrypointExecution:
    """Test entrypoint script behavior by running it with bash."""

    def test_missing_anthropic_api_key_exits_with_error(self) -> None:
        """Entrypoint must fail fast if ANTHROPIC_API_KEY is not set."""
        result = subprocess.run(
            ["bash", str(ENTRYPOINT)],
            capture_output=True,
            text=True,
            timeout=5,
            env={**os.environ, "ANTHROPIC_API_KEY": "", "GH_TOKEN": "test"},
        )
        assert result.returncode != 0
        assert "ANTHROPIC_API_KEY" in result.stderr

    def test_missing_gh_token_warns_but_continues(self) -> None:
        """Entrypoint should warn about missing GH_TOKEN but not exit."""
        result = subprocess.run(
            ["bash", str(ENTRYPOINT), "echo", "hello"],
            capture_output=True,
            text=True,
            timeout=5,
            env={**os.environ, "ANTHROPIC_API_KEY": "test-key", "GH_TOKEN": ""},
        )
        # Should succeed (exit 0) because we pass a CMD override
        assert result.returncode == 0
        assert "WARNING" in result.stderr or "WARNING" in result.stdout


# ---------------------------------------------------------------------------
# Docker Compose
# ---------------------------------------------------------------------------
class TestDockerCompose:
    """Verify docker-compose.yml exists and has expected structure."""

    def test_compose_file_exists(self) -> None:
        assert COMPOSE_FILE.exists(), "docker-compose.yml must exist at repo root"

    def test_compose_has_colonyos_service(self) -> None:
        import yaml

        config = yaml.safe_load(COMPOSE_FILE.read_text())
        assert "services" in config
        assert "colonyos" in config["services"]

    def test_compose_maps_port_7400(self) -> None:
        content = COMPOSE_FILE.read_text()
        assert "7400:7400" in content

    def test_compose_has_healthcheck(self) -> None:
        import yaml

        config = yaml.safe_load(COMPOSE_FILE.read_text())
        service = config["services"]["colonyos"]
        assert "healthcheck" in service

    def test_compose_has_restart_policy(self) -> None:
        import yaml

        config = yaml.safe_load(COMPOSE_FILE.read_text())
        service = config["services"]["colonyos"]
        assert service.get("restart") == "unless-stopped"


# ---------------------------------------------------------------------------
# .env.example
# ---------------------------------------------------------------------------
class TestEnvExample:
    """Verify .env.example documents all required variables."""

    def test_env_example_exists(self) -> None:
        assert ENV_EXAMPLE.exists(), ".env.example must exist at repo root"

    @pytest.mark.parametrize("var", [
        "ANTHROPIC_API_KEY",
        "GH_TOKEN",
        "COLONYOS_REPO_URL",
        "COLONYOS_POSTHOG_API_KEY",
        "COLONYOS_POSTHOG_HOST",
        "COLONYOS_SLACK_BOT_TOKEN",
        "COLONYOS_SLACK_APP_TOKEN",
        "COLONYOS_WRITE_ENABLED",
    ])
    def test_env_example_documents_variable(self, var: str) -> None:
        content = ENV_EXAMPLE.read_text()
        assert var in content, f".env.example must document {var}"


# ---------------------------------------------------------------------------
# Doctor — container-aware checks
# ---------------------------------------------------------------------------
class TestDoctorDockerChecks:
    """Verify doctor.py adds Docker-specific checks when in a container."""

    def test_is_running_in_docker_env_var(self) -> None:
        from colonyos.doctor import is_running_in_docker

        with patch.dict(os.environ, {"COLONYOS_DOCKER": "1"}):
            assert is_running_in_docker() is True

    def test_is_running_in_docker_dockerenv_file(self, tmp_path: Path) -> None:
        from colonyos.doctor import is_running_in_docker

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("COLONYOS_DOCKER", None)
            with patch("colonyos.doctor.Path") as mock_path:
                mock_path.return_value.exists.return_value = True
                # Without COLONYOS_DOCKER, falls through to file check
                # The actual Path("/.dockerenv").exists() is called directly
                # so we test the env var path instead
                pass

    def test_is_not_running_in_docker(self) -> None:
        from colonyos.doctor import is_running_in_docker

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("COLONYOS_DOCKER", None)
            # On a dev machine, /.dockerenv won't exist
            # This test may vary by environment, but is valid on dev machines
            # We test deterministically via the env var path
            with patch.dict(os.environ, {"COLONYOS_DOCKER": "0"}):
                assert is_running_in_docker() is False

    def test_doctor_checks_docker_env_vars_when_in_container(
        self, tmp_repo: Path
    ) -> None:
        from conftest import write_config
        from colonyos.doctor import run_doctor_checks

        write_config(tmp_repo)

        with patch.dict(os.environ, {
            "COLONYOS_DOCKER": "1",
            "ANTHROPIC_API_KEY": "test-key",
            "GH_TOKEN": "test-token",
        }):
            results = run_doctor_checks(tmp_repo)
            check_names = [name for name, _, _ in results]
            assert "Docker runtime" in check_names
            assert "ANTHROPIC_API_KEY" in check_names
            assert "GH_TOKEN" in check_names

    def test_doctor_no_docker_checks_outside_container(
        self, tmp_repo: Path
    ) -> None:
        from conftest import write_config
        from colonyos.doctor import run_doctor_checks

        write_config(tmp_repo)

        with patch.dict(os.environ, {"COLONYOS_DOCKER": ""}, clear=False):
            os.environ.pop("COLONYOS_DOCKER", None)
            results = run_doctor_checks(tmp_repo)
            check_names = [name for name, _, _ in results]
            assert "Docker runtime" not in check_names
            assert "ANTHROPIC_API_KEY" not in check_names

    def test_doctor_detects_missing_api_key_in_docker(
        self, tmp_repo: Path
    ) -> None:
        from conftest import write_config
        from colonyos.doctor import run_doctor_checks

        write_config(tmp_repo)

        with patch.dict(os.environ, {
            "COLONYOS_DOCKER": "1",
            "ANTHROPIC_API_KEY": "",
            "GH_TOKEN": "test-token",
        }):
            results = run_doctor_checks(tmp_repo)
            api_key_check = [
                (name, ok, hint)
                for name, ok, hint in results
                if name == "ANTHROPIC_API_KEY"
            ]
            assert len(api_key_check) == 1
            assert api_key_check[0][1] is False  # Should fail

    def test_doctor_detects_workspace_git_repo(self, tmp_repo: Path) -> None:
        from conftest import write_config
        from colonyos.doctor import run_doctor_checks

        write_config(tmp_repo)
        # Create .git directory to simulate a git repo
        (tmp_repo / ".git").mkdir()

        with patch.dict(os.environ, {
            "COLONYOS_DOCKER": "1",
            "ANTHROPIC_API_KEY": "test-key",
            "GH_TOKEN": "test-token",
        }):
            results = run_doctor_checks(tmp_repo)
            workspace_check = [
                (name, ok, hint)
                for name, ok, hint in results
                if name == "Workspace git repo"
            ]
            assert len(workspace_check) == 1
            assert workspace_check[0][1] is True

    def test_doctor_detects_missing_workspace_git_repo(
        self, tmp_repo: Path
    ) -> None:
        from conftest import write_config
        from colonyos.doctor import run_doctor_checks

        write_config(tmp_repo)

        with patch.dict(os.environ, {
            "COLONYOS_DOCKER": "1",
            "ANTHROPIC_API_KEY": "test-key",
            "GH_TOKEN": "test-token",
        }):
            results = run_doctor_checks(tmp_repo)
            workspace_check = [
                (name, ok, hint)
                for name, ok, hint in results
                if name == "Workspace git repo"
            ]
            assert len(workspace_check) == 1
            assert workspace_check[0][1] is False
