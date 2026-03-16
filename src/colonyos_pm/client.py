from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urlparse

from openai import AzureOpenAI, OpenAI

DEFAULT_MODEL = "gpt-4o"
DEFAULT_AZURE_RESPONSES_API_VERSION = "2025-03-01-preview"


def get_default_model() -> str:
    return (
        os.environ.get("COLONYOS_MODEL")
        or os.environ.get("AZURE_OPENAI_MODEL")
        or DEFAULT_MODEL
    )


def _normalize_azure_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme and parsed.netloc:
        scheme = parsed.scheme
        host = parsed.netloc
    else:
        scheme = "https"
        host = endpoint.rstrip("/")

    return f"{scheme}://{host}"


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

    azure_endpoint = _normalize_azure_endpoint(endpoint)
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", DEFAULT_AZURE_RESPONSES_API_VERSION)
    return api_key, azure_endpoint, api_version


@lru_cache(maxsize=1)
def get_client() -> OpenAI | AzureOpenAI:
    azure_config = _get_azure_config()
    if azure_config:
        api_key, azure_endpoint, api_version = azure_config
        return AzureOpenAI(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
        )

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
