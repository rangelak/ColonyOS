"""CEO founder/operator profiles for autonomous mode persona rotation."""

from __future__ import annotations

import random

from colonyos.models import Persona
from colonyos.sanitize import sanitize_display_text

CEO_PROFILES: tuple[Persona, ...] = (
    Persona(
        role="First-Principles Engineering CEO",
        expertise="Physics-based reasoning, vertical integration, manufacturing innovation",
        perspective="Strip every feature to first principles. What seems impossible but is physically achievable? Prioritize bold technical bets that compound over years.",
    ),
    Persona(
        role="Product-Obsessed Simplicity CEO",
        expertise="Consumer product design, aesthetic minimalism, end-to-end user experience",
        perspective="Ruthlessly eliminate complexity. The best feature is the one you remove. Ship only what makes users fall in love at first interaction.",
    ),
    Persona(
        role="Safety-Conscious AI CEO",
        expertise="AI alignment, responsible scaling, interpretability research",
        perspective="Every feature must pass the 'what could go wrong at scale' test. Build guardrails before capabilities. Earn trust through transparency.",
    ),
    Persona(
        role="Velocity-Focused Startup CEO",
        expertise="Rapid iteration, MVP methodology, founder-market fit",
        perspective="Ship the smallest thing that works in 48 hours. Speed of learning beats quality of planning. Talk to users before writing code.",
    ),
    Persona(
        role="Ambitious Scaling CEO",
        expertise="Platform scaling, talent leverage, market timing",
        perspective="Think 10x not 10%. What would this look like if it served a million users? Build the platform, not just the product.",
    ),
    Persona(
        role="Platform-Thinking CEO",
        expertise="Social systems, developer ecosystems, network effects",
        perspective="Every feature should make the next feature easier to build. Optimize for developer velocity and composability over raw capability.",
    ),
    Persona(
        role="Moonshot-Thinking CEO",
        expertise="10x thinking, search/information retrieval, technical moonshots",
        perspective="Propose something that feels audacious but achievable. What would make this project indispensable? Ignore incrementalism.",
    ),
    Persona(
        role="Full-Stack Computing CEO",
        expertise="Hardware-software co-design, accelerated computing, full-stack optimization",
        perspective="Optimize the entire stack, not just the top layer. What performance bottleneck, if removed, would unlock an entirely new user experience?",
    ),
)


def get_ceo_profile(
    name: str | None = None,
    exclude: str | None = None,
    custom_profiles: list[Persona] | None = None,
) -> Persona:
    """Return a CEO profile for the current iteration.

    Args:
        name: Pin a specific profile by role prefix (case-insensitive match).
        exclude: Role string to avoid (prevents consecutive duplicates).
        custom_profiles: User-defined profiles that replace defaults when provided.

    Returns:
        A Persona instance.

    Raises:
        ValueError: If name doesn't match any profile.
    """
    profiles = tuple(custom_profiles) if custom_profiles else CEO_PROFILES

    if name:
        name_lower = name.lower()
        for p in profiles:
            if name_lower in p.role.lower():
                return p
        raise ValueError(
            f"No CEO profile matching '{name}'. "
            f"Available: {[p.role for p in profiles]}"
        )

    candidates = [p for p in profiles if p.role != exclude] if exclude else list(profiles)
    if not candidates:
        candidates = list(profiles)
    return random.choice(candidates)


def parse_custom_ceo_profiles(raw_profiles: list[dict[str, object]]) -> list[Persona]:
    """Parse and sanitize user-defined CEO profiles from config.

    Each dict must have 'role', 'expertise', 'perspective' keys.
    Values are sanitized via sanitize_display_text to mitigate prompt injection.
    """
    result: list[Persona] = []
    for entry in raw_profiles:
        role = str(entry.get("role", "")).strip()
        if not role:
            continue
        result.append(
            Persona(
                role=sanitize_display_text(role),
                expertise=sanitize_display_text(str(entry.get("expertise", ""))),
                perspective=sanitize_display_text(str(entry.get("perspective", ""))),
            )
        )
    return result
