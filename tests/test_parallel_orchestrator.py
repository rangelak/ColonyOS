"""Tests for parallel implement orchestration (Task 6.0)."""

import asyncio
import subprocess
from pathlib import Path

import pytest

from colonyos.config import ColonyConfig, ParallelImplementConfig
from colonyos.models import Phase, PhaseResult, TaskStatus
from colonyos.parallel_orchestrator import (
    ParallelOrchestrator,
    ParallelRunState,
    TaskState,
    should_use_parallel,
)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository for testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    (repo / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    return repo


class TestTaskState:
    def test_default_values(self) -> None:
        state = TaskState(task_id="1.0")
        assert state.task_id == "1.0"
        assert state.status == TaskStatus.PENDING
        assert state.worktree_path is None
        assert state.phase_result is None

    def test_duration_not_started(self) -> None:
        state = TaskState(task_id="1.0")
        assert state.duration_ms == 0

    def test_duration_completed(self) -> None:
        state = TaskState(task_id="1.0")
        state.started_at = 100.0
        state.finished_at = 102.5
        assert state.duration_ms == 2500


class TestParallelRunState:
    def test_mark_task_started(self) -> None:
        state = ParallelRunState()
        state.tasks["1.0"] = TaskState(task_id="1.0")
        state.mark_task_started("1.0")
        assert state.tasks["1.0"].status == TaskStatus.RUNNING
        assert state.tasks["1.0"].started_at is not None

    def test_mark_task_completed(self) -> None:
        state = ParallelRunState()
        state.tasks["1.0"] = TaskState(task_id="1.0")
        state.tasks["1.0"].started_at = 100.0
        result = PhaseResult(phase=Phase.IMPLEMENT, success=True)
        state.mark_task_completed("1.0", result)
        assert state.tasks["1.0"].status == TaskStatus.COMPLETED
        assert "1.0" in state.completed

    def test_mark_task_failed(self) -> None:
        state = ParallelRunState()
        state.tasks["1.0"] = TaskState(task_id="1.0")
        state.tasks["1.0"].started_at = 100.0
        state.mark_task_failed("1.0", "Test error")
        assert state.tasks["1.0"].status == TaskStatus.FAILED
        assert "1.0" in state.failed
        assert state.tasks["1.0"].error == "Test error"

    def test_all_done_empty(self) -> None:
        state = ParallelRunState()
        assert state.all_done() is True

    def test_all_done_partial(self) -> None:
        state = ParallelRunState()
        state.tasks["1.0"] = TaskState(task_id="1.0")
        state.tasks["2.0"] = TaskState(task_id="2.0")
        state.completed.add("1.0")
        assert state.all_done() is False

    def test_all_done_complete(self) -> None:
        state = ParallelRunState()
        state.tasks["1.0"] = TaskState(task_id="1.0")
        state.tasks["2.0"] = TaskState(task_id="2.0")
        state.completed.add("1.0")
        state.failed.add("2.0")
        assert state.all_done() is True

    def test_parallelism_ratio(self) -> None:
        state = ParallelRunState()
        state.wall_start_time = 0.0
        state.wall_end_time = 1.0
        state.agent_time_ms = 3000
        assert state.parallelism_ratio == 3.0


class TestParallelOrchestrator:
    def test_parse_tasks_simple(self, tmp_repo: Path) -> None:
        config = ColonyConfig()
        task_content = """
- [ ] 1.0 Add config
  depends_on: []
- [ ] 2.0 Add DAG
  depends_on: [1.0]
"""
        orchestrator = ParallelOrchestrator(
            repo_root=tmp_repo,
            config=config,
            task_file_content=task_content,
            base_branch="main",
        )
        orchestrator.parse_tasks()
        assert len(orchestrator.state.tasks) == 2
        assert "1.0" in orchestrator.state.tasks
        assert "2.0" in orchestrator.state.tasks

    def test_parse_tasks_no_tasks(self, tmp_repo: Path) -> None:
        config = ColonyConfig()
        task_content = "No tasks here"
        orchestrator = ParallelOrchestrator(
            repo_root=tmp_repo,
            config=config,
            task_file_content=task_content,
            base_branch="main",
        )
        with pytest.raises(ValueError, match="No tasks found"):
            orchestrator.parse_tasks()

    def test_parse_tasks_cycle_detected(self, tmp_repo: Path) -> None:
        from colonyos.dag import CircularDependencyError
        config = ColonyConfig()
        task_content = """
- [ ] 1.0 Task A
  depends_on: [2.0]
- [ ] 2.0 Task B
  depends_on: [1.0]
"""
        orchestrator = ParallelOrchestrator(
            repo_root=tmp_repo,
            config=config,
            task_file_content=task_content,
            base_branch="main",
        )
        with pytest.raises(CircularDependencyError):
            orchestrator.parse_tasks()

    def test_preflight_success(self, tmp_repo: Path) -> None:
        config = ColonyConfig()
        task_content = """
- [ ] 1.0 Task A
  depends_on: []
"""
        orchestrator = ParallelOrchestrator(
            repo_root=tmp_repo,
            config=config,
            task_file_content=task_content,
            base_branch="main",
        )
        orchestrator.parse_tasks()
        assert orchestrator.preflight() is True

    def test_create_worktrees(self, tmp_repo: Path) -> None:
        config = ColonyConfig()
        task_content = """
- [ ] 1.0 Task A
  depends_on: []
"""
        orchestrator = ParallelOrchestrator(
            repo_root=tmp_repo,
            config=config,
            task_file_content=task_content,
            base_branch="main",
        )
        orchestrator.parse_tasks()
        orchestrator.create_worktrees()
        assert orchestrator.state.tasks["1.0"].worktree_path is not None
        assert orchestrator.state.tasks["1.0"].worktree_path.exists()
        orchestrator.cleanup_worktrees()

    def test_get_summary(self, tmp_repo: Path) -> None:
        config = ColonyConfig()
        task_content = """
- [ ] 1.0 Task A
  depends_on: []
- [ ] 2.0 Task B
  depends_on: []
"""
        orchestrator = ParallelOrchestrator(
            repo_root=tmp_repo,
            config=config,
            task_file_content=task_content,
            base_branch="main",
        )
        orchestrator.parse_tasks()
        orchestrator.state.completed.add("1.0")
        orchestrator.state.failed.add("2.0")
        summary = orchestrator.get_summary()
        assert summary["total_tasks"] == 2
        assert summary["completed"] == 1
        assert summary["failed"] == 1


class TestRunAllAsync:
    def test_run_all_simple(self, tmp_repo: Path) -> None:
        config = ColonyConfig()
        task_content = """
- [ ] 1.0 Task A
  depends_on: []
"""
        orchestrator = ParallelOrchestrator(
            repo_root=tmp_repo,
            config=config,
            task_file_content=task_content,
            base_branch="main",
        )
        orchestrator.parse_tasks()
        orchestrator.create_worktrees()

        def mock_runner(task_id: str, worktree: Path, desc: str) -> PhaseResult:
            return PhaseResult(
                phase=Phase.IMPLEMENT,
                success=True,
                artifacts={"task_id": task_id},
            )

        result = asyncio.run(orchestrator.run_all(mock_runner))
        assert result.all_done() is True
        assert "1.0" in result.completed
        orchestrator.cleanup_worktrees()

    def test_run_all_with_dependencies(self, tmp_repo: Path) -> None:
        config = ColonyConfig()
        task_content = """
- [ ] 1.0 Task A
  depends_on: []
- [ ] 2.0 Task B
  depends_on: [1.0]
"""
        orchestrator = ParallelOrchestrator(
            repo_root=tmp_repo,
            config=config,
            task_file_content=task_content,
            base_branch="main",
        )
        orchestrator.parse_tasks()
        orchestrator.create_worktrees()

        execution_order = []

        def mock_runner(task_id: str, worktree: Path, desc: str) -> PhaseResult:
            execution_order.append(task_id)
            return PhaseResult(
                phase=Phase.IMPLEMENT,
                success=True,
                artifacts={"task_id": task_id},
            )

        result = asyncio.run(orchestrator.run_all(mock_runner))
        assert result.all_done() is True
        # 1.0 must complete before 2.0 starts
        assert execution_order.index("1.0") < execution_order.index("2.0")
        orchestrator.cleanup_worktrees()


class TestShouldUseParallel:
    def test_disabled_in_config(self) -> None:
        config = ColonyConfig(
            parallel_implement=ParallelImplementConfig(enabled=False)
        )
        assert should_use_parallel(config, task_count=5) is False

    def test_single_task(self) -> None:
        config = ColonyConfig()
        assert should_use_parallel(config, task_count=1) is False

    def test_multiple_tasks_enabled(self) -> None:
        config = ColonyConfig()
        assert should_use_parallel(config, task_count=3) is True

    def test_zero_tasks(self) -> None:
        config = ColonyConfig()
        assert should_use_parallel(config, task_count=0) is False
