"""Tests to verify GitHub Actions workflow YAML files are valid and complete."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestCIWorkflow:
    """Verify .github/workflows/ci.yml structure."""

    def setup_method(self):
        ci_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
        assert ci_path.exists(), f"CI workflow not found at {ci_path}"
        with open(ci_path) as f:
            self.workflow = yaml.safe_load(f)

    def test_has_name(self):
        assert "name" in self.workflow

    def test_triggers_on_push_to_main(self):
        # YAML parses bare `on:` as boolean True
        triggers = self.workflow.get("on") or self.workflow.get(True)
        assert triggers is not None, "Workflow must have 'on' triggers"
        assert "push" in triggers
        assert "main" in triggers["push"].get("branches", [])

    def test_triggers_on_pull_request(self):
        triggers = self.workflow.get("on") or self.workflow.get(True)
        assert triggers is not None
        assert "pull_request" in triggers

    def test_has_test_job(self):
        assert "jobs" in self.workflow
        assert "test" in self.workflow["jobs"]

    def test_python_matrix_includes_311_and_312(self):
        test_job = self.workflow["jobs"]["test"]
        strategy = test_job.get("strategy", {})
        matrix = strategy.get("matrix", {})
        python_versions = matrix.get("python-version", [])
        assert "3.11" in python_versions, "Python 3.11 missing from matrix"
        assert "3.12" in python_versions, "Python 3.12 missing from matrix"

    def test_has_pytest_step(self):
        test_job = self.workflow["jobs"]["test"]
        steps = test_job.get("steps", [])
        step_texts = " ".join(
            str(s.get("run", "")) + str(s.get("name", "")) for s in steps
        )
        assert "pytest" in step_texts, "No pytest step found in CI workflow"

    def test_installs_dev_dependencies(self):
        test_job = self.workflow["jobs"]["test"]
        steps = test_job.get("steps", [])
        step_texts = " ".join(str(s.get("run", "")) for s in steps)
        assert "dev" in step_texts, "Dev dependencies not installed in CI"


class TestReleaseWorkflow:
    """Verify .github/workflows/release.yml structure."""

    def setup_method(self):
        release_path = REPO_ROOT / ".github" / "workflows" / "release.yml"
        assert release_path.exists(), f"Release workflow not found at {release_path}"
        with open(release_path) as f:
            self.workflow = yaml.safe_load(f)

    def test_has_name(self):
        assert "name" in self.workflow

    def test_triggers_on_version_tag(self):
        triggers = self.workflow.get("on") or self.workflow.get(True)
        assert triggers is not None, "Workflow must have 'on' triggers"
        assert "push" in triggers
        tags = triggers["push"].get("tags", [])
        assert any("v*" in t or "v**" in t for t in tags), (
            "Release workflow must trigger on v* tags"
        )

    def test_has_test_job(self):
        assert "test" in self.workflow["jobs"], (
            "Release workflow must have a test gate job"
        )

    def test_has_build_job(self):
        assert "build" in self.workflow["jobs"]

    def test_has_publish_job(self):
        assert "publish" in self.workflow["jobs"]

    def test_has_release_job(self):
        assert "release" in self.workflow["jobs"]

    def test_publish_has_id_token_permission(self):
        publish_job = self.workflow["jobs"]["publish"]
        permissions = publish_job.get("permissions", {})
        assert permissions.get("id-token") == "write", (
            "Publish job must have id-token: write for OIDC"
        )

    def test_build_uses_python_build(self):
        build_job = self.workflow["jobs"]["build"]
        steps = build_job.get("steps", [])
        step_texts = " ".join(str(s.get("run", "")) for s in steps)
        assert "build" in step_texts, "Build job must use python -m build"

    def test_release_creates_github_release(self):
        release_job = self.workflow["jobs"]["release"]
        steps = release_job.get("steps", [])
        step_texts = " ".join(
            str(s.get("run", "")) + str(s.get("name", "")) for s in steps
        )
        assert "release" in step_texts.lower(), (
            "Release job must create a GitHub Release"
        )
