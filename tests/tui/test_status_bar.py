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
    """StatusBar should display the animated colony idle state when inactive."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        assert not bar.is_running
        assert bar.phase_name == ""
        assert "colony" in bar._last_rendered.lower()


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
async def test_status_bar_set_phase_renders_extra():
    """set_phase should render any extra phase metadata."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        bar.set_phase("Planning", budget=1.0, model="opus", extra="branch: feat/tui")
        await pilot.pause()

        assert "branch: feat/tui" in bar._last_rendered


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
        assert bar.phase_name == ""


@pytest.mark.asyncio
async def test_status_bar_shows_cost_when_idle():
    """After a phase completes, idle state should still show total cost."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        bar.set_phase("Planning")
        bar.set_complete(cost=0.75, turns=2, duration=5.0)
        await pilot.pause()

        assert "$0.75" in bar._last_rendered
        assert "Planning" not in bar._last_rendered


@pytest.mark.asyncio
async def test_status_bar_returns_to_idle_animation_after_complete():
    """Completing a phase should restore the idle colony banner state."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        bar.set_phase("Planning", model="opus", extra="branch: feat/tui")
        bar.set_complete(cost=0.25, turns=1, duration=2.0)
        await pilot.pause()

        assert not bar.is_running
        assert bar.phase_name == ""
        assert bar.phase_model == ""
        assert bar.phase_extra == ""
        assert "colony" in bar._last_rendered.lower()


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
async def test_status_bar_spinner_timer_not_running_when_idle():
    """The spinner timer should not be active when no phase is running."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        assert bar.is_running is False
        assert bar._spinner_timer is None
        assert bar._idle_timer is not None


@pytest.mark.asyncio
async def test_status_bar_spinner_timer_stops_on_complete():
    """The spinner timer should stop when a phase completes."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        bar.set_phase("Planning")
        assert bar._spinner_timer is not None

        bar.set_complete(cost=0.10, turns=1, duration=5.0)
        assert bar._spinner_timer is None


@pytest.mark.asyncio
async def test_status_bar_spinner_timer_stops_on_error():
    """The spinner timer should stop when a phase errors."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        bar.set_phase("Planning")
        assert bar._spinner_timer is not None

        bar.set_error("something broke")
        assert bar._spinner_timer is None


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


@pytest.mark.asyncio
async def test_status_bar_idle_animation_cycles():
    """Idle animation should advance through multiple colony phrases."""
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one(StatusBar)
        first = bar._last_rendered
        bar._advance_idle()
        second = bar._last_rendered
        assert first != second
