from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Phase(str, Enum):
    CEO = "ceo"
    PLAN = "plan"
    IMPLEMENT = "implement"
    REVIEW = "review"
    DECISION = "decision"
    FIX = "fix"
    DELIVER = "deliver"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


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
    error: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)


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

    def mark_finished(self) -> None:
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.total_cost_usd = sum(
            p.cost_usd for p in self.phases if p.cost_usd is not None
        )
