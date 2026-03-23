"""Textual pilot tests for the StatusBar widget."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from colonyos.tui.widgets.status_bar import StatusBar


class StatusBarApp(App):
    """Minimal app that mounts a StatusBar for testing."""

    def compose(self) -> ComposeResult:
        yield StatusBar()


@pytest.mark.asyncio
async def test_status_bar_mounts_idle():
    """StatusBar should display 'idle' when no phase is active."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        assert not bar.is_running
        assert bar.phase_name == ""
        assert "idle" in bar._last_rendered


@pytest.mark.asyncio
async def test_status_bar_set_phase():
    """set_phase should show the phase name and start the running state."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        bar.set_phase("Planning", budget=1.0, model="opus")
        await pilot.pause()

        assert bar.is_running is True
        assert bar.phase_name == "Planning"
        assert bar.phase_model == "opus"
        assert "Planning" in bar._last_rendered
        assert "opus" in bar._last_rendered


@pytest.mark.asyncio
async def test_status_bar_set_complete_accumulates_cost():
    """set_complete should accumulate cost and stop the running state."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)

        bar.set_phase("Planning")
        bar.set_complete(cost=0.50, turns=3, duration=10.0)
        await pilot.pause()

        assert bar.is_running is False
        assert bar.total_cost == pytest.approx(0.50)
        assert bar.turn_count == 3

        # Second phase accumulates cost
        bar.set_phase("Implementing")
        bar.set_complete(cost=1.25, turns=5, duration=30.0)
        await pilot.pause()

        assert bar.total_cost == pytest.approx(1.75)


@pytest.mark.asyncio
async def test_status_bar_increment_turn():
    """increment_turn should bump the turn counter."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        bar.set_phase("Review")
        bar.increment_turn()
        bar.increment_turn()
        bar.increment_turn()
        await pilot.pause()

        assert bar.turn_count == 3
        assert "3 turns" in bar._last_rendered


@pytest.mark.asyncio
async def test_status_bar_single_turn_label():
    """A single turn should display 'turn' not 'turns'."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        bar.set_phase("Review")
        bar.increment_turn()
        await pilot.pause()

        assert "1 turn" in bar._last_rendered
        assert "1 turns" not in bar._last_rendered


@pytest.mark.asyncio
async def test_status_bar_set_error():
    """set_error should display the error message."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        bar.set_phase("Planning")
        bar.set_error("Budget exceeded")
        await pilot.pause()

        assert bar.is_running is False
        assert bar.error_msg == "Budget exceeded"
        assert "Budget exceeded" in bar._last_rendered


@pytest.mark.asyncio
async def test_status_bar_shows_cost_when_idle():
    """After a phase completes, idle state should still show total cost."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        bar.set_phase("Planning")
        bar.set_complete(cost=0.75, turns=2, duration=5.0)
        await pilot.pause()

        assert "$0.75" in bar._last_rendered


@pytest.mark.asyncio
async def test_status_bar_spinner_cycles():
    """The spinner index should advance when running."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        bar.set_phase("Planning")

        initial_index = bar._spinner_index
        bar._advance_spinner()
        bar._advance_spinner()
        bar._advance_spinner()

        assert bar._spinner_index == initial_index + 3


@pytest.mark.asyncio
async def test_status_bar_spinner_does_not_cycle_when_idle():
    """The spinner should not advance when not running."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        assert bar.is_running is False

        initial_index = bar._spinner_index
        bar._advance_spinner()
        bar._advance_spinner()

        assert bar._spinner_index == initial_index


@pytest.mark.asyncio
async def test_status_bar_set_phase_resets_turns():
    """Starting a new phase should reset the turn counter to 0."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        bar.set_phase("Planning")
        bar.increment_turn()
        bar.increment_turn()
        assert bar.turn_count == 2

        bar.set_phase("Review")
        assert bar.turn_count == 0
