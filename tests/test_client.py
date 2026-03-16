from __future__ import annotations

from unittest.mock import patch

import pytest

from colonyos_pm.client import get_client, get_default_model, reset_client_cache


@pytest.fixture(autouse=True)
def clear_client_cache() -> None:
    reset_client_cache()
    yield
    reset_client_cache()


class TestSharedClientConfig:
    def test_prefers_azure_config_and_normalizes_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
        monkeypatch.setenv(
            "AZURE_OPENAI_ENDPOINT",
            "https://example-resource.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview",
        )
        with patch("colonyos_pm.client.AzureOpenAI") as azure_client:
            get_client()

        azure_client.assert_called_once_with(
            api_key="azure-key",
            azure_endpoint="https://example-resource.cognitiveservices.azure.com",
            api_version="2025-03-01-preview",
        )

    def test_uses_openai_key_when_azure_env_is_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

        with patch("colonyos_pm.client.OpenAI") as openai_client:
            get_client()

        openai_client.assert_called_once_with(api_key="openai-key")

    def test_uses_custom_azure_api_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
        monkeypatch.setenv(
            "AZURE_OPENAI_ENDPOINT",
            "https://example-resource.cognitiveservices.azure.com/",
        )
        monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")

        with patch("colonyos_pm.client.AzureOpenAI") as azure_client:
            get_client()

        azure_client.assert_called_once_with(
            api_key="azure-key",
            azure_endpoint="https://example-resource.cognitiveservices.azure.com",
            api_version="2025-04-01-preview",
        )

    def test_azure_endpoint_without_api_version_uses_repo_default_preview(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_API_VERSION", raising=False)
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
        monkeypatch.setenv(
            "AZURE_OPENAI_ENDPOINT",
            "https://example-resource.cognitiveservices.azure.com/",
        )

        with patch("colonyos_pm.client.AzureOpenAI") as azure_client:
            get_client()

        azure_client.assert_called_once_with(
            api_key="azure-key",
            azure_endpoint="https://example-resource.cognitiveservices.azure.com",
            api_version="2025-03-01-preview",
        )

    def test_default_model_uses_azure_model_when_no_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("COLONYOS_MODEL", raising=False)
        monkeypatch.setenv("AZURE_OPENAI_MODEL", "gpt-5.4-pro")

        assert get_default_model() == "gpt-5.4-pro"

    def test_colonyos_model_override_wins_over_azure_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("COLONYOS_MODEL", "gpt-4o-mini")
        monkeypatch.setenv("AZURE_OPENAI_MODEL", "gpt-5.4-pro")

        assert get_default_model() == "gpt-4o-mini"

    def test_raises_on_partial_azure_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)

        with pytest.raises(RuntimeError, match="Azure OpenAI is partially configured"):
            get_client()

    def test_raises_when_no_provider_credentials_exist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)

        with pytest.raises(RuntimeError, match="No LLM credentials found"):
            get_client()
