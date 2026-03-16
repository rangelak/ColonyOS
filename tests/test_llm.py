from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from openai import APIConnectionError
import pytest

from colonyos_pm.llm import chat, chat_json


class TestLlmResponsesApi:
    def test_chat_uses_responses_api_and_returns_output_text(self) -> None:
        mock_client = MagicMock()
        mock_client.responses.create.return_value = SimpleNamespace(
            output_text="hello from responses api"
        )

        with (
            patch("colonyos_pm.llm.get_client", return_value=mock_client),
            patch("colonyos_pm.llm.get_default_model", return_value="gpt-5.4-pro"),
        ):
            result = chat("system prompt", "user prompt", temperature=0.2, max_tokens=321)

        assert result == "hello from responses api"
        mock_client.responses.create.assert_called_once_with(
            model="gpt-5.4-pro",
            instructions="system prompt",
            input="user prompt",
            max_output_tokens=321,
        )

    def test_chat_json_parses_fenced_json_output(self) -> None:
        mock_client = MagicMock()
        mock_client.responses.create.return_value = SimpleNamespace(
            output_text='```json\n{"questions": [{"text": "What matters?"}]}\n```'
        )

        with (
            patch("colonyos_pm.llm.get_client", return_value=mock_client),
            patch("colonyos_pm.llm.get_default_model", return_value="gpt-5.4-pro"),
        ):
            result = chat_json("return json", "user prompt")

        assert result == {"questions": [{"text": "What matters?"}]}

    def test_chat_json_raises_on_truncated_responses_output(self) -> None:
        mock_client = MagicMock()
        mock_client.responses.create.return_value = SimpleNamespace(
            output_text="",
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
            output=[
                SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            text='{"questions": [{"text": "partial output"}]}'
                        )
                    ]
                )
            ],
        )

        with (
            patch("colonyos_pm.llm.get_client", return_value=mock_client),
            patch("colonyos_pm.llm.get_default_model", return_value="gpt-5.4-pro"),
        ):
            with pytest.raises(RuntimeError, match="truncated"):
                chat_json("return json", "user prompt")

    def test_chat_retries_transient_connection_errors(self) -> None:
        mock_client = MagicMock()
        mock_client.responses.create.side_effect = [
            APIConnectionError(message="server disconnected", request=MagicMock()),
            SimpleNamespace(output_text="retry succeeded"),
        ]

        with (
            patch("colonyos_pm.llm.get_client", return_value=mock_client),
            patch("colonyos_pm.llm.get_default_model", return_value="gpt-5.4-pro"),
            patch("colonyos_pm.llm.time.sleep") as sleep,
        ):
            result = chat("system prompt", "user prompt")

        assert result == "retry succeeded"
        assert mock_client.responses.create.call_count == 2
        sleep.assert_called_once_with(1)
