"""Parallel implement orchestration for ColonyOS.

This module coordinates parallel task execution:
1. Parses task dependencies from task file
2. Creates isolated worktrees for each task
3. Runs agents in parallel batches respecting dependencies
4. Merges results back and resolves conflicts
5. Tracks progress and handles failures
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from colonyos.config import ColonyConfig, ParallelImplementConfig
from colonyos.dag import TaskDAG, parse_task_file, CircularDependencyError
from colonyos.models import Phase, PhaseResult, TaskStatus
from colonyos.parallel_preflight import check_parallel_preflight
from colonyos.worktree import WorktreeManager, WorktreeError

logger = logging.getLogger(__name__)


@dataclass
class TaskState:
    """State of a single task during parallel execution."""

    task_id: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    worktree_path: Path | None = None
    phase_result: PhaseResult | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None

    @property
    def duration_ms(self) -> int:
        if self.started_at is None or self.finished_at is None:
            return 0
        return int((self.finished_at - self.started_at) * 1000)


@dataclass
class ParallelRunState:
    """State of an entire parallel implementation run."""

    tasks: dict[str, TaskState] = field(default_factory=dict)
    dag: TaskDAG | None = None
    completed: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    wall_start_time: float | None = None
    wall_end_time: float | None = None
    agent_time_ms: int = 0  # Sum of all task durations

    @property
    def wall_time_ms(self) -> int:
        if self.wall_start_time is None or self.wall_end_time is None:
            return 0
        return int((self.wall_end_time - self.wall_start_time) * 1000)

    @property
    def parallelism_ratio(self) -> float:
        if self.wall_time_ms == 0:
            return 1.0
        return self.agent_time_ms / self.wall_time_ms

    def mark_task_started(self, task_id: str) -> None:
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.RUNNING
            self.tasks[task_id].started_at = time.monotonic()

    def mark_task_completed(self, task_id: str, result: PhaseResult) -> None:
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.status = TaskStatus.COMPLETED
            task.finished_at = time.monotonic()
            task.phase_result = result
            self.completed.add(task_id)
            self.agent_time_ms += task.duration_ms

    def mark_task_failed(self, task_id: str, error: str) -> None:
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.status = TaskStatus.FAILED
            task.finished_at = time.monotonic()
            task.error = error
            self.failed.add(task_id)
            self.agent_time_ms += task.duration_ms

    def get_ready_tasks(self) -> list[str]:
        """Get tasks ready to execute (dependencies satisfied)."""
        if self.dag is None:
            return []
        return self.dag.get_ready_tasks(self.completed)

    def all_done(self) -> bool:
        """Check if all tasks are completed or failed."""
        return len(self.completed) + len(self.failed) == len(self.tasks)


class ParallelOrchestrator:
    """Orchestrates parallel task execution."""

    def __init__(
        self,
        repo_root: Path,
        config: ColonyConfig,
        task_file_content: str,
        base_branch: str,
        on_task_start: Callable[[str], None] | None = None,
        on_task_complete: Callable[[str, PhaseResult], None] | None = None,
        on_task_error: Callable[[str, str], None] | None = None,
    ) -> None:
        """Initialize the parallel orchestrator.

        Args:
            repo_root: Path to repository root.
            config: ColonyOS configuration.
            task_file_content: Content of the task file (markdown).
            base_branch: Branch to base worktrees on.
            on_task_start: Callback when a task starts.
            on_task_complete: Callback when a task completes.
            on_task_error: Callback when a task fails.
        """
        self.repo_root = repo_root
        self.config = config
        self.pi_config = config.parallel_implement
        self.task_file_content = task_file_content
        self.base_branch = base_branch
        self.on_task_start = on_task_start
        self.on_task_complete = on_task_complete
        self.on_task_error = on_task_error

        self.worktree_manager = WorktreeManager(repo_root)
        self.state = ParallelRunState()

    def parse_tasks(self) -> None:
        """Parse task file and build DAG."""
        dependencies = parse_task_file(self.task_file_content)
        if not dependencies:
            raise ValueError("No tasks found in task file")

        self.state.dag = TaskDAG(dependencies)

        # Check for cycles
        cycle = self.state.dag.detect_cycle()
        if cycle is not None:
            raise CircularDependencyError(cycle)

        # Initialize task states
        for task_id in self.state.dag.get_all_tasks():
            self.state.tasks[task_id] = TaskState(task_id=task_id)

        logger.info(
            "Parsed %d tasks with dependencies",
            len(self.state.tasks),
        )

    def preflight(self) -> bool:
        """Run preflight checks. Returns True if parallel mode can proceed."""
        result = check_parallel_preflight(
            self.repo_root,
            num_tasks=len(self.state.tasks),
        )

        if not result.can_proceed:
            for error in result.blocking_errors:
                logger.warning("Preflight failed: %s", error)
            return False

        return True

    def create_worktrees(self) -> None:
        """Create worktrees for all tasks."""
        for task_id in self.state.tasks:
            try:
                path = self.worktree_manager.create_worktree(
                    task_id=task_id,
                    base_branch=self.base_branch,
                )
                self.state.tasks[task_id].worktree_path = path
            except WorktreeError as e:
                logger.error("Failed to create worktree for %s: %s", task_id, e)
                raise

    def cleanup_worktrees(self) -> None:
        """Clean up all worktrees."""
        if self.pi_config.worktree_cleanup:
            self.worktree_manager.cleanup_all_worktrees()

    async def run_task(
        self,
        task_id: str,
        agent_runner: Callable[[str, Path, str], PhaseResult],
    ) -> None:
        """Run a single task in its worktree.

        Args:
            task_id: The task ID to run.
            agent_runner: Function that runs the agent and returns PhaseResult.
                         Signature: (task_id, worktree_path, task_description) -> PhaseResult
        """
        task = self.state.tasks[task_id]
        if task.worktree_path is None:
            self.state.mark_task_failed(task_id, "No worktree created")
            return

        self.state.mark_task_started(task_id)
        if self.on_task_start:
            self.on_task_start(task_id)

        try:
            # Run the agent (this would be async in production)
            result = await asyncio.to_thread(
                agent_runner,
                task_id,
                task.worktree_path,
                task.description,
            )

            if result.success:
                self.state.mark_task_completed(task_id, result)
                if self.on_task_complete:
                    self.on_task_complete(task_id, result)
            else:
                self.state.mark_task_failed(task_id, result.error or "Unknown error")
                if self.on_task_error:
                    self.on_task_error(task_id, result.error or "Unknown error")

        except Exception as e:
            error_msg = str(e)
            self.state.mark_task_failed(task_id, error_msg)
            if self.on_task_error:
                self.on_task_error(task_id, error_msg)
            logger.exception("Task %s failed with exception", task_id)

    async def run_parallel_batch(
        self,
        task_ids: list[str],
        agent_runner: Callable[[str, Path, str], PhaseResult],
    ) -> None:
        """Run a batch of tasks in parallel.

        Args:
            task_ids: List of task IDs to run concurrently.
            agent_runner: Function that runs the agent.
        """
        # Limit parallelism
        max_parallel = self.pi_config.max_parallel_agents
        semaphore = asyncio.Semaphore(max_parallel)

        async def run_with_semaphore(task_id: str) -> None:
            async with semaphore:
                await self.run_task(task_id, agent_runner)

        await asyncio.gather(
            *[run_with_semaphore(tid) for tid in task_ids],
            return_exceptions=True,
        )

    async def run_all(
        self,
        agent_runner: Callable[[str, Path, str], PhaseResult],
    ) -> ParallelRunState:
        """Run all tasks respecting dependencies.

        Args:
            agent_runner: Function that runs the agent for each task.

        Returns:
            Final ParallelRunState with results.
        """
        self.state.wall_start_time = time.monotonic()

        while not self.state.all_done():
            ready = self.state.get_ready_tasks()
            if not ready:
                # No tasks ready but not all done - blocked
                blocked_tasks = [
                    tid for tid, task in self.state.tasks.items()
                    if task.status == TaskStatus.PENDING
                ]
                logger.error(
                    "No tasks ready to run. Blocked tasks: %s",
                    blocked_tasks,
                )
                for tid in blocked_tasks:
                    self.state.mark_task_failed(tid, "Blocked by failed dependencies")
                break

            logger.info("Running batch of %d tasks: %s", len(ready), ready)
            await self.run_parallel_batch(ready, agent_runner)

        self.state.wall_end_time = time.monotonic()
        return self.state

    def merge_worktrees(self) -> list[str]:
        """Merge all task branches back into base branch.

        Returns:
            List of files with merge conflicts.
        """
        conflicts: list[str] = []

        for task_id, task in self.state.tasks.items():
            if task.status != TaskStatus.COMPLETED:
                continue

            branch_name = f"task-{task_id}"
            try:
                # Merge task branch into base
                result = subprocess.run(
                    ["git", "merge", "--no-ff", branch_name, "-m", f"Merge task {task_id}"],
                    cwd=self.repo_root,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    # Check for conflicts
                    if "CONFLICT" in result.stdout or "CONFLICT" in result.stderr:
                        # Parse conflict files
                        for line in (result.stdout + result.stderr).splitlines():
                            if "CONFLICT" in line and "Merge conflict in" in line:
                                file_path = line.split("Merge conflict in")[-1].strip()
                                conflicts.append(file_path)
                    else:
                        logger.error(
                            "Merge failed for task %s: %s",
                            task_id,
                            result.stderr,
                        )
            except subprocess.SubprocessError as e:
                logger.error("Merge subprocess error for task %s: %s", task_id, e)

        return conflicts

    def get_summary(self) -> dict:
        """Get summary of parallel run results."""
        return {
            "total_tasks": len(self.state.tasks),
            "completed": len(self.state.completed),
            "failed": len(self.state.failed),
            "wall_time_ms": self.state.wall_time_ms,
            "agent_time_ms": self.state.agent_time_ms,
            "parallelism_ratio": self.state.parallelism_ratio,
        }


def should_use_parallel(
    config: ColonyConfig,
    task_count: int,
) -> bool:
    """Determine if parallel mode should be used.

    Args:
        config: ColonyOS configuration.
        task_count: Number of tasks to implement.

    Returns:
        True if parallel mode should be used.
    """
    if not config.parallel_implement.enabled:
        return False

    # Only use parallel for 2+ tasks
    if task_count < 2:
        return False

    return True
