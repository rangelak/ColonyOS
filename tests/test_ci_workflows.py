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

    def test_supports_workflow_call(self):
        """CI workflow must support workflow_call for reuse from release.yml."""
        triggers = self.workflow.get("on") or self.workflow.get(True)
        assert triggers is not None
        assert "workflow_call" in triggers, (
            "CI workflow must support workflow_call for reuse"
        )

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

    def test_has_top_level_permissions(self):
        """CI workflow must have top-level permissions: {} for least privilege."""
        assert "permissions" in self.workflow, (
            "CI workflow must set top-level permissions: {} for least privilege"
        )

    def test_actions_pinned_to_shas(self):
        """All 'uses' steps must reference commit SHAs, not mutable tags."""
        import re
        for job_name, job in self.workflow.get("jobs", {}).items():
            for step in job.get("steps", []):
                uses = step.get("uses", "")
                if uses:
                    assert re.search(r"@[0-9a-f]{40}", uses), (
                        f"Action '{uses}' in job '{job_name}' is not pinned "
                        f"to a commit SHA — supply chain risk"
                    )


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

    def test_test_job_reuses_ci_workflow(self):
        """Release test job must use workflow_call to reuse ci.yml, not duplicate it."""
        test_job = self.workflow["jobs"]["test"]
        uses = test_job.get("uses", "")
        assert "ci.yml" in uses, (
            "Release test job must reuse ci.yml via workflow_call, not duplicate it"
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

    def test_has_top_level_permissions(self):
        """Release workflow must have top-level permissions: {} for least privilege."""
        assert "permissions" in self.workflow, (
            "Release workflow must set top-level permissions: {} for least privilege"
        )

    def test_has_concurrency_control(self):
        """Release workflow must have concurrency control to prevent racing releases."""
        assert "concurrency" in self.workflow, (
            "Release workflow must have concurrency control"
        )

    def test_actions_pinned_to_shas(self):
        """All 'uses' steps must reference commit SHAs, not mutable tags."""
        import re
        for job_name, job in self.workflow.get("jobs", {}).items():
            # Skip reusable workflow calls (uses: ./.github/workflows/ci.yml)
            if "uses" in job and "steps" not in job:
                continue
            for step in job.get("steps", []):
                uses = step.get("uses", "")
                if uses:
                    assert re.search(r"@[0-9a-f]{40}", uses), (
                        f"Action '{uses}' in job '{job_name}' is not pinned "
                        f"to a commit SHA — supply chain risk"
                    )

    def test_has_update_homebrew_job(self):
        """Release workflow must include a job to auto-update the Homebrew formula."""
        assert "update-homebrew" in self.workflow["jobs"], (
            "Release workflow must have an update-homebrew job (FR-5.4)"
        )

    def test_update_homebrew_pushes_to_main(self):
        """Homebrew update must push directly to main."""
        homebrew_job = self.workflow["jobs"]["update-homebrew"]
        steps = homebrew_job.get("steps", [])
        all_run = " ".join(str(s.get("run", "")) for s in steps)
        assert "git push origin main" in all_run, (
            "update-homebrew must push directly to main"
        )

    def test_update_homebrew_validates_version_format(self):
        """Homebrew update must validate version format to prevent injection."""
        homebrew_job = self.workflow["jobs"]["update-homebrew"]
        steps = homebrew_job.get("steps", [])
        all_run = " ".join(str(s.get("run", "")) for s in steps)
        assert "grep" in all_run and "VERSION" in all_run, (
            "update-homebrew must validate VERSION format before sed substitution"
        )

    def test_update_homebrew_has_contents_write(self):
        """Homebrew update job must have contents: write permission."""
        homebrew_job = self.workflow["jobs"]["update-homebrew"]
        permissions = homebrew_job.get("permissions", {})
        assert permissions.get("contents") == "write", (
            "update-homebrew must have contents: write to push to main"
        )

    def test_checksums_not_in_pypi_upload_path(self):
        """SHA256SUMS.txt must not be in the dist/ artifact uploaded to PyPI."""
        build_job = self.workflow["jobs"]["build"]
        steps = build_job.get("steps", [])
        all_run = " ".join(str(s.get("run", "")) for s in steps)
        assert "mv SHA256SUMS.txt" in all_run or "cp SHA256SUMS.txt" in all_run, (
            "Build job must move SHA256SUMS.txt out of dist/ before upload"
        )

    def test_checksums_include_install_script(self):
        """SHA256SUMS.txt must include a checksum for install.sh (FR-4.6)."""
        build_job = self.workflow["jobs"]["build"]
        steps = build_job.get("steps", [])
        all_run = " ".join(str(s.get("run", "")) for s in steps)
        assert "install.sh" in all_run, (
            "Build job must include install.sh in SHA256SUMS.txt (FR-4.6)"
        )

    def test_release_notes_use_curl_f_flag(self):
        """Release notes curl command must include -f flag for HTTP error detection."""
        release_job = self.workflow["jobs"]["release"]
        steps = release_job.get("steps", [])
        all_run = " ".join(str(s.get("run", "")) for s in steps)
        assert "curl -fsSL" in all_run, (
            "Release notes must use curl -fsSL (with -f for HTTP error detection)"
        )


class TestHomebrewFormula:
    """Verify Formula/colonyos.rb structure."""

    def setup_method(self):
        self.formula_path = REPO_ROOT / "Formula" / "colonyos.rb"
        assert self.formula_path.exists(), "Homebrew formula not found"
        self.content = self.formula_path.read_text(encoding="utf-8")

    def test_formula_documents_auto_update(self):
        """Formula must document that it is auto-updated by the release workflow."""
        assert "release workflow" in self.content.lower() or "auto" in self.content.lower(), (
            "Formula should document that it is auto-updated by the release workflow"
        )

    def test_formula_uses_canonical_pypi_url(self):
        """Formula must use files.pythonhosted.org, not pypi.io."""
        assert "files.pythonhosted.org" in self.content, (
            "Formula must use canonical PyPI URL (files.pythonhosted.org)"
        )
        assert "pypi.io" not in self.content, (
            "Formula must not use pypi.io — use files.pythonhosted.org instead"
        )

    def test_formula_documents_placeholder_state(self):
        """Formula must document that sha256 is a placeholder before first release."""
        assert "placeholder" in self.content.lower() or "first release" in self.content.lower(), (
            "Formula should document that sha256 is a placeholder before first release"
        )
