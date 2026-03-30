from __future__ import annotations

from colonyos.prioritizer import _extract_json_payload


def test_extract_json_payload_handles_json_prefix() -> None:
    payload = _extract_json_payload(
        'json\n{"decisions":[{"item_id":"ceo-1","urgency_score":0.82,"reason":"important"}]}'
    )
    assert payload is not None
    assert payload["decisions"] == [
        {"item_id": "ceo-1", "urgency_score": 0.82, "reason": "important"}
    ]


def test_extract_json_payload_handles_fenced_json() -> None:
    payload = _extract_json_payload(
        '```json\n{"decisions":[{"item_id":"slack-1","urgency_score":1.0,"reason":"user pain"}]}\n```'
    )
    assert payload is not None
    assert payload["decisions"] == [
        {"item_id": "slack-1", "urgency_score": 1.0, "reason": "user pain"}
    ]
