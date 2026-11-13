"""Server-sent events: tell open dashboards when the board changed.

The event carries no data beyond a version number. Each page refetches its own
board fragment with its own filters, so one event works for every view.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable


class BoardNotifier:
    def __init__(self) -> None:
        self.version = 0
        self._cond = asyncio.Condition()

    async def publish(self) -> None:
        async with self._cond:
            self.version += 1
            self._cond.notify_all()

    async def wait(self, seen: int, timeout: float) -> int:
        """Wait until the version differs from ``seen`` or ``timeout`` passes; return the version."""
        async with self._cond:
            try:
                await asyncio.wait_for(self._cond.wait_for(lambda: self.version != seen), timeout)
            except TimeoutError:
                pass
            return self.version


async def event_stream(notifier: BoardNotifier, is_disconnected: Callable[[], Awaitable[bool]],
                       heartbeat: float = 20.0,
                       still_allowed: Callable[[], Awaitable[bool]] | None = None) -> AsyncIterator[str]:
    seen = notifier.version
    yield "retry: 5000\n\n"  # browser reconnect delay
    while not await is_disconnected():
        if still_allowed is not None and not await still_allowed():
            return  # access was revoked; the reconnect will be refused
        version = await notifier.wait(seen, heartbeat)
        if version != seen:
            seen = version
            yield f"event: board\ndata: {version}\n\n"
        else:
            yield ": keepalive\n\n"  # keeps proxies from closing an idle connection
