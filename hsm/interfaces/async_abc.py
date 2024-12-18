"""Async protocol definitions for HSM."""

from typing import Any, Protocol, runtime_checkable

from hsm.interfaces.protocols import Event


@runtime_checkable
class AsyncGuard(Protocol):
    """Protocol for async guard conditions."""

    async def check(self, event: Event, state_data: Any) -> bool: ...


@runtime_checkable
class AsyncAction(Protocol):
    """Protocol for async actions."""

    async def execute(self, event: Event, state_data: Any) -> None: ...
