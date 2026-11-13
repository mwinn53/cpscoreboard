import asyncio

import pytest

from app.events import BoardNotifier, event_stream

pytestmark = pytest.mark.anyio


async def test_wait_returns_on_publish_or_timeout():
    n = BoardNotifier()
    assert await n.wait(0, timeout=0.01) == 0  # timed out, unchanged

    waiter = asyncio.create_task(n.wait(0, timeout=5))
    await asyncio.sleep(0)
    await n.publish()
    assert await asyncio.wait_for(waiter, 1) == 1


async def test_stream_sends_board_events_and_keepalives_until_disconnect():
    n = BoardNotifier()
    disconnected = False

    async def is_disconnected():
        return disconnected

    stream = event_stream(n, is_disconnected, heartbeat=0.05)
    assert await anext(stream) == "retry: 5000\n\n"
    assert await anext(stream) == ": keepalive\n\n"

    nxt = asyncio.create_task(anext(stream))
    await asyncio.sleep(0.01)
    await n.publish()
    assert await asyncio.wait_for(nxt, 1) == "event: board\ndata: 1\n\n"

    disconnected = True
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


async def test_stream_ends_when_access_is_revoked():
    allowed = True

    async def never_disconnected():
        return False

    async def still_allowed():
        return allowed

    stream = event_stream(BoardNotifier(), never_disconnected, heartbeat=0.01, still_allowed=still_allowed)
    await anext(stream)  # retry
    assert await anext(stream) == ": keepalive\n\n"
    allowed = False
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
