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
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from colonyos.config import ColonyConfig, ParallelImplementConfig
from colonyos.dag import TaskDAG, parse_task_file, CircularDependencyError
from colonyos.models import Phase, PhaseResult, TaskStatus
from colonyos.parallel_preflight import check_parallel_preflight
from colonyos.worktree import WorktreeManager, WorktreeError

logger = logging.getLogger(__name__)


class MergeLockTimeout(Exception):
    """Raised when merge lock acquisition times out."""
    pass


class ConflictResolutionFailed(Exception):
    """Raised when automatic conflict resolution fails."""
    pass


class ManualInterventionRequired(Exception):
    """Raised when conflict_strategy is 'manual' and conflicts are detected."""

    def __init__(self, conflict_files: list[str], task_id: str) -> None:
        self.conflict_files = conflict_files
        self.task_id = task_id
        super().__init__(
            f"Manual intervention required: merge conflicts in task {task_id}. "
            f"Conflicting files: {', '.join(conflict_files)}"
        )


class AgentRunnerProtocol(Protocol):
    """Protocol for agent runner callbacks with budget support."""

    def __call__(
        self,
        task_id: str,
        worktree_path: Path,
        task_description: str,
        budget_usd: float,
    ) -> PhaseResult:
        """Run an agent for a task.

        Args:
            task_id: The task ID to run.
            worktree_path: Path to the isolated worktree.
            task_description: Description of the task.
            budget_usd: Budget allocated for this agent.

        Returns:
            PhaseResult with task completion status.
        """
        ...


class ConflictResolverProtocol(Protocol):
    """Protocol for conflict resolution agent callbacks."""

    def __call__(
        self,
        conflict_files: list[str],
        task_id: str,
        working_dir: Path,
        prd_path: str,
        task_file_path: str,
        budget_usd: float,
    ) -> PhaseResult:
        """Run a conflict resolution agent.

        Args:
            conflict_files: List of files with merge conflicts.
            task_id: The task that caused the conflict.
            working_dir: Working directory (repo root).
            prd_path: Path to the PRD file.
            task_file_path: Path to the task file.
            budget_usd: Budget allocated for conflict resolution.

        Returns:
            PhaseResult with resolution status.
        """
        ...


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
    budget_usd: float = 0.0  # Budget allocated for this task
    actual_cost_usd: float = 0.0  # Actual cost incurred

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
        prd_path: str = "",
        task_file_path: str = "",
        phase_budget_usd: float = 5.0,
        on_task_start: Callable[[str], None] | None = None,
        on_task_complete: Callable[[str, PhaseResult], None] | None = None,
        on_task_error: Callable[[str, str], None] | None = None,
        conflict_resolver: ConflictResolverProtocol | None = None,
    ) -> None:
        """Initialize the parallel orchestrator.

        Args:
            repo_root: Path to repository root.
            config: ColonyOS configuration.
            task_file_content: Content of the task file (markdown).
            base_branch: Branch to base worktrees on.
            prd_path: Path to the PRD file (for conflict resolution context).
            task_file_path: Path to the task file (for conflict resolution context).
            phase_budget_usd: Total budget for the implement phase (FR-7).
            on_task_start: Callback when a task starts.
            on_task_complete: Callback when a task completes.
            on_task_error: Callback when a task fails.
            conflict_resolver: Callback for spawning conflict resolution agent.
        """
        self.repo_root = repo_root
        self.config = config
        self.pi_config = config.parallel_implement
        self.task_file_content = task_file_content
        self.base_branch = base_branch
        self.prd_path = prd_path
        self.task_file_path = task_file_path
        self.phase_budget_usd = phase_budget_usd
        self.on_task_start = on_task_start
        self.on_task_complete = on_task_complete
        self.on_task_error = on_task_error
        self.conflict_resolver = conflict_resolver

        self.worktree_manager = WorktreeManager(repo_root)
        self.state = ParallelRunState()

        # Asyncio lock for serializing merge operations (FR-5)
        self._merge_lock = asyncio.Lock()
        self._merge_timeout_seconds = self.pi_config.merge_timeout_seconds

        # Conflict resolution budget (separate from per-task budget)
        self._conflict_resolution_budget_usd = phase_budget_usd * 0.1  # 10% of phase budget

    def parse_tasks(self) -> None:
        """Parse task file and build DAG.

        Also allocates per-task budgets based on FR-7:
        Each agent receives budget = phase_budget / max_parallel_agents
        """
        dependencies = parse_task_file(self.task_file_content)
        if not dependencies:
            raise ValueError("No tasks found in task file")

        self.state.dag = TaskDAG(dependencies)

        # Check for cycles
        cycle = self.state.dag.detect_cycle()
        if cycle is not None:
            raise CircularDependencyError(cycle)

        # Calculate per-task budget (FR-7)
        # Budget per agent = phase_budget / max_parallel_agents
        max_agents = self.pi_config.max_parallel_agents
        per_task_budget = self.phase_budget_usd / max_agents

        # Initialize task states with budget allocation
        for task_id in self.state.dag.get_all_tasks():
            self.state.tasks[task_id] = TaskState(
                task_id=task_id,
                budget_usd=per_task_budget,
            )

        logger.info(
            "Parsed %d tasks with dependencies. Per-task budget: $%.2f",
            len(self.state.tasks),
            per_task_budget,
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
        agent_runner: Callable[[str, Path, str, float], PhaseResult],
    ) -> None:
        """Run a single task in its worktree.

        Args:
            task_id: The task ID to run.
            agent_runner: Function that runs the agent and returns PhaseResult.
                         Signature: (task_id, worktree_path, task_description, budget_usd) -> PhaseResult
        """
        task = self.state.tasks[task_id]
        if task.worktree_path is None:
            self.state.mark_task_failed(task_id, "No worktree created")
            return

        self.state.mark_task_started(task_id)
        if self.on_task_start:
            self.on_task_start(task_id)

        try:
            # Run the agent with allocated budget (FR-7)
            result = await asyncio.to_thread(
                agent_runner,
                task_id,
                task.worktree_path,
                task.description,
                task.budget_usd,  # Pass per-task budget
            )

            # Track actual cost for reporting
            if result.cost_usd is not None:
                task.actual_cost_usd = result.cost_usd

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
        agent_runner: Callable[[str, Path, str, float], PhaseResult],
    ) -> None:
        """Run a batch of tasks in parallel.

        Args:
            task_ids: List of task IDs to run concurrently.
            agent_runner: Function that runs the agent with signature
                         (task_id, worktree_path, task_description, budget_usd) -> PhaseResult
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
        agent_runner: Callable[[str, Path, str, float], PhaseResult],
    ) -> ParallelRunState:
        """Run all tasks respecting dependencies.

        Args:
            agent_runner: Function that runs the agent for each task with signature
                         (task_id, worktree_path, task_description, budget_usd) -> PhaseResult

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
                    self.state.tasks[tid].status = TaskStatus.BLOCKED
                    self.state.mark_task_failed(tid, "Blocked by failed dependencies")
                break

            logger.info("Running batch of %d tasks: %s", len(ready), ready)
            await self.run_parallel_batch(ready, agent_runner)

        self.state.wall_end_time = time.monotonic()
        return self.state

    async def merge_worktrees(self) -> list[str]:
        """Merge all task branches back into base branch.

        Uses an asyncio lock with configurable timeout (FR-5) to prevent
        race conditions during concurrent merges. Lock acquisition is logged
        with timestamps for audit trails.

        Returns:
            List of files with merge conflicts (empty if all merges succeeded).

        Raises:
            MergeLockTimeout: If lock acquisition times out.
            ManualInterventionRequired: If conflict_strategy is 'manual' and conflicts occur.
            ConflictResolutionFailed: If conflict resolution fails.
        """
        all_conflicts: list[str] = []

        for task_id, task in self.state.tasks.items():
            if task.status != TaskStatus.COMPLETED:
                continue

            conflicts = await self._merge_single_task(task_id)
            all_conflicts.extend(conflicts)

        return all_conflicts

    async def _merge_single_task(self, task_id: str) -> list[str]:
        """Merge a single task branch with lock protection.

        Args:
            task_id: The task ID to merge.

        Returns:
            List of conflict files (empty if merge succeeded).

        Raises:
            MergeLockTimeout: If lock acquisition times out.
            ManualInterventionRequired: If conflict_strategy is 'manual' and conflicts occur.
            ConflictResolutionFailed: If conflict resolution fails.
        """
        branch_name = f"task-{task_id}"

        # Acquire merge lock with timeout (FR-5)
        lock_request_time = datetime.now(timezone.utc)
        logger.info(
            "Task %s: Requesting merge lock at %s",
            task_id,
            lock_request_time.isoformat(),
        )

        try:
            await asyncio.wait_for(
                self._merge_lock.acquire(),
                timeout=self._merge_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Task %s: Merge lock acquisition timed out after %d seconds",
                task_id,
                self._merge_timeout_seconds,
            )
            raise MergeLockTimeout(
                f"Failed to acquire merge lock for task {task_id} "
                f"after {self._merge_timeout_seconds} seconds"
            )

        lock_acquired_time = datetime.now(timezone.utc)
        logger.info(
            "Task %s: Merge lock acquired at %s (waited %.2f seconds)",
            task_id,
            lock_acquired_time.isoformat(),
            (lock_acquired_time - lock_request_time).total_seconds(),
        )

        try:
            return await self._perform_merge(task_id, branch_name)
        finally:
            self._merge_lock.release()
            logger.info(
                "Task %s: Merge lock released at %s",
                task_id,
                datetime.now(timezone.utc).isoformat(),
            )

    async def _perform_merge(self, task_id: str, branch_name: str) -> list[str]:
        """Perform the actual git merge operation.

        Args:
            task_id: The task ID being merged.
            branch_name: The branch name to merge.

        Returns:
            List of conflict files (empty if merge succeeded).

        Raises:
            ManualInterventionRequired: If conflict_strategy is 'manual' and conflicts occur.
            ConflictResolutionFailed: If conflict resolution fails.
        """
        conflicts: list[str] = []

        try:
            # Run merge in thread pool to avoid blocking
            result = await asyncio.to_thread(
                subprocess.run,
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

                    logger.warning(
                        "Task %s: Merge conflicts detected in %d files: %s",
                        task_id,
                        len(conflicts),
                        conflicts,
                    )

                    # Handle conflicts based on conflict_strategy
                    await self._handle_conflicts(task_id, conflicts)
                else:
                    logger.error(
                        "Merge failed for task %s: %s",
                        task_id,
                        result.stderr,
                    )
            else:
                logger.info("Task %s: Merge completed successfully", task_id)

        except subprocess.SubprocessError as e:
            logger.error("Merge subprocess error for task %s: %s", task_id, e)

        return conflicts

    async def _handle_conflicts(
        self,
        task_id: str,
        conflict_files: list[str],
    ) -> None:
        """Handle merge conflicts based on conflict_strategy configuration.

        Args:
            task_id: The task that caused the conflict.
            conflict_files: List of files with conflicts.

        Raises:
            ManualInterventionRequired: If conflict_strategy is 'manual'.
            ConflictResolutionFailed: If resolution fails with 'auto' strategy.
            RuntimeError: If conflict_strategy is 'fail'.
        """
        strategy = self.pi_config.conflict_strategy

        if strategy == "fail":
            # Abort the merge and fail immediately
            await asyncio.to_thread(
                subprocess.run,
                ["git", "merge", "--abort"],
                cwd=self.repo_root,
                capture_output=True,
            )
            raise RuntimeError(
                f"Merge conflicts in task {task_id}: {conflict_files}. "
                f"conflict_strategy='fail' - aborting."
            )

        elif strategy == "manual":
            # Leave conflicts in place and raise for user intervention
            raise ManualInterventionRequired(conflict_files, task_id)

        elif strategy == "auto":
            # Spawn conflict resolution agent (FR-6)
            await self._spawn_conflict_resolver(task_id, conflict_files)

        else:
            logger.warning(
                "Unknown conflict_strategy '%s', defaulting to 'fail'",
                strategy,
            )
            await asyncio.to_thread(
                subprocess.run,
                ["git", "merge", "--abort"],
                cwd=self.repo_root,
                capture_output=True,
            )
            raise RuntimeError(
                f"Merge conflicts in task {task_id}: {conflict_files}"
            )

    async def _spawn_conflict_resolver(
        self,
        task_id: str,
        conflict_files: list[str],
    ) -> None:
        """Spawn a conflict resolution agent (FR-6).

        Args:
            task_id: The task that caused the conflict.
            conflict_files: List of files with conflicts.

        Raises:
            ConflictResolutionFailed: If resolution fails.
        """
        if self.conflict_resolver is None:
            logger.error(
                "Task %s: No conflict resolver configured, aborting merge",
                task_id,
            )
            await asyncio.to_thread(
                subprocess.run,
                ["git", "merge", "--abort"],
                cwd=self.repo_root,
                capture_output=True,
            )
            raise ConflictResolutionFailed(
                f"No conflict resolver available for task {task_id}"
            )

        logger.info(
            "Task %s: Spawning conflict resolution agent for files: %s",
            task_id,
            conflict_files,
        )

        try:
            # Run conflict resolver in thread pool
            result = await asyncio.to_thread(
                self.conflict_resolver,
                conflict_files,
                task_id,
                self.repo_root,
                self.prd_path,
                self.task_file_path,
                self._conflict_resolution_budget_usd,
            )

            if not result.success:
                logger.error(
                    "Task %s: Conflict resolution failed: %s",
                    task_id,
                    result.error,
                )
                # Abort merge on failure
                await asyncio.to_thread(
                    subprocess.run,
                    ["git", "merge", "--abort"],
                    cwd=self.repo_root,
                    capture_output=True,
                )
                raise ConflictResolutionFailed(
                    f"Conflict resolution failed for task {task_id}: {result.error}"
                )

            logger.info("Task %s: Conflict resolution completed successfully", task_id)

        except Exception as e:
            if isinstance(e, ConflictResolutionFailed):
                raise
            logger.exception("Task %s: Conflict resolver raised exception", task_id)
            await asyncio.to_thread(
                subprocess.run,
                ["git", "merge", "--abort"],
                cwd=self.repo_root,
                capture_output=True,
            )
            raise ConflictResolutionFailed(
                f"Conflict resolution exception for task {task_id}: {e}"
            )

    def get_summary(self) -> dict:
        """Get summary of parallel run results."""
        # Calculate total actual cost from all tasks
        total_actual_cost = sum(
            task.actual_cost_usd
            for task in self.state.tasks.values()
        )

        # Get per-task cost breakdown for artifacts (FR-7, FR-10)
        task_costs = {
            task_id: {
                "budget_usd": task.budget_usd,
                "actual_cost_usd": task.actual_cost_usd,
                "status": task.status.value,
            }
            for task_id, task in self.state.tasks.items()
        }

        return {
            "total_tasks": len(self.state.tasks),
            "completed": len(self.state.completed),
            "failed": len(self.state.failed),
            "blocked": sum(
                1 for t in self.state.tasks.values()
                if t.status == TaskStatus.BLOCKED
            ),
            "wall_time_ms": self.state.wall_time_ms,
            "agent_time_ms": self.state.agent_time_ms,
            "parallelism_ratio": self.state.parallelism_ratio,
            "phase_budget_usd": self.phase_budget_usd,
            "total_actual_cost_usd": total_actual_cost,
            "per_task_budget_usd": self.phase_budget_usd / self.pi_config.max_parallel_agents,
            "task_costs": task_costs,
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
