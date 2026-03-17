"""Prebuilt persona packs for common project archetypes.

Each pack contains 3-5 curated Persona instances designed for a specific
type of project. Users can select a pack during `colonyos init` instead
of defining personas from scratch.
"""

from __future__ import annotations

from colonyos.models import Persona, PersonaPack

PACKS: tuple[PersonaPack, ...] = (
    PersonaPack(
        key="startup",
        name="Startup Team",
        description="Product-market fit, velocity, and pragmatic engineering",
        personas=(
            Persona(
                role="YC Partner",
                expertise="Product-market fit, growth strategy, lean validation",
                perspective="Does this solve a real problem? Will users pay for it? What's the fastest path to learning?",
            ),
            Persona(
                role="Full-Stack Tech Lead",
                expertise="Rapid prototyping, system architecture, technical debt management",
                perspective="Can we ship this in a week? What shortcuts are acceptable now vs. dangerous later?",
            ),
            Persona(
                role="Product Designer",
                expertise="User experience, interaction design, user research",
                perspective="Is this intuitive? What's the simplest flow that gets users to their goal?",
            ),
            Persona(
                role="Pragmatic Security Engineer",
                expertise="Application security, authentication, data protection",
                perspective="What's the minimum security bar we must clear before launch? Where are the real risks?",
            ),
        ),
    ),
    PersonaPack(
        key="backend",
        name="Backend / API",
        description="API design, data modeling, reliability, and performance",
        personas=(
            Persona(
                role="Senior API Designer",
                expertise="REST/GraphQL API design, versioning, developer experience",
                perspective="Is this API consistent, discoverable, and hard to misuse? Will it age well?",
            ),
            Persona(
                role="Database Architect",
                expertise="Data modeling, query optimization, schema migrations",
                perspective="Is the data model normalized correctly? Will this query scale to 10x traffic?",
            ),
            Persona(
                role="Site Reliability Engineer",
                expertise="Observability, incident response, infrastructure-as-code",
                perspective="How will we know when this breaks? What's the blast radius of a failure here?",
            ),
            Persona(
                role="Staff Security Engineer",
                expertise="AuthN/AuthZ, input validation, supply-chain security",
                perspective="What can an attacker do with this endpoint? Are we following least-privilege?",
            ),
            Persona(
                role="Performance Engineer",
                expertise="Profiling, caching strategies, load testing",
                perspective="What's the p99 latency? Where are the hot paths and how do we keep them fast?",
            ),
        ),
    ),
    PersonaPack(
        key="fullstack",
        name="Full-Stack Web",
        description="Frontend UX, backend architecture, DevOps, and accessibility",
        personas=(
            Persona(
                role="Senior Frontend Engineer",
                expertise="Component architecture, state management, responsive design",
                perspective="Is this component reusable? Does the UI degrade gracefully on slow connections?",
            ),
            Persona(
                role="Backend Architect",
                expertise="Service design, API contracts, data flow",
                perspective="Is the separation of concerns clean? Will this architecture support the next 3 features?",
            ),
            Persona(
                role="DevOps / CI-CD Specialist",
                expertise="Build pipelines, deployment automation, environment parity",
                perspective="Can we deploy this with zero downtime? Is the pipeline fast and reliable?",
            ),
            Persona(
                role="Accessibility Advocate",
                expertise="WCAG compliance, assistive technology, inclusive design",
                perspective="Can a screen reader navigate this? Does it work with keyboard-only input?",
            ),
            Persona(
                role="Product-Minded Engineer",
                expertise="User analytics, feature flagging, A/B testing",
                perspective="How will we measure success? What's the rollout plan if something goes wrong?",
            ),
        ),
    ),
    PersonaPack(
        key="opensource",
        name="Open Source Library",
        description="API surface design, documentation, compatibility, and community",
        personas=(
            Persona(
                role="API Surface Designer",
                expertise="Public API design, type signatures, ergonomics",
                perspective="Is this API obvious to a first-time user? Can we add features without breaking it?",
            ),
            Persona(
                role="Developer Experience Lead",
                expertise="Documentation, examples, error messages, onboarding",
                perspective="Can someone get started in 5 minutes? Are error messages actionable?",
            ),
            Persona(
                role="Backward Compatibility Guardian",
                expertise="Semantic versioning, deprecation strategy, migration paths",
                perspective="Does this change break existing users? How do we communicate the migration?",
            ),
            Persona(
                role="Security & Supply-Chain Auditor",
                expertise="Dependency auditing, CVE monitoring, secure defaults",
                perspective="Are we pulling in unnecessary dependencies? Are defaults secure out of the box?",
            ),
            Persona(
                role="Community & Adoption Strategist",
                expertise="Open source governance, contributor experience, ecosystem fit",
                perspective="Will contributors find this codebase welcoming? Does this fit the ecosystem norms?",
            ),
        ),
    ),
)


def get_pack(key: str) -> PersonaPack | None:
    """Return the pack with the given key, or None if not found."""
    for pack in PACKS:
        if pack.key == key:
            return pack
    return None


def pack_keys() -> list[str]:
    """Return the keys of all available packs."""
    return [pack.key for pack in PACKS]
