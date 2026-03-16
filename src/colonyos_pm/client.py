from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urlparse

from openai import OpenAI

DEFAULT_MODEL = "gpt-4o"
DEFAULT_AZURE_RESPONSES_API_VERSION = "2025-03-01-preview"


def get_default_model() -> str:
    return (
        os.environ.get("COLONYOS_MODEL")
        or os.environ.get("AZURE_OPENAI_MODEL")
        or DEFAULT_MODEL
    )


def _normalize_azure_base_url(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme and parsed.netloc:
        scheme = parsed.scheme
        host = parsed.netloc
    else:
        scheme = "https"
        host = endpoint.rstrip("/")

    if host.endswith(".cognitiveservices.azure.com"):
        host = host.removesuffix(".cognitiveservices.azure.com") + ".openai.azure.com"

    return f"{scheme}://{host}/openai/v1/"


def _get_azure_config() -> tuple[str, str, str | None] | None:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")

    if not api_key and not endpoint:
        return None

    missing = []
    if not api_key:
        missing.append("AZURE_OPENAI_API_KEY")
    if not endpoint:
        missing.append("AZURE_OPENAI_ENDPOINT")

    if missing:
        raise RuntimeError(
            "Azure OpenAI is partially configured. Missing: "
            + ", ".join(missing)
            + ". Export them or add them to .env"
        )

    base_url = _normalize_azure_base_url(endpoint)
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", DEFAULT_AZURE_RESPONSES_API_VERSION)
    return api_key, base_url, api_version


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    azure_config = _get_azure_config()
    if azure_config:
        api_key, base_url, api_version = azure_config
        client_kwargs: dict[str, object] = {
            "api_key": api_key,
            "base_url": base_url,
        }
        if api_version:
            client_kwargs["default_query"] = {"api-version": api_version}
        return OpenAI(**client_kwargs)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No LLM credentials found. Set Azure OpenAI vars "
            "(AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT) "
            "or OPENAI_API_KEY in .env."
        )
    return OpenAI(api_key=api_key)


def reset_client_cache() -> None:
    get_client.cache_clear()
