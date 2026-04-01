"""Tests for daemon state persistence and budget tracking."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from colonyos.daemon_state import (
    DaemonState,
    atomic_write_json,
    load_daemon_state,
    save_daemon_state,
)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    (tmp_path / ".colonyos").mkdir()
    return tmp_path


class TestDaemonState:
    def test_default_fields(self):
        state = DaemonState()
        assert state.daily_spend_usd == 0.0
        assert state.consecutive_failures == 0
        assert state.circuit_breaker_until is None
        assert state.total_items_today == 0
        assert state.paused is False
        assert state.last_heartbeat is None

    def test_to_dict_roundtrip(self):
        state = DaemonState(daily_spend_usd=12.5, consecutive_failures=2, paused=True)
        d = state.to_dict()
        restored = DaemonState.from_dict(d)
        assert restored.daily_spend_usd == 12.5
        assert restored.consecutive_failures == 2
        assert restored.paused is True

    def test_from_dict_defaults_for_missing_keys(self):
        state = DaemonState.from_dict({})
        assert state.daily_spend_usd == 0.0
        assert state.paused is False

    def test_check_daily_budget_allowed(self):
        state = DaemonState(daily_spend_usd=10.0)
        allowed, remaining = state.check_daily_budget(50.0)
        assert allowed is True
        assert remaining == 40.0

    def test_check_daily_budget_exhausted(self):
        state = DaemonState(daily_spend_usd=50.0)
        allowed, remaining = state.check_daily_budget(50.0)
        assert allowed is False
        assert remaining == 0.0

    def test_check_daily_budget_resets_on_new_day(self):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        state = DaemonState(daily_spend_usd=100.0, daily_reset_date=yesterday, total_items_today=5)
        allowed, remaining = state.check_daily_budget(50.0)
        assert allowed is True
        assert remaining == 50.0
        assert state.daily_spend_usd == 0.0
        assert state.total_items_today == 0

    def test_check_daily_budget_unlimited(self):
        state = DaemonState(daily_spend_usd=123.45)
        allowed, remaining = state.check_daily_budget(None)
        assert allowed is True
        assert remaining is None

    def test_record_spend(self):
        state = DaemonState()
        state.record_spend(5.0)
        state.record_spend(3.0)
        assert state.daily_spend_usd == 8.0
        assert state.total_items_today == 2

    def test_record_failure_increments(self):
        state = DaemonState()
        assert state.record_failure() == 1
        assert state.record_failure() == 2
        assert state.consecutive_failures == 2

    def test_record_success_resets_failures(self):
        state = DaemonState(consecutive_failures=5)
        state.record_success()
        assert state.consecutive_failures == 0
        assert state.circuit_breaker_until is None

    def test_circuit_breaker_lifecycle(self):
        state = DaemonState()
        # Not active initially
        assert state.is_circuit_breaker_active() is False

        # Activate with 30 min cooldown
        expiry = state.activate_circuit_breaker(30)
        assert expiry is not None
        assert state.is_circuit_breaker_active() is True

        # After success, should be cleared
        state.record_success()
        assert state.is_circuit_breaker_active() is False

    def test_circuit_breaker_expired(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        state = DaemonState(circuit_breaker_until=past)
        assert state.is_circuit_breaker_active() is False

    def test_circuit_breaker_escalating_cooldowns(self):
        state = DaemonState()
        result1 = state.activate_circuit_breaker(30)
        assert result1 is not None
        assert state.circuit_breaker_activations == 1
        assert state.is_circuit_breaker_active() is True

        state.circuit_breaker_until = None
        result2 = state.activate_circuit_breaker(30)
        assert result2 is not None
        assert state.circuit_breaker_activations == 2

        result3 = state.activate_circuit_breaker(30)
        assert result3 is None
        assert state.circuit_breaker_activations == 3

    def test_record_success_resets_circuit_breaker_activations(self):
        state = DaemonState(
            consecutive_failures=5,
            circuit_breaker_activations=2,
        )
        state.activate_circuit_breaker(30)
        state.record_success()
        assert state.circuit_breaker_activations == 0
        assert state.consecutive_failures == 0
        assert state.circuit_breaker_until is None

    def test_circuit_breaker_activations_serialization(self):
        state = DaemonState(circuit_breaker_activations=2)
        d = state.to_dict()
        assert d["circuit_breaker_activations"] == 2
        restored = DaemonState.from_dict(d)
        assert restored.circuit_breaker_activations == 2

    def test_circuit_breaker_activations_default_from_old_state(self):
        state = DaemonState.from_dict({"daily_spend_usd": 5.0})
        assert state.circuit_breaker_activations == 0

    def test_touch_heartbeat(self):
        state = DaemonState()
        assert state.last_heartbeat is None
        state.touch_heartbeat()
        assert state.last_heartbeat is not None

    def test_daily_thread_fields_default_none(self):
        state = DaemonState()
        assert state.daily_thread_ts is None
        assert state.daily_thread_date is None
        assert state.daily_thread_channel is None

    def test_daily_thread_fields_roundtrip(self):
        state = DaemonState(
            daily_thread_ts="1711929600.123456",
            daily_thread_date="2026-04-01",
            daily_thread_channel="C01ABCDEF",
        )
        d = state.to_dict()
        assert d["daily_thread_ts"] == "1711929600.123456"
        assert d["daily_thread_date"] == "2026-04-01"
        assert d["daily_thread_channel"] == "C01ABCDEF"
        restored = DaemonState.from_dict(d)
        assert restored.daily_thread_ts == "1711929600.123456"
        assert restored.daily_thread_date == "2026-04-01"
        assert restored.daily_thread_channel == "C01ABCDEF"

    def test_daily_thread_fields_missing_from_old_state(self):
        state = DaemonState.from_dict({"daily_spend_usd": 5.0})
        assert state.daily_thread_ts is None
        assert state.daily_thread_date is None
        assert state.daily_thread_channel is None

    def test_daily_thread_fields_none_values_roundtrip(self):
        state = DaemonState()
        d = state.to_dict()
        assert d["daily_thread_ts"] is None
        assert d["daily_thread_date"] is None
        assert d["daily_thread_channel"] is None
        restored = DaemonState.from_dict(d)
        assert restored.daily_thread_ts is None
        assert restored.daily_thread_date is None
        assert restored.daily_thread_channel is None


class TestAtomicWriteJson:
    def test_writes_valid_json(self, tmp_path: Path):
        path = tmp_path / "test.json"
        data = {"key": "value", "num": 42}
        atomic_write_json(path, data)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded == data

    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "sub" / "dir" / "test.json"
        atomic_write_json(path, {"hello": "world"})
        assert path.exists()

    def test_overwrites_existing(self, tmp_path: Path):
        path = tmp_path / "test.json"
        atomic_write_json(path, {"v": 1})
        atomic_write_json(path, {"v": 2})
        assert json.loads(path.read_text())["v"] == 2

    def test_no_temp_file_left_on_success(self, tmp_path: Path):
        path = tmp_path / "test.json"
        atomic_write_json(path, {"ok": True})
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


class TestLoadSaveDaemonState:
    def test_save_and_load_roundtrip(self, tmp_repo: Path):
        state = DaemonState(daily_spend_usd=25.0, consecutive_failures=1, paused=True)
        save_daemon_state(tmp_repo, state)
        loaded = load_daemon_state(tmp_repo)
        assert loaded.daily_spend_usd == 25.0
        assert loaded.consecutive_failures == 1
        assert loaded.paused is True

    def test_load_returns_fresh_when_no_file(self, tmp_repo: Path):
        state = load_daemon_state(tmp_repo)
        assert state.daily_spend_usd == 0.0

    def test_load_returns_fresh_on_corrupt_json(self, tmp_repo: Path):
        state_path = tmp_repo / ".colonyos" / "daemon_state.json"
        state_path.write_text("not json{{{", encoding="utf-8")
        state = load_daemon_state(tmp_repo)
        assert state.daily_spend_usd == 0.0

    def test_load_returns_fresh_on_valid_json_non_object(self, tmp_repo: Path):
        state_path = tmp_repo / ".colonyos" / "daemon_state.json"
        state_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        state = load_daemon_state(tmp_repo)
        assert state.daily_spend_usd == 0.0

    def test_load_returns_fresh_on_valid_json_wrong_numeric_types(self, tmp_repo: Path):
        state_path = tmp_repo / ".colonyos" / "daemon_state.json"
        state_path.write_text(
            json.dumps(
                {
                    "daily_spend_usd": "not-a-number",
                    "consecutive_failures": 0,
                }
            ),
            encoding="utf-8",
        )
        state = load_daemon_state(tmp_repo)
        assert state.daily_spend_usd == 0.0
        assert state.consecutive_failures == 0
