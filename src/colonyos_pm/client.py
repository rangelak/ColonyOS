from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urlparse

from openai import AzureOpenAI, OpenAI

DEFAULT_MODEL = "gpt-4o"
DEFAULT_AZURE_API_VERSION = "2024-12-01-preview"


def get_default_model() -> str:
    return (
        os.environ.get("COLONYOS_MODEL")
        or os.environ.get("AZURE_OPENAI_MODEL")
        or DEFAULT_MODEL
    )


def _normalize_azure_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return endpoint.rstrip("/")


def _get_azure_config() -> tuple[str, str, str] | None:
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

    api_version = os.environ.get(
        "AZURE_OPENAI_API_VERSION", DEFAULT_AZURE_API_VERSION
    )
    return api_key, _normalize_azure_endpoint(endpoint), api_version


@lru_cache(maxsize=1)
def get_client() -> OpenAI | AzureOpenAI:
    azure_config = _get_azure_config()
    if azure_config:
        api_key, endpoint, api_version = azure_config
        return AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=api_key,
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
