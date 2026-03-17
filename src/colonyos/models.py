from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Phase(str, Enum):
    CEO = "ceo"
    PLAN = "plan"
    IMPLEMENT = "implement"
    REVIEW = "review"
    DECISION = "decision"
    FIX = "fix"
    LEARN = "learn"
    DELIVER = "deliver"


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
class ResumeState:
    """Typed container for resume-from parameters passed to the orchestrator."""

    log: "RunLog"
    branch_name: str
    prd_rel: str
    task_rel: str
    last_successful_phase: str


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

    def mark_finished(self) -> None:
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.total_cost_usd = sum(
            p.cost_usd for p in self.phases if p.cost_usd is not None
        )


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
