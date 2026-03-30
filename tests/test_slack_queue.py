from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from colonyos.config import ColonyConfig, SlackConfig
from colonyos.models import QueueItem, QueueItemStatus, QueueState
from colonyos.slack import SlackWatchState, TriageResult
from colonyos.slack_queue import SlackQueueEngine


def _make_engine(tmp_path: Path, queue_state: QueueState, watch_state: SlackWatchState) -> SlackQueueEngine:
    config = ColonyConfig(slack=SlackConfig(enabled=True, channels=["C1"], auto_approve=True))
    return SlackQueueEngine(
        repo_root=tmp_path,
        config=config,
        queue_state=queue_state,
        watch_state=watch_state,
        state_lock=threading.Lock(),
        shutdown_event=threading.Event(),
        bot_user_id="UBOT",
        slack_client_ready=threading.Event(),
        publish_client=lambda client: None,
        persist_queue=lambda: None,
        persist_watch_state=lambda: None,
        is_time_exceeded=lambda: False,
        is_budget_exceeded=lambda: False,
        is_daily_budget_exceeded=lambda: False,
    )


def test_triage_enqueues_slack_item_and_marks_processed(tmp_path: Path) -> None:
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    client = MagicMock()

    with patch(
        "colonyos.slack_queue.triage_message",
        return_value=TriageResult(
            actionable=True,
            confidence=0.95,
            summary="Add brew install support",
            base_branch=None,
            reasoning="clear feature request",
        ),
    ):
        engine._triage_and_enqueue(
            client=client,
            channel="C1",
            ts="1.0",
            user="U1",
            prompt_text="Add brew installation support",
        )

    assert len(queue_state.items) == 1
    item = queue_state.items[0]
    assert item.source_type == "slack"
    assert item.summary == "Add brew install support"
    assert item.notification_thread_ts == "1.0"
    assert watch_state.is_processed("C1", "1.0")
    assert client.chat_postMessage.called


def test_triage_merges_similar_request_into_existing_item(tmp_path: Path) -> None:
    existing = QueueItem(
        id="slack-existing",
        source_type="slack",
        source_value="Add brew install support",
        raw_prompt="Add brew install support",
        summary="Add brew install support",
        status=QueueItemStatus.PENDING,
        demand_count=1,
    )
    queue_state = QueueState(queue_id="q", items=[existing])
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    client = MagicMock()

    with patch(
        "colonyos.slack_queue.triage_message",
        return_value=TriageResult(
            actionable=True,
            confidence=0.9,
            summary="Add brew install support",
            base_branch=None,
            reasoning="same request",
        ),
    ):
        engine._triage_and_enqueue(
            client=client,
            channel="C1",
            ts="2.0",
            user="U2",
                prompt_text="Add brew install support for global installs",
        )

    assert len(queue_state.items) == 1
    assert existing.demand_count == 2
    assert watch_state.is_processed("C1", "2.0")
    assert client.chat_postMessage.called
