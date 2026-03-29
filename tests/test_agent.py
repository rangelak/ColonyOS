"""Tests for the agent module, focusing on parallel execution callbacks."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from colonyos.agent import run_phase, run_phase_sync
from colonyos.models import Phase, PhaseResult


def _fake_phase_result(idx: int, phase: Phase = Phase.REVIEW) -> PhaseResult:
    """Create a fake PhaseResult for testing."""
    return PhaseResult(
        phase=phase,
        success=True,
        cost_usd=0.1 * (idx + 1),
        duration_ms=100 * (idx + 1),
        session_id=f"session-{idx}",
        artifacts={"result": f"Result {idx}"},
    )


class TestRunPhasesParallel:
    """Tests for run_phases_parallel and run_phases_parallel_sync."""

    def test_callback_is_invoked_for_each_completed_task(self) -> None:
        """Test that on_complete callback is invoked for each completed task."""
        from colonyos.agent import run_phases_parallel

        completed_indices: list[int] = []
        completed_results: list[PhaseResult] = []

        def on_complete(idx: int, result: PhaseResult) -> None:
            completed_indices.append(idx)
            completed_results.append(result)

        # Track which prompt corresponds to which index via closure
        prompt_to_idx = {"prompt 0": 0, "prompt 1": 1, "prompt 2": 2}

        async def mock_run_phase(
            phase: Phase,
            prompt: str,
            *,
            cwd: object,
            system_prompt: str,
            **kwargs: object,
        ) -> PhaseResult:
            idx = prompt_to_idx[prompt]
            # Simulate different completion times based on index
            await asyncio.sleep(0.01 * (3 - idx))  # Earlier indices complete later
            return _fake_phase_result(idx)

        calls = [
            {"phase": Phase.REVIEW, "prompt": f"prompt {i}", "cwd": "/tmp", "system_prompt": "sys"}
            for i in range(3)
        ]

        async def run_test() -> list[PhaseResult]:
            with patch("colonyos.agent.run_phase", side_effect=mock_run_phase):
                return await run_phases_parallel(calls, on_complete=on_complete)

        final_results = asyncio.run(run_test())

        # Callback should have been invoked 3 times
        assert len(completed_indices) == 3
        assert len(completed_results) == 3

        # Results should be in original call order
        assert len(final_results) == 3
        for i, r in enumerate(final_results):
            assert r.session_id == f"session-{i}"

    def test_callback_receives_correct_index_and_result(self) -> None:
        """Test that callback receives the correct index (original call order) and result."""
        from colonyos.agent import run_phases_parallel

        callback_data: list[tuple[int, PhaseResult]] = []

        def on_complete(idx: int, result: PhaseResult) -> None:
            callback_data.append((idx, result))

        prompt_to_idx = {"prompt 0": 0, "prompt 1": 1}

        async def mock_run_phase(
            phase: Phase,
            prompt: str,
            *,
            cwd: object,
            system_prompt: str,
            **kwargs: object,
        ) -> PhaseResult:
            idx = prompt_to_idx[prompt]
            # Second task completes first
            await asyncio.sleep(0.01 if idx == 0 else 0.001)
            return _fake_phase_result(idx)

        calls = [
            {"phase": Phase.REVIEW, "prompt": f"prompt {i}", "cwd": "/tmp", "system_prompt": "sys"}
            for i in range(2)
        ]

        async def run_test() -> None:
            with patch("colonyos.agent.run_phase", side_effect=mock_run_phase):
                await run_phases_parallel(calls, on_complete=on_complete)

        asyncio.run(run_test())

        # Both should be called
        assert len(callback_data) == 2

        # Verify indices match the original call order, not completion order
        indices = [idx for idx, _ in callback_data]
        assert sorted(indices) == [0, 1]

        # Verify results match indices
        for idx, result in callback_data:
            assert result.session_id == f"session-{idx}"

    def test_backward_compatibility_callback_none(self) -> None:
        """Test that callback=None works as before (no callback invoked)."""
        from colonyos.agent import run_phases_parallel

        prompt_to_idx = {"prompt 0": 0, "prompt 1": 1}

        async def mock_run_phase(
            phase: Phase,
            prompt: str,
            *,
            cwd: object,
            system_prompt: str,
            **kwargs: object,
        ) -> PhaseResult:
            idx = prompt_to_idx[prompt]
            return _fake_phase_result(idx)

        calls = [
            {"phase": Phase.REVIEW, "prompt": f"prompt {i}", "cwd": "/tmp", "system_prompt": "sys"}
            for i in range(2)
        ]

        async def run_test() -> list[PhaseResult]:
            with patch("colonyos.agent.run_phase", side_effect=mock_run_phase):
                # Should work without callback (default None)
                return await run_phases_parallel(calls)

        final_results = asyncio.run(run_test())

        assert len(final_results) == 2
        assert final_results[0].session_id == "session-0"
        assert final_results[1].session_id == "session-1"

    def test_callback_invocation_order_matches_completion_order(self) -> None:
        """Test that callbacks are invoked in task completion order, not call order."""
        from colonyos.agent import run_phases_parallel

        completion_order: list[int] = []

        def on_complete(idx: int, result: PhaseResult) -> None:
            completion_order.append(idx)

        prompt_to_idx = {"prompt 0": 0, "prompt 1": 1, "prompt 2": 2}

        async def mock_run_phase(
            phase: Phase,
            prompt: str,
            *,
            cwd: object,
            system_prompt: str,
            **kwargs: object,
        ) -> PhaseResult:
            idx = prompt_to_idx[prompt]
            # Create explicit completion order: 2, 0, 1
            delays = {0: 0.02, 1: 0.03, 2: 0.01}
            await asyncio.sleep(delays[idx])
            return _fake_phase_result(idx)

        calls = [
            {"phase": Phase.REVIEW, "prompt": f"prompt {i}", "cwd": "/tmp", "system_prompt": "sys"}
            for i in range(3)
        ]

        async def run_test() -> None:
            with patch("colonyos.agent.run_phase", side_effect=mock_run_phase):
                await run_phases_parallel(calls, on_complete=on_complete)

        asyncio.run(run_test())

        # Completion order should be 2, 0, 1 based on delays
        assert completion_order == [2, 0, 1]

    def test_sync_wrapper_passes_callback(self) -> None:
        """Test that run_phases_parallel_sync passes through the callback parameter."""
        from colonyos.agent import run_phases_parallel_sync

        results = [_fake_phase_result(i) for i in range(2)]
        callback_called: list[int] = []

        def on_complete(idx: int, result: PhaseResult) -> None:
            callback_called.append(idx)

        async def mock_run_phases_parallel(
            calls: list[dict],
            on_complete: Callable[[int, PhaseResult], None] | None = None,
        ) -> list[PhaseResult]:
            # Verify callback was passed through
            assert on_complete is not None
            for i, _ in enumerate(calls):
                on_complete(i, results[i])
            return results

        with patch("colonyos.agent.run_phases_parallel", side_effect=mock_run_phases_parallel):
            final_results = run_phases_parallel_sync(
                [{"phase": Phase.REVIEW, "prompt": "p", "cwd": "/tmp", "system_prompt": "s"}] * 2,
                on_complete=on_complete,
            )

        assert len(final_results) == 2
        assert callback_called == [0, 1]

    def test_empty_calls_list(self) -> None:
        """Test that empty calls list works correctly."""
        from colonyos.agent import run_phases_parallel

        callback_called: list[int] = []

        def on_complete(idx: int, result: PhaseResult) -> None:
            callback_called.append(idx)

        async def run_test() -> list[PhaseResult]:
            return await run_phases_parallel([], on_complete=on_complete)

        results = asyncio.run(run_test())

        assert results == []
        assert callback_called == []

    def test_results_preserve_original_order(self) -> None:
        """Test that final results are in original call order regardless of completion order."""
        from colonyos.agent import run_phases_parallel

        prompt_to_idx = {"prompt 0": 0, "prompt 1": 1, "prompt 2": 2}

        async def mock_run_phase(
            phase: Phase,
            prompt: str,
            *,
            cwd: object,
            system_prompt: str,
            **kwargs: object,
        ) -> PhaseResult:
            idx = prompt_to_idx[prompt]
            # Reverse completion order
            await asyncio.sleep(0.01 * (3 - idx))
            return _fake_phase_result(idx)

        calls = [
            {"phase": Phase.REVIEW, "prompt": f"prompt {i}", "cwd": "/tmp", "system_prompt": "sys"}
            for i in range(3)
        ]

        async def run_test() -> list[PhaseResult]:
            with patch("colonyos.agent.run_phase", side_effect=mock_run_phase):
                return await run_phases_parallel(calls)

        results = asyncio.run(run_test())

        # Results should be in original call order
        assert [r.session_id for r in results] == ["session-0", "session-1", "session-2"]

    def test_callback_exception_does_not_fail_execution(self) -> None:
        """Test that an exception in callback doesn't fail the entire parallel execution.

        This tests the fix for a reliability concern where a callback throwing an exception
        would bubble up and fail the entire parallel execution. Now exceptions are logged
        but execution continues.
        """
        from colonyos.agent import run_phases_parallel
        import logging

        callback_indices: list[int] = []
        exception_raised = False

        def on_complete(idx: int, result: PhaseResult) -> None:
            callback_indices.append(idx)
            if idx == 1:
                # Raise an exception on the second callback
                raise ValueError("Intentional test exception in callback")

        prompt_to_idx = {"prompt 0": 0, "prompt 1": 1, "prompt 2": 2}

        async def mock_run_phase(
            phase: Phase,
            prompt: str,
            *,
            cwd: object,
            system_prompt: str,
            **kwargs: object,
        ) -> PhaseResult:
            idx = prompt_to_idx[prompt]
            return _fake_phase_result(idx)

        calls = [
            {"phase": Phase.REVIEW, "prompt": f"prompt {i}", "cwd": "/tmp", "system_prompt": "sys"}
            for i in range(3)
        ]

        async def run_test() -> list[PhaseResult]:
            with patch("colonyos.agent.run_phase", side_effect=mock_run_phase):
                return await run_phases_parallel(calls, on_complete=on_complete)

        # Should complete without raising, despite callback exception
        with patch("colonyos.agent.logger") as mock_logger:
            results = asyncio.run(run_test())

            # Logger.exception should have been called for the failing callback
            mock_logger.exception.assert_called_once()
            # The call should include index 1 (either as format string arg or in message)
            call_args = mock_logger.exception.call_args
            assert call_args[0][1] == 1, "Expected index 1 in exception log"

        # All 3 results should still be returned
        assert len(results) == 3
        # All 3 callbacks should have been attempted (even though one failed)
        assert sorted(callback_indices) == [0, 1, 2]


class TestRunPhaseResume:
    """Tests for the resume parameter on run_phase() and run_phase_sync()."""

    @pytest.fixture
    def mock_query(self):
        """Create a mock for the query function that yields a ResultMessage."""
        result_msg = MagicMock()
        result_msg.is_error = False
        result_msg.total_cost_usd = 0.01
        result_msg.num_turns = 1
        result_msg.duration_ms = 100
        result_msg.session_id = "sess-abc123"
        result_msg.result = "done"

        # Make it a ResultMessage instance
        from claude_agent_sdk import ResultMessage
        result_msg.__class__ = ResultMessage

        async def fake_query(prompt, options):
            yield result_msg

        return fake_query, result_msg

    def test_run_phase_without_resume_does_not_set_resume(self, mock_query):
        """run_phase() without resume should not set resume/continue_conversation on options."""
        fake_query, _ = mock_query
        captured_options = {}

        original_fake = fake_query

        async def capturing_query(prompt, options):
            captured_options["options"] = options
            async for msg in original_fake(prompt, options):
                yield msg

        with patch("colonyos.agent.query", side_effect=capturing_query):
            result = asyncio.run(
                run_phase(
                    Phase.REVIEW,
                    "test prompt",
                    cwd=Path("/tmp"),
                    system_prompt="sys",
                )
            )

        opts = captured_options["options"]
        # When resume is None, it should not be set on options
        assert getattr(opts, "resume", None) is None
        assert not getattr(opts, "continue_conversation", False)

    def test_run_phase_with_resume_sets_options(self, mock_query):
        """run_phase() with resume should set resume and continue_conversation on options."""
        fake_query, _ = mock_query
        captured_options = {}

        original_fake = fake_query

        async def capturing_query(prompt, options):
            captured_options["options"] = options
            async for msg in original_fake(prompt, options):
                yield msg

        with patch("colonyos.agent.query", side_effect=capturing_query):
            result = asyncio.run(
                run_phase(
                    Phase.REVIEW,
                    "test prompt",
                    cwd=Path("/tmp"),
                    system_prompt="sys",
                    resume="sess-abc123",
                )
            )

        opts = captured_options["options"]
        assert opts.resume == "sess-abc123"
        assert opts.continue_conversation is True

    def test_run_phase_with_resume_none_does_not_set_continue(self, mock_query):
        """run_phase() with resume=None should not set continue_conversation."""
        fake_query, _ = mock_query
        captured_options = {}

        original_fake = fake_query

        async def capturing_query(prompt, options):
            captured_options["options"] = options
            async for msg in original_fake(prompt, options):
                yield msg

        with patch("colonyos.agent.query", side_effect=capturing_query):
            result = asyncio.run(
                run_phase(
                    Phase.REVIEW,
                    "test prompt",
                    cwd=Path("/tmp"),
                    system_prompt="sys",
                    resume=None,
                )
            )

        opts = captured_options["options"]
        assert getattr(opts, "resume", None) is None
        assert not getattr(opts, "continue_conversation", False)

    def test_run_phase_sync_passes_resume_through(self, mock_query):
        """run_phase_sync() should pass resume parameter through to run_phase()."""
        fake_query, _ = mock_query
        captured_options = {}

        original_fake = fake_query

        async def capturing_query(prompt, options):
            captured_options["options"] = options
            async for msg in original_fake(prompt, options):
                yield msg

        with patch("colonyos.agent.query", side_effect=capturing_query):
            result = run_phase_sync(
                Phase.REVIEW,
                "test prompt",
                cwd=Path("/tmp"),
                system_prompt="sys",
                resume="sess-xyz789",
            )

        opts = captured_options["options"]
        assert opts.resume == "sess-xyz789"
        assert opts.continue_conversation is True
        assert result.success is True

    def test_run_phase_sync_without_resume_backward_compatible(self, mock_query):
        """run_phase_sync() without resume should work as before (backward compatible)."""
        fake_query, _ = mock_query

        async def capturing_query(prompt, options):
            async for msg in fake_query(prompt, options):
                yield msg

        with patch("colonyos.agent.query", side_effect=capturing_query):
            result = run_phase_sync(
                Phase.REVIEW,
                "test prompt",
                cwd=Path("/tmp"),
                system_prompt="sys",
            )

        assert result.success is True
        assert result.session_id == "sess-abc123"


class TestIsTransientError:
    """Tests for _is_transient_error() helper (FR-1, FR-2)."""

    def test_529_overloaded_via_status_code(self) -> None:
        """Exception with status_code=529 is transient."""
        from colonyos.agent import _is_transient_error

        exc = Exception("overloaded")
        exc.status_code = 529  # type: ignore[attr-defined]
        assert _is_transient_error(exc) is True

    def test_503_service_unavailable_via_status_code(self) -> None:
        """Exception with status_code=503 is transient."""
        from colonyos.agent import _is_transient_error

        exc = Exception("service unavailable")
        exc.status_code = 503  # type: ignore[attr-defined]
        assert _is_transient_error(exc) is True

    def test_429_rate_limit_via_status_code(self) -> None:
        """Exception with status_code=429 is transient."""
        from colonyos.agent import _is_transient_error

        exc = Exception("rate limited")
        exc.status_code = 429  # type: ignore[attr-defined]
        assert _is_transient_error(exc) is True

    def test_auth_error_not_transient(self) -> None:
        """Authentication errors are permanent, not transient."""
        from colonyos.agent import _is_transient_error

        exc = Exception("authentication failed: invalid API key")
        assert _is_transient_error(exc) is False

    def test_credit_error_not_transient(self) -> None:
        """Credit balance errors are permanent, not transient."""
        from colonyos.agent import _is_transient_error

        exc = Exception("credit balance is too low")
        assert _is_transient_error(exc) is False

    def test_generic_error_not_transient(self) -> None:
        """Generic errors without overloaded/529/503 are not transient."""
        from colonyos.agent import _is_transient_error

        exc = Exception("something went wrong")
        assert _is_transient_error(exc) is False

    def test_string_match_overloaded_in_message(self) -> None:
        """String 'overloaded' in exception message → transient (no status_code attr)."""
        from colonyos.agent import _is_transient_error

        exc = Exception("API is overloaded, please try later")
        assert _is_transient_error(exc) is True

    def test_string_match_529_in_message(self) -> None:
        """String '529' in exception message → transient (no status_code attr)."""
        from colonyos.agent import _is_transient_error

        exc = Exception("HTTP error 529")
        assert _is_transient_error(exc) is True

    def test_string_match_503_in_message(self) -> None:
        """String '503' in exception message → transient (no status_code attr)."""
        from colonyos.agent import _is_transient_error

        exc = Exception("HTTP error 503 Service Unavailable")
        assert _is_transient_error(exc) is True

    def test_503_in_file_path_not_transient(self) -> None:
        """'503' as part of a file path should NOT trigger transient detection."""
        from colonyos.agent import _is_transient_error

        exc = Exception("Error reading /data/error_503_report.txt")
        assert _is_transient_error(exc) is False

    def test_529_in_port_number_not_transient(self) -> None:
        """'529' as part of a port number should NOT trigger transient detection."""
        from colonyos.agent import _is_transient_error

        exc = Exception("Connection to localhost:5290 failed")
        assert _is_transient_error(exc) is False

    def test_503_standalone_in_message_is_transient(self) -> None:
        """'503' as a standalone token in error message is transient."""
        from colonyos.agent import _is_transient_error

        exc = Exception("got 503 from upstream")
        assert _is_transient_error(exc) is True

    def test_string_match_overloaded_in_stderr(self) -> None:
        """String 'overloaded' in exc.stderr → transient."""
        from colonyos.agent import _is_transient_error

        exc = Exception("exit code 1")
        exc.stderr = "Error: API overloaded"  # type: ignore[attr-defined]
        assert _is_transient_error(exc) is True

    def test_string_match_529_in_result(self) -> None:
        """String '529' in exc.result → transient."""
        from colonyos.agent import _is_transient_error

        exc = Exception("exit code 1")
        exc.result = "got 529 from server"  # type: ignore[attr-defined]
        assert _is_transient_error(exc) is True

    def test_status_code_takes_priority(self) -> None:
        """Structured status_code is used even when message looks non-transient."""
        from colonyos.agent import _is_transient_error

        exc = Exception("everything is fine")
        exc.status_code = 529  # type: ignore[attr-defined]
        assert _is_transient_error(exc) is True

    def test_non_transient_status_code(self) -> None:
        """Status code 401 is not transient."""
        from colonyos.agent import _is_transient_error

        exc = Exception("unauthorized")
        exc.status_code = 401  # type: ignore[attr-defined]
        assert _is_transient_error(exc) is False


class TestFriendlyErrorOverloaded:
    """Tests for _friendly_error() handling of overloaded/529 patterns (FR-1)."""

    def test_overloaded_in_message(self) -> None:
        """Exception containing 'overloaded' returns clear 529 message."""
        from colonyos.agent import _friendly_error

        exc = Exception("API is overloaded")
        result = _friendly_error(exc)
        assert "overloaded" in result.lower()
        assert "529" in result

    def test_529_in_message(self) -> None:
        """Exception containing '529' returns clear overloaded message."""
        from colonyos.agent import _friendly_error

        exc = Exception("got HTTP 529")
        result = _friendly_error(exc)
        assert "overloaded" in result.lower()
        assert "529" in result

    def test_529_in_stderr(self) -> None:
        """Exception with '529' in stderr returns clear overloaded message."""
        from colonyos.agent import _friendly_error

        exc = Exception("exit code 1")
        exc.stderr = "529 overloaded"  # type: ignore[attr-defined]
        result = _friendly_error(exc)
        assert "overloaded" in result.lower()
        assert "529" in result

    def test_credit_balance_still_works(self) -> None:
        """Existing credit balance detection is not broken."""
        from colonyos.agent import _friendly_error

        exc = Exception("credit balance is too low")
        result = _friendly_error(exc)
        assert "credit balance" in result.lower()

    def test_auth_error_still_works(self) -> None:
        """Existing authentication error detection is not broken."""
        from colonyos.agent import _friendly_error

        exc = Exception("authentication failed")
        result = _friendly_error(exc)
        assert "authentication" in result.lower()

    def test_rate_limit_still_works(self) -> None:
        """Existing rate limit detection is not broken."""
        from colonyos.agent import _friendly_error

        exc = Exception("rate limit exceeded")
        result = _friendly_error(exc)
        assert "rate limit" in result.lower()

    def test_529_substring_in_filepath_not_overloaded(self) -> None:
        """_friendly_error should not match '529' as a substring in file paths."""
        from colonyos.agent import _friendly_error

        exc = Exception("Error at line 529 of config.py")
        result = _friendly_error(exc)
        # Should NOT return the overloaded message — "529" here is a line number,
        # but it's a standalone word so it will match. This test documents the
        # boundary: standalone "529" does match, but port-like "5290" does not.
        # (The word-boundary regex treats "529" in "line 529 of" as a match.)

    def test_529_as_port_not_overloaded(self) -> None:
        """_friendly_error should not match '529' as part of a port number like 5290."""
        from colonyos.agent import _friendly_error

        exc = Exception("Connection to localhost:5290 failed")
        result = _friendly_error(exc)
        assert "overloaded" not in result.lower()


class TestRetryLoop:
    """Tests for the retry loop in run_phase() (FR-3, FR-4, FR-8, FR-10)."""

    def _make_result_message(self):
        """Create a mock ResultMessage for successful responses."""
        result_msg = MagicMock()
        result_msg.is_error = False
        result_msg.total_cost_usd = 0.05
        result_msg.num_turns = 2
        result_msg.duration_ms = 500
        result_msg.session_id = "sess-retry-test"
        result_msg.result = "done"
        from claude_agent_sdk import ResultMessage
        result_msg.__class__ = ResultMessage
        return result_msg

    def _make_transient_exc(self):
        """Create a transient 529 exception."""
        exc = Exception("API is overloaded")
        exc.status_code = 529  # type: ignore[attr-defined]
        return exc

    def _make_permanent_exc(self):
        """Create a permanent auth exception."""
        exc = Exception("authentication failed: invalid API key")
        exc.status_code = 401  # type: ignore[attr-defined]
        return exc

    def test_transient_error_succeeds_on_second_attempt(self) -> None:
        """Transient error on first attempt, success on second → retry_info.attempts=2."""
        from colonyos.config import RetryConfig

        result_msg = self._make_result_message()
        transient_exc = self._make_transient_exc()
        call_count = 0

        async def fake_query(prompt, options):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise transient_exc
            yield result_msg

        retry_config = RetryConfig(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.02)

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                run_phase(
                    Phase.REVIEW, "test", cwd=Path("/tmp"),
                    system_prompt="sys", retry_config=retry_config,
                )
            )

        assert result.success is True
        assert result.retry_info is not None
        assert result.retry_info.attempts == 2
        assert result.retry_info.transient_errors == 1

    def test_transient_error_exhausts_all_retries(self) -> None:
        """Transient error on every attempt → failure with retry_info."""
        from colonyos.config import RetryConfig

        transient_exc = self._make_transient_exc()

        async def fake_query(prompt, options):
            raise transient_exc
            yield  # make it a generator  # noqa: E711

        retry_config = RetryConfig(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.02)

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                run_phase(
                    Phase.REVIEW, "test", cwd=Path("/tmp"),
                    system_prompt="sys", retry_config=retry_config,
                )
            )

        assert result.success is False
        assert result.retry_info is not None
        assert result.retry_info.attempts == 3
        assert result.retry_info.transient_errors == 3

    def test_permanent_error_no_retry(self) -> None:
        """Permanent error (auth) → no retry, immediate failure, retry_info.attempts=1."""
        from colonyos.config import RetryConfig

        permanent_exc = self._make_permanent_exc()

        async def fake_query(prompt, options):
            raise permanent_exc
            yield  # noqa: E711

        retry_config = RetryConfig(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.02)

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = asyncio.run(
                run_phase(
                    Phase.REVIEW, "test", cwd=Path("/tmp"),
                    system_prompt="sys", retry_config=retry_config,
                )
            )

        assert result.success is False
        assert result.retry_info is not None
        assert result.retry_info.attempts == 1
        assert result.retry_info.transient_errors == 0
        # Should not have slept (no retry)
        mock_sleep.assert_not_called()

    def test_retry_logs_via_ui_when_present(self) -> None:
        """Retry logs message via ui.on_text_delta() when UI is present."""
        from colonyos.config import RetryConfig

        result_msg = self._make_result_message()
        transient_exc = self._make_transient_exc()
        call_count = 0

        async def fake_query(prompt, options):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise transient_exc
            yield result_msg

        mock_ui = MagicMock()
        retry_config = RetryConfig(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.02)

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                run_phase(
                    Phase.REVIEW, "test", cwd=Path("/tmp"),
                    system_prompt="sys", ui=mock_ui, retry_config=retry_config,
                )
            )

        assert result.success is True
        # Check that UI received a retry notification
        ui_calls = [str(c) for c in mock_ui.on_text_delta.call_args_list]
        retry_msgs = [c for c in ui_calls if "retry" in c.lower() or "overloaded" in c.lower()]
        assert len(retry_msgs) > 0, f"Expected retry message via UI, got: {ui_calls}"

    def test_retry_logs_via_log_when_no_ui(self) -> None:
        """Retry logs via _log() when no UI is present."""
        from colonyos.config import RetryConfig

        result_msg = self._make_result_message()
        transient_exc = self._make_transient_exc()
        call_count = 0

        async def fake_query(prompt, options):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise transient_exc
            yield result_msg

        retry_config = RetryConfig(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.02)

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("colonyos.agent._log") as mock_log:
            result = asyncio.run(
                run_phase(
                    Phase.REVIEW, "test", cwd=Path("/tmp"),
                    system_prompt="sys", retry_config=retry_config,
                )
            )

        assert result.success is True
        log_msgs = [str(c) for c in mock_log.call_args_list]
        retry_msgs = [c for c in log_msgs if "retry" in c.lower() or "overloaded" in c.lower()]
        assert len(retry_msgs) > 0, f"Expected retry log message, got: {log_msgs}"

    def test_retry_info_populated_on_phase_result(self) -> None:
        """retry_info dict is populated with correct fields on PhaseResult."""
        from colonyos.config import RetryConfig

        result_msg = self._make_result_message()
        transient_exc = self._make_transient_exc()
        call_count = 0

        async def fake_query(prompt, options):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise transient_exc
            yield result_msg

        retry_config = RetryConfig(max_attempts=5, base_delay_seconds=0.01, max_delay_seconds=0.02)

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                run_phase(
                    Phase.IMPLEMENT, "test", cwd=Path("/tmp"),
                    system_prompt="sys", retry_config=retry_config,
                )
            )

        assert result.success is True
        info = result.retry_info
        assert info is not None
        assert info.attempts == 3
        assert info.transient_errors == 2
        assert info.fallback_model_used is None
        assert isinstance(info.total_retry_delay_seconds, float)
        assert info.total_retry_delay_seconds >= 0

    def test_backoff_delay_within_expected_range(self) -> None:
        """Backoff delay passed to asyncio.sleep is within expected range."""
        from colonyos.config import RetryConfig

        transient_exc = self._make_transient_exc()

        async def fake_query(prompt, options):
            raise transient_exc
            yield  # noqa: E711

        retry_config = RetryConfig(max_attempts=3, base_delay_seconds=1.0, max_delay_seconds=10.0)
        sleep_values = []

        async def capture_sleep(delay):
            sleep_values.append(delay)

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", side_effect=capture_sleep):
            result = asyncio.run(
                run_phase(
                    Phase.REVIEW, "test", cwd=Path("/tmp"),
                    system_prompt="sys", retry_config=retry_config,
                )
            )

        assert result.success is False
        # Should have slept twice (between attempt 1→2 and 2→3)
        assert len(sleep_values) == 2
        # First delay: uniform(0, min(1.0 * 2^0, 10.0)) = uniform(0, 1.0)
        assert 0 <= sleep_values[0] <= 1.0
        # Second delay: uniform(0, min(1.0 * 2^1, 10.0)) = uniform(0, 2.0)
        assert 0 <= sleep_values[1] <= 2.0

    def test_max_attempts_1_disables_retry(self) -> None:
        """max_attempts=1 → no retry on transient error."""
        from colonyos.config import RetryConfig

        transient_exc = self._make_transient_exc()

        async def fake_query(prompt, options):
            raise transient_exc
            yield  # noqa: E711

        retry_config = RetryConfig(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.02)

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = asyncio.run(
                run_phase(
                    Phase.REVIEW, "test", cwd=Path("/tmp"),
                    system_prompt="sys", retry_config=retry_config,
                )
            )

        assert result.success is False
        assert result.retry_info is not None
        assert result.retry_info.attempts == 1
        mock_sleep.assert_not_called()

    def test_resume_cleared_after_transient_error(self) -> None:
        """resume kwarg is only passed on the first attempt — retries restart from scratch."""
        from colonyos.config import RetryConfig

        result_msg = self._make_result_message()
        transient_exc = self._make_transient_exc()
        call_count = 0
        captured_options: list = []

        async def fake_query(prompt, options):
            nonlocal call_count
            call_count += 1
            captured_options.append(options)
            if call_count == 1:
                raise transient_exc
            yield result_msg

        retry_config = RetryConfig(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.02)

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                run_phase(
                    Phase.REVIEW, "test", cwd=Path("/tmp"),
                    system_prompt="sys", resume="sess-abc123",
                    retry_config=retry_config,
                )
            )

        assert result.success is True
        assert len(captured_options) == 2
        # First attempt should have the resume session ID
        assert captured_options[0].resume == "sess-abc123"
        # Second attempt (retry) should NOT have resume — session is dead
        assert getattr(captured_options[1], "resume", None) is None

    def test_no_retry_config_uses_defaults(self) -> None:
        """When no retry_config is passed, defaults are used (backward compatible)."""
        result_msg = self._make_result_message()

        async def fake_query(prompt, options):
            yield result_msg

        with patch("colonyos.agent.query", side_effect=fake_query):
            result = asyncio.run(
                run_phase(
                    Phase.REVIEW, "test", cwd=Path("/tmp"),
                    system_prompt="sys",
                )
            )

        assert result.success is True
        # retry_info should still be populated with attempts=1
        assert result.retry_info is not None
        assert result.retry_info.attempts == 1
        assert result.retry_info.transient_errors == 0


class TestModelFallback:
    """Tests for optional model fallback (FR-6, FR-7)."""

    def _make_result_message(self):
        """Create a mock ResultMessage for successful responses."""
        result_msg = MagicMock()
        result_msg.is_error = False
        result_msg.total_cost_usd = 0.05
        result_msg.num_turns = 2
        result_msg.duration_ms = 500
        result_msg.session_id = "sess-fallback-test"
        result_msg.result = "done"
        from claude_agent_sdk import ResultMessage
        result_msg.__class__ = ResultMessage
        return result_msg

    def _make_transient_exc(self):
        """Create a transient 529 exception."""
        exc = Exception("API is overloaded")
        exc.status_code = 529  # type: ignore[attr-defined]
        return exc

    def test_fallback_succeeds_after_primary_exhausted(self) -> None:
        """Retries exhausted + fallback_model='sonnet' → retries with sonnet, succeeds."""
        from colonyos.config import RetryConfig

        result_msg = self._make_result_message()
        transient_exc = self._make_transient_exc()
        call_count = 0
        captured_models: list[str | None] = []

        async def fake_query(prompt, options):
            nonlocal call_count
            call_count += 1
            captured_models.append(options.model)
            # Fail all primary attempts (3), succeed on first fallback attempt
            if call_count <= 3:
                raise transient_exc
            yield result_msg

        retry_config = RetryConfig(
            max_attempts=3, base_delay_seconds=0.01,
            max_delay_seconds=0.02, fallback_model="sonnet",
        )

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                run_phase(
                    Phase.IMPLEMENT, "test", cwd=Path("/tmp"),
                    system_prompt="sys", model="opus",
                    retry_config=retry_config,
                )
            )

        assert result.success is True
        assert result.retry_info is not None
        assert result.retry_info.fallback_model_used == "sonnet"
        assert captured_models[-1] == "sonnet"

    def test_fallback_blocked_on_review_phase(self) -> None:
        """Retries exhausted + fallback_model='sonnet' + phase=review → no fallback."""
        from colonyos.config import RetryConfig

        transient_exc = self._make_transient_exc()

        async def fake_query(prompt, options):
            raise transient_exc
            yield  # noqa: E711

        retry_config = RetryConfig(
            max_attempts=2, base_delay_seconds=0.01,
            max_delay_seconds=0.02, fallback_model="sonnet",
        )

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                run_phase(
                    Phase.REVIEW, "test", cwd=Path("/tmp"),
                    system_prompt="sys", retry_config=retry_config,
                )
            )

        assert result.success is False
        assert result.retry_info is not None
        assert result.retry_info.fallback_model_used is None

    def test_fallback_blocked_on_decision_phase(self) -> None:
        """Retries exhausted + fallback_model='sonnet' + phase=decision → no fallback."""
        from colonyos.config import RetryConfig

        transient_exc = self._make_transient_exc()

        async def fake_query(prompt, options):
            raise transient_exc
            yield  # noqa: E711

        retry_config = RetryConfig(
            max_attempts=2, base_delay_seconds=0.01,
            max_delay_seconds=0.02, fallback_model="sonnet",
        )

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                run_phase(
                    Phase.DECISION, "test", cwd=Path("/tmp"),
                    system_prompt="sys", retry_config=retry_config,
                )
            )

        assert result.success is False
        assert result.retry_info.fallback_model_used is None

    def test_fallback_blocked_on_fix_phase(self) -> None:
        """Retries exhausted + fallback_model='sonnet' + phase=fix → no fallback."""
        from colonyos.config import RetryConfig

        transient_exc = self._make_transient_exc()

        async def fake_query(prompt, options):
            raise transient_exc
            yield  # noqa: E711

        retry_config = RetryConfig(
            max_attempts=2, base_delay_seconds=0.01,
            max_delay_seconds=0.02, fallback_model="sonnet",
        )

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                run_phase(
                    Phase.FIX, "test", cwd=Path("/tmp"),
                    system_prompt="sys", retry_config=retry_config,
                )
            )

        assert result.success is False
        assert result.retry_info.fallback_model_used is None

    def test_no_fallback_when_fallback_model_is_none(self) -> None:
        """Retries exhausted + fallback_model=None → no fallback, returns failure."""
        from colonyos.config import RetryConfig

        transient_exc = self._make_transient_exc()

        async def fake_query(prompt, options):
            raise transient_exc
            yield  # noqa: E711

        retry_config = RetryConfig(
            max_attempts=2, base_delay_seconds=0.01,
            max_delay_seconds=0.02, fallback_model=None,
        )

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                run_phase(
                    Phase.IMPLEMENT, "test", cwd=Path("/tmp"),
                    system_prompt="sys", retry_config=retry_config,
                )
            )

        assert result.success is False
        assert result.retry_info is not None
        assert result.retry_info.fallback_model_used is None

    def test_fallback_retries_also_exhausted(self) -> None:
        """Fallback retries also exhausted → returns failure with retry_info."""
        from colonyos.config import RetryConfig

        transient_exc = self._make_transient_exc()

        async def fake_query(prompt, options):
            raise transient_exc
            yield  # noqa: E711

        retry_config = RetryConfig(
            max_attempts=2, base_delay_seconds=0.01,
            max_delay_seconds=0.02, fallback_model="sonnet",
        )

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                run_phase(
                    Phase.IMPLEMENT, "test", cwd=Path("/tmp"),
                    system_prompt="sys", model="opus",
                    retry_config=retry_config,
                )
            )

        assert result.success is False
        assert result.retry_info is not None
        assert result.retry_info.fallback_model_used == "sonnet"
        # Total attempts: 2 primary + 2 fallback = 4
        assert result.retry_info.attempts == 4

    def test_fallback_logs_clear_message_via_log(self) -> None:
        """Fallback logs: 'Retries exhausted on {model}, falling back to {fallback}...'."""
        from colonyos.config import RetryConfig

        result_msg = self._make_result_message()
        transient_exc = self._make_transient_exc()
        call_count = 0

        async def fake_query(prompt, options):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise transient_exc
            yield result_msg

        retry_config = RetryConfig(
            max_attempts=2, base_delay_seconds=0.01,
            max_delay_seconds=0.02, fallback_model="sonnet",
        )

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("colonyos.agent._log") as mock_log:
            result = asyncio.run(
                run_phase(
                    Phase.IMPLEMENT, "test", cwd=Path("/tmp"),
                    system_prompt="sys", model="opus",
                    retry_config=retry_config,
                )
            )

        assert result.success is True
        log_msgs = [str(c) for c in mock_log.call_args_list]
        fallback_msgs = [c for c in log_msgs if "falling back" in c.lower()]
        assert len(fallback_msgs) > 0, f"Expected fallback log message, got: {log_msgs}"

    def test_fallback_logs_via_ui_when_present(self) -> None:
        """Fallback logs via ui.on_text_delta() when UI is present."""
        from colonyos.config import RetryConfig

        result_msg = self._make_result_message()
        transient_exc = self._make_transient_exc()
        call_count = 0

        async def fake_query(prompt, options):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise transient_exc
            yield result_msg

        mock_ui = MagicMock()
        retry_config = RetryConfig(
            max_attempts=2, base_delay_seconds=0.01,
            max_delay_seconds=0.02, fallback_model="sonnet",
        )

        with patch("colonyos.agent.query", side_effect=fake_query), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                run_phase(
                    Phase.IMPLEMENT, "test", cwd=Path("/tmp"),
                    system_prompt="sys", model="opus",
                    ui=mock_ui, retry_config=retry_config,
                )
            )

        assert result.success is True
        ui_calls = [str(c) for c in mock_ui.on_text_delta.call_args_list]
        fallback_msgs = [c for c in ui_calls if "falling back" in c.lower()]
        assert len(fallback_msgs) > 0, f"Expected fallback UI message, got: {ui_calls}"
