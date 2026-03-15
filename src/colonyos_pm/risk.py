from __future__ import annotations

from colonyos_pm.llm import chat_json
from colonyos_pm.models import RiskAssessment, RiskTier

RISK_SYSTEM_PROMPT = """\
You are a risk classification engine for an autonomous PM workflow.

Given a feature request prompt, assess the risk of letting an autonomous system \
plan and hand off this work without human review.

Consider these dimensions:
- Does it touch auth, billing, payments, secrets, PII, compliance, or security?
- Does it involve database migrations or production infrastructure changes?
- Is the prompt vague or ambiguous enough that misinterpretation is likely?
- Does it span many systems or have high blast radius?

Return JSON with this exact schema:
{
  "tier": "low" | "medium" | "high" | "critical",
  "score": <integer 0-10>,
  "escalate_to_human": true | false,
  "rationale": ["<reason 1>", "<reason 2>", ...]
}

Guidelines:
- low (0-2): Safe for full autonomy. Docs, small features, refactors.
- medium (3-4): Autonomy OK but flag for review. Multi-system or moderate scope.
- high (5-7): Requires human review. Touches sensitive systems.
- critical (8-10): Must have human approval. Auth, billing, infra, compliance.
- escalate_to_human should be true for high and critical.
"""


def assess_risk(prompt: str) -> RiskAssessment:
    data = chat_json(
        system=RISK_SYSTEM_PROMPT,
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
