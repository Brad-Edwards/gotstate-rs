# hsm/runtime/async_support.py
# Copyright (c) 2024 Brad Edwards
# Licensed under the MIT License - see LICENSE file for details

from __future__ import annotations

import asyncio
from typing import List, Optional

from hsm.core.events import Event
from hsm.core.hooks import HookManager, HookProtocol
from hsm.core.state_machine import StateMachine, _StateMachineContext
from hsm.core.states import State
from hsm.core.transitions import Transition
from hsm.core.validations import Validator


class _AsyncLock:
    """
    Internal async-compatible lock abstraction, providing awaitable acquisition
    methods.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        await self._lock.acquire()

    def release(self) -> None:
        self._lock.release()


class AsyncEventQueue:
    """
    An asynchronous event queue providing non-blocking enqueue/dequeue methods,
    suitable for use with AsyncStateMachine.
    """

    def __init__(self, priority: bool = False) -> None:
        """
        Initialize the async event queue.

        :param priority: If True, operates in a priority-based mode.
                         Currently, we only implement a simple FIFO using asyncio.Queue.
                         Priority mode could be implemented separately if needed.
        """
        self._priority_mode = priority
        # For simplicity, we ignore priority in the async variant and just use FIFO.
        self._queue = asyncio.Queue()

    async def enqueue(self, event: Event) -> None:
        """
        Asynchronously insert an event into the queue.
        """
        await self._queue.put(event)

    async def dequeue(self) -> Optional[Event]:
        """
        Asynchronously retrieve the next event, or None if empty.
        This will block until an event is available.
        If a non-blocking or timeout approach is needed, adapt accordingly.
        """
        try:
            # Wait for an event with a small timeout
            return await asyncio.wait_for(self._queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None

    async def clear(self) -> None:
        """
        Asynchronously clear all events from the queue.
        This is not a standard asyncio.Queue operation; we implement by draining.
        """
        while not self._queue.empty():
            await self._queue.get()

    @property
    def priority_mode(self) -> bool:
        """
        Indicates if this async queue uses priority ordering.
        """
        return self._priority_mode


class AsyncStateMachine:
    """
    An asynchronous version of the state machine. Allows event processing in an
    async context, integrating with asyncio-based loops and async event queues.

    This class parallels StateMachine, but provides async start/stop/process_event.
    """

    def __init__(self, initial_state: State, validator: Validator = None, hooks: List[HookProtocol] = None):
        self._context = _StateMachineContext(initial_state)
        self.validator = validator or Validator()
        self._hooks = HookManager(hooks or [])
        self._lock = _AsyncLock()
        self._started = False
        self._stopped = False

    @property
    def current_state(self) -> State:
        return self._context.get_current_state()

    async def start(self) -> None:
        if self._started:
            return
        await self._lock.acquire()
        try:
            if self.validator:
                self.validator.validate_state_machine(self)
            self._context.start()
            self._hooks.execute_on_enter(self.current_state)
            self._started = True
        finally:
            self._lock.release()

    async def process_event(self, event: Event) -> None:
        if not self._started or self._stopped:
            return
        await self._lock.acquire()
        try:
            transitions = self._context.get_transitions()
            valid_transitions = [t for t in transitions if t.source == self.current_state and t.evaluate_guards(event)]

            if valid_transitions:
                chosen_transition = sorted(valid_transitions, key=lambda t: t.get_priority(), reverse=True)[0]
                self._hooks.execute_on_exit(self.current_state)
                self.current_state.on_exit()
                chosen_transition.execute_actions(event)
                self._context.set_current_state(chosen_transition.target)
                self.current_state.on_enter()
                self._hooks.execute_on_enter(self.current_state)
        except Exception as e:
            self._hooks.execute_on_error(e)
        finally:
            self._lock.release()

    async def stop(self) -> None:
        if self._stopped:
            return
        await self._lock.acquire()
        try:
            self._hooks.execute_on_exit(self.current_state)
            self._context.stop()
            self._stopped = True
        finally:
            self._lock.release()

    def add_transition(self, transition: Transition) -> None:
        """
        Add a transition to the state machine.
        """
        self._context.add_transition(transition)


class _AsyncEventProcessingLoop:
    """
    Internal async loop for event processing, integrating with asyncio's event loop
    to continuously process events until stopped.
    """

    def __init__(self, machine: AsyncStateMachine, event_queue: AsyncEventQueue) -> None:
        """
        Store references for async iteration.
        """
        self._machine = machine
        self._queue = event_queue
        self._running = False

    async def start_loop(self) -> None:
        """
        Begin processing events asynchronously.
        """
        self._running = True
        await self._machine.start()  # Ensure machine started

        while self._running:
            event = await self._queue.dequeue()
            if event:
                await self._machine.process_event(event)
            else:
                # If no event, we can await a small sleep or wait again
                await asyncio.sleep(0.01)

    async def stop_loop(self) -> None:
        """
        Stop processing events, allowing async tasks to conclude gracefully.
        """
        self._running = False
        await self._machine.stop()
