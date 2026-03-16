from __future__ import annotations

import json
import sys
import time

from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
from colonyos_pm.client import get_client, get_default_model

RETRYABLE_ERRORS = (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)


def _response_text(response: object) -> str:
    output_text = getattr(response, "output_text", "") or ""
    if output_text:
        return output_text

    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", "")
            if text:
                chunks.append(text)
    return "".join(chunks)


def _parse_json_response(raw: str) -> dict | list:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return json.loads(cleaned or "{}")


def _ensure_not_truncated(response: object) -> None:
    incomplete = getattr(response, "incomplete_details", None)
    if incomplete and getattr(incomplete, "reason", None) == "max_output_tokens":
        raise RuntimeError(
            "Responses API output was truncated by max_output_tokens. "
            "Increase the max_tokens value for this call."
        )


def _create_response(
    system: str,
    user: str,
    *,
    model: str | None,
    max_tokens: int | None,
) -> object:
    client = get_client()
    request_kwargs = {
        "model": model or get_default_model(),
        "instructions": system,
        "input": user,
    }
    if max_tokens is not None:
        request_kwargs["max_output_tokens"] = max_tokens
    for attempt in range(3):
        try:
            return client.responses.create(**request_kwargs)
        except RETRYABLE_ERRORS as exc:
            if attempt == 2:
                raise
            print(
                f"[llm] Retrying Responses API request after {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            time.sleep(attempt + 1)
    raise RuntimeError("Unreachable Responses API retry state")


def chat(
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = 4096,
) -> str:
    response = _create_response(
        system,
        user,
        model=model,
        max_tokens=max_tokens,
    )
    _ensure_not_truncated(response)
    return _response_text(response)


def chat_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int | None = 4096,
) -> dict | list:
    """Call the model and parse the response as JSON."""
    response = _create_response(
        system,
        user,
        model=model,
        max_tokens=max_tokens,
    )
    _ensure_not_truncated(response)
    return _parse_json_response(_response_text(response))
