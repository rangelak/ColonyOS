"""Tests for the cleanup module and CleanupConfig."""
from __future__ import annotations

import json
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from colonyos.cleanup import (
    ArtifactInfo,
    BranchInfo,
    ComplexityCategory,
    FileComplexity,
    delete_artifacts,
    delete_branches,
    list_merged_branches,
    list_stale_artifacts,
    check_branch_safety,
    scan_file_complexity,
    scan_directory,
    synthesize_refactor_prompt,
    write_cleanup_log,
    _categorize_complexity,
)
from colonyos.config import (
    CleanupConfig,
    ColonyConfig,
    load_config,
    save_config,
    _parse_cleanup_config,
    DEFAULTS,
)


# ---------------------------------------------------------------------------
# CleanupConfig tests (Task 1)
# ---------------------------------------------------------------------------

class TestCleanupConfig:
    def test_defaults(self):
        cfg = CleanupConfig()
        assert cfg.branch_retention_days == 0
        assert cfg.artifact_retention_days == 30
        assert cfg.scan_max_lines == 500
        assert cfg.scan_max_functions == 20

    def test_parse_empty(self):
        cfg = _parse_cleanup_config({})
        assert cfg.branch_retention_days == 0
        assert cfg.artifact_retention_days == 30

    def test_parse_custom_values(self):
        cfg = _parse_cleanup_config({
            "branch_retention_days": 7,
            "artifact_retention_days": 60,
            "scan_max_lines": 1000,
            "scan_max_functions": 50,
        })
        assert cfg.branch_retention_days == 7
        assert cfg.artifact_retention_days == 60
        assert cfg.scan_max_lines == 1000
        assert cfg.scan_max_functions == 50

    def test_parse_negative_branch_retention(self):
        with pytest.raises(ValueError, match="non-negative"):
            _parse_cleanup_config({"branch_retention_days": -1})

    def test_parse_negative_artifact_retention(self):
        with pytest.raises(ValueError, match="non-negative"):
            _parse_cleanup_config({"artifact_retention_days": -5})

    def test_parse_zero_scan_max_lines(self):
        with pytest.raises(ValueError, match="positive"):
            _parse_cleanup_config({"scan_max_lines": 0})

    def test_parse_zero_scan_max_functions(self):
        with pytest.raises(ValueError, match="positive"):
            _parse_cleanup_config({"scan_max_functions": 0})

    def test_colony_config_has_cleanup_default(self):
        cfg = ColonyConfig()
        assert isinstance(cfg.cleanup, CleanupConfig)
        assert cfg.cleanup.artifact_retention_days == 30

    def test_load_config_with_cleanup_section(self, tmp_path: Path):
        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir(parents=True)
        config_data = {
            "model": "sonnet",
            "cleanup": {
                "branch_retention_days": 14,
                "artifact_retention_days": 90,
                "scan_max_lines": 800,
                "scan_max_functions": 30,
            },
        }
        (config_dir / "config.yaml").write_text(
            yaml.dump(config_data, default_flow_style=False), encoding="utf-8"
        )
        cfg = load_config(tmp_path)
        assert cfg.cleanup.branch_retention_days == 14
        assert cfg.cleanup.artifact_retention_days == 90
        assert cfg.cleanup.scan_max_lines == 800
        assert cfg.cleanup.scan_max_functions == 30

    def test_load_config_without_cleanup_section(self, tmp_path: Path):
        config_dir = tmp_path / ".colonyos"
        config_dir.mkdir(parents=True)
        config_data = {"model": "sonnet"}
        (config_dir / "config.yaml").write_text(
            yaml.dump(config_data, default_flow_style=False), encoding="utf-8"
        )
        cfg = load_config(tmp_path)
        assert cfg.cleanup.branch_retention_days == 0
        assert cfg.cleanup.artifact_retention_days == 30

    def test_save_config_roundtrip(self, tmp_path: Path):
        cfg = ColonyConfig(
            cleanup=CleanupConfig(
                branch_retention_days=7,
                artifact_retention_days=60,
                scan_max_lines=1000,
                scan_max_functions=50,
            ),
        )
        save_config(tmp_path, cfg)
        loaded = load_config(tmp_path)
        assert loaded.cleanup.branch_retention_days == 7
        assert loaded.cleanup.artifact_retention_days == 60
        assert loaded.cleanup.scan_max_lines == 1000
        assert loaded.cleanup.scan_max_functions == 50

    def test_save_config_omits_defaults(self, tmp_path: Path):
        """When cleanup is all defaults, it should not appear in YAML."""
        cfg = ColonyConfig()
        save_config(tmp_path, cfg)
        raw = yaml.safe_load(
            (tmp_path / ".colonyos" / "config.yaml").read_text(encoding="utf-8")
        )
        assert "cleanup" not in raw

    def test_defaults_dict_has_cleanup(self):
        assert "cleanup" in DEFAULTS
        assert DEFAULTS["cleanup"]["artifact_retention_days"] == 30


# ---------------------------------------------------------------------------
# Branch cleanup tests (Task 2)
# ---------------------------------------------------------------------------

class TestListMergedBranches:
    def test_filters_by_prefix(self, tmp_path: Path):
        git_output = "  colonyos/feature-a\n  colonyos/feature-b\n  other-branch\n"
        with patch("colonyos.cleanup.subprocess.run") as mock_run:
            # First call: _get_default_branch (symbolic-ref)
            # Second call: _get_current_branch
            # Third call: git branch --merged
            # Then: _get_branch_last_commit_date for each matched branch
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),  # default branch
                MagicMock(returncode=0, stdout="main\n"),  # current branch
                MagicMock(returncode=0, stdout=git_output),  # merged branches
                MagicMock(returncode=0, stdout="2026-01-01T00:00:00+00:00\n"),  # date for feature-a
                MagicMock(returncode=0, stdout="2026-01-02T00:00:00+00:00\n"),  # date for feature-b
            ]
            result = list_merged_branches(tmp_path, prefix="colonyos/")
        assert len(result) == 2
        assert all(b.name.startswith("colonyos/") for b in result)

    def test_include_all_branches(self, tmp_path: Path):
        git_output = "  colonyos/feature-a\n  other-branch\n"
        with patch("colonyos.cleanup.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),
                MagicMock(returncode=0, stdout="main\n"),
                MagicMock(returncode=0, stdout=git_output),
                MagicMock(returncode=0, stdout="2026-01-01T00:00:00+00:00\n"),
                MagicMock(returncode=0, stdout="2026-01-02T00:00:00+00:00\n"),
            ]
            result = list_merged_branches(tmp_path, include_all=True)
        assert len(result) == 2

    def test_excludes_current_and_default(self, tmp_path: Path):
        git_output = "* main\n  colonyos/feature\n"
        with patch("colonyos.cleanup.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),
                MagicMock(returncode=0, stdout="main\n"),
                MagicMock(returncode=0, stdout=git_output),
                MagicMock(returncode=0, stdout="2026-01-01T00:00:00+00:00\n"),
            ]
            result = list_merged_branches(tmp_path, prefix="colonyos/")
        names = [b.name for b in result]
        assert "main" not in names
        assert "colonyos/feature" in names

    def test_handles_git_failure(self, tmp_path: Path):
        with patch("colonyos.cleanup.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),
                MagicMock(returncode=0, stdout="main\n"),
                MagicMock(returncode=1, stdout="", stderr="error"),
            ]
            result = list_merged_branches(tmp_path)
        assert result == []


class TestCheckBranchSafety:
    def test_default_branch_is_unsafe(self, tmp_path: Path):
        with patch("colonyos.cleanup.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),
                MagicMock(returncode=0, stdout="develop\n"),
            ]
            reason = check_branch_safety("main", tmp_path)
        assert reason == "default branch"

    def test_current_branch_is_unsafe(self, tmp_path: Path):
        with patch("colonyos.cleanup.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),
                MagicMock(returncode=0, stdout="my-branch\n"),
            ]
            reason = check_branch_safety("my-branch", tmp_path)
        assert reason == "current branch"

    def test_branch_with_open_pr_is_unsafe(self, tmp_path: Path):
        with patch("colonyos.cleanup.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),
                MagicMock(returncode=0, stdout="main\n"),
            ]
            with patch("colonyos.github.check_open_pr", return_value=(42, "https://example.com/pr/42")):
                reason = check_branch_safety("colonyos/feature", tmp_path)
        assert reason is not None
        assert "42" in reason

    def test_safe_branch_returns_none(self, tmp_path: Path):
        with patch("colonyos.cleanup.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),
                MagicMock(returncode=0, stdout="main\n"),
            ]
            with patch("colonyos.github.check_open_pr", return_value=(None, None)):
                reason = check_branch_safety("colonyos/old-feature", tmp_path)
        assert reason is None


class TestDeleteBranches:
    def test_dry_run_returns_candidates(self, tmp_path: Path):
        branches = [
            BranchInfo(name="colonyos/a", last_commit_date="2026-01-01", is_merged=True),
        ]
        with patch("colonyos.cleanup.check_branch_safety", return_value=None):
            result = delete_branches(branches, tmp_path, execute=False)
        assert "colonyos/a" in result.deleted_local
        assert len(result.skipped) == 0

    def test_dry_run_with_remote(self, tmp_path: Path):
        branches = [
            BranchInfo(name="colonyos/a", last_commit_date="2026-01-01", is_merged=True),
        ]
        with patch("colonyos.cleanup.check_branch_safety", return_value=None):
            result = delete_branches(branches, tmp_path, include_remote=True, execute=False)
        assert "colonyos/a" in result.deleted_local
        assert "colonyos/a" in result.deleted_remote

    def test_skips_unsafe_branches(self, tmp_path: Path):
        branches = [
            BranchInfo(name="main", last_commit_date="2026-01-01", is_merged=True),
        ]
        with patch("colonyos.cleanup.check_branch_safety", return_value="default branch"):
            result = delete_branches(branches, tmp_path, execute=False)
        assert len(result.deleted_local) == 0
        assert len(result.skipped) == 1
        assert result.skipped[0].skip_reason == "default branch"

    def test_execute_calls_git_delete(self, tmp_path: Path):
        branches = [
            BranchInfo(name="colonyos/done", last_commit_date="2026-01-01", is_merged=True),
        ]
        with patch("colonyos.cleanup.check_branch_safety", return_value=None):
            with patch("colonyos.cleanup.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = delete_branches(branches, tmp_path, execute=True)
        assert "colonyos/done" in result.deleted_local
        mock_run.assert_called_once()

    def test_execute_handles_delete_failure(self, tmp_path: Path):
        branches = [
            BranchInfo(name="colonyos/fail", last_commit_date="2026-01-01", is_merged=True),
        ]
        with patch("colonyos.cleanup.check_branch_safety", return_value=None):
            with patch("colonyos.cleanup.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stderr="error msg")
                result = delete_branches(branches, tmp_path, execute=True)
        assert len(result.errors) == 1
        assert "fail" in result.errors[0]


# ---------------------------------------------------------------------------
# Artifact cleanup tests (Task 3)
# ---------------------------------------------------------------------------

class TestListStaleArtifacts:
    def _write_run_log(self, runs_dir: Path, run_id: str, status: str, days_ago: int) -> Path:
        date = datetime.now(timezone.utc) - timedelta(days=days_ago)
        log_data = {
            "run_id": run_id,
            "status": status,
            "started_at": date.isoformat(),
            "prompt": "test",
        }
        path = runs_dir / f"{run_id}.json"
        path.write_text(json.dumps(log_data), encoding="utf-8")
        return path

    def test_finds_old_completed_runs(self, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        self._write_run_log(runs_dir, "run-old", "completed", days_ago=60)
        self._write_run_log(runs_dir, "run-new", "completed", days_ago=5)

        stale, skipped = list_stale_artifacts(runs_dir, retention_days=30)
        assert len(stale) == 1
        assert stale[0].run_id == "run-old"
        assert len(skipped) == 1

    def test_skips_running_runs(self, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        self._write_run_log(runs_dir, "run-active", "running", days_ago=60)

        stale, skipped = list_stale_artifacts(runs_dir, retention_days=30)
        assert len(stale) == 0
        assert len(skipped) == 1
        assert skipped[0].status == "running"

    def test_skips_cleanup_logs(self, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        (runs_dir / "cleanup_20260101_000000.json").write_text('{"operation": "test"}')
        self._write_run_log(runs_dir, "run-old", "completed", days_ago=60)

        stale, _ = list_stale_artifacts(runs_dir, retention_days=30)
        assert len(stale) == 1
        assert all(not a.run_id.startswith("cleanup_") for a in stale)

    def test_empty_dir(self, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        stale, skipped = list_stale_artifacts(runs_dir, retention_days=30)
        assert stale == []
        assert skipped == []

    def test_nonexistent_dir(self, tmp_path: Path):
        runs_dir = tmp_path / "nonexistent"
        stale, skipped = list_stale_artifacts(runs_dir, retention_days=30)
        assert stale == []
        assert skipped == []


class TestDeleteArtifacts:
    def test_dry_run_reports_without_deleting(self, tmp_path: Path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        path = runs_dir / "run-old.json"
        path.write_text('{"run_id": "run-old"}')

        artifacts = [ArtifactInfo(
            run_id="run-old", date="2026-01-01", status="completed",
            size_bytes=1024, path=path,
        )]
        result = delete_artifacts(artifacts, execute=False)
        assert len(result.removed) == 1
        assert result.bytes_reclaimed == 1024
        assert path.exists()  # Not actually deleted

    def test_execute_removes_files(self, tmp_path: Path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        path = runs_dir / "run-old.json"
        path.write_text('{"run_id": "run-old"}')

        artifacts = [ArtifactInfo(
            run_id="run-old", date="2026-01-01", status="completed",
            size_bytes=100, path=path,
        )]
        result = delete_artifacts(artifacts, execute=True)
        assert len(result.removed) == 1
        assert not path.exists()

    def test_handles_permission_error(self, tmp_path: Path):
        path = tmp_path / "readonly.json"
        artifacts = [ArtifactInfo(
            run_id="run-fail", date="2026-01-01", status="completed",
            size_bytes=100, path=path,
        )]
        # Path doesn't exist, so unlink will raise
        result = delete_artifacts(artifacts, execute=True)
        assert len(result.errors) == 1


# ---------------------------------------------------------------------------
# Structural scan tests (Task 4)
# ---------------------------------------------------------------------------

class TestScanFileComplexity:
    def test_python_file(self, tmp_path: Path):
        src = tmp_path / "example.py"
        src.write_text(textwrap.dedent("""\
            class MyClass:
                def method_a(self):
                    pass

                def method_b(self):
                    pass

            def standalone():
                pass

            async def async_func():
                pass
        """))
        lines, funcs = scan_file_complexity(src)
        assert lines == 12
        assert funcs == 5  # class, 2 methods, standalone, async_func

    def test_javascript_file(self, tmp_path: Path):
        src = tmp_path / "example.js"
        src.write_text(textwrap.dedent("""\
            function foo() {}
            class Bar {}
            const baz = () => {};
        """))
        lines, funcs = scan_file_complexity(src)
        assert lines == 3
        assert funcs >= 2  # at least function and class

    def test_empty_file(self, tmp_path: Path):
        src = tmp_path / "empty.py"
        src.write_text("")
        lines, funcs = scan_file_complexity(src)
        assert lines == 0
        assert funcs == 0

    def test_nonexistent_file(self, tmp_path: Path):
        src = tmp_path / "nope.py"
        lines, funcs = scan_file_complexity(src)
        assert lines == 0
        assert funcs == 0


class TestCategorizeComplexity:
    def test_under_threshold(self):
        assert _categorize_complexity(100, 5, 500, 20) is None

    def test_large(self):
        assert _categorize_complexity(600, 5, 500, 20) == ComplexityCategory.LARGE

    def test_very_large(self):
        assert _categorize_complexity(1200, 5, 500, 20) == ComplexityCategory.VERY_LARGE

    def test_massive(self):
        assert _categorize_complexity(1600, 5, 500, 20) == ComplexityCategory.MASSIVE

    def test_function_count_based(self):
        assert _categorize_complexity(100, 25, 500, 20) == ComplexityCategory.LARGE

    def test_exact_threshold(self):
        assert _categorize_complexity(500, 20, 500, 20) == ComplexityCategory.LARGE


class TestScanDirectory:
    def test_flags_large_files(self, tmp_path: Path):
        # Create a large Python file
        large = tmp_path / "big.py"
        large.write_text("\n".join([f"def func_{i}(): pass" for i in range(30)]) + "\n")

        results = scan_directory(tmp_path, max_lines=10, max_functions=5)
        assert len(results) >= 1
        assert results[0].path == "big.py"
        assert results[0].function_count == 30

    def test_skips_small_files(self, tmp_path: Path):
        small = tmp_path / "small.py"
        small.write_text("x = 1\n")
        results = scan_directory(tmp_path, max_lines=500, max_functions=20)
        assert len(results) == 0

    def test_skips_git_directory(self, tmp_path: Path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "big.py").write_text("\n" * 1000)

        results = scan_directory(tmp_path, max_lines=100)
        assert len(results) == 0

    def test_skips_non_source_files(self, tmp_path: Path):
        txt = tmp_path / "notes.txt"
        txt.write_text("\n" * 1000)

        results = scan_directory(tmp_path, max_lines=100)
        assert len(results) == 0

    def test_sorted_by_line_count(self, tmp_path: Path):
        (tmp_path / "medium.py").write_text("\n".join(["x = 1"] * 600) + "\n")
        (tmp_path / "large.py").write_text("\n".join(["x = 1"] * 1200) + "\n")

        results = scan_directory(tmp_path, max_lines=500)
        assert len(results) == 2
        assert results[0].line_count > results[1].line_count


# ---------------------------------------------------------------------------
# Refactor prompt tests (Task 7)
# ---------------------------------------------------------------------------

class TestSynthesizeRefactorPrompt:
    def test_basic_prompt(self):
        prompt = synthesize_refactor_prompt("src/big.py")
        assert "src/big.py" in prompt
        assert "Refactor" in prompt

    def test_with_scan_results(self):
        results = [
            FileComplexity(
                path="src/big.py",
                line_count=800,
                function_count=25,
                category=ComplexityCategory.MASSIVE,
            ),
        ]
        prompt = synthesize_refactor_prompt("src/big.py", scan_results=results)
        assert "800 lines" in prompt
        assert "25 functions" in prompt
        assert "massive" in prompt

    def test_file_not_in_results(self):
        results = [
            FileComplexity(
                path="src/other.py",
                line_count=600,
                function_count=15,
                category=ComplexityCategory.LARGE,
            ),
        ]
        prompt = synthesize_refactor_prompt("src/missing.py", scan_results=results)
        assert "src/missing.py" in prompt
        assert "Analyze" in prompt


# ---------------------------------------------------------------------------
# Audit logging tests
# ---------------------------------------------------------------------------

class TestWriteCleanupLog:
    def test_creates_log_file(self, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        runs_dir.mkdir(parents=True)
        result = {"deleted": 5, "skipped": 2}
        log_path = write_cleanup_log(runs_dir, "branches", result)
        assert log_path.exists()
        assert log_path.name.startswith("cleanup_")
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert data["operation"] == "branches"
        assert data["result"]["deleted"] == 5

    def test_creates_runs_dir_if_missing(self, tmp_path: Path):
        runs_dir = tmp_path / ".colonyos" / "runs"
        log_path = write_cleanup_log(runs_dir, "artifacts", {"removed": 0})
        assert log_path.exists()
        assert runs_dir.exists()
