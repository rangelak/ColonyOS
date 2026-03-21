from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar

import click

logger = logging.getLogger(__name__)


class PreflightError(click.ClickException):
    """Raised when a pre-flight git state check fails.

    Subclass of ClickException so callers can catch it specifically
    without catching all ClickExceptions from other phases.
    """
    pass


class BranchRestoreError(RuntimeError):
    """Raised when git checkout fails to restore the original branch.

    This is a **fatal** error for queue execution — if the branch cannot be
    restored, subsequent queue items would silently run on the wrong branch,
    risking data corruption.  Callers (e.g. ``QueueExecutor``) should catch
    this and halt the queue rather than proceeding.
    """
    pass


class Phase(str, Enum):
    CEO = "ceo"
    PLAN = "plan"
    TRIAGE = "triage"
    IMPLEMENT = "implement"
    REVIEW = "review"
    DECISION = "decision"
    FIX = "fix"
    LEARN = "learn"
    VERIFY = "verify"
    DELIVER = "deliver"
    CI_FIX = "ci_fix"
    CONFLICT_RESOLVE = "conflict_resolve"


class TaskStatus(str, Enum):
    """Status of a task in parallel implement mode."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class LoopStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class Persona:
    role: str
    expertise: str
    perspective: str
    reviewer: bool = False


@dataclass(frozen=True)
class PersonaPack:
    """A curated set of personas for a common project archetype."""

    key: str
    name: str
    description: str
    personas: tuple[Persona, ...]


@dataclass(frozen=True)
class ProjectInfo:
    name: str
    description: str
    stack: str


@dataclass(frozen=True)
class RepoContext:
    """Deterministically gathered signals from the repository.

    Used by AI-assisted init to provide context to the LLM without
    spending tokens on file exploration.
    """

    name: str
    description: str
    stack: str
    readme_excerpt: str = ""
    manifest_type: str = ""
    raw_signals: dict[str, str] = field(default_factory=dict)


@dataclass
class PhaseResult:
    phase: Phase
    success: bool
    cost_usd: float | None = None
    duration_ms: int = 0
    session_id: str = ""
    model: str | None = None
    error: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass
class PreflightResult:
    """Result of the git state pre-flight check run before any agent phases."""

    current_branch: str
    is_clean: bool
    branch_exists: bool
    open_pr_number: int | None = None
    open_pr_url: str | None = None
    main_behind_count: int | None = None
    action_taken: str = "proceed"
    warnings: list[str] = field(default_factory=list)
    head_sha: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_branch": self.current_branch,
            "is_clean": self.is_clean,
            "branch_exists": self.branch_exists,
            "open_pr_number": self.open_pr_number,
            "open_pr_url": self.open_pr_url,
            "main_behind_count": self.main_behind_count,
            "action_taken": self.action_taken,
            "warnings": list(self.warnings),
            "head_sha": self.head_sha,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PreflightResult:
        for key in ("current_branch", "is_clean", "branch_exists"):
            if key not in data:
                raise ValueError(f"PreflightResult missing required key: {key!r}")
        return cls(
            current_branch=data["current_branch"],
            is_clean=data["is_clean"],
            branch_exists=data["branch_exists"],
            open_pr_number=data.get("open_pr_number"),
            open_pr_url=data.get("open_pr_url"),
            main_behind_count=data.get("main_behind_count"),
            action_taken=data.get("action_taken", "proceed"),
            warnings=list(data.get("warnings", [])),
            head_sha=data.get("head_sha"),
        )


@dataclass
class ResumeState:
    """Typed container for resume-from parameters passed to the orchestrator."""

    log: "RunLog"
    branch_name: str
    prd_rel: str
    task_rel: str
    last_successful_phase: str
    # Parallel task resume information (FR-8)
    failed_task_ids: list[str] = field(default_factory=list)
    blocked_task_ids: list[str] = field(default_factory=list)
    completed_task_ids: list[str] = field(default_factory=list)


@dataclass
class RunLog:
    run_id: str
    prompt: str
    status: RunStatus
    phases: list[PhaseResult] = field(default_factory=list)
    total_cost_usd: float = 0.0
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: str | None = None
    branch_name: str | None = None
    prd_rel: str | None = None
    task_rel: str | None = None
    source_issue: int | None = None
    source_issue_url: str | None = None
    preflight: PreflightResult | None = None
    pr_url: str | None = None
    post_fix_head_sha: str | None = None
    # Parallel implement metadata
    parallel_tasks: int | None = None
    wall_time_ms: int | None = None
    agent_time_ms: int | None = None

    def mark_finished(self) -> None:
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.total_cost_usd = sum(
            p.cost_usd for p in self.phases if p.cost_usd is not None
        )

    def get_task_results(self, task_id: str) -> list[PhaseResult]:
        """Return all PhaseResults for a specific task ID.

        Args:
            task_id: The task identifier to filter by.

        Returns:
            List of PhaseResults where artifacts["task_id"] matches.
        """
        return [
            p for p in self.phases
            if p.artifacts.get("task_id") == task_id
        ]

    def get_parallelism_ratio(self) -> float:
        """Return the parallelism ratio (agent_time / wall_time).

        Returns:
            The ratio, or 1.0 if wall_time is not set (sequential run).
        """
        if not self.wall_time_ms or self.wall_time_ms == 0:
            return 1.0
        if not self.agent_time_ms:
            return 1.0
        return self.agent_time_ms / self.wall_time_ms


@dataclass
class LoopState:
    """Persistent state for long-running autonomous loops."""

    loop_id: str
    total_iterations: int
    current_iteration: int = 0
    aggregate_cost_usd: float = 0.0
    start_time_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_run_ids: list[str] = field(default_factory=list)
    failed_run_ids: list[str] = field(default_factory=list)
    status: LoopStatus = LoopStatus.RUNNING

    def to_dict(self) -> dict[str, Any]:
        return {
            "loop_id": self.loop_id,
            "current_iteration": self.current_iteration,
            "total_iterations": self.total_iterations,
            "aggregate_cost_usd": self.aggregate_cost_usd,
            "start_time_iso": self.start_time_iso,
            "completed_run_ids": list(self.completed_run_ids),
            "failed_run_ids": list(self.failed_run_ids),
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoopState:
        raw_status = data.get("status", "running")
        try:
            status = LoopStatus(raw_status)
        except ValueError:
            logger.warning(
                "Unknown loop status %r in persisted state, defaulting to RUNNING",
                raw_status,
            )
            status = LoopStatus.RUNNING
        return cls(
            loop_id=data["loop_id"],
            current_iteration=data.get("current_iteration", 0),
            total_iterations=data.get("total_iterations", 0),
            aggregate_cost_usd=data.get("aggregate_cost_usd", 0.0),
            start_time_iso=data.get("start_time_iso", ""),
            completed_run_ids=list(data.get("completed_run_ids", [])),
            failed_run_ids=list(data.get("failed_run_ids", [])),
            status=status,
        )


class QueueItemStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass
class QueueItem:
    """A single item in the execution queue.

    The ``schema_version`` field tracks serialization format evolution.
    Increment when adding or removing fields so that readers can distinguish
    "field missing because it didn't exist yet" from "field missing due to
    corruption".
    """

    SCHEMA_VERSION: ClassVar[int] = 2  # class-level constant; bump on structural changes

    id: str
    source_type: str  # "prompt", "issue", "slack", or "slack_fix"
    source_value: str  # prompt text or issue number
    status: QueueItemStatus
    added_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    run_id: str | None = None
    cost_usd: float = 0.0
    duration_ms: int = 0
    pr_url: str | None = None
    error: str | None = None
    issue_title: str | None = None
    base_branch: str | None = None
    slack_ts: str | None = None
    slack_channel: str | None = None
    branch_name: str | None = None
    fix_rounds: int = 0
    parent_item_id: str | None = None
    head_sha: str | None = None
    raw_prompt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "id": self.id,
            "source_type": self.source_type,
            "source_value": self.source_value,
            "status": self.status.value,
            "added_at": self.added_at,
            "run_id": self.run_id,
            "cost_usd": self.cost_usd,
            "duration_ms": self.duration_ms,
            "pr_url": self.pr_url,
            "error": self.error,
            "issue_title": self.issue_title,
            "base_branch": self.base_branch,
            "slack_ts": self.slack_ts,
            "slack_channel": self.slack_channel,
            "branch_name": self.branch_name,
            "fix_rounds": self.fix_rounds,
            "parent_item_id": self.parent_item_id,
            "head_sha": self.head_sha,
            "raw_prompt": self.raw_prompt,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueueItem:
        stored_version = data.get("schema_version", 1)
        if stored_version < cls.SCHEMA_VERSION:
            logger.debug(
                "QueueItem schema_version %d < current %d; missing fields "
                "will use defaults",
                stored_version, cls.SCHEMA_VERSION,
            )
        raw_status = data.get("status", "pending")
        try:
            status = QueueItemStatus(raw_status)
        except ValueError:
            logger.warning(
                "Unknown queue item status %r, defaulting to PENDING",
                raw_status,
            )
            status = QueueItemStatus.PENDING
        return cls(
            id=data["id"],
            source_type=data.get("source_type", "prompt"),
            source_value=data.get("source_value", ""),
            status=status,
            added_at=data.get("added_at", ""),
            run_id=data.get("run_id"),
            cost_usd=data.get("cost_usd", 0.0),
            duration_ms=data.get("duration_ms", 0),
            pr_url=data.get("pr_url"),
            error=data.get("error"),
            issue_title=data.get("issue_title"),
            base_branch=data.get("base_branch"),
            slack_ts=data.get("slack_ts"),
            slack_channel=data.get("slack_channel"),
            branch_name=data.get("branch_name"),
            fix_rounds=data.get("fix_rounds", 0),
            parent_item_id=data.get("parent_item_id"),
            head_sha=data.get("head_sha"),
            raw_prompt=data.get("raw_prompt"),
        )


class QueueStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


@dataclass
class QueueState:
    """Persistent state for the execution queue."""

    queue_id: str
    items: list[QueueItem] = field(default_factory=list)
    aggregate_cost_usd: float = 0.0
    start_time_iso: str | None = None
    status: QueueStatus = QueueStatus.PENDING

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_id": self.queue_id,
            "items": [item.to_dict() for item in self.items],
            "aggregate_cost_usd": self.aggregate_cost_usd,
            "start_time_iso": self.start_time_iso,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueueState:
        raw_status = data.get("status", "pending")
        try:
            status = QueueStatus(raw_status)
        except ValueError:
            logger.warning(
                "Unknown queue status %r, defaulting to PENDING",
                raw_status,
            )
            status = QueueStatus.PENDING
        items = [
            QueueItem.from_dict(item_data)
            for item_data in data.get("items", [])
        ]
        return cls(
            queue_id=data["queue_id"],
            items=items,
            aggregate_cost_usd=data.get("aggregate_cost_usd", 0.0),
            start_time_iso=data.get("start_time_iso"),
            status=status,
        )
