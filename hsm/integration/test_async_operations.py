"""Integration tests for asynchronous operations."""

import asyncio
from typing import Any, List

import pytest

from hsm.core.states import State
from hsm.core.transitions import Transition
from hsm.interfaces.abc import AbstractEvent
from hsm.interfaces.async_abc import AsyncAction, AsyncGuard
from hsm.runtime.async_support import (
    AsyncHSMError,
    AsyncLockManager,
    AsyncState,
    AsyncStateError,
    AsyncStateMachine,
    AsyncTransition,
    AsyncTransitionError,
)
from hsm.runtime.event_queue import AsyncEventQueue


@pytest.fixture
async def async_states() -> List[AsyncState]:
    """Fixture providing states for async testing."""

    class AsyncTestState(AsyncState):
        async def _do_enter(self) -> None:
            self.set_data("status", self.get_id())

        async def _do_exit(self) -> None:
            self.set_data("previous_status", self.get_id())

    return [AsyncTestState("idle"), AsyncTestState("working"), AsyncTestState("done"), AsyncTestState("failed")]


@pytest.fixture
async def async_transitions(async_states: List[AsyncState]) -> List[AsyncTransition]:
    """Fixture providing transitions for async testing."""

    class EventGuard(AsyncGuard):
        def __init__(self, event_id: str):
            self._event_id = event_id

        async def check(self, event: AbstractEvent, state_data: Any) -> bool:
            return event.get_id() == self._event_id

    class SimpleAction(AsyncAction):
        async def execute(self, event: AbstractEvent, state_data: Any) -> None:
            pass

    return [
        AsyncTransition(
            source_id="idle", target_id="working", guard=EventGuard("start_work"), actions=[SimpleAction()]
        ),
        AsyncTransition(
            source_id="working", target_id="done", guard=EventGuard("complete_work"), actions=[SimpleAction()]
        ),
        AsyncTransition(
            source_id="working", target_id="failed", guard=EventGuard("fail_work"), actions=[SimpleAction()]
        ),
        AsyncTransition(source_id="failed", target_id="idle", guard=EventGuard("retry"), actions=[SimpleAction()]),
    ]


@pytest.fixture
async def async_machine(async_states: List[AsyncState], async_transitions: List[AsyncTransition]) -> AsyncStateMachine:
    """Fixture providing an async state machine."""
    initial_state = next(s for s in async_states if s.get_id() == "idle")
    machine = AsyncStateMachine(async_states, async_transitions, initial_state)

    # Override the start method to reinitialize event queue
    original_start = machine.start

    async def start_with_new_queue():
        machine._event_queue = AsyncEventQueue()  # Create fresh event queue
        await original_start()

    machine.start = start_with_new_queue

    return machine


@pytest.mark.asyncio
@pytest.mark.integration
class TestAsyncStateMachine:
    """Test suite for async state machine operations."""

    async def test_async_start_stop(self, async_machine: AsyncStateMachine):
        """Test async start/stop operations."""
        # Initial state should be 'idle'
        assert not async_machine.is_running()
        assert async_machine.get_current_state() is None

        # Start the machine
        await async_machine.start()
        assert async_machine.is_running()
        current_state = async_machine.get_current_state()
        assert current_state is not None
        assert current_state.get_id() == "idle"

        # Stop the machine
        await async_machine.stop()
        assert not async_machine.is_running()

        # Test multiple start/stops
        await async_machine.start()
        assert async_machine.is_running()
        await async_machine.stop()
        assert not async_machine.is_running()

        # Test idempotency of stop
        await async_machine.stop()  # Should not raise
        assert not async_machine.is_running()

    async def test_async_event_processing(self, async_machine: AsyncStateMachine):
        """Test async event processing."""

        # Create a test event
        class TestEvent(AbstractEvent):
            def get_id(self) -> str:
                return "test_event"

            def get_payload(self) -> Any:
                return None

            def get_priority(self) -> int:
                return 0

        # Start the machine
        await async_machine.start()
        assert async_machine.get_current_state().get_id() == "idle"

        # Process event - should be queued even without valid transition
        event = TestEvent()
        await async_machine.process_event(event)

        # Let the event loop process the event
        await asyncio.sleep(0.1)

        # State should not change as there's no transition for this event
        assert async_machine.get_current_state().get_id() == "idle"

        # Test concurrent event processing
        events = [TestEvent() for _ in range(5)]
        await asyncio.gather(*[async_machine.process_event(e) for e in events])
        await asyncio.sleep(0.1)  # Allow events to be processed

        # Clean up
        await async_machine.stop()

    async def test_async_transitions(self, async_machine: AsyncStateMachine):
        """Test async transitions."""

        # Create a transition event
        class TransitionEvent(AbstractEvent):
            def __init__(self, event_id: str):
                self._event_id = event_id

            def get_id(self) -> str:
                return self._event_id

            def get_payload(self) -> Any:
                return None

            def get_priority(self) -> int:
                return 0

        # Start the machine in idle state
        await async_machine.start()
        assert async_machine.get_current_state().get_id() == "idle"

        # Test transition from idle to working
        await async_machine.process_event(TransitionEvent("start_work"))
        await asyncio.sleep(0.1)  # Allow transition to process
        assert async_machine.get_current_state().get_id() == "working"

        # Test transition from working to done
        await async_machine.process_event(TransitionEvent("complete_work"))
        await asyncio.sleep(0.1)  # Allow transition to process
        assert async_machine.get_current_state().get_id() == "done"

        # Test transition from working to failed (after resetting to working)
        await async_machine.reset()  # Reset to idle
        await async_machine.process_event(TransitionEvent("start_work"))  # Go to working
        await asyncio.sleep(0.1)
        assert async_machine.get_current_state().get_id() == "working"

        await async_machine.process_event(TransitionEvent("fail_work"))
        await asyncio.sleep(0.1)
        assert async_machine.get_current_state().get_id() == "failed"

        # Test transition from failed back to idle
        await async_machine.process_event(TransitionEvent("retry"))
        await asyncio.sleep(0.1)
        assert async_machine.get_current_state().get_id() == "idle"

        # Clean up
        await async_machine.stop()

    async def test_async_error_handling(self, async_machine: AsyncStateMachine):
        """Test async error handling."""
        # Test starting an already running machine
        await async_machine.start()
        await async_machine.start()  # Should not raise
        assert async_machine.is_running()

        # Test processing events when machine is stopped
        await async_machine.stop()

        class TestEvent(AbstractEvent):
            def get_id(self) -> str:
                return "test_event"

            def get_payload(self) -> Any:
                return None

            def get_priority(self) -> int:
                return 0

        with pytest.raises(AsyncHSMError):
            await async_machine.process_event(TestEvent())

        # Test invalid state transitions
        await async_machine.start()
        current_state = async_machine.get_current_state()
        assert current_state is not None

        # Try to process events rapidly to test error handling
        events = [TestEvent() for _ in range(10)]
        await asyncio.gather(*[async_machine.process_event(e) for e in events], return_exceptions=True)

        # Test error handling during shutdown
        await asyncio.gather(async_machine.stop(), async_machine.process_event(TestEvent()), return_exceptions=True)
        assert not async_machine.is_running()

        # Clean up
        await async_machine.stop()


@pytest.mark.asyncio
@pytest.mark.integration
class TestAsyncResourceManagement:
    """Test suite for async resource management."""

    async def test_async_cleanup(self, async_machine: AsyncStateMachine):
        """Test async cleanup."""
        # Start the machine
        await async_machine.start()
        assert async_machine.is_running()

        # Create and queue multiple events
        class TestEvent(AbstractEvent):
            def get_id(self) -> str:
                return "test_event"

            def get_payload(self) -> Any:
                return None

            def get_priority(self) -> int:
                return 0

        # Queue multiple events
        events = [TestEvent() for _ in range(5)]
        for event in events:
            await async_machine.process_event(event)

        # Stop the machine - should clean up queued events
        await async_machine.stop()
        assert not async_machine.is_running()

        # Verify machine can be restarted cleanly
        await async_machine.start()
        assert async_machine.is_running()
        assert async_machine.get_current_state().get_id() == "idle"

        # Test cleanup with context manager
        async with async_machine as machine:
            assert machine.is_running()
            await machine.process_event(TestEvent())

        # Verify machine is stopped after context
        assert not async_machine.is_running()

    async def test_resource_locking(self, async_machine: AsyncStateMachine):
        """Test resource locking."""

        # Create an event that will trigger state changes
        class StateChangeEvent(AbstractEvent):
            def __init__(self, event_id: str):
                self._event_id = event_id

            def get_id(self) -> str:
                return self._event_id

            def get_payload(self) -> Any:
                return None

            def get_priority(self) -> int:
                return 0

        # Start the machine
        await async_machine.start()
        assert async_machine.get_current_state().get_id() == "idle"

        # Create multiple concurrent state change attempts
        events = [
            StateChangeEvent("start_work"),
            StateChangeEvent("complete_work"),
            StateChangeEvent("fail_work"),
            StateChangeEvent("retry"),
        ]

        # Process events concurrently to test locking
        await asyncio.gather(*[async_machine.process_event(e) for e in events])
        await asyncio.sleep(0.1)  # Allow events to be processed

        # Verify the machine is in a valid state
        current_state = async_machine.get_current_state()
        assert current_state is not None
        assert current_state.get_id() in {"idle", "working", "done", "failed"}

        # Test rapid state changes
        for _ in range(3):
            await async_machine.reset()
            await asyncio.gather(*[async_machine.process_event(e) for e in events])
            await asyncio.sleep(0.1)
            assert async_machine.get_current_state() is not None

        # Clean up
        await async_machine.stop()

    async def test_async_queue_management(self, async_machine: AsyncStateMachine):
        """Test async queue management."""

        # Create test events
        class PrioritizedEvent(AbstractEvent):
            def __init__(self, event_id: str, priority: int):
                self._event_id = event_id
                self._priority = priority

            def get_id(self) -> str:
                return self._event_id

            def get_payload(self) -> Any:
                return None

            def get_priority(self) -> int:
                return self._priority

        # Start the machine
        await async_machine.start()
        assert async_machine.get_current_state().get_id() == "idle"

        # Create events with different priorities
        high_priority_events = [PrioritizedEvent(f"high_{i}", 2) for i in range(3)]
        low_priority_events = [PrioritizedEvent(f"low_{i}", 1) for i in range(3)]

        # Mix events with different priorities
        events = []
        events.extend(low_priority_events)
        events.extend(high_priority_events)

        # Process events concurrently
        await asyncio.gather(*[async_machine.process_event(e) for e in events])
        await asyncio.sleep(0.1)  # Allow events to be processed

        # Test queue behavior during machine stop/start
        await async_machine.stop()

        # Queue should be cleared after stop
        await async_machine.start()

        # Test queue behavior with rapid event submission
        rapid_events = [PrioritizedEvent(f"rapid_{i}", i % 3) for i in range(10)]
        await asyncio.gather(*[async_machine.process_event(e) for e in rapid_events])
        await asyncio.sleep(0.1)

        # Clean up
        await async_machine.stop()

    async def test_context_manager_behavior(self, async_machine: AsyncStateMachine):
        """Test context manager behavior."""
        # Test basic context manager functionality
        async with async_machine as machine:
            assert machine.is_running()
            assert machine.get_current_state().get_id() == "idle"

        assert not async_machine.is_running()

        # Create a new machine instance for nested context test
        initial_state = next(s for s in async_machine._states.values() if s.get_id() == "idle")
        nested_machine = AsyncStateMachine(
            list(async_machine._states.values()), async_machine._transitions, initial_state
        )

        async with nested_machine as outer_machine:
            assert outer_machine.is_running()

            # Create and process an event
            class TestEvent(AbstractEvent):
                def get_id(self) -> str:
                    return "test_event"

                def get_payload(self) -> Any:
                    return None

                def get_priority(self) -> int:
                    return 0

            await outer_machine.process_event(TestEvent())

            # Create another new machine for inner context
            inner_machine = AsyncStateMachine(
                list(async_machine._states.values()), async_machine._transitions, initial_state
            )

            async with inner_machine as inner:
                assert inner.is_running()
                await inner.process_event(TestEvent())

            # Outer context should still be running
            assert outer_machine.is_running()

        # Machine should be stopped after all contexts exit
        assert not nested_machine.is_running()

        # Test context manager error handling
        error_machine = AsyncStateMachine(
            list(async_machine._states.values()), async_machine._transitions, initial_state
        )
        with pytest.raises(AsyncHSMError):
            async with error_machine as machine:
                assert machine.is_running()
                raise AsyncHSMError("Test error")

        # Machine should be stopped even if an error occurred
        assert not error_machine.is_running()
