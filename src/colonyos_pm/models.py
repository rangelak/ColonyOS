from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ExpertPersona(str, Enum):
    SENIOR_DESIGNER = "super senior designer (Apple/Airbnb caliber)"
    SENIOR_ENGINEER = "super senior engineer (Google-level systems judgment)"
    STARTUP_CEO = "CEO of an insanely fast-growing startup"
    YC_PARTNER = "YC partner"


class RiskTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ClarifyingQuestion:
    id: str
    text: str
    category: str


@dataclass(frozen=True)
class AutonomousAnswer:
    question_id: str
    question: str
    answer: str
    answered_by: ExpertPersona
    reasoning: str


@dataclass(frozen=True)
class RiskAssessment:
    tier: RiskTier
    score: int
    escalate_to_human: bool
    rationale: list[str]


@dataclass(frozen=True)
class HandoffPayload:
    target_flow: str
    source_artifact: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class HumanInterventionRecord:
    work_id: str
    tier: RiskTier
    decision: str
    guidance: str
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True)
class WorkflowArtifacts:
    work_id: str
    prompt: str
    clarifying_questions: list[ClarifyingQuestion]
    autonomous_answers: list[AutonomousAnswer]
    risk_assessment: RiskAssessment
    prd_markdown: str
    handoff_payload: HandoffPayload
    internal_trace: dict[str, object]
