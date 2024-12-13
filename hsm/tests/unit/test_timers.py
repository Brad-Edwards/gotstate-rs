# hsm/tests/test_timers.py
# Copyright (c) 2024 Brad Edwards
# Licensed under the MIT License - see LICENSE file for details

import asyncio
import threading
import time
from typing import Any, Dict, Generator, Optional

import pytest

from hsm.core.errors import HSMError
from hsm.core.events import Event
from hsm.interfaces.abc import AbstractTimer
from hsm.runtime.timers import (
    AsyncTimer,
    Timer,
    TimerCallback,
    TimerCancellationError,
    TimerError,
    TimerInfo,
    TimerManager,
    TimerSchedulingError,
    TimerState,
)


# -----------------------------------------------------------------------------
# FIXTURES
# -----------------------------------------------------------------------------
@pytest.fixture
def event() -> Event:
    """Create a test event."""
    return Event("test_event", payload={"test": "data"}, priority=1)


@pytest.fixture
def callback_data() -> Dict[str, Any]:
    """Create a dictionary to store callback data."""
    return {"called": False, "timer_id": None, "event": None}


@pytest.fixture
def callback(callback_data: Dict[str, Any]) -> TimerCallback:
    """Create a test callback function."""

    def _callback(timer_id: str, event: Event) -> None:
        callback_data["called"] = True
        callback_data["timer_id"] = timer_id
        callback_data["event"] = event

    return _callback


@pytest.fixture
def timer(callback: TimerCallback) -> Timer:
    """Create a test timer."""
    return Timer("test_timer", callback)


@pytest.fixture
def async_timer(callback: TimerCallback) -> AsyncTimer:
    """Create a test async timer."""
    return AsyncTimer("test_timer", callback)


@pytest.fixture
def timer_manager() -> TimerManager:
    """Create a test timer manager."""
    return TimerManager()


# -----------------------------------------------------------------------------
# TIMER ERROR TESTS
# -----------------------------------------------------------------------------
def test_timer_error_inheritance() -> None:
    """Test that timer errors inherit from HSMError."""
    assert issubclass(TimerError, HSMError)
    assert issubclass(TimerCancellationError, TimerError)
    assert issubclass(TimerSchedulingError, TimerError)


def test_timer_error_attributes() -> None:
    """Test timer error attributes."""
    # Test with details
    error = TimerError("test message", {"key": "value"})
    assert str(error) == "test message (details: {'key': 'value'})"
    assert error.details == {"key": "value"}

    # Test without details
    error = TimerError("test message")
    assert str(error) == "test message"
    assert error.details == {}


def test_timer_cancellation_error() -> None:
    """Test timer cancellation error attributes."""
    error = TimerCancellationError("test message", "timer1", TimerState.RUNNING)
    assert error.timer_id == "timer1"
    assert error.state == TimerState.RUNNING
    assert "timer1" in str(error)


def test_timer_scheduling_error() -> None:
    """Test timer scheduling error attributes."""
    error = TimerSchedulingError("test message", "timer1", 1.0, "test reason")
    assert error.timer_id == "timer1"
    assert abs(error.duration - 1.0) < 1e-9
    assert error.reason == "test reason"
    assert "timer1" in str(error)


# -----------------------------------------------------------------------------
# TIMER STATE TESTS
# -----------------------------------------------------------------------------
def test_timer_state_transitions(timer: Timer, event: Event) -> None:
    """Test timer state transitions."""
    assert timer.get_info().state == TimerState.IDLE

    timer.schedule_timeout(0.1, event)
    assert timer.get_info().state == TimerState.RUNNING

    timer.cancel_timeout(event.get_id())
    assert timer.get_info().state == TimerState.CANCELLED


def test_timer_state_completion(timer: Timer, event: Event, callback_data: Dict[str, Any]) -> None:
    """Test timer completion state."""
    timer.schedule_timeout(0.1, event)
    time.sleep(0.2)  # Wait for timer to complete
    assert timer.get_info().state == TimerState.COMPLETED
    assert callback_data["called"]


# -----------------------------------------------------------------------------
# TIMER FUNCTIONALITY TESTS
# -----------------------------------------------------------------------------
def test_timer_initialization() -> None:
    """Test timer initialization."""
    with pytest.raises(ValueError):
        Timer("", lambda x, y: None)

    with pytest.raises(ValueError):
        Timer("timer1", None)  # type: ignore

    timer = Timer("timer1", lambda x, y: None)
    assert isinstance(timer, AbstractTimer)
    assert timer.get_info().id == "timer1"


def test_timer_schedule_timeout(timer: Timer, event: Event) -> None:
    """Test scheduling timeouts."""
    with pytest.raises(ValueError):
        timer.schedule_timeout(-1.0, event)

    duration = 0.1
    timer.schedule_timeout(duration, event)
    info = timer.get_info()
    assert info.state == TimerState.RUNNING
    assert abs(info.duration - duration) < 1e-9
    assert info.start_time is not None


def test_timer_cancel_timeout(timer: Timer, event: Event) -> None:
    """Test cancelling timeouts."""
    # Cancel non-existent timer
    timer.cancel_timeout("non_existent")  # Should not raise

    timer.schedule_timeout(1.0, event)
    timer.cancel_timeout(event.get_id())
    assert timer.get_info().state == TimerState.CANCELLED


def test_timer_callback_execution(timer: Timer, event: Event, callback_data: Dict[str, Any]) -> None:
    """Test callback execution."""
    timer.schedule_timeout(0.1, event)
    time.sleep(0.2)  # Wait for callback

    assert callback_data["called"]
    assert callback_data["timer_id"] == "test_timer"
    assert callback_data["event"] == event


# -----------------------------------------------------------------------------
# ASYNC TIMER TESTS
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_async_timer_initialization() -> None:
    """Test async timer initialization."""
    with pytest.raises(ValueError):
        AsyncTimer("", lambda x, y: None)

    with pytest.raises(ValueError):
        AsyncTimer("timer1", None)  # type: ignore

    timer = AsyncTimer("timer1", lambda x, y: None)
    assert isinstance(timer, AbstractTimer)
    assert timer.get_info().id == "timer1"


@pytest.mark.asyncio
async def test_async_timer_schedule_timeout(async_timer: AsyncTimer, event: Event) -> None:
    """Test async timer scheduling."""
    with pytest.raises(ValueError):
        await async_timer.schedule_timeout(-1.0, event)

    duration = 0.1
    await async_timer.schedule_timeout(duration, event)
    info = async_timer.get_info()
    assert info.state == TimerState.RUNNING
    assert abs(info.duration - duration) < 1e-9
    assert info.start_time is not None


@pytest.mark.asyncio
async def test_async_timer_cancel_timeout(async_timer: AsyncTimer, event: Event) -> None:
    """Test async timer cancellation."""
    await async_timer.schedule_timeout(1.0, event)
    await async_timer.cancel_timeout(event.get_id())
    assert async_timer.get_info().state == TimerState.CANCELLED


@pytest.mark.asyncio
async def test_async_timer_callback_execution(
    async_timer: AsyncTimer, event: Event, callback_data: Dict[str, Any]
) -> None:
    """Test async timer callback execution."""
    await async_timer.schedule_timeout(0.1, event)
    await asyncio.sleep(0.2)  # Wait for callback

    assert callback_data["called"]
    assert callback_data["timer_id"] == "test_timer"
    assert callback_data["event"] == event


# -----------------------------------------------------------------------------
# TIMER MANAGER TESTS
# -----------------------------------------------------------------------------
def test_timer_manager_initialization(timer_manager: TimerManager) -> None:
    """Test timer manager initialization."""
    assert isinstance(timer_manager, TimerManager)


def test_timer_manager_create_timer(timer_manager: TimerManager, callback: TimerCallback) -> None:
    """Test timer creation."""
    timer = timer_manager.create_timer("timer1", callback)
    assert isinstance(timer, Timer)
    assert timer.get_info().id == "timer1"

    # Test duplicate timer creation
    with pytest.raises(ValueError):
        timer_manager.create_timer("timer1", callback)


def test_timer_manager_create_async_timer(timer_manager: TimerManager, callback: TimerCallback) -> None:
    """Test async timer creation."""
    timer = timer_manager.create_async_timer("timer1", callback)
    assert isinstance(timer, AsyncTimer)
    assert timer.get_info().id == "timer1"

    # Test duplicate timer creation
    with pytest.raises(ValueError):
        timer_manager.create_async_timer("timer1", callback)


def test_timer_manager_get_timer(timer_manager: TimerManager, callback: TimerCallback) -> None:
    """Test timer retrieval."""
    timer = timer_manager.create_timer("timer1", callback)
    retrieved = timer_manager.get_timer("timer1")
    assert retrieved == timer

    assert timer_manager.get_timer("non_existent") is None


def test_timer_manager_remove_timer(timer_manager: TimerManager, callback: TimerCallback, event: Event) -> None:
    """Test timer removal."""
    timer = timer_manager.create_timer("timer1", callback)

    # Cannot remove active timer
    timer.schedule_timeout(1.0, event)
    with pytest.raises(TimerError):
        timer_manager.remove_timer("timer1")

    # Can remove after cancellation
    timer.cancel_timeout(event.get_id())
    timer_manager.remove_timer("timer1")
    assert timer_manager.get_timer("timer1") is None

    # Cannot remove non-existent timer
    with pytest.raises(ValueError):
        timer_manager.remove_timer("non_existent")


def test_timer_manager_get_all_timers(timer_manager: TimerManager, callback: TimerCallback) -> None:
    """Test retrieving all timers."""
    timer1 = timer_manager.create_timer("timer1", callback)
    timer2 = timer_manager.create_timer("timer2", callback)

    all_timers = timer_manager.get_all_timers()
    assert len(all_timers) == 2
    assert all_timers["timer1"] == timer1.get_info()
    assert all_timers["timer2"] == timer2.get_info()


# -----------------------------------------------------------------------------
# EDGE CASES AND STRESS TESTS
# -----------------------------------------------------------------------------
def test_timer_concurrent_operations(timer_manager: TimerManager, callback: TimerCallback, event: Event) -> None:
    """Test concurrent timer operations."""
    timer = timer_manager.create_timer("timer1", callback)

    def worker() -> None:
        for _ in range(10):
            try:
                timer.schedule_timeout(0.1, event)
                time.sleep(0.05)
                timer.cancel_timeout(event.get_id())
            except (TimerError, ValueError):
                # Reset timer state if error occurs
                timer._cleanup()
                timer._state = TimerState.IDLE
                pass  # Expected when timer is already scheduled

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Timer should be in a valid end state
    assert timer.get_info().state in (TimerState.CANCELLED, TimerState.COMPLETED, TimerState.IDLE)


@pytest.mark.asyncio
async def test_async_timer_concurrent_operations(
    timer_manager: TimerManager, callback: TimerCallback, event: Event
) -> None:
    """Test concurrent async timer operations."""
    timer = timer_manager.create_async_timer("timer1", callback)

    async def worker() -> None:
        for _ in range(10):
            try:
                await timer.schedule_timeout(0.1, event)
                await asyncio.sleep(0.05)
                await timer.cancel_timeout(event.get_id())
            except TimerError:
                pass  # Expected when timer is already scheduled

    tasks = [asyncio.create_task(worker()) for _ in range(5)]
    await asyncio.gather(*tasks)

    # Timer should be in a valid end state
    assert timer.get_info().state in (TimerState.CANCELLED, TimerState.COMPLETED, TimerState.IDLE)


def test_timer_cleanup(timer: Timer, event: Event) -> None:
    """Test timer resource cleanup."""
    timer.schedule_timeout(0.1, event)
    timer.cancel_timeout(event.get_id())

    info = timer.get_info()
    assert info.start_time is None
    assert info.duration is None
    assert info.remaining is None


def test_timer_info_remaining_time(timer: Timer, event: Event) -> None:
    """Test timer remaining time calculation."""
    duration = 1.0
    timer.schedule_timeout(duration, event)
    time.sleep(0.1)

    info = timer.get_info()
    assert info.remaining is not None
    assert 0 <= info.remaining <= duration + 1e-9

    timer.cancel_timeout(event.get_id())
    assert timer.get_info().remaining is None


@pytest.mark.asyncio
async def test_async_timer_shutdown(async_timer: AsyncTimer, event: Event) -> None:
    """Test AsyncTimer shutdown functionality."""
    await async_timer.schedule_timeout(1.0, event)
    assert async_timer.get_info().state == TimerState.RUNNING

    await async_timer.shutdown()
    assert async_timer.get_info().state == TimerState.IDLE
    assert async_timer.get_info().start_time is None
    assert async_timer.get_info().duration is None


def test_timer_callback_error_handling(timer: Timer, event: Event) -> None:
    """Test timer behavior when callback raises an error."""

    def error_callback(timer_id: str, evt: Event) -> None:
        raise RuntimeError("Callback error")

    error_timer = Timer("error_timer", error_callback)
    error_timer.schedule_timeout(0.1, event)
    time.sleep(0.2)  # Wait for callback

    assert error_timer.get_info().state == TimerState.ERROR


@pytest.mark.asyncio
async def test_async_timer_callback_error_handling(async_timer: AsyncTimer, event: Event) -> None:
    """Test async timer behavior when callback raises an error."""

    def error_callback(timer_id: str, evt: Event) -> None:
        raise RuntimeError("Callback error")

    error_timer = AsyncTimer("error_timer", error_callback)
    await error_timer.schedule_timeout(0.1, event)
    await asyncio.sleep(0.2)  # Wait for callback

    assert error_timer.get_info().state == TimerState.ERROR


def test_timer_invalid_operations(timer: Timer, event: Event) -> None:
    """Test timer behavior with invalid operations."""
    # Test scheduling when already running
    timer.schedule_timeout(1.0, event)
    with pytest.raises(TimerSchedulingError):
        timer.schedule_timeout(1.0, event)

    # Test scheduling with invalid duration
    with pytest.raises(ValueError):
        timer.schedule_timeout(-1.0, event)

    # Clean up
    timer.cancel_timeout(event.get_id())


@pytest.mark.asyncio
async def test_async_timer_invalid_operations(async_timer: AsyncTimer, event: Event) -> None:
    """Test async timer behavior with invalid operations."""
    # Test scheduling when already running
    await async_timer.schedule_timeout(1.0, event)
    with pytest.raises(TimerSchedulingError):
        await async_timer.schedule_timeout(1.0, event)

    # Test scheduling with invalid duration
    with pytest.raises(ValueError):
        await async_timer.schedule_timeout(-1.0, event)

    # Clean up
    await async_timer.cancel_timeout(event.get_id())


def test_timer_manager_concurrent_timer_creation(timer_manager: TimerManager) -> None:
    """Test concurrent timer creation in TimerManager."""

    def create_timer(idx: int) -> None:
        try:
            timer_manager.create_timer(f"timer_{idx}", callback)
        except ValueError:
            pass  # Expected for duplicate IDs

    threads = [threading.Thread(target=create_timer, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Verify we have some successfully created timers
    timers = timer_manager.get_all_timers()
    assert len(timers) > 0


def test_timer_manager_remove_active_timer(timer_manager: TimerManager, event: Event) -> None:
    """Test removing an active timer from TimerManager."""

    timer = timer_manager.create_timer("test_timer", callback)
    timer.schedule_timeout(1.0, event)

    with pytest.raises(TimerError):
        timer_manager.remove_timer("test_timer")

    # Clean up
    timer.cancel_timeout(event.get_id())
    timer_manager.remove_timer("test_timer")


def test_timer_state_transitions_detailed(timer: Timer, event: Event) -> None:
    """Test detailed timer state transitions."""
    # Initial state
    assert timer.get_info().state == TimerState.IDLE

    # Schedule -> Running
    timer.schedule_timeout(1.0, event)
    assert timer.get_info().state == TimerState.RUNNING

    # Running -> Cancelled
    timer.cancel_timeout(event.get_id())
    assert timer.get_info().state == TimerState.CANCELLED

    # Can schedule again after cancellation
    timer.schedule_timeout(0.1, event)
    assert timer.get_info().state == TimerState.RUNNING

    # Wait for completion
    time.sleep(0.2)
    assert timer.get_info().state == TimerState.COMPLETED


@pytest.mark.asyncio
async def test_async_timer_state_transitions_detailed(async_timer: AsyncTimer, event: Event) -> None:
    """Test detailed async timer state transitions."""
    # Initial state
    assert async_timer.get_info().state == TimerState.IDLE

    # Schedule -> Running
    await async_timer.schedule_timeout(1.0, event)
    assert async_timer.get_info().state == TimerState.RUNNING

    # Running -> Cancelled
    await async_timer.cancel_timeout(event.get_id())
    assert async_timer.get_info().state == TimerState.CANCELLED

    # Can schedule again after cancellation
    await async_timer.schedule_timeout(0.1, event)
    assert async_timer.get_info().state == TimerState.RUNNING

    # Wait for completion
    await asyncio.sleep(0.2)
    assert async_timer.get_info().state == TimerState.COMPLETED


def test_timer_info_immutability(timer: Timer, event: Event) -> None:
    """Test that TimerInfo objects are immutable."""
    timer.schedule_timeout(1.0, event)
    info = timer.get_info()

    with pytest.raises(Exception):  # dataclass is frozen
        info.state = TimerState.COMPLETED  # type: ignore

    with pytest.raises(Exception):
        info.duration = 2.0  # type: ignore


@pytest.mark.asyncio
async def test_base_timer_template_methods(async_timer: AsyncTimer, event: Event) -> None:
    """Test the template methods in BaseTimer."""
    # Test _schedule_timeout_impl
    await async_timer._schedule_timeout_impl(0.1, event)
    assert async_timer.get_info().state == TimerState.RUNNING

    # Test _cancel_timeout_impl
    await async_timer._cancel_timeout_impl(event.get_id())
    assert async_timer.get_info().state == TimerState.CANCELLED


@pytest.mark.filterwarnings("ignore:coroutine.*never awaited")
def test_timer_asyncio_run_error(timer: Timer, event: Event, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test error handling when asyncio.run fails."""

    def mock_run(*args: Any) -> None:
        raise RuntimeError("asyncio.run failed")

    monkeypatch.setattr(asyncio, "run", mock_run)

    with pytest.raises(TimerError):
        timer.schedule_timeout(0.1, event)

    with pytest.raises(TimerError):
        timer.cancel_timeout(event.get_id())


def test_timer_shutdown(timer: Timer, event: Event) -> None:
    """Test Timer shutdown behavior."""
    timer.schedule_timeout(1.0, event)
    assert timer.get_info().state == TimerState.RUNNING

    # Cancel should effectively shut down the timer
    timer.cancel_timeout(event.get_id())
    assert timer.get_info().state == TimerState.CANCELLED
    assert timer.get_info().start_time is None
    assert timer.get_info().duration is None


@pytest.mark.asyncio
async def test_concurrent_shutdown(timer_manager: TimerManager, event: Event) -> None:
    """Test concurrent shutdown of multiple timers."""
    timers = []
    for i in range(5):
        timer = timer_manager.create_async_timer(f"timer_{i}", callback)
        await timer.schedule_timeout(1.0, event)
        timers.append(timer)

    # Shutdown all timers concurrently
    await asyncio.gather(*(timer.shutdown() for timer in timers))

    # Verify all timers are properly shut down
    for timer in timers:
        info = timer.get_info()
        assert info.state == TimerState.IDLE
        assert info.start_time is None
        assert info.duration is None


@pytest.mark.asyncio
async def test_timer_cleanup_after_error(async_timer: AsyncTimer, event: Event) -> None:
    """Test timer cleanup after error conditions."""

    # Force an error in the timer callback
    def error_callback(timer_id: str, evt: Event) -> None:
        raise RuntimeError("Callback error")

    error_timer = AsyncTimer("error_timer", error_callback)
    await error_timer.schedule_timeout(0.1, event)
    await asyncio.sleep(0.2)  # Wait for callback to fail

    assert error_timer.get_info().state == TimerState.ERROR

    # Should be able to shutdown cleanly even after error
    await error_timer.shutdown()
    assert error_timer.get_info().state == TimerState.IDLE


def test_timer_manager_cleanup_after_error(timer_manager: TimerManager, event: Event) -> None:
    """Test TimerManager cleanup after timer errors."""

    def error_callback(timer_id: str, evt: Event) -> None:
        raise RuntimeError("Callback error")

    timer = timer_manager.create_timer("error_timer", error_callback)
    timer.schedule_timeout(0.1, event)
    time.sleep(0.2)  # Wait for callback to fail

    assert timer.get_info().state == TimerState.ERROR

    # Should be able to remove errored timer
    timer_manager.remove_timer("error_timer")
    assert timer_manager.get_timer("error_timer") is None


def test_timer_validate_schedule_state(timer: Timer, event: Event) -> None:
    """Test schedule validation for different timer states."""
    # Test scheduling in RUNNING state
    timer.schedule_timeout(0.1, event)
    with pytest.raises(TimerSchedulingError):
        timer.schedule_timeout(0.1, event)

    # Test scheduling in ERROR state
    timer._state = TimerState.ERROR
    with pytest.raises(TimerSchedulingError):
        timer.schedule_timeout(0.1, event)

    # Test scheduling in CANCELLED state (should work)
    timer._state = TimerState.CANCELLED
    timer.schedule_timeout(0.1, event)
    assert timer.get_info().state == TimerState.RUNNING


def test_timer_cancel_with_wrong_event(timer: Timer, event: Event) -> None:
    """Test cancelling with wrong event ID."""
    timer.schedule_timeout(1.0, event)

    # Try to cancel with wrong event ID
    timer.cancel_timeout("wrong_id")
    # Timer should still be running
    assert timer.get_info().state == TimerState.RUNNING

    # Cancel with correct ID
    timer.cancel_timeout(event.get_id())
    assert timer.get_info().state == TimerState.CANCELLED


def test_timer_info_remaining_edge_cases(timer: Timer, event: Event) -> None:
    """Test edge cases for timer remaining time calculation."""
    # Test remaining time when not running
    assert timer.get_info().remaining is None

    # Test remaining time at start
    timer.schedule_timeout(1.0, event)
    info = timer.get_info()
    assert info.remaining is not None
    assert abs(info.remaining - 1.0) < 0.1

    # Test remaining time after completion
    time.sleep(1.1)  # Wait for completion
    assert timer.get_info().remaining is None


@pytest.mark.asyncio
async def test_async_timer_cancel_during_shutdown(async_timer: AsyncTimer, event: Event) -> None:
    """Test cancelling async timer during shutdown."""
    await async_timer.schedule_timeout(1.0, event)

    # Start shutdown and cancel concurrently
    await asyncio.gather(async_timer.shutdown(), async_timer.cancel_timeout(event.get_id()))

    assert async_timer.get_info().state == TimerState.IDLE


def test_timer_callback_with_none_event(timer: Timer) -> None:
    """Test timer behavior when event becomes None."""
    timer._event = None  # Simulate event being cleared

    # Attempt cancel should not raise and should be no-op
    timer.cancel_timeout("any_id")
    assert timer.get_info().state == TimerState.IDLE


def test_timer_manager_duplicate_removal(timer_manager: TimerManager, callback: TimerCallback) -> None:
    """Test removing the same timer multiple times."""
    timer = timer_manager.create_timer("test_timer", callback)

    timer_manager.remove_timer("test_timer")
    with pytest.raises(ValueError):
        timer_manager.remove_timer("test_timer")


@pytest.mark.asyncio
async def test_async_timer_event_during_shutdown(async_timer: AsyncTimer, event: Event) -> None:
    """Test event handling during shutdown."""
    await async_timer.schedule_timeout(0.1, event)
    await async_timer.shutdown()

    # Scheduling after shutdown should work
    await async_timer.schedule_timeout(0.1, event)
    assert async_timer.get_info().state == TimerState.RUNNING


def test_timer_manager_concurrent_access(timer_manager: TimerManager, callback: TimerCallback) -> None:
    """Test concurrent timer manager operations."""

    def worker(idx: int) -> None:
        try:
            timer = timer_manager.create_timer(f"timer_{idx}", callback)
            timer_manager.remove_timer(f"timer_{idx}")
        except (ValueError, TimerError):
            pass

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Verify no timers remain
    assert len(timer_manager.get_all_timers()) == 0


def test_timer_manager_get_all_timers_snapshot(
    timer_manager: TimerManager, callback: TimerCallback, event: Event
) -> None:
    """Test that get_all_timers returns a point-in-time snapshot."""
    timer1 = timer_manager.create_timer("timer1", callback)
    timer2 = timer_manager.create_timer("timer2", callback)

    # Get snapshot
    timers = timer_manager.get_all_timers()

    # Modify timer states
    timer1.schedule_timeout(0.1, event)
    timer2.schedule_timeout(0.1, event)

    # Verify snapshot hasn't changed
    assert timers["timer1"].state == TimerState.IDLE
    assert timers["timer2"].state == TimerState.IDLE
