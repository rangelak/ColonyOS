from __future__ import annotations

from colonyos_pm.llm import chat_json
from colonyos_pm.models import RiskAssessment, RiskTier
from colonyos_pm.prompts import RISK_CLASSIFICATION_SYSTEM


def assess_risk(prompt: str) -> RiskAssessment:
    data = chat_json(
        system=RISK_CLASSIFICATION_SYSTEM,
        user=f"Feature request:\n\n{prompt}",
        temperature=0.3,
    )

    if not isinstance(data, dict):
        return RiskAssessment(
            tier=RiskTier.MEDIUM,
            score=5,
            escalate_to_human=True,
            rationale=["Failed to parse risk assessment; defaulting to medium."],
        )

    tier_str = data.get("tier", "medium").lower()
    try:
        tier = RiskTier(tier_str)
    except ValueError:
        tier = RiskTier.MEDIUM

    score = int(data.get("score", 5))
    escalate = bool(data.get("escalate_to_human", tier in {RiskTier.HIGH, RiskTier.CRITICAL}))
    rationale = data.get("rationale", [])
    if not isinstance(rationale, list):
        rationale = [str(rationale)]

    return RiskAssessment(
        tier=tier,
        score=score,
        escalate_to_human=escalate,
        rationale=rationale,
    )
