from __future__ import annotations

from colonyos_pm.models import RiskAssessment, RiskTier


SENSITIVE_KEYWORDS = {
    "auth",
    "billing",
    "payment",
    "secret",
    "pii",
    "compliance",
    "migration",
    "security",
    "infra",
    "production",
}


def assess_risk(prompt: str) -> RiskAssessment:
    normalized = prompt.lower()
    token_hits = [kw for kw in SENSITIVE_KEYWORDS if kw in normalized]
    ambiguity_penalty = 1 if len(prompt.split()) < 8 else 0

    score = len(token_hits) * 2 + ambiguity_penalty
    if score >= 8:
        tier = RiskTier.CRITICAL
    elif score >= 4:
        tier = RiskTier.HIGH
    elif score >= 2:
        tier = RiskTier.MEDIUM
    else:
        tier = RiskTier.LOW

    rationale = []
    if token_hits:
        rationale.append(f"Sensitive keywords detected: {', '.join(sorted(token_hits))}.")
    if ambiguity_penalty:
        rationale.append("Prompt is brief/ambiguous, increasing execution uncertainty.")
    if not rationale:
        rationale.append("No high-sensitivity signals detected in prompt.")

    return RiskAssessment(
        tier=tier,
        score=score,
        escalate_to_human=tier in {RiskTier.HIGH, RiskTier.CRITICAL},
        rationale=rationale,
    )
