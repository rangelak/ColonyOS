"""Shared fixtures for PM workflow tests.

All tests mock the OpenAI client so they run fast with no API key.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from colonyos_pm.client import reset_client_cache


@dataclass
class _FakeResponse:
    output_text: str


def _make_fake_response(content: str) -> _FakeResponse:
    return _FakeResponse(output_text=content)


FAKE_QUESTIONS_JSON = json.dumps({
    "questions": [
        {"id": "q1", "category": "goal", "text": "What is the primary business outcome?"},
        {"id": "q2", "category": "users", "text": "Who are the target users?"},
        {"id": "q3", "category": "scope", "text": "What is out of scope for v1?"},
        {"id": "q4", "category": "risk", "text": "What are the main risks?"},
        {"id": "q5", "category": "handoff", "text": "What happens after PRD generation?"},
        {"id": "q6", "category": "design", "text": "Any design constraints?"},
        {"id": "q7", "category": "technical", "text": "Any key technical constraints?"},
        {"id": "q8", "category": "quality", "text": "What quality bar must the output meet?"},
    ]
})

FAKE_ANSWER_JSON = json.dumps({
    "answer": "Ship the highest-impact path with minimal scope.",
    "reasoning": "Velocity matters more than perfection in v1.",
})

FAKE_RISK_JSON = json.dumps({
    "tier": "low",
    "score": 2,
    "escalate_to_human": False,
    "rationale": ["No sensitive systems touched.", "Scope is narrow and well-defined."],
})

FAKE_RISK_HIGH_JSON = json.dumps({
    "tier": "high",
    "score": 7,
    "escalate_to_human": True,
    "rationale": ["Touches auth and billing.", "Production migration involved."],
})

FAKE_PRD_MARKDOWN = """\
# PRD: Autonomous PM Workflow

## Clarifying Questions And Autonomous Answers

### 1. What is the primary business outcome?
**Answer:** Ship the highest-impact path with minimal scope.
**Answered by:** CEO of an insanely fast-growing startup
**Reasoning:** Velocity matters more than perfection in v1.

## Introduction/Overview

This feature creates an autonomous PM workflow.

## Goals

- Generate high-quality PRDs from rough prompts.
- Reduce ambiguity before coding begins.

## User Stories

- As a founder, I want to submit rough ideas and get PRDs back.

## Functional Requirements

1. The system must accept an initial feature prompt.
2. The system must generate clarifying questions and autonomous answers.
3. Downstream implementation tasks must follow a tests-first approach.

## Non-Goals (Out of Scope)

- Coding-agent implementation.

## Design Considerations

- Keep outputs readable for junior developers.

## Technical Considerations

- Enforce tests-first sequencing in downstream task generation.

## Success Metrics

- Faster spec-to-code cycle time.

## Open Questions

- What risk taxonomy thresholds should be used in production?
"""


def _route_fake_response(*args, **kwargs) -> _FakeResponse:
    """Route to different fake responses based on the system prompt content."""
    system_content = kwargs.get("instructions", "")
    user_content = kwargs.get("input", "")

    if "clarifying questions" in system_content.lower() and "json" in system_content.lower():
        return _make_fake_response(FAKE_QUESTIONS_JSON)
    elif "risk classification" in system_content.lower():
        if any(kw in user_content.lower() for kw in ["billing", "auth", "migration", "secret"]):
            return _make_fake_response(FAKE_RISK_HIGH_JSON)
        return _make_fake_response(FAKE_RISK_JSON)
    elif "answering a clarifying question" in system_content.lower():
        return _make_fake_response(FAKE_ANSWER_JSON)
    elif "product requirements document" in system_content.lower():
        return _make_fake_response(FAKE_PRD_MARKDOWN)
    else:
        return _make_fake_response(FAKE_ANSWER_JSON)


@pytest.fixture(autouse=True)
def mock_openai(monkeypatch):
    """Patch OpenAI client globally so no real API calls are made."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-fake")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_VERSION", raising=False)
    reset_client_cache()

    mock_client = MagicMock()
    mock_client.responses.create.side_effect = _route_fake_response

    with patch("colonyos_pm.client.OpenAI", return_value=mock_client):
        yield mock_client
    reset_client_cache()
