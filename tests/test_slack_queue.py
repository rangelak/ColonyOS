from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from colonyos.config import ColonyConfig, SlackConfig
from colonyos.models import QueueItem, QueueItemStatus, QueueState
from colonyos.slack import SlackWatchState, TriageResult
from colonyos.slack_queue import SlackQueueEngine, _generate_id


def _make_engine(
    tmp_path: Path,
    queue_state: QueueState,
    watch_state: SlackWatchState,
    *,
    agent_lock: threading.Lock | None = None,
) -> SlackQueueEngine:
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
        agent_lock=agent_lock,
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


def test_triage_completes_while_agent_lock_is_held(tmp_path: Path) -> None:
    """Triage must NOT acquire agent_lock — it should complete even when the lock is held."""
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    agent_lock = threading.Lock()
    engine = _make_engine(tmp_path, queue_state, watch_state, agent_lock=agent_lock)
    client = MagicMock()
    finished = threading.Event()

    def _triage(*args, **kwargs):
        finished.set()
        return TriageResult(
            actionable=True,
            confidence=0.95,
            summary="Add brew install support",
            base_branch=None,
            reasoning="clear feature request",
        )

    # Hold the agent_lock (simulating a running pipeline)
    agent_lock.acquire()
    try:
        worker = threading.Thread(
            target=engine._triage_and_enqueue,
            kwargs={
                "client": client,
                "channel": "C1",
                "ts": "3.0",
                "user": "U1",
                "prompt_text": "Add brew installation support",
            },
        )
        with patch("colonyos.slack_queue.triage_message", side_effect=_triage):
            worker.start()
            # Triage should complete within 1s even though agent_lock is held
            assert finished.wait(timeout=1), "Triage blocked on agent_lock"
            worker.join(timeout=2)
    finally:
        agent_lock.release()

    assert len(queue_state.items) == 1


def test_triage_completes_when_agent_lock_is_none(tmp_path: Path) -> None:
    """Triage must work when agent_lock is None (the default)."""
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state, agent_lock=None)
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
            ts="4.0",
            user="U1",
            prompt_text="Add brew installation support",
        )

    assert len(queue_state.items) == 1
    assert watch_state.is_processed("C1", "4.0")


def test_generate_id_is_unique_with_same_timestamp() -> None:
    fixed_now = datetime(2026, 3, 30, 12, 0, 0, 123456, tzinfo=timezone.utc)

    with patch("colonyos.slack_queue.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        first = _generate_id("slack")
        second = _generate_id("slack")

    assert first != second
    assert first.startswith("slack-20260330_120000_123456-")
    assert second.startswith("slack-20260330_120000_123456-")


def test_handle_event_rejects_duplicate_while_pending(tmp_path: Path) -> None:
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    client = MagicMock()
    event = {
        "channel": "C1",
        "ts": "1.0",
        "user": "U1",
        "text": "<@UBOT> Add brew installation support",
    }

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.extract_prompt_from_mention", return_value="Add brew installation support"), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch.object(engine, "_ensure_triage_worker"), \
         patch("colonyos.slack_queue.react_to_message") as mock_react:
        engine._handle_event(event, client)
        engine._handle_event(event, client)

    assert engine._triage_queue.qsize() == 1
    assert mock_react.call_count == 1
    assert watch_state.is_processed("C1", "1.0") is False
    assert engine.watch_state.message_key("C1", "1.0") in engine._pending_messages


def test_triage_worker_survives_unhandled_exception(tmp_path: Path) -> None:
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    processed_second_task = threading.Event()
    calls: list[str] = []

    engine._triage_queue.put({
        "client": MagicMock(),
        "channel": "C1",
        "ts": "1.0",
        "user": "U1",
        "prompt_text": "first",
    })
    engine._triage_queue.put({
        "client": MagicMock(),
        "channel": "C1",
        "ts": "2.0",
        "user": "U1",
        "prompt_text": "second",
    })

    def _triage_side_effect(**task):
        calls.append(task["ts"])
        if task["ts"] == "1.0":
            raise RuntimeError("boom")
        processed_second_task.set()
        engine.shutdown_event.set()

    with patch.object(engine, "_triage_and_enqueue", side_effect=_triage_side_effect):
        worker = threading.Thread(target=engine._triage_worker_loop, daemon=True)
        worker.start()
        assert processed_second_task.wait(timeout=1)
        worker.join(timeout=1)

    assert calls == ["1.0", "2.0"]


def test_ensure_triage_worker_restarts_if_previous_thread_died(tmp_path: Path) -> None:
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    dead_worker = MagicMock()
    dead_worker.is_alive.return_value = False
    replacement_worker = MagicMock()
    engine._triage_worker = dead_worker

    with patch("colonyos.slack_queue.threading.Thread", return_value=replacement_worker) as mock_thread:
        engine._ensure_triage_worker()

    mock_thread.assert_called_once_with(
        target=engine._triage_worker_loop,
        daemon=True,
        name="slack-triage-worker",
    )
    replacement_worker.start.assert_called_once()
    assert engine._triage_worker is replacement_worker
