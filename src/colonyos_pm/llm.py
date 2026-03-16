from __future__ import annotations

import json

from colonyos_pm.client import get_client, get_default_model


def chat(
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    client = get_client()
    response = client.chat.completions.create(
        model=model or get_default_model(),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_completion_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


def chat_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 4096,
) -> dict | list:
    """Call the model and parse the response as JSON."""
    client = get_client()
    response = client.chat.completions.create(
        model=model or get_default_model(),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_completion_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    return json.loads(raw)
