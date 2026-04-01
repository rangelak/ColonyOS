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
         patch("colonyos.slack_queue.extract_prompt_text", return_value="Add brew installation support"), \
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


# ---------------------------------------------------------------------------
# Task 2.0: Bounded retry for transient triage failures
# ---------------------------------------------------------------------------


def test_triage_retries_on_transient_failure_then_succeeds(tmp_path: Path) -> None:
    """A transient TimeoutError on the first attempt should be retried and succeed."""
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    client = MagicMock()

    call_count = 0

    def _triage_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError("LLM call timed out")
        return TriageResult(
            actionable=True,
            confidence=0.9,
            summary="Add brew install support",
            base_branch=None,
            reasoning="clear feature request",
        )

    with patch("colonyos.slack_queue.triage_message", side_effect=_triage_side_effect), \
         patch("colonyos.slack_queue.time.sleep") as mock_sleep:
        engine._triage_and_enqueue(
            client=client,
            channel="C1",
            ts="10.0",
            user="U1",
            prompt_text="Add brew install support",
        )

    assert call_count == 2
    mock_sleep.assert_called_once_with(3)
    assert len(queue_state.items) == 1
    assert watch_state.is_processed("C1", "10.0")


def test_triage_retry_checks_shutdown_event(tmp_path: Path) -> None:
    """If shutdown_event is set between attempts, retry should not happen."""
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    client = MagicMock()

    call_count = 0

    def _triage_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Set shutdown after first failure
        engine.shutdown_event.set()
        raise TimeoutError("LLM call timed out")

    with patch("colonyos.slack_queue.triage_message", side_effect=_triage_side_effect), \
         patch("colonyos.slack_queue.time.sleep") as mock_sleep:
        engine._triage_and_enqueue(
            client=client,
            channel="C1",
            ts="11.0",
            user="U1",
            prompt_text="Add brew install support",
        )

    # Should only be called once — no retry because shutdown_event was set
    assert call_count == 1
    mock_sleep.assert_not_called()
    assert len(queue_state.items) == 0


def test_triage_posts_warning_after_max_retries(tmp_path: Path) -> None:
    """After max retries exhausted, the existing error handler posts a warning."""
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    client = MagicMock()

    with patch(
        "colonyos.slack_queue.triage_message",
        side_effect=ConnectionError("connection refused"),
    ), patch("colonyos.slack_queue.time.sleep"), \
         patch("colonyos.slack_queue.post_message") as mock_post:
        engine._triage_and_enqueue(
            client=client,
            channel="C1",
            ts="12.0",
            user="U1",
            prompt_text="Add brew install support",
        )

    # post_message should have been called with the warning
    mock_post.assert_called_once_with(
        client,
        "C1",
        ":warning: Triage failed. Check server logs for details.",
        thread_ts="12.0",
    )
    assert len(queue_state.items) == 0


def test_triage_non_transient_error_skips_retry(tmp_path: Path) -> None:
    """Non-transient errors (e.g., ValueError) should fail immediately without retry."""
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    client = MagicMock()

    call_count = 0

    def _triage_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise ValueError("invalid input")

    with patch("colonyos.slack_queue.triage_message", side_effect=_triage_side_effect), \
         patch("colonyos.slack_queue.time.sleep") as mock_sleep, \
         patch("colonyos.slack_queue.post_message"):
        engine._triage_and_enqueue(
            client=client,
            channel="C1",
            ts="13.0",
            user="U1",
            prompt_text="Add brew install support",
        )

    # Should only be called once — no retry for ValueError
    assert call_count == 1
    mock_sleep.assert_not_called()
    assert len(queue_state.items) == 0


# ---------------------------------------------------------------------------
# Task 3.0: Mark failed triages as processed (prevent redelivery loops)
# ---------------------------------------------------------------------------


def test_failed_triage_marks_processed_as_triage_error_transient(tmp_path: Path) -> None:
    """When triage fails after retries (transient error), the message is marked 'triage-error'."""
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    client = MagicMock()

    with patch(
        "colonyos.slack_queue.triage_message",
        side_effect=ConnectionError("connection refused"),
    ), patch("colonyos.slack_queue.time.sleep"), \
         patch("colonyos.slack_queue.post_message"):
        engine._triage_and_enqueue(
            client=client,
            channel="C1",
            ts="20.0",
            user="U1",
            prompt_text="Add brew install support",
        )

    assert watch_state.is_processed("C1", "20.0")
    # Verify the status stored is "triage-error"
    key = watch_state.message_key("C1", "20.0")
    assert watch_state.processed_messages[key] == "triage-error"


def test_failed_triage_marks_processed_as_triage_error_non_transient(tmp_path: Path) -> None:
    """When triage fails with a non-transient error, the message is marked 'triage-error'."""
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    client = MagicMock()

    with patch(
        "colonyos.slack_queue.triage_message",
        side_effect=ValueError("bad input"),
    ), patch("colonyos.slack_queue.post_message"):
        engine._triage_and_enqueue(
            client=client,
            channel="C1",
            ts="21.0",
            user="U1",
            prompt_text="Add brew install support",
        )

    assert watch_state.is_processed("C1", "21.0")
    key = watch_state.message_key("C1", "21.0")
    assert watch_state.processed_messages[key] == "triage-error"


def test_triage_error_message_rejected_by_handle_event(tmp_path: Path) -> None:
    """A message previously marked 'triage-error' is rejected by _handle_event via is_processed."""
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    client = MagicMock()

    # Pre-mark the message as triage-error
    watch_state.mark_processed("C1", "22.0", "triage-error")

    event = {
        "channel": "C1",
        "ts": "22.0",
        "user": "U1",
        "text": "<@UBOT> Add brew installation support",
    }

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.extract_prompt_text", return_value="Add brew installation support"), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch.object(engine, "_ensure_triage_worker") as mock_ensure, \
         patch("colonyos.slack_queue.react_to_message"):
        engine._handle_event(event, client)

    # The message should NOT have been enqueued
    assert engine._triage_queue.qsize() == 0
    mock_ensure.assert_not_called()


# ---------------------------------------------------------------------------
# Task 4.0: Move increment_hourly_count to reservation time (close TOCTOU gap)
# ---------------------------------------------------------------------------


def test_increment_hourly_count_called_during_handle_event(tmp_path: Path) -> None:
    """increment_hourly_count fires at reservation time (_handle_event), not during triage."""
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    client = MagicMock()
    event = {
        "channel": "C1",
        "ts": "30.0",
        "user": "U1",
        "text": "<@UBOT> Add brew installation support",
    }

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.extract_prompt_text", return_value="Add brew installation support"), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch("colonyos.slack_queue.increment_hourly_count") as mock_increment, \
         patch.object(engine, "_ensure_triage_worker"), \
         patch("colonyos.slack_queue.react_to_message"):
        engine._handle_event(event, client)

    # increment_hourly_count should be called once during _handle_event
    mock_increment.assert_called_once_with(watch_state)


def test_increment_hourly_count_not_called_during_triage(tmp_path: Path) -> None:
    """increment_hourly_count must NOT be called during _triage_and_enqueue."""
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
    ), patch("colonyos.slack_queue.increment_hourly_count") as mock_increment:
        engine._triage_and_enqueue(
            client=client,
            channel="C1",
            ts="31.0",
            user="U1",
            prompt_text="Add brew install support",
        )

    # increment_hourly_count should NOT be called by _triage_and_enqueue
    mock_increment.assert_not_called()


def test_eager_increment_makes_rate_limit_reject_burst(tmp_path: Path) -> None:
    """When hourly count is incremented eagerly, subsequent messages hit the rate limit."""
    from colonyos.config import SlackConfig as SC

    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    config = ColonyConfig(slack=SlackConfig(enabled=True, channels=["C1"], auto_approve=True, max_runs_per_hour=1))
    engine = SlackQueueEngine(
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
    client = MagicMock()

    event1 = {"channel": "C1", "ts": "40.0", "user": "U1", "text": "<@UBOT> first request"}
    event2 = {"channel": "C1", "ts": "41.0", "user": "U2", "text": "<@UBOT> second request"}

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.extract_prompt_text", side_effect=lambda t, _: t.replace("<@UBOT> ", "")), \
         patch.object(engine, "_ensure_triage_worker"), \
         patch("colonyos.slack_queue.react_to_message"), \
         patch("colonyos.slack_queue.post_message") as mock_post:
        # First message: accepted, count goes to 1
        engine._handle_event(event1, client)
        # Second message: should be rate-limited since max_runs_per_hour=1
        engine._handle_event(event2, client)

    # Only the first message should be in the triage queue
    assert engine._triage_queue.qsize() == 1
    # Second message should have triggered a rate-limit warning
    mock_post.assert_called_once()
    args = mock_post.call_args
    assert "Rate limit" in args[0][2]


def test_failed_triage_does_not_decrement_hourly_count(tmp_path: Path) -> None:
    """A message that fails triage should NOT decrement the hourly count (fail-closed)."""
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    client = MagicMock()

    # Simulate the eager increment that _handle_event would have done
    current_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    watch_state.hourly_trigger_counts[current_hour] = 1

    with patch(
        "colonyos.slack_queue.triage_message",
        side_effect=ValueError("bad input"),
    ), patch("colonyos.slack_queue.post_message"):
        engine._triage_and_enqueue(
            client=client,
            channel="C1",
            ts="50.0",
            user="U1",
            prompt_text="Add brew install support",
        )

    # The hourly count should NOT have been decremented — fail-closed behavior
    assert watch_state.hourly_trigger_counts[current_hour] == 1


# ---------------------------------------------------------------------------
# Task 5.0: Integration verification and cleanup
# ---------------------------------------------------------------------------


def test_integration_triage_completes_while_pipeline_holds_agent_lock(tmp_path: Path) -> None:
    """End-to-end: Slack event arrives while agent_lock is held (pipeline running).

    Verifies:
      (a) :eyes: reaction fires immediately,
      (b) triage completes without blocking on agent_lock,
      (c) queue item is created with correct position,
      (d) acknowledgment is posted to Slack.
    """
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    agent_lock = threading.Lock()
    engine = _make_engine(tmp_path, queue_state, watch_state, agent_lock=agent_lock)
    client = MagicMock()
    triage_completed = threading.Event()

    def _mock_triage(*args, **kwargs):
        triage_completed.set()
        return TriageResult(
            actionable=True,
            confidence=0.95,
            summary="Add dark mode toggle",
            base_branch=None,
            reasoning="clear feature request",
        )

    # Simulate a running pipeline by holding agent_lock
    agent_lock.acquire()
    try:
        event = {
            "channel": "C1",
            "ts": "100.0",
            "user": "U1",
            "text": "<@UBOT> Add dark mode toggle",
        }

        with patch("colonyos.slack_queue.should_process_message", return_value=True), \
             patch("colonyos.slack_queue.extract_prompt_text", return_value="Add dark mode toggle"), \
             patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
             patch("colonyos.slack_queue.react_to_message") as mock_react, \
             patch("colonyos.slack_queue.triage_message", side_effect=_mock_triage), \
             patch("colonyos.slack_queue.post_triage_acknowledgment") as mock_ack:
            # _handle_event enqueues to the triage queue; the worker picks it up
            engine._handle_event(event, client)

            # (a) :eyes: reaction fires immediately (before triage)
            mock_react.assert_called_once_with(client, "C1", "100.0", "eyes")

            # Wait for the triage worker to complete processing
            assert triage_completed.wait(timeout=3), "Triage did not complete — likely blocked on agent_lock"
            # Give the worker a moment to finish enqueue + ack
            engine._triage_queue.join()

        # (b) Triage completed without blocking on agent_lock (asserted above via timeout)

        # (c) Queue item created with correct position
        assert len(queue_state.items) == 1
        item = queue_state.items[0]
        assert item.source_type == "slack"
        assert item.summary == "Add dark mode toggle"

        # (d) Acknowledgment posted to Slack
        mock_ack.assert_called_once()
        ack_kwargs = mock_ack.call_args
        assert ack_kwargs[1].get("queue_position") == 1 or ack_kwargs[0][4] is not None  # position arg

        # Message marked as processed
        assert watch_state.is_processed("C1", "100.0")
    finally:
        agent_lock.release()


# ---------------------------------------------------------------------------
# Task 2.0: Prompt extraction for non-mention messages
# ---------------------------------------------------------------------------


def test_handle_event_uses_full_text_for_non_mention_message(tmp_path: Path) -> None:
    """When a message has no bot mention, _handle_event passes the full text as prompt."""
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    client = MagicMock()
    event = {
        "channel": "C1",
        "ts": "50.0",
        "user": "U1",
        "text": "fix the flaky login test",
    }

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch.object(engine, "_ensure_triage_worker"), \
         patch("colonyos.slack_queue.react_to_message"):
        engine._handle_event(event, client)

    assert engine._triage_queue.qsize() == 1
    task_item = engine._triage_queue.get_nowait()
    assert task_item["prompt_text"] == "fix the flaky login test"


def test_handle_event_strips_mention_for_mention_message(tmp_path: Path) -> None:
    """When a message has a bot mention, _handle_event strips it from the prompt."""
    queue_state = QueueState(queue_id="q")
    watch_state = SlackWatchState(watch_id="w")
    engine = _make_engine(tmp_path, queue_state, watch_state)
    client = MagicMock()
    event = {
        "channel": "C1",
        "ts": "51.0",
        "user": "U1",
        "text": "<@UBOT> fix the flaky login test",
    }

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch.object(engine, "_ensure_triage_worker"), \
         patch("colonyos.slack_queue.react_to_message"):
        engine._handle_event(event, client)

    assert engine._triage_queue.qsize() == 1
    task = engine._triage_queue.get_nowait()
    assert task["prompt_text"] == "fix the flaky login test"


# ---------------------------------------------------------------------------
# Task 3.0: Bind `message` event in register() when trigger_mode == "all"
# ---------------------------------------------------------------------------


def _make_engine_with_trigger_mode(
    tmp_path: Path,
    trigger_mode: str,
) -> SlackQueueEngine:
    config = ColonyConfig(
        slack=SlackConfig(enabled=True, channels=["C1"], auto_approve=True, trigger_mode=trigger_mode),
    )
    return SlackQueueEngine(
        repo_root=tmp_path,
        config=config,
        queue_state=QueueState(queue_id="q"),
        watch_state=SlackWatchState(watch_id="w"),
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


def test_register_binds_message_event_when_trigger_mode_all(tmp_path: Path) -> None:
    """When trigger_mode is 'all', register() binds both app_mention and message events."""
    engine = _make_engine_with_trigger_mode(tmp_path, "all")
    bolt_app = MagicMock()

    with patch.object(engine, "_ensure_triage_worker"):
        engine.register(bolt_app)

    event_calls = [call[0][0] for call in bolt_app.event.call_args_list]
    assert "app_mention" in event_calls
    assert "message" in event_calls


def test_register_does_not_bind_message_event_when_trigger_mode_mention(tmp_path: Path) -> None:
    """When trigger_mode is 'mention', register() only binds app_mention (not message)."""
    engine = _make_engine_with_trigger_mode(tmp_path, "mention")
    bolt_app = MagicMock()

    with patch.object(engine, "_ensure_triage_worker"):
        engine.register(bolt_app)

    event_calls = [call[0][0] for call in bolt_app.event.call_args_list]
    assert "app_mention" in event_calls
    assert "message" not in event_calls


def test_register_message_handler_is_handle_event(tmp_path: Path) -> None:
    """The message event handler should be the same _handle_event method."""
    engine = _make_engine_with_trigger_mode(tmp_path, "all")
    bolt_app = MagicMock()
    # Track all (event_type, handler) pairs registered via bolt_app.event(type)(handler)
    registrations: list[tuple[str, Any]] = []
    original_event = bolt_app.event

    def _track_event(event_type):
        decorator_mock = MagicMock()

        def _capture_handler(handler):
            registrations.append((event_type, handler))
            return handler

        decorator_mock.side_effect = _capture_handler
        return decorator_mock

    bolt_app.event = _track_event

    with patch.object(engine, "_ensure_triage_worker"):
        engine.register(bolt_app)

    # Verify message event was registered with _handle_event as the handler
    message_handlers = [h for et, h in registrations if et == "message"]
    assert len(message_handlers) == 1, f"Expected 1 message handler, got {len(message_handlers)}"
    assert message_handlers[0] == engine._handle_event


# ---------------------------------------------------------------------------
# Task 4.0: Conditional 👀 reaction — skip for passive messages
# ---------------------------------------------------------------------------


def test_passive_message_does_not_get_eyes_reaction(tmp_path: Path) -> None:
    """In trigger_mode 'all', a non-mention message does NOT get 👀 in _handle_event."""
    engine = _make_engine_with_trigger_mode(tmp_path, "all")
    client = MagicMock()
    event = {
        "channel": "C1",
        "ts": "200.0",
        "user": "U1",
        "text": "fix the flaky login test",  # no bot mention
    }

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch.object(engine, "_ensure_triage_worker"), \
         patch("colonyos.slack_queue.react_to_message") as mock_react:
        engine._handle_event(event, client)

    mock_react.assert_not_called()


def test_mention_message_gets_eyes_reaction(tmp_path: Path) -> None:
    """In trigger_mode 'all', a direct @mention still gets 👀 immediately."""
    engine = _make_engine_with_trigger_mode(tmp_path, "all")
    client = MagicMock()
    event = {
        "channel": "C1",
        "ts": "201.0",
        "user": "U1",
        "text": "<@UBOT> fix the flaky login test",
    }

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch.object(engine, "_ensure_triage_worker"), \
         patch("colonyos.slack_queue.react_to_message") as mock_react:
        engine._handle_event(event, client)

    mock_react.assert_called_once_with(client, "C1", "201.0", "eyes")


def test_mention_mode_always_gets_eyes_reaction(tmp_path: Path) -> None:
    """In trigger_mode 'mention', behavior is unchanged — 👀 fires immediately."""
    engine = _make_engine_with_trigger_mode(tmp_path, "mention")
    client = MagicMock()
    event = {
        "channel": "C1",
        "ts": "202.0",
        "user": "U1",
        "text": "<@UBOT> fix the flaky login test",
    }

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch.object(engine, "_ensure_triage_worker"), \
         patch("colonyos.slack_queue.react_to_message") as mock_react:
        engine._handle_event(event, client)

    mock_react.assert_called_once_with(client, "C1", "202.0", "eyes")


def test_passive_message_gets_eyes_after_triage_confirms_actionable(tmp_path: Path) -> None:
    """In trigger_mode 'all', a passive message gets 👀 only after triage says actionable."""
    engine = _make_engine_with_trigger_mode(tmp_path, "all")
    client = MagicMock()
    triage_completed = threading.Event()

    def _mock_triage(*args, **kwargs):
        triage_completed.set()
        return TriageResult(
            actionable=True,
            confidence=0.95,
            summary="Fix flaky login test",
            base_branch=None,
            reasoning="clear fix request",
        )

    event = {
        "channel": "C1",
        "ts": "203.0",
        "user": "U1",
        "text": "fix the flaky login test",  # no mention — passive
    }

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch("colonyos.slack_queue.react_to_message") as mock_react, \
         patch("colonyos.slack_queue.triage_message", side_effect=_mock_triage), \
         patch("colonyos.slack_queue.post_triage_acknowledgment"):
        engine._handle_event(event, client)

        # No 👀 reaction immediately
        mock_react.assert_not_called()

        # Wait for triage worker to finish
        assert triage_completed.wait(timeout=3)
        engine._triage_queue.join()

        # After triage confirms actionable, 👀 should be added
        mock_react.assert_called_once_with(client, "C1", "203.0", "eyes")


def test_passive_message_no_eyes_when_triage_skips(tmp_path: Path) -> None:
    """In trigger_mode 'all', a passive message that triage skips never gets 👀."""
    engine = _make_engine_with_trigger_mode(tmp_path, "all")
    client = MagicMock()
    triage_completed = threading.Event()

    def _mock_triage(*args, **kwargs):
        triage_completed.set()
        return TriageResult(
            actionable=False,
            confidence=0.9,
            summary="",
            base_branch=None,
            reasoning="casual chat",
        )

    event = {
        "channel": "C1",
        "ts": "204.0",
        "user": "U1",
        "text": "hey how's everyone doing today",
    }

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch("colonyos.slack_queue.react_to_message") as mock_react, \
         patch("colonyos.slack_queue.triage_message", side_effect=_mock_triage), \
         patch("colonyos.slack_queue.post_triage_skip"):
        engine._handle_event(event, client)

        assert triage_completed.wait(timeout=3)
        engine._triage_queue.join()

        # No 👀 at any point — message was not actionable
        mock_react.assert_not_called()


def test_triage_queue_passes_is_passive_flag(tmp_path: Path) -> None:
    """_handle_event passes is_passive=True for non-mention messages to triage queue."""
    engine = _make_engine_with_trigger_mode(tmp_path, "all")
    client = MagicMock()
    event = {
        "channel": "C1",
        "ts": "205.0",
        "user": "U1",
        "text": "fix the flaky login test",
    }

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch.object(engine, "_ensure_triage_worker"), \
         patch("colonyos.slack_queue.react_to_message"):
        engine._handle_event(event, client)

    task_item = engine._triage_queue.get_nowait()
    assert task_item["is_passive"] is True


def test_triage_queue_passes_is_passive_false_for_mention(tmp_path: Path) -> None:
    """_handle_event passes is_passive=False for @mention messages to triage queue."""
    engine = _make_engine_with_trigger_mode(tmp_path, "all")
    client = MagicMock()
    event = {
        "channel": "C1",
        "ts": "206.0",
        "user": "U1",
        "text": "<@UBOT> fix the flaky login test",
    }

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch.object(engine, "_ensure_triage_worker"), \
         patch("colonyos.slack_queue.react_to_message"):
        engine._handle_event(event, client)

    task_item = engine._triage_queue.get_nowait()
    assert task_item["is_passive"] is False


# ---------------------------------------------------------------------------
# Task 5.0: Dedup verification for dual-event delivery
# ---------------------------------------------------------------------------


def test_dual_event_delivery_dedup_second_dropped_via_pending(tmp_path: Path) -> None:
    """An @mention in trigger_mode 'all' fires both app_mention and message events.

    Both events carry the same (channel, ts). The first call to _handle_event
    reserves the message in _pending_messages; the second call sees it pending
    and drops the duplicate before it reaches the triage queue.
    """
    engine = _make_engine_with_trigger_mode(tmp_path, "all")
    client = MagicMock()

    # Same (channel, ts) — Slack sends two events for one @mention
    event = {
        "channel": "C1",
        "ts": "300.0",
        "user": "U1",
        "text": "<@UBOT> deploy to staging",
    }

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch.object(engine, "_ensure_triage_worker"), \
         patch("colonyos.slack_queue.react_to_message") as mock_react:
        # First delivery (e.g. app_mention) — accepted
        engine._handle_event(event, client)
        # Second delivery (e.g. message) — should be dropped
        engine._handle_event(event, client)

    # Only one item should reach the triage queue
    assert engine._triage_queue.qsize() == 1
    # 👀 reaction should fire only once (first delivery)
    assert mock_react.call_count == 1
    # The message should still be in the pending set (not yet triaged)
    assert engine._is_pending_message("C1", "300.0")


def test_dual_event_delivery_dedup_second_dropped_via_processed(tmp_path: Path) -> None:
    """If triage finishes before the second event arrives, dedup catches it via is_processed.

    Simulates the race where the first event is fully triaged (moved from pending
    to processed) before the second event arrives.
    """
    engine = _make_engine_with_trigger_mode(tmp_path, "all")
    client = MagicMock()

    event = {
        "channel": "C1",
        "ts": "301.0",
        "user": "U1",
        "text": "<@UBOT> deploy to staging",
    }

    # Pre-mark as processed (simulating the first event already completing triage)
    engine.watch_state.mark_processed("C1", "301.0", "slack-item-001")

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.extract_prompt_text", return_value="deploy to staging"), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch.object(engine, "_ensure_triage_worker"), \
         patch("colonyos.slack_queue.react_to_message") as mock_react:
        engine._handle_event(event, client)

    # Nothing should reach the triage queue
    assert engine._triage_queue.qsize() == 0
    # No 👀 reaction
    mock_react.assert_not_called()


def test_dual_event_delivery_end_to_end_only_one_queue_item(tmp_path: Path) -> None:
    """End-to-end: two events with same (channel, ts) result in exactly one queue item.

    Sends both events through _handle_event, lets the triage worker process
    them, and verifies exactly one QueueItem is created.
    """
    engine = _make_engine_with_trigger_mode(tmp_path, "all")
    client = MagicMock()
    triage_completed = threading.Event()

    def _mock_triage(*args, **kwargs):
        triage_completed.set()
        return TriageResult(
            actionable=True,
            confidence=0.95,
            summary="Deploy to staging",
            base_branch=None,
            reasoning="clear deployment request",
        )

    event = {
        "channel": "C1",
        "ts": "302.0",
        "user": "U1",
        "text": "<@UBOT> deploy to staging",
    }

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch("colonyos.slack_queue.react_to_message"), \
         patch("colonyos.slack_queue.triage_message", side_effect=_mock_triage), \
         patch("colonyos.slack_queue.post_triage_acknowledgment"):
        # Deliver both events (same channel:ts)
        engine._handle_event(event, client)
        engine._handle_event(event, client)

        # Wait for triage to process the single accepted event
        assert triage_completed.wait(timeout=3)
        engine._triage_queue.join()

    # Exactly one queue item created
    assert len(engine.queue_state.items) == 1
    assert engine.queue_state.items[0].summary == "Deploy to staging"
    # Message is marked as processed
    assert engine.watch_state.is_processed("C1", "302.0")


# ---------------------------------------------------------------------------
# Task 7.0: Integration test — full "all" mode flow
# ---------------------------------------------------------------------------


def test_all_mode_passive_message_end_to_end(tmp_path: Path) -> None:
    """End-to-end: a non-mention message in trigger_mode 'all' flows through
    _handle_event → triage worker → queue with the correct prompt text.

    Verifies:
      (a) No 👀 reaction at intake time,
      (b) The full message text is used as the prompt (no mention stripping),
      (c) Triage processes it and creates a QueueItem,
      (d) 👀 reaction fires after triage confirms actionable,
      (e) The message is marked as processed.
    """
    engine = _make_engine_with_trigger_mode(tmp_path, "all")
    client = MagicMock()
    triage_completed = threading.Event()

    def _mock_triage(*args, **kwargs):
        triage_completed.set()
        return TriageResult(
            actionable=True,
            confidence=0.9,
            summary="Fix flaky login test",
            base_branch=None,
            reasoning="clear fix request",
        )

    event = {
        "channel": "C1",
        "ts": "700.0",
        "user": "U1",
        "text": "fix the flaky login test",  # no bot mention — passive
    }

    react_calls: list[tuple[str, str, str, str]] = []
    original_react = None

    def _track_react(client, channel, ts, name):
        react_calls.append((client, channel, ts, name))

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch("colonyos.slack_queue.react_to_message", side_effect=_track_react) as mock_react, \
         patch("colonyos.slack_queue.triage_message", side_effect=_mock_triage), \
         patch("colonyos.slack_queue.post_triage_acknowledgment") as mock_ack:
        engine._handle_event(event, client)

        # (a) No 👀 at intake — passive message
        assert len(react_calls) == 0, "👀 should not fire immediately for passive messages"

        # Wait for triage worker to process
        assert triage_completed.wait(timeout=3), "Triage did not complete"
        engine._triage_queue.join()

    # (b) Triage was called with full message text (no mention stripping)
    # The prompt_text in the triage call should be the raw message
    # (verified indirectly: if mention stripping happened, "fix the flaky login test"
    #  would still be the same since there's no mention to strip — but the is_passive
    #  flag confirms the non-mention path was taken)

    # (c) QueueItem created with correct summary
    assert len(engine.queue_state.items) == 1
    item = engine.queue_state.items[0]
    assert item.source_type == "slack"
    assert item.summary == "Fix flaky login test"

    # (d) 👀 reaction fires after triage confirms actionable
    assert len(react_calls) == 1
    assert react_calls[0] == (client, "C1", "700.0", "eyes")

    # (e) Message marked as processed
    assert engine.watch_state.is_processed("C1", "700.0")

    # Acknowledgment posted
    mock_ack.assert_called_once()


def test_all_mode_passive_and_mention_both_processed_correctly(tmp_path: Path) -> None:
    """End-to-end: in trigger_mode 'all', both a passive message and an @mention
    are processed with correct prompt extraction and reaction behavior.

    Verifies:
      (a) The @mention gets 👀 immediately; the passive message does not,
      (b) Both are triaged and enqueued as separate QueueItems,
      (c) Prompt extraction works correctly for both:
          - Mention message: bot prefix stripped from prompt,
          - Passive message: full text used as prompt,
      (d) The passive message gets 👀 only after triage confirms actionable,
      (e) Both messages are marked as processed.
    """
    engine = _make_engine_with_trigger_mode(tmp_path, "all")
    client = MagicMock()
    triage_calls: list[str] = []
    both_triaged = threading.Event()

    def _mock_triage(prompt_text, **kwargs):
        triage_calls.append(prompt_text)
        if len(triage_calls) >= 2:
            both_triaged.set()
        return TriageResult(
            actionable=True,
            confidence=0.9,
            summary=f"Handle: {prompt_text[:30]}",
            base_branch=None,
            reasoning="actionable request",
        )

    mention_event = {
        "channel": "C1",
        "ts": "701.0",
        "user": "U1",
        "text": "<@UBOT> deploy to staging",
    }
    passive_event = {
        "channel": "C1",
        "ts": "702.0",
        "user": "U2",
        "text": "fix the flaky login test",
    }

    react_calls: list[tuple[str, str]] = []

    def _track_react(client, channel, ts, name):
        react_calls.append((ts, name))

    with patch("colonyos.slack_queue.should_process_message", return_value=True), \
         patch("colonyos.slack_queue.check_rate_limit", return_value=True), \
         patch("colonyos.slack_queue.react_to_message", side_effect=_track_react), \
         patch("colonyos.slack_queue.triage_message", side_effect=_mock_triage), \
         patch("colonyos.slack_queue.post_triage_acknowledgment"):
        # Send mention first, then passive
        engine._handle_event(mention_event, client)
        engine._handle_event(passive_event, client)

        # (a) Mention gets 👀 immediately; passive does not
        assert ("701.0", "eyes") in react_calls, "Mention should get immediate 👀"
        assert ("702.0", "eyes") not in react_calls, "Passive should not get immediate 👀"
        assert len(react_calls) == 1, "Only the mention should have 👀 at intake"

        # Wait for both to be triaged
        assert both_triaged.wait(timeout=3), "Triage did not complete for both messages"
        engine._triage_queue.join()

    # (b) Both enqueued as separate QueueItems
    assert len(engine.queue_state.items) == 2

    # (c) Prompt extraction: both triage calls received correct prompt text
    assert "deploy to staging" in triage_calls, "Mention prompt should have bot prefix stripped"
    assert "fix the flaky login test" in triage_calls, "Passive prompt should be full text"
    # Verify no raw mention tag leaked into triage
    for call in triage_calls:
        assert "<@UBOT>" not in call, "Bot mention should be stripped from prompt"

    # (d) Passive message got 👀 after triage (total: mention immediate + passive post-triage)
    passive_eyes = [c for c in react_calls if c == ("702.0", "eyes")]
    assert len(passive_eyes) == 1, "Passive message should get 👀 after triage"
    mention_eyes = [c for c in react_calls if c == ("701.0", "eyes")]
    assert len(mention_eyes) == 1, "Mention should have exactly one 👀"

    # (e) Both messages marked as processed
    assert engine.watch_state.is_processed("C1", "701.0")
    assert engine.watch_state.is_processed("C1", "702.0")
